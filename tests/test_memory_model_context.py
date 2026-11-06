"""Model-facing memory stays concise while internal ownership and commits remain strict."""

import json

import pytest

from tests.test_characters import client_pair, character, child
from tests.test_durable_memory import add, write_turn
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ok, completion, tool_call


def results(request):
    return {message['tool_call_id']: json.loads(message['content'])
        for message in request['messages'] if message['role'] == 'tool'}


def clean_request(request, owner, session):
    wire = json.dumps({'messages': request['messages'], 'tools': request.get('tools')}, ensure_ascii=False)
    for text in ('[Persona:', '[User-message ID:', 'character', 'persona', 'session=', 'session_id',
                 'pool', 'revision', 'pending', 'source_message_ids', 'commit only', 'until the run succeeds',
                 owner['id'], owner['persona_id'], session['session_id']):
        assert text.lower() not in wire.lower(), text


@pytest.mark.parametrize('strategy', ['token_budget', 'message_window', 'history_retrieval'])
def test_clean_memory_protocol_and_sequential_candidate_changes(client_pair, strategy):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic',
        context_policy={'strategy': strategy})
    ok(client.patch(f"/api/personas/{owner['persona_id']}", json={'background': '用户喜欢简短回答😀'}))
    session = child(client, owner)
    baseline = add(client, owner, owner['persona_id'], summary='Known preference', body='Prefers quiet rooms.')
    ids = []

    def list_and_search(request):
        ids.append(results(request)['remember']['data']['id'])
        return completion(tool_call('memory_list', '{}', 'list'),
            tool_call('memory_search', {'query': 'quiet'}, 'search'))

    def read_new(request):
        for name in ('list', 'search'):
            data = results(request)[name]['data']
            assert set(data) == {'items', 'total', 'next_offset'}
            assert data['items'] == [{'id': baseline['id'], 'summary': 'Known preference',
                'date': baseline['observed_at'][:10]}]
        return completion(tool_call('memory_read', {'ids': ids}, 'read'))

    def update_new(request):
        item, = results(request)['read']['data']['items']
        assert set(item) == {'id', 'summary', 'body', 'observed_at'}
        assert item['body'] == 'The user prefers oolong tea.'
        return completion(tool_call('memory_write', {'id': ids[0], 'summary': 'Prefers coffee',
            'body': 'The user now prefers coffee.'}, 'update'))

    def read_updated(request):
        assert results(request)['update']['data'] == {'id': ids[0]}
        return completion(tool_call('memory_read', {'ids': ids}, 'read-updated'))

    def forget_new(request):
        assert results(request)['read-updated']['data']['items'][0]['body'] == 'The user now prefers coffee.'
        return completion(tool_call('memory_forget', {'id': ids[0]}, 'forget'))

    def finish(request):
        assert results(request)['forget']['data'] == {'id': ids[0]}
        assert state.memory.store.get(ids[0]) is None
        return completion(content='Understood.')

    upstream.turns = [write_turn, list_and_search, read_new, update_new, read_updated, forget_new, finish]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages",
        json={'content': '我喜欢乌龙茶😀，现在改为咖啡，最后请忘记这项偏好。'}))
    assert response['success'], response
    assert response['run']['metadata']['memory'] == {'status': 'saved', 'count': 3}
    entry = state.memory.store.get(ids[0])
    assert entry.status == 'deleted' and entry.revision == 3
    assert entry.origin.run_id == response['run']['run_id'] and entry.origin.evidence == []
    for request in upstream.calls:
        clean_request(request, owner, session)
    assert '<user_background>' in upstream.calls[0]['messages'][0]['content']
    assert state.memory.get(baseline['id']).character_id == owner['id']


@pytest.mark.parametrize('known_via', ['recall', 'memory_list', 'memory_search', 'memory_read', 'unread'])
def test_existing_updates_use_internal_read_versions(client_pair, monkeypatch, known_via):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}/messages"
    upstream.turns = [write_turn, completion(content='Understood.')]
    ok(client.post(path, json={'content': 'I prefer oolong tea.'}))
    entry = state.memory.list().items[0]
    if known_via != 'recall':
        def no_automatic_recall(context, trace, work, query, capacity):
            work.allowance = 1024
            return context, trace
        monkeypatch.setattr(state.chat_runner.durable_memory, 'recall', no_automatic_recall)
    update = completion(tool_call('memory_write', {'id': entry.id, 'summary': 'Coffee', 'body': 'Prefers coffee.'}, 'update'))
    calls = []
    if known_via.startswith('memory_'):
        arguments = {'ids': [entry.id]} if known_via == 'memory_read' else {'query': 'oolong'} if known_via == 'memory_search' else {}
        calls.append(completion(tool_call(known_via, json.dumps(arguments), 'discover')))
    upstream.turns = [*calls, update, completion(content='Understood.')]
    response = ok(client.post(path, json={'content': 'Now I prefer coffee.'}))
    assert response['success'], response
    current = state.memory.get(entry.id)
    if known_via == 'unread':
        assert current.revision == 1
        assert results(upstream.calls[-1])['update']['error_code'] == 'MEMORY_READ_REQUIRED'
    else:
        assert current.revision == 2 and current.body == 'Prefers coffee.'
        assert current.origin.run_id == response['run']['run_id'] and current.origin.evidence == []
        upstream.turns = [completion(tool_call('memory_read', {'ids': [entry.id]}, 'read')),
            completion(tool_call('memory_forget', {'id': entry.id}, 'forget')), completion(content='Understood.')]
        assert ok(client.post(path, json={'content': 'Forget that preference.'}))['success']
        assert state.memory.store.get(entry.id).status == 'deleted'
    for request in upstream.calls:
        clean_request(request, owner, session)


@pytest.mark.parametrize('operation,extra', [
    ('memory_write', {'source_message_ids': ['invented']}),
    ('memory_write', {'expected_revision': 1}), ('memory_forget', {'expected_revision': 1}),
])
def test_removed_model_parameters_are_rejected(client_pair, operation, extra):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    session = child(client, owner)
    arguments = {'summary': 'Tea', 'body': 'Prefers tea.'} if operation == 'memory_write' else {'id': 'unknown'}
    upstream.turns = [completion(tool_call(operation, {**arguments, **extra}, 'invalid')), completion(content='Understood.')]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer tea.'}))
    assert response['success'] and state.memory.list().total == 0
    assert results(upstream.calls[-1])['invalid']['error_code'] == 'TOOL_INVALID_ARGUMENTS'


def test_run_provenance_invalidates_memory_without_message_evidence(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    session = child(client, owner)
    upstream.turns = [write_turn, completion(content='Understood.')]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer oolong tea.'}))
    entry = state.memory.get(state.memory.list().items[0].id)
    with state.memory.store.transaction() as db:
        state.memory.store.invalidate_history([response['run']['metadata']['input_message_id']], [], transaction=db)
    assert state.memory.get(entry.id).status == 'active' and entry.origin.evidence == []
    ok(client.delete(f"/api/runs/{response['run']['run_id']}"))
    assert state.memory.get(entry.id).status == 'needs_review'


def test_user_authored_markers_are_preserved(client_pair):
    client, upstream, _ = client_pair
    configure_model(client)
    session = child(client, character(client))
    text = '[Persona: user-written]\n[User-message ID: user-written]\ncharacter=example; revision=1'
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': text}))
    assert response['success']
    assert upstream.calls[-1]['messages'][-1]['content'] == text


def test_retry_and_edit_keep_clean_history_and_internal_identity(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client)
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}/messages"
    first = ok(client.post(path, json={'content': '第一条😀'}))
    second = ok(client.post(path, json={'content': '第二条😀'}))
    retried = ok(client.post(f"/api/runs/{second['run']['run_id']}/retry"))
    assert retried['success'], retried
    input_id = second['run']['metadata']['input_message_id']
    edited = ok(client.post(f'/api/messages/{input_id}/edit', json={'content': '修改😀', 'attachment_ids': []}))
    assert edited['success'], edited
    assert state.messages.get_message(input_id).speaker_id == owner['persona_id']
    assert state.messages.get_message(first['run']['metadata']['input_message_id']).speaker_id == owner['persona_id']
    assert [message['content'] for message in upstream.calls[-1]['messages'] if message['role'] == 'user'] == ['第一条😀', '修改😀']
    for request in upstream.calls:
        clean_request(request, owner, session)
