"""Explicit raw history windows remain bounded and independent of checkpoints."""
import pytest
from pydantic import ValidationError

from ai_workbench.core.message_parts import make_tool_call_part, make_tool_result_part
from ai_workbench.core.schema.context_policy import ContextPolicy
from tests.test_chat_presentation import presentation_client, configure, send
from tests.test_context_compaction import setup, seed, summarize, summary_call
from tests.chat_fixtures import normal_character, child
from tests.tool_fixtures import ok


def window(client, session, limit=100, **values):
    policy = ContextPolicy(strategy='message_window', message_window={'max_messages': limit}, **values).model_dump()
    return ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': policy}}))


def answer_detail(client, result):
    run = ok(client.get(f"/api/runs/{result['run']['run_id']}"))
    assert not any(step['kind'] == 'compaction' for step in run['steps'])
    answer = next(step for step in run['steps'] if step['kind'] == 'model')
    return ok(client.get(f"/api/runs/{run['run_id']}/steps/{answer['step_id']}/context"))


@pytest.mark.parametrize('value', [None, 0, -1, 10001, True, 1.5, '20'])
def test_message_window_is_a_strict_positive_bounded_count(value):
    with pytest.raises(ValidationError):
        ContextPolicy(strategy='message_window', message_window={'max_messages': value})
    assert ContextPolicy().strategy == 'token_budget'
    assert ContextPolicy().message_window.max_messages == 100


@pytest.mark.parametrize('limit,retained', [(1, 0), (3, 2), (6, 6), (8, 8)])
def test_message_window_keeps_complete_recent_turns_and_current_input(presentation_client, limit, retained):
    client, upstream = presentation_client
    session = window(client, configure(client, harness=False, streaming=False), limit)
    state = client.app.state.runtime_state
    messages = []
    for label in ('a', 'b', 'c'):
        user = state.messages.add_message(session['session_id'], 'user', f'question-{label}')
        messages.append(user)
        if label == 'b':
            messages.append(state.messages.add_message(session['session_id'], 'assistant', parent_message_id=user.message_id,
                parts=[make_tool_call_part('old-call', 'test_echo', {'value': 'evidence'})]))
            messages.append(state.messages.add_message(session['session_id'], 'tool', parent_message_id=user.message_id,
                parts=[make_tool_result_part('old-call', 'test_echo', 'success', {'value': 'evidence'})]))
        messages.append(state.messages.add_message(session['session_id'], 'assistant', f'answer-{label}', parent_message_id=user.message_id))
    result = send(client, session, 'CURRENT')
    assert result['success'], result
    detail = answer_detail(client, result)
    selected = [source['reference_id'] for source in detail['sources'] if source['kind'] == 'history']
    assert selected == [item.message_id for item in messages[len(messages) - retained:]]
    assert detail['request']['messages'][-1]['content'] == "CURRENT"
    assert len(upstream.calls) == 1 and not summary_call(upstream.calls[0])
    excluded = [item for item in detail['exclusions'] if item['reason'] == 'message_limit']
    assert sum(item['count'] for item in excluded) == 8 - retained
    assert detail['policy'] == session['effective']['context_policy']


@pytest.mark.parametrize('attachment_change', [False, True])
def test_window_ignores_checkpoint_without_reading_or_deleting_it(presentation_client, monkeypatch, attachment_change):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    upstream.turns = [summarize] * 16
    assert send(client, session)['success']
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    session = window(client, session, 2, include_attachments='none' if attachment_change else 'explicit')
    offset = len(upstream.calls)
    with monkeypatch.context() as patch:
        patch.setattr(state.sessions, 'get_context_checkpoint', lambda _: pytest.fail('Message windows must not read a summary'))
        result = send(client, session, 'WINDOW')
    assert result['success'] and len(upstream.calls) == offset + 1
    assert state.sessions.get_context_checkpoint(session['session_id']) == checkpoint
    detail = answer_detail(client, result)
    assert not any(source['kind'] == 'summary' for source in detail['sources'])
    assert '[Historical summary;' not in str(detail['request'])
    policy = {**session['effective']['context_policy'], 'strategy': 'token_budget', 'compaction': {'enabled': False}}
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': policy}}))
    switched = send(client, session, 'BACK')
    assert switched['success']
    resumed = answer_detail(client, switched)
    assert any(source['kind'] == 'summary' for source in resumed['sources']) is not attachment_change
    assert state.sessions.get_context_checkpoint(session['session_id']) == (None if attachment_change else checkpoint)
    # Historical call detail remains the policy and input captured before switching.
    assert answer_detail(client, result) == detail


@pytest.mark.parametrize('harness', [False, True])
def test_message_window_still_prunes_whole_turns_to_the_token_budget(presentation_client, harness):
    client, upstream = presentation_client
    session = configure(client, harness=harness, streaming=False)
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'tools_allowed': ['test_echo']}}))
    ok(client.patch(f"/api/models/profiles/{session['effective']['model_profile_id']}", json={'context_window_tokens': 1024}))
    session = window(client, session, 2)
    state = client.app.state.runtime_state
    user = state.messages.add_message(session['session_id'], 'user', 'large history ' * 2000)
    state.messages.add_message(session['session_id'], 'assistant', 'old answer', parent_message_id=user.message_id)
    result = send(client, session, 'CURRENT')
    assert result['success'], result
    detail = answer_detail(client, result)
    assert not any(source['kind'] == 'history' for source in detail['sources'])
    assert detail['budget']['removed_turns'] == 1
    assert detail['budget']['input_tokens'] <= detail['budget']['input_budget_tokens']
    assert len(upstream.calls) == 1
    failed = send(client, session, 'fixed input ' * 2000)
    assert failed['error_code'] == 'CONTEXT_WINDOW_EXCEEDED'
    assert len(upstream.calls) == 1


def test_window_stops_reading_at_boundary_and_history_off_reads_nothing(presentation_client, monkeypatch):
    client, _ = presentation_client
    session = window(client, configure(client, harness=False, streaming=False), 2)
    state = client.app.state.runtime_state
    for index in range(150):
        state.messages.add_message(session['session_id'], 'user', f'history-{index}')
    original = state.messages.iter_context_history
    read = []
    def counted(*args, **kwargs):
        for row in original(*args, **kwargs):
            read.append(row.message_id)
            yield row
    monkeypatch.setattr(state.messages, 'iter_context_history', counted)
    assert send(client, session)['success']
    assert len(read) == 3
    window(client, session, 2, history_enabled=False)
    monkeypatch.setattr(state.sessions, 'get_context_checkpoint', lambda _: pytest.fail('History is disabled'))
    monkeypatch.setattr(state.messages, 'context_history_counts', lambda *_: pytest.fail('History is disabled'))
    assert send(client, session)['success'] and len(read) == 3


def test_workspace_inherits_and_overrides_the_entire_history_strategy(presentation_client):
    client, _ = presentation_client
    configure(client, harness=False, streaming=False)
    policy = ContextPolicy(strategy='message_window', message_window={'max_messages': 3}).model_dump()
    project = normal_character(client, context_policy=policy)
    session = child(client, project)
    path = f"/api/sessions/{session['session_id']}"
    assert session['effective']['context_policy'] == policy
    overridden = ok(client.patch(path, json={'overrides': {'context_policy': {'strategy': 'token_budget'}}}))
    assert overridden['effective']['context_policy']['strategy'] == 'token_budget'
    policy['message_window']['max_messages'] = 7
    ok(client.patch(f"/api/characters/{project['id']}", json={'context_policy': policy}))
    assert ok(client.get(path))['effective']['context_policy']['message_window']['max_messages'] == 100
    restored = ok(client.patch(path, json={'overrides': {'context_policy': None}}))
    assert restored['effective']['context_policy'] == policy
    for invalid in ({'strategy': 'automatic'}, {'message_window': {'max_messages': 0}}):
        assert client.patch(path, json={'overrides': {'context_policy': invalid}}).status_code == 422
