import asyncio
import json
import time

import pytest

from tests.test_chat_presentation import presentation_client, send
from tests.test_context_compaction import setup, seed, summarize, summary_call
from tests.tool_fixtures import completion, ok
from ai_workbench.core.chat_service import ChatError


def compact(client, session):
    response = client.post(f"/api/sessions/{session['session_id']}/compact")
    assert response.status_code == 202, response.text
    run = response.json()
    deadline = time.monotonic() + 10
    while run['status'] in {'PENDING', 'RUNNING', 'CANCELLING'} and time.monotonic() < deadline:
        time.sleep(.02)
        run = ok(client.get(f"/api/runs/{run['run_id']}"))
    assert run['status'] not in {'PENDING', 'RUNNING', 'CANCELLING'}, run
    return run


def test_manual_compaction_without_auto_creates_only_an_unnumbered_event(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client)
    policy = session['context_policy']
    policy['compaction']['enabled'] = False
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'context_policy': policy}))
    seed(state, session)
    before = [m.model_dump(mode='json') for m in state.messages.list_messages(session['session_id'])]
    title = state.sessions.get_session(session['session_id']).title
    upstream.turns = [summarize] * 12
    run = compact(client, session)
    assert run['status'] == 'DONE', run
    assert run['kind'] == 'compaction' and run['metadata']['compaction']['status'] == 'compacted'
    assert all(summary_call(call) for call in upstream.calls)
    assert before == [m.model_dump(mode='json') for m in state.messages.list_messages(session['session_id'])]
    assert state.sessions.get_session(session['session_id']).title == title
    assert all(step['metadata']['llm']['message_id'] is None for step in run['steps'] if step['kind'] == 'compaction')
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    page = ok(client.get(f"/api/sessions/{session['session_id']}/history"))
    event = next(item for item in page['items'] if item['id'] == run['run_id'])
    assert event['kind'] == 'compaction' and event['number'] is None and 'messages' not in event
    assert checkpoint.summary not in json.dumps(run)
    upstream.turns = [completion(content='next answer')]
    result = send(client, session, 'NEXT INPUT')
    assert result['success']
    assert any(checkpoint.summary in (m.get('content') or '') for m in upstream.calls[-1]['messages'])
    assert client.post(f"/api/runs/{run['run_id']}/retry").status_code == 400
    assert client.delete(f"/api/runs/{run['run_id']}").status_code == 400


@pytest.mark.parametrize('history,reason', [(False, 'no_history'), (True, 'below_target')])
def test_manual_noop_does_not_generate(presentation_client, history, reason):
    client, upstream = presentation_client
    session, state = setup(client)
    if history:
        state.messages.add_message(session['session_id'], 'user', 'short')
    run = compact(client, session)
    assert run['status'] == 'DONE'
    assert run['metadata']['compaction']['reason'] == reason
    assert not upstream.calls


def test_manual_fixed_only_native_count_frame_never_becomes_history(presentation_client, monkeypatch):
    client, upstream = presentation_client
    session, state = setup(client)
    state.messages.add_message(session['session_id'], 'user', 'real history')
    measure = state.model_manager.measure_chat
    frames = []
    async def native_shape(profile, request, limits):
        assert any(message.role == 'user' for message in request.messages), 'No user query found in messages.'
        frames.append(request.model_dump())
        return await measure(profile, request, limits)
    monkeypatch.setattr(state.model_manager, 'measure_chat', native_shape)
    assert compact(client, session)['status'] == 'DONE'
    assert frames[0]['messages'][-1]['content'] == ''
    assert len(state.messages.list_messages(session['session_id'])) == 1
    assert not upstream.calls


@pytest.mark.parametrize('policy', [{'history_enabled': False}, {'strategy': 'message_window'}])
def test_manual_policy_and_body_rejection_preserve_history(presentation_client, policy):
    client, _ = presentation_client
    session, state = setup(client)
    path = f"/api/sessions/{session['session_id']}/compact"
    assert client.post(path, json={'target_percent': 1}).status_code == 422
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'context_policy': policy}))
    assert client.post(path).status_code == 409
    assert not state.runs.list_runs(session['session_id'])
    assert not state.messages.list_messages(session['session_id'])


def test_manual_failure_is_failed_even_when_original_fits(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client, trigger=90, target=15, summary=128)
    seed(state, session, count=3)
    upstream.turns = [completion(content='')]
    run = compact(client, session)
    assert run['status'] == 'FAILED' and run['error_code'] == 'CONTEXT_COMPACTION_FAILED', run
    assert state.sessions.get_context_checkpoint(session['session_id']) is None
    assert len(upstream.calls) == 1


def test_manual_compacts_below_automatic_trigger(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client, trigger=90, target=15, summary=128)
    seed(state, session, count=4)
    upstream.turns = [summarize] * 4
    run = compact(client, session)
    assert run['status'] == 'DONE', run
    result = run['metadata']['compaction']
    assert result['status'] == 'compacted'
    assert result['input_tokens_after'] < result['input_tokens_before'] < (4096 - 1024 - 410) * .9


def test_manual_cancel_busy_and_boundary_snapshot(presentation_client, monkeypatch):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)

    async def scenario():
        entered = asyncio.Event()
        original = upstream.handle
        async def waiting(request):
            if request.url.path.endswith('/chat/completions'):
                entered.set()
                await asyncio.Event().wait()
            return await original(request)
        monkeypatch.setattr(upstream, 'handle', waiting)
        service = state.runtime.manual_compaction
        run = service.start(state.sessions.get_session(session['session_id']))
        with pytest.raises(ChatError, match='Cancel the active run'):
            service.start(state.sessions.get_session(session['session_id']))
        await asyncio.wait_for(entered.wait(), 10)
        state.active_runs.cancel(run.run_id)
        await asyncio.gather(*state.active_runs._tasks.values())
        await asyncio.sleep(0)
        assert state.runs.get_run(run.run_id).status == 'CANCELLED'
        assert state.sessions.get_context_checkpoint(session['session_id']) is None
        assert state.active_runs.active_count() == 0
    client.portal.call(scenario)


def test_message_entry_recognizes_command_without_message(presentation_client):
    client, _ = presentation_client
    session, state = setup(client)
    result = send(client, session, '  /compact  ')
    assert result['run']['kind'] == 'compaction' and result['messages'] == []
    assert not state.messages.list_messages(session['session_id'])
    assert client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': '/compact extra'}).status_code == 422


def test_command_rejects_attachments_before_decoding_or_storing_them(presentation_client, monkeypatch):
    client, _ = presentation_client
    session, state = setup(client)
    monkeypatch.setattr('ai_workbench.api.routes.messages.validate_attachments', lambda *_, **__: pytest.fail('Decoded command attachment'))
    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={
        'content': '/compact', 'attachments': [{'data_url': 'invalid but never decoded'}]})
    assert response.status_code == 422 and response.json()['error']['code'] == 'INVALID_COMPACTION_COMMAND'
    assert not state.messages.list_messages(session['session_id']) and not state.runs.list_runs(session['session_id'])


def test_workspace_snapshot_and_history_cutoff_survive_later_changes(presentation_client, monkeypatch):
    from tests.test_projects import workspace, child
    client, upstream = presentation_client
    ordinary, state = setup(client)
    project = workspace(client, model_profile_id=ordinary['model_profile_id'], context_policy=ordinary['context_policy'],
                        system_prompt='PROJECT_FIXED')
    session = child(client, project)
    seed(state, session)
    original_end = state.messages.list_messages(session['session_id'])[-1]
    upstream.turns = [summarize] * 12
    def reject_retrieval(**_):
        pytest.fail('Manual compaction queried Knowledge')
    monkeypatch.setattr(state.chat_runner.knowledge_service, 'search', reject_retrieval)
    async def scenario():
        run = state.runtime.manual_compaction.start(state.sessions.get_session(session['session_id']))
        state.chat_service.update_session(session['session_id'], {'overrides': {'context_policy': {'history_enabled': False}}})
        state.messages.add_message(session['session_id'], 'user', 'FACT_999=value999; NEW AFTER CAPTURE')
        task = state.active_runs._tasks[run.run_id]
        await task
        assert state.runs.get_run(run.run_id).status == 'DONE'
        snapshot = state.runs.get_config_snapshot(run.run_id)
        assert snapshot['context_policy']['history_enabled'] is True
        assert snapshot['project_system_prompt'] == 'PROJECT_FIXED'
        checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
        assert checkpoint and (checkpoint.boundary_created_at, checkpoint.boundary_message_id) <= (original_end.created_at, original_end.message_id)
        assert 'FACT_999' not in checkpoint.summary
        assert all('NEW AFTER CAPTURE' not in json.dumps(call) for call in upstream.calls)
    client.portal.call(scenario)


@pytest.mark.parametrize('finish', ['length', 'tool_calls'])
def test_manual_invalid_summary_preserves_existing_checkpoint(presentation_client, finish):
    client, upstream = presentation_client
    session, state = setup(client)
    seed(state, session)
    upstream.turns = [summarize] * 12
    assert compact(client, session)['status'] == 'DONE'
    checkpoint = state.sessions.get_context_checkpoint(session['session_id'])
    seed(state, session, 12)
    response = completion(content='invalid replacement')
    response['finish_reason'] = finish
    upstream.turns = [response]
    run = compact(client, session)
    assert run['status'] == 'FAILED'
    assert state.sessions.get_context_checkpoint(session['session_id']) == checkpoint


def test_manual_fixed_prompt_overflow_and_explicit_summary_cap(presentation_client):
    client, upstream = presentation_client
    session, state = setup(client, summary=10000)
    seed(state, session)
    run = compact(client, session)
    assert run['status'] == 'FAILED' and not upstream.calls
    assert state.sessions.get_context_checkpoint(session['session_id']) is None
    state.personas.update(session['persona_id'], {'system_prompt': 'fixed ' * 6000})
    run = compact(client, session)
    assert run['error_code'] == 'CONTEXT_WINDOW_EXCEEDED'


def test_manual_immediate_cancel_marks_terminal(presentation_client):
    client, _ = presentation_client
    session, state = setup(client)
    async def scenario():
        run = state.runtime.manual_compaction.start(state.sessions.get_session(session['session_id']))
        state.active_runs.cancel(run.run_id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert state.runs.get_run(run.run_id).status == 'CANCELLED'
        assert state.active_runs.active_count() == 0
    client.portal.call(scenario)
