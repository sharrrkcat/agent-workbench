from tests.chat_fixtures import create_chat
import json
import re
import asyncio

import pytest

from ai_workbench.core.compaction_generation import SUMMARY_INSTRUCTION
from ai_workbench.core.schema.context_policy import ContextPolicy
from tests.test_chat_presentation import presentation_client, configure, send
from tests.tool_fixtures import completion, ok, tool_call


def setup(client, *, trigger=50, target=35, summary=512, harness=False):
    session = configure(client, harness=harness, streaming=False)
    ok(client.patch(f"/api/models/profiles/{session['effective']['model_profile_id']}", json={'context_window_tokens': 4096}))
    policy = ContextPolicy(compaction={'trigger_percent': trigger, 'target_percent': target,
                                      'max_summary_tokens': summary}).model_dump()
    session = ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': policy}}))
    return session, client.app.state.runtime_state


def seed(state, session, start=0, count=12):
    for i in range(start, start + count):
        user = state.messages.add_message(session['session_id'], 'user', f'FACT_{i}=value{i}; ' + 'padding ' * 110,
            speaker_id=session['effective']['persona_id'])
        state.messages.add_message(session['session_id'], 'assistant', 'Recorded.', parent_message_id=user.message_id)


def summary_call(data):
    return data['messages'][0]['content'] == SUMMARY_INSTRUCTION


def summarize(data):
    if not summary_call(data):
        return completion(content='Answer.')
    facts = list(dict.fromkeys(re.findall(r'FACT_\d+=value\d+;', data['messages'][1]['content'])))
    return {**completion(content='## Confirmed facts\n' + '\n'.join(facts)),
            'usage': {'prompt_tokens': 500, 'completion_tokens': 100, 'total_tokens': 600}}


def test_three_compactions_preserve_coverage_and_private_immutable_inputs(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client)
    assert state.provider_profiles.list()[0].connection.concurrency == 1
    upstream.turns = [summarize] * 40
    previous = None
    old_detail = None
    for cycle in range(3):
        seed(state, session, cycle * 12)
        result = send(client, session, f'CURRENT-{cycle}')
        assert result['success'], result
        cp = state.sessions.get_context_checkpoint(session['session_id'])
        assert cp is not None and (previous is None or cp.boundary_created_at > previous.boundary_created_at)
        assert f'CURRENT-{cycle}' not in cp.summary
        assert cp.input_tokens_after <= 4096 - 1024 - 410
        steps = state.runs.list_steps(result['run']['run_id'])
        summaries = [step for step in steps if step.kind == 'compaction']
        assert 1 <= len(summaries) <= 4
        assert all(step.metadata['llm']['message_id'] is None for step in summaries)
        assert all(step.status == 'completed' for step in summaries)
        answer = next(step for step in steps if step.kind == 'model')
        detail = ok(client.get(f"/api/runs/{result['run']['run_id']}/steps/{answer.step_id}/context"))
        wire = '\n'.join(m['content'] for m in detail['request']['messages'])
        for i in range((cycle + 1) * 12):
            assert wire.count(f'FACT_{i}=value{i};') == 1
        assert detail['request'] == upstream.calls[-1]
        assert any(s['kind'] == 'summary' and s['compaction']['checkpoint_id'] == cp.checkpoint_id for s in detail['sources'])
        public = ok(client.get(f"/api/runs/{result['run']['run_id']}"))
        assert cp.summary not in json.dumps(public, ensure_ascii=False)
        first = summaries[0]
        summary_detail = ok(client.get(f"/api/runs/{result['run']['run_id']}/steps/{first.step_id}/context"))
        assert not summary_detail['request'].get('tools')
        if old_detail:
            assert ok(client.get(old_detail[0])) == old_detail[1]
        old_detail = (f"/api/runs/{result['run']['run_id']}/steps/{answer.step_id}/context", detail)
        previous = cp
    assert len(state.messages.list_messages(session['session_id'])) == 3 * (24 + 2)
    for call in filter(summary_call, upstream.calls):
        assert not call.get('tools') and not call['stream'] and call['temperature'] == 0
        assert call['max_tokens'] == 512
        assert '[Persona:' not in json.dumps(call) and session['effective']['persona_id'] not in json.dumps(call)
        assert '; message=' not in json.dumps(call)


@pytest.mark.parametrize('failure', ['empty', 'length', 'tool', 'large'])
@pytest.mark.parametrize('fits', [True, False])
def test_failed_compaction_keeps_original_or_stops_without_checkpoint(presentation_client, failure, fits):
    client, upstream = presentation_client
    session, state = setup(client, trigger=20, target=10)
    seed(state, session, count=7 if fits else 35)
    failed = {'empty': completion(content=''), 'length': completion(content='partial', finish='length'),
              'tool': completion(tool_call()), 'large': completion(content='unhelpful ' * 4000)}[failure]
    upstream.turns = [lambda data: failed if summary_call(data) else completion(content='Answer.')] * 8
    result = send(client, session)
    assert state.sessions.get_context_checkpoint(session['session_id']) is None
    assert result['success'] is fits, result
    if fits:
        user = state.messages.get_message(result['run']['metadata']['input_message_id'])
        assert 'context_compaction_failed' in user.metadata['request_warnings']['codes']
        assert not summary_call(upstream.calls[-1])
    else:
        assert result['error_code'] == 'CONTEXT_COMPACTION_FAILED'
        assert all(summary_call(call) for call in upstream.calls)


def test_disable_history_reuse_checkpoint_and_history_mutation(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    upstream.turns = [summarize] * 20
    first = send(client, session)
    assert first['success'], first
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    policy = session['effective']['context_policy']
    policy['history_enabled'] = False
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': policy}}))
    assert send(client, session, 'History off')['success']
    assert 'FACT_' not in json.dumps(upstream.calls[-1])
    assert state.sessions.get_context_checkpoint(session['session_id']) == checkpoint
    policy['history_enabled'] = True
    policy['compaction']['enabled'] = False
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': policy}}))
    offset = len(upstream.calls)
    assert send(client, session, 'Reuse')['success']
    assert len(upstream.calls) == offset + 1 and checkpoint.summary in json.dumps(upstream.calls[-1], ensure_ascii=False).replace('\\n', '\n')
    old = state.messages.list_messages(session['session_id'])[0]
    ok(client.delete(f'/api/messages/{old.message_id}'))
    assert state.sessions.get_context_checkpoint(session['session_id']) is None


@pytest.mark.parametrize('policy', [{'max_messages': 5}, {'max_chars': 50}, {'history_enabled': 1},
    {'compaction': {'trigger_percent': 40, 'target_percent': 40}}, {'compaction': {'trigger_percent': 99.5}},
    {'compaction': {'max_summary_tokens': 0}}])
def test_new_policy_rejects_old_or_invalid_values(presentation_client, policy):
    client, _ = presentation_client
    assert create_chat(client, overrides={'context_policy': policy}).status_code == 422


def test_history_edit_rolls_back_checkpoint_invalidation(presentation_client):
    from sqlalchemy import event
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    upstream.turns = [summarize] * 12
    result = send(client, session)
    assert result['success']
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    if hasattr(state.history.store, 'engine'):
        def fail(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith('DELETE FROM context_checkpoints'):
                raise RuntimeError('checkpoint rollback')
        event.listen(state.history.store.engine, 'before_cursor_execute', fail)
        try:
            with pytest.raises(RuntimeError, match='checkpoint rollback'):
                state.history.delete_reply(result['run']['run_id'])
        finally:
            event.remove(state.history.store.engine, 'before_cursor_execute', fail)
        assert state.sessions.get_context_checkpoint(session['session_id']) == checkpoint
        assert state.runs.get_run(result['run']['run_id']).status == 'DONE'
    state.history.delete_reply(result['run']['run_id'])
    assert state.sessions.get_context_checkpoint(session['session_id']) is None


def test_attachment_policy_and_version_reject_stale_checkpoint(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    upstream.turns = [summarize] * 12
    assert send(client, session)['success']
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    state.sessions.update_session(session['session_id'], {'history_version': checkpoint.history_version + 1})
    assert state.sessions.save_context_checkpoint(checkpoint.model_copy(update={'summary': 'STALE'})) is False
    policy = session['effective']['context_policy']
    policy['include_attachments'] = 'none'
    policy['compaction']['enabled'] = False
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': policy}}))
    assert send(client, session)['success']
    assert state.sessions.get_context_checkpoint(session['session_id']) is None
    assert '[Historical summary;' not in json.dumps(upstream.calls[-1])


def test_cancellation_does_not_commit_and_retains_dispatched_snapshot(presentation_client, monkeypatch):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    async def scenario():
        entered = asyncio.Event()
        handle = upstream.handle
        async def wait_summary(request):
            if request.url.path.endswith('/chat/completions') and summary_call(json.loads(request.content)):
                entered.set()
                await asyncio.Event().wait()
            return await handle(request)
        monkeypatch.setattr(upstream, 'handle', wait_summary)
        task = asyncio.create_task(state.chat_runner.run(session_id=session['session_id'], text='cancel'))
        await asyncio.wait_for(entered.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state.sessions.get_context_checkpoint(session['session_id']) is None
        run = state.runs.list_runs(session['session_id'])[-1]
        assert run.status == 'CANCELLED'
        step = next(s for s in state.runs.list_steps(run.run_id) if s.kind == 'compaction')
        assert step.status == 'failed'
        assert state.runs.get_context_snapshot(step.step_id).request.messages[0].content == SUMMARY_INSTRUCTION
    asyncio.run(scenario())


def test_approval_resume_freezes_compacted_base_and_never_resummarizes(presentation_client):
    from tests.tool_fixtures import register_approval_tool
    client, upstream = presentation_client
    session, state = setup(client, harness=True)
    register_approval_tool(state.tool_registry)
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'tools_allowed': ['test_approval']}}))
    seed(state, session)
    def first(data):
        return summarize(data) if summary_call(data) else completion(tool_call('test_approval', {'value': 'go'}))
    upstream.turns = [first] * 8
    paused = send(client, session)
    assert paused['run']['status'] == 'WAITING_FOR_USER', paused
    cp = state.sessions.get_context_checkpoint(session['session_id'])
    assert cp
    original = state.runs.get_harness_state(paused['run']['run_id'])
    assert cp.summary in json.dumps(original, ensure_ascii=False).replace('\\n', '\n')
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': {'history_enabled': False}}}))
    offset = len(upstream.calls)
    upstream.turns = [completion(content='Confirmed.')]
    result = ok(client.post(f"/api/tools/approvals/{paused['run']['run_id']}", json={'decision': 'approve'}))
    assert result['run']['status'] == 'DONE', result
    assert len(upstream.calls) == offset + 1 and not summary_call(upstream.calls[-1])
    assert any(m['role'] == 'tool' for m in upstream.calls[-1]['messages'])
    assert any(cp.summary in (m.get('content') or '') for m in upstream.calls[-1]['messages'])


@pytest.mark.parametrize('words,expected_calls', [(1300, 2), (7000, 4)])
def test_oversized_turn_is_split_and_commits_only_after_all_pieces(presentation_client, words, expected_calls):
    client, upstream = presentation_client
    session, state = setup(client)
    original = state.messages.add_message(session['session_id'], 'user',
        'FACT_0=value0; ' + 'padding ' * words + ' FACT_1=value1;')
    upstream.turns = [summarize] * 8
    result = send(client, session)
    calls = list(filter(summary_call, upstream.calls))
    assert len(calls) == expected_calls
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    if words == 1300:
        assert result['success'] and checkpoint.boundary_message_id == original.message_id
        assert 'FACT_0=value0;' in checkpoint.summary and 'FACT_1=value1;' in checkpoint.summary
        assert checkpoint.covered_messages == 1
    else:
        assert not result['success'] and result['error_code'] == 'CONTEXT_COMPACTION_FAILED'
        assert checkpoint is None


def test_summary_reasoning_markers_are_not_saved(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    def response(data):
        result = summarize(data)
        if summary_call(data):
            result['message']['content'] = '<think>PRIVATE REASONING</think>' + result['message']['content']
        return result
    upstream.turns = [response] * 12
    assert send(client, session)['success']
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    assert '<think>' not in checkpoint.summary and 'PRIVATE REASONING' not in checkpoint.summary


def test_explicit_summary_reserve_is_not_reduced(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client, trigger=20, target=10, summary=4096)
    seed(state, session, count=7)
    result = send(client, session)
    assert result['success']
    assert not any(summary_call(data) for data in upstream.calls)
    assert state.sessions.get_context_checkpoint(session['session_id']) is None
    assert 'context_compaction_failed' in state.messages.get_message(result['run']['metadata']['input_message_id']).metadata['request_warnings']['codes']


def test_checkpoint_survives_store_restart_and_stale_commit(presentation_client, monkeypatch):
    from ai_workbench.db.stores import SqlSessionStore
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    upstream.turns = [summarize] * 20
    assert send(client, session)['success']
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    if hasattr(state.sessions, 'engine'):
        assert SqlSessionStore(state.sessions.engine).get_context_checkpoint(session['session_id']) == checkpoint
    seed(state, session, start=12)
    monkeypatch.setattr(state.sessions, 'save_context_checkpoint', lambda _: False)
    result = send(client, session)
    assert state.sessions.get_context_checkpoint(session['session_id']) == checkpoint
    assert any(step.error_code == 'CONTEXT_COMPACTION_FAILED' for step in state.runs.list_steps(result['run']['run_id']))


def test_model_switch_can_shorten_only_the_previous_summary(presentation_client):
    from ai_workbench.core.schema.compaction import ContextCheckpoint
    from tests.model_fixtures import configure_model
    client, upstream = presentation_client
    session, state = setup(client, summary=256)
    old = state.messages.add_message(session['session_id'], 'user', 'FACT_0=value0;')
    checkpoint = ContextCheckpoint(session_id=session['session_id'], summary='FACT_0=value0; ' + 'padding ' * 1400,
        boundary_created_at=old.created_at, boundary_message_id=old.message_id, covered_messages=1,
        history_version=0, include_attachments='explicit', model_profile_id=session['effective']['model_profile_id'],
        step_id='old-summary', input_tokens_after=1600, counting='estimated')
    assert state.sessions.save_context_checkpoint(checkpoint)
    smaller = configure_model(client, alias='smaller', context_window_tokens=2048, request_options={'streaming': False})
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'model_profile_id': smaller['id']}}))
    upstream.turns = [summarize] * 8
    result = send(client, session)
    assert result['success'], result
    updated = state.sessions.get_context_checkpoint(session['session_id'])
    assert updated.checkpoint_id != checkpoint.checkpoint_id and updated.model_profile_id == smaller['id']
    assert updated.boundary_message_id == old.message_id and updated.covered_messages == 1
    assert updated.input_tokens_after < updated.input_tokens_before
    assert 'FACT_0=value0;' in updated.summary
