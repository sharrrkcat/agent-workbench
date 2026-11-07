"""On-demand history must recover facts without summary inference or tool replay."""
import json
from dataclasses import replace
import asyncio

import pytest

from ai_workbench.core.message_parts import make_text_part
from ai_workbench.core.schema.retrieval import CONTEXT_TOOL_NAMES
from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES
from ai_workbench.core.schema.retrieval import SessionRetrievalState, RetrievalCheckpoint
from ai_workbench.core.harness.schema import HarnessState
from tests.test_phase4_harness import harness_client, configure, send
from tests.tool_fixtures import completion, ok, tool_call


def setup(client, *, tools=None, history=True, window=8192):
    session, _, profile = configure(client, tools=tools or [], streaming=False)
    ok(client.patch(f"/api/models/profiles/{profile['id']}", json={"context_window_tokens": window}))
    session = ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {"context_policy": {
        "strategy": "history_retrieval", "history_enabled": history,
        "retrieval": {"trigger_percent": 40, "target_percent": 25, "max_checkpoint_tokens": 512}}}}))
    return session, client.app.state.runtime_state


def test_empty_business_tools_support_checkpoint_and_private_history(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    seen = []
    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            current = state.messages.list_messages(session['session_id'])[-1]
            return completion(tool_call('context_checkpoint_update', {'scope': 'memory', 'text': 'SECRET_MEMORY: budget 47 EUR',
                'references': ['message:' + current.message_id]}, 'remember'))
        return completion(content='Done')
    upstream.turns = [respond] * 2
    result = send(client, session, 'The budget is 47 EUR')
    assert result['success'], result
    assert len(seen) == 2
    assert {tool['function']['name'] for tool in seen[0]['tools']} == CONTEXT_TOOL_NAMES | MEMORY_TOOL_NAMES
    saved = state.sessions.get_retrieval_state(session['session_id'])
    assert saved.memory.text == 'SECRET_MEMORY: budget 47 EUR'
    assert state.runs.get_harness_state(result['run']['run_id']) == {}
    assert 'SECRET_MEMORY' not in json.dumps(result)
    assert not CONTEXT_TOOL_NAMES.intersection(row['name'] for row in ok(client.get('/api/tools')))
    upstream.turns = [completion(content='Next')]
    result = send(client, session, 'Continue')
    assert result['success'], result.get('error')
    assert state.sessions.get_retrieval_state(session['session_id']).memory.text == saved.memory.text


def test_three_resets_keep_current_input_and_recover_old_tool_fact(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, tools=['test_echo'], history=False)
    executed, seen = [], []
    async def echo(args, context):
        executed.append(context.tool_call_id)
        return {'text': 'FACT_' + args['value'] + '=verified; ' + 'padding ' * 4200}
    state.tool_registry._tools['test_echo'] = replace(state.tool_registry.get('test_echo'), handler=echo)
    def respond(request):
        seen.append(request)
        index = len(seen) - 1
        assert 'CURRENT_MUST_SURVIVE' in json.dumps(request['messages'])
        if index < 4:
            return completion(tool_call('test_echo', {'value': str(index)}, f'call_{index}'))
        if index == 4:
            return completion(tool_call('context_read', {'source_id': 'call:call_0', 'max_tokens': 100}, 'recall'))
        assert 'FACT_0=verified' in request['messages'][-1]['content']
        return completion(content='Recovered FACT_0')
    upstream.turns = [respond] * 6
    result = send(client, session, 'CURRENT_MUST_SURVIVE')
    assert result['success'], result
    steps = state.runs.list_steps(result['run']['run_id'])
    assert len([s for s in steps if s.metadata.get('operation') == 'reset']) >= 3
    assert not [s for s in steps if s.kind == 'compaction']
    assert len(seen) == 6 and executed == [f'call_{i}' for i in range(4)]
    assert state.sessions.get_retrieval_state(session['session_id']) is None


def test_manual_reset_never_calls_model_and_does_not_restore_archived_prefix(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    for i in range(20):
        state.messages.add_message(session['session_id'], role='user', parts=[make_text_part(f'OLD_{i} ' + 'old ' * 600)])
    accepted = client.post(f"/api/sessions/{session['session_id']}/compact", json={})
    assert accepted.status_code == 202
    response = accepted.json()
    import time
    for _ in range(100):
        run = state.runs.get_run(response['run_id'])
        if run.status in {'DONE', 'FAILED'}:
            break
        time.sleep(.01)
    assert run.status == 'DONE', (run.error_code, run.error_message)
    assert run.metadata['compaction']['operation'] == 'reset'
    assert run.metadata['compaction']['input_tokens_before'] > run.metadata['compaction']['input_tokens_after']
    assert upstream.calls == []
    saved = state.sessions.get_retrieval_state(session['session_id'])
    assert saved.boundary is not None
    upstream.turns = [lambda request: completion(content='Done')]
    result = send(client, session, 'Continue')
    assert result['success'], result.get('error')
    assert 'OLD_0 ' not in json.dumps(upstream.calls[-1])
    assert state.sessions.get_retrieval_state(session['session_id']).boundary.key >= saved.boundary.key


def test_requires_harness_and_context_tools_cannot_be_selected_directly(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'harness_enabled': False}}))
    result = send(client, session)
    assert not result['success'] and result['error_code'] == 'HISTORY_RETRIEVAL_REQUIRES_HARNESS'
    assert client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'tools_allowed': ['context_read']}}).status_code == 422


def test_search_empty_page_continues_and_reads_old_fact(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    for i in range(180):
        state.messages.add_message(session['session_id'], role='user', speaker_id=session['effective']['persona_id'],
            parts=[make_text_part('UNIQUE_OLD_FACT=47' if i == 0 else f'noise_{i}')])
    seen = []
    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            return completion(tool_call('context_search', {'scope': 'history', 'query': 'UNIQUE_OLD_FACT'}, 'search1'))
        data = json.loads(request['messages'][-1]['content'])['data']
        if len(seen) == 2:
            assert data['items'] == [] and data['scanned'] == 128 and data['has_more']
            return completion(tool_call('context_search', {'scope': 'history', 'query': 'UNIQUE_OLD_FACT', 'cursor': data['next_cursor']}, 'search2'))
        if len(seen) == 3:
            assert len(data['items']) == 1 and not data['has_more']
            return completion(tool_call('context_read', {'source_id': data['items'][0]['source_id']}, 'read'))
        assert 'UNIQUE_OLD_FACT=47' in data['text'] and not data['truncated']
        assert '[Persona:' not in data['text'] and session['effective']['persona_id'] not in json.dumps(request)
        assert 'message=' not in data['text']
        return completion(content='47')
    upstream.turns = [respond] * 4
    result = send(client, session, 'Find the old fact')
    assert result['success'], result.get('error')


def test_history_off_cannot_be_bypassed_and_internal_records_do_not_recur(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, history=False)
    old = state.messages.add_message(session['session_id'], role='user', parts=[make_text_part('OLD_SECRET')])
    other, _, _ = configure(client, model=False)
    foreign = state.messages.add_message(other['session_id'], role='user', parts=[make_text_part('FOREIGN_SECRET')])
    calls = [tool_call('context_read', {'source_id': 'message:' + old.message_id}, 'old'),
        tool_call('context_read', {'source_id': 'message:' + foreign.message_id}, 'foreign'),
        tool_call('context_list', {'scope': 'history'}, 'disabled')]
    def finish(request):
        outcomes = [json.loads(m['content']) for m in request['messages'] if m['role'] == 'tool']
        assert [o['error_code'] for o in outcomes] == ['CONTEXT_SOURCE_NOT_FOUND', 'CONTEXT_SOURCE_NOT_FOUND', 'CONTEXT_HISTORY_DISABLED']
        assert 'FOREIGN_SECRET' not in json.dumps(request) and 'OLD_SECRET' not in json.dumps(request)
        return completion(content='No old history')
    upstream.turns = [completion(*calls), finish]
    result = send(client, session)
    assert result['success'], result.get('error')
    from ai_workbench.core.context_history import ConversationHistory
    from ai_workbench.core.schema.context_policy import ContextPolicy
    records = list(ConversationHistory(state.messages, session['session_id'], ContextPolicy(), None).iterate())
    assert all(not any(name in row.summary_text for name in CONTEXT_TOOL_NAMES) for row in records)
    assert state.sessions.get_retrieval_state(session['session_id']) is None


@pytest.mark.parametrize('failure', ['provider', 'cancel'])
def test_failed_or_cancelled_run_preserves_committed_memory(harness_client, failure):
    client, upstream, _ = harness_client
    session, state = setup(client)
    saved = SessionRetrievalState(session_id=session['session_id'], history_version=0, include_attachments='explicit',
        memory=RetrievalCheckpoint(text='Original'))
    state.sessions.save_retrieval_state(saved)
    def update(request):
        current = state.messages.list_messages(session['session_id'])[-1]
        return completion(tool_call('context_checkpoint_update', {'scope': 'memory', 'text': 'Candidate',
            'references': ['message:' + current.message_id]}, 'write'))
    def stop(request):
        if failure == 'cancel':
            raise asyncio.CancelledError()
        from ai_workbench.core.models.errors import ModelError
        raise ModelError('MODEL_UNAVAILABLE', 'Provider failed', 503)
    upstream.turns = [update, stop]
    result = send(client, session)
    assert not result['success']
    assert state.sessions.get_retrieval_state(session['session_id']) == saved
    assert state.runs.get_harness_state(result['run']['run_id']) == {}


def test_checkpoint_limit_rejects_candidate_and_keeps_prior_body(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    saved = SessionRetrievalState(session_id=session['session_id'], history_version=0, include_attachments='explicit',
        memory=RetrievalCheckpoint(text='Original'))
    state.sessions.save_retrieval_state(saved)
    upstream.turns = [completion(tool_call('context_checkpoint_update', {'scope': 'progress', 'text': 'too much ' * 1000,
        'references': []}, 'oversize')), lambda request: completion(content=json.loads(request['messages'][-1]['content'])['error_code'])]
    result = send(client, session)
    assert result['success'] and result['data'] == 'CONTEXT_CHECKPOINT_LIMIT'
    assert state.sessions.get_retrieval_state(session['session_id']).memory == saved.memory


def test_eight_business_and_eight_context_rounds(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, tools=['test_echo'], history=False, window=16384)
    upstream.turns = [completion(tool_call('test_echo', {'value': str(i)}, f'call_{i}')) if i % 2 else
        completion(tool_call('context_list', {'scope': 'run', 'limit': 1}, f'call_{i}')) for i in range(16)]
    upstream.turns.append(completion(content='Sixteen rounds'))
    result = send(client, session)
    assert result['success'], result.get('error')
    assert len(upstream.calls) == 17


def test_ninth_pure_context_round_is_rejected(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, history=False)
    upstream.turns = [completion(tool_call('context_list', {'scope': 'run', 'limit': 1}, f'call_{i}')) for i in range(9)]
    result = send(client, session)
    assert not result['success'] and result['error_code'] == 'TOOL_LOOP_LIMIT'
    assert len([row for row in state.messages.messages_for_run(result['run']['run_id']) if row.role == 'tool']) == 8


def test_approval_restores_retrieval_state_and_counters_without_replay(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, tools=['test_echo', 'test_approval'], history=False)
    executed = []
    async def echo(arguments, context):
        executed.append(context.tool_call_id)
        return {'content': 'padding ' * 4200}
    state.tool_registry._tools['test_echo'] = replace(state.tool_registry.get('test_echo'), handler=echo)
    upstream.turns = [completion(tool_call('test_echo', {'value': '1'}, 'first')),
        completion(tool_call('test_echo', {'value': '2'}, 'second')),
        completion(tool_call('test_approval', {'value': 'go'}, 'approval'), tool_call('context_list', {'scope': 'run'}, 'lookup'))]
    result = send(client, session)
    assert result['run']['status'] == 'WAITING_FOR_USER', result.get('error')
    run_id = result['run']['run_id']
    saved = state.runs.get_harness_state(run_id)
    assert saved['retrieval']['transcript_end'] > 0 and saved['retrieval']['business_rounds'] == 3
    invalid = {**saved, 'retrieval': {**saved['retrieval'], 'transcript_end': 1}}
    with pytest.raises(ValueError, match='complete execution'):
        HarnessState.model_validate(invalid)
    upstream.turns = [completion(content='Resumed')]
    resumed = ok(client.post(f'/api/tools/approvals/{run_id}', json={'decision': 'approve'}))
    assert resumed['run']['status'] == 'DONE', resumed
    assert executed == ['first', 'second']
    assert state.runs.get_harness_state(run_id) == {}


def test_history_edit_invalidates_memory_and_stale_commit(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    saved = SessionRetrievalState(session_id=session['session_id'], history_version=0, include_attachments='explicit',
        memory=RetrievalCheckpoint(text='Old facts'))
    state.sessions.save_retrieval_state(saved)
    upstream.turns = [completion(content='Done')]
    result = send(client, session, 'Original input')
    message_id = result['run']['metadata']['input_message_id']
    response = client.post(f'/api/messages/{message_id}/edit', json={'content': 'Changed input', 'attachment_ids': [], 'rerun': False})
    assert response.status_code == 200, response.text
    assert state.sessions.get_retrieval_state(session['session_id']) is None
    assert not state.sessions.save_retrieval_state(saved)


def test_restart_keeps_staged_checkpoint_and_pending_approval(tmp_path):
    from fastapi.testclient import TestClient
    from tests.tool_fixtures import create_tool_app, register_approval_tool, ToolOpenAI
    upstream = ToolOpenAI()
    options = {'root': tmp_path, 'database_url': f"sqlite:///{tmp_path / 'restart.db'}", 'use_memory': False,
        'adapter_factory': upstream.factory}
    app = create_tool_app(**options)
    register_approval_tool(app.state.runtime_state.tool_registry)
    with TestClient(app) as client:
        session, state = setup(client, tools=['test_approval'])
        upstream.turns = [completion(tool_call('context_checkpoint_update', {'scope': 'progress', 'text': 'Resume this task.',
            'references': []}, 'write')), completion(tool_call('test_approval', {'value': 'once'}, 'approval'))]
        result = send(client, session)
        assert result['run']['status'] == 'WAITING_FOR_USER'
        run_id = result['run']['run_id']
        saved = state.runs.get_harness_state(run_id)
    restarted = create_tool_app(**options)
    register_approval_tool(restarted.state.runtime_state.tool_registry)
    upstream.turns = [completion(content='Restored')]
    with TestClient(restarted) as client:
        state = restarted.state.runtime_state
        assert state.runs.get_harness_state(run_id) == saved
        response = ok(client.post(f'/api/tools/approvals/{run_id}', json={'decision': 'approve'}))
        assert response['run']['status'] == 'DONE', response
        assert 'Resume this task.' in json.dumps(upstream.calls[-1])
        assert state.runs.get_harness_state(run_id) == {}
        assert state.sessions.get_retrieval_state(session['session_id']).memory.text == ''
        assert client.post(f'/api/tools/approvals/{run_id}', json={'decision': 'approve'}).status_code == 409


def test_retrieval_migration_preserves_existing_records_and_files(tmp_path):
    from sqlalchemy import inspect, text
    from sqlmodel import Session
    from ai_workbench.db import migrations
    from ai_workbench.db.database import get_engine
    from ai_workbench.db.models import MessageRecord, ContextCheckpointRecord
    from tests.migration_fixtures import insert_historical_row
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.QQ_CONTEXT_COMPACTION_REVISION)
    paths = [tmp_path / name / 'keep' for name in ['models', 'attachments', 'runtimes']]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b'preserved')
    with Session(engine) as db:
        insert_historical_row(db, "sessionrecord", session_id="session", kind="ordinary", configuration_json='{"context_policy":{"strategy":"message_window"}}')
        db.add(MessageRecord(message_id='message', session_id='session', role='user', parts_json='[]'))
        db.add(ContextCheckpointRecord(session_id='session', checkpoint_json='{"summary":"preserve"}'))
        db.commit()
        before = {table: db.execute(text(f'SELECT * FROM {table}')).all() for table in ['sessionrecord', 'messagerecord', 'context_checkpoints']}
    migrations.upgrade(engine, migrations.HISTORY_RETRIEVAL_REVISION)
    assert 'context_retrieval' in inspect(engine).get_table_names()
    with Session(engine) as db:
        assert all(db.execute(text(f'SELECT * FROM {table}')).all() == rows for table, rows in before.items())
    assert all(path.read_bytes() == b'preserved' for path in paths)


def test_oversized_saved_checkpoint_is_referenced_and_read_in_ranges(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    body = 'kept original text ' * 700
    memory = RetrievalCheckpoint(text=body)
    saved = SessionRetrievalState(session_id=session['session_id'], history_version=0,
        include_attachments='explicit', memory=memory)
    state.sessions.save_retrieval_state(saved)
    seen = []
    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            assert body not in json.dumps(request)
            assert memory.checkpoint_id in json.dumps(request)
            return completion(tool_call('context_read', {'source_id': 'checkpoint:' + memory.checkpoint_id, 'max_tokens': 50}, 'read1'))
        data = json.loads(request['messages'][-1]['content'])['data']
        assert body[data['offset']:data['next_offset']] == data['text']
        assert data['truncated'] and data['next_offset'] > data['offset']
        if len(seen) == 2:
            return completion(tool_call('context_read', {'source_id': data['source_id'], 'offset': data['next_offset'], 'max_tokens': 50}, 'read2'))
        return completion(content='Read two ranges')
    upstream.turns = [respond] * 3
    result = send(client, session)
    assert result['success'], result.get('error')
    assert state.sessions.get_retrieval_state(session['session_id']).memory == memory


def test_strategy_switches_preserve_private_memory_without_injection(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    saved = SessionRetrievalState(session_id=session['session_id'], history_version=0,
        include_attachments='explicit', memory=RetrievalCheckpoint(text='PRIVATE_SWITCH_MEMORY'))
    state.sessions.save_retrieval_state(saved)
    for strategy in ['message_window', 'token_budget', 'history_retrieval']:
        ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'context_policy': {'strategy': strategy}}}))
        upstream.turns = [completion(content='Done')]
        result = send(client, session)
        assert result['success'], result.get('error')
        assert ('PRIVATE_SWITCH_MEMORY' in json.dumps(upstream.calls[-1])) == (strategy == 'history_retrieval')
        assert state.sessions.get_retrieval_state(session['session_id']).memory == saved.memory


def test_mixed_batch_counts_as_business_and_retains_only_business_history(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, tools=['test_echo', 'test_approval'])
    upstream.turns = [completion(tool_call('context_list', {'scope': 'run'}, 'context'),
        tool_call('test_echo', {'value': 'BUSINESS_FACT'}, 'business')),
        completion(tool_call('test_approval', {'value': 'go'}, 'approval'))]
    result = send(client, session)
    saved = state.runs.get_harness_state(result['run']['run_id'])
    assert saved['retrieval']['business_rounds'] == 2 and saved['retrieval']['context_rounds'] == 0
    upstream.turns = [completion(content='Done')]
    ok(client.post(f"/api/tools/approvals/{result['run']['run_id']}", json={'decision': 'approve'}))
    from ai_workbench.core.context_history import ConversationHistory
    from ai_workbench.core.schema.context_policy import ContextPolicy
    text = ''.join(row.summary_text for row in ConversationHistory(state.messages, session['session_id'], ContextPolicy(), None).iterate())
    assert 'BUSINESS_FACT' in text and 'context_list' not in text


def test_history_version_conflict_discards_candidate_but_keeps_reply(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    saved = SessionRetrievalState(session_id=session['session_id'], history_version=0,
        include_attachments='explicit', memory=RetrievalCheckpoint(text='Original'))
    state.sessions.save_retrieval_state(saved)
    def finish(request):
        state.sessions.update_session(session['session_id'], {'history_version': 1})
        return completion(content='Reply survives conflict')
    upstream.turns = [completion(tool_call('context_checkpoint_update', {'scope': 'memory', 'text': 'Candidate', 'references': []}, 'update')), finish]
    result = send(client, session)
    assert result['success'] and result['data'] == 'Reply survives conflict'
    assert state.sessions.get_retrieval_state(session['session_id']) == saved
    assert len(upstream.calls) == 2


def test_fixed_input_overflow_never_calls_model_or_resets(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    result = send(client, session, 'current input ' * 10000)
    assert not result['success'] and result['error_code'] == 'CONTEXT_WINDOW_EXCEEDED'
    assert not upstream.calls
    assert not any(step.metadata.get('operation') == 'reset' for step in state.runs.list_steps(result['run']['run_id']))


def test_list_pagination_and_deleted_source_rejection(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client)
    rows = [state.messages.add_message(session['session_id'], role='user', parts=[make_text_part('row ' + str(i))]) for i in range(30)]
    ids, seen = set(), []
    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            return completion(tool_call('context_list', {'scope': 'history', 'limit': 20}, 'page1'))
        data = json.loads(request['messages'][-1]['content'])['data']
        new_ids = {item['source_id'] for item in data['items']}
        assert not ids.intersection(new_ids) and len(data['items']) <= 20
        ids.update(new_ids)
        if data['has_more']:
            return completion(tool_call('context_list', {'scope': 'history', 'cursor': data['next_cursor']}, 'page' + str(len(seen))))
        return completion(content='Listed')
    upstream.turns = [respond] * 8
    result = send(client, session)
    assert result['success'], result.get('error')
    assert ids == {'message:' + row.message_id for row in rows}
    response = client.delete(f'/api/messages/{rows[0].message_id}')
    assert response.status_code == 200, response.text
    upstream.turns = [completion(tool_call('context_read', {'source_id': 'message:' + rows[0].message_id}, 'deleted')),
        lambda request: completion(content=json.loads(request['messages'][-1]['content'])['error_code'])]
    result = send(client, session)
    assert result['success'] and result['data'] == 'CONTEXT_SOURCE_NOT_FOUND'


def test_run_search_offsets_match_source_reads(harness_client):
    client, upstream, _ = harness_client
    session, state = setup(client, tools=['test_echo'])
    preview = []
    def read_found(request):
        found = json.loads(request['messages'][-1]['content'])['data']['items'][0]
        assert found['time']
        preview.append(found['preview'])
        return completion(tool_call('context_read', {'source_id': found['source_id'], 'offset': found['offset']}, 'read'))
    def finish(request):
        text = json.loads(request['messages'][-1]['content'])['data']['text']
        assert text.startswith(preview[0])
        return completion(content='Matching range')
    upstream.turns = [completion(tool_call('test_echo', {'value': 'padding ' * 20 + 'SEARCH_NEEDLE'}, 'business')),
        completion(tool_call('context_search', {'scope': 'run', 'query': 'SEARCH_NEEDLE'}, 'search')), read_found, finish]
    result = send(client, session)
    assert result['success'], result.get('error')
