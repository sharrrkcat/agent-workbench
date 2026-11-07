"""Independent recall pools and atomic removal of model memories with their Runs."""

import pytest

from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES
from tests.test_characters import client_pair, character, child
from tests.test_context_detail import details
from tests.test_durable_memory import add, visible, write_turn
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ok, completion, tool_call


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('blocked', [True, False])
@pytest.mark.parametrize('isolation', ['shared', 'isolated'])
def test_independent_pools_filter_ids_search_and_model_requests(client_pair, enabled, blocked, isolation):
    client, upstream, _ = client_pair
    configure_model(client)
    owner = character(client, memory_enabled=enabled, memory_external_isolation=blocked,
        harness_enabled=True, tools_allowed=[], context_policy={'history_enabled': False})
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}"
    ok(client.post(path + '/messages', json={'content': 'Bind identity.'}))
    own = add(client, owner, owner['persona_id'], session, summary='Local violet', body='LOCAL-BODY-ONLY')
    general = add(client, owner, owner['persona_id'], pool='general', summary='General violet', body='GENERAL-BODY-ONLY')
    ok(client.patch(path, json={'memory_isolation': isolation}))
    general_readable = not blocked and isolation == 'shared'
    expected = ({own['id']} if enabled else set()) | ({general['id']} if general_readable else set())
    for query in ['', 'violet']:
        page = visible(client, session, q=query)
        assert page['total'] == len(expected)
        assert {item['id'] for item in page['items']} == expected
    for entry in [own, general]:
        assert client.get(path + '/memories/' + entry['id']).status_code == (200 if entry['id'] in expected else 404)
    result = ok(client.post(path + '/messages', json={'content': 'Recall violet.'}))
    assert result['success'], result
    request = upstream.calls[-1]
    system = '\n'.join(m['content'] for m in request['messages'] if m['role'] == 'system')
    assert (own['summary'] in system) == enabled
    assert (general['summary'] in system) == general_readable
    assert own['body'] not in system and general['body'] not in system
    assert {tool['function']['name'] for tool in request.get('tools', [])} == (MEMORY_TOOL_NAMES if enabled else set())
    assert ('<memory_instruction>' in system) == enabled
    if not enabled:
        assert 'Your own:' not in system and '(empty)' not in system and 'Memory is ' not in system
        assert ('# MEMORY' in system) == general_readable
        assert ('<memory_index>' in system) == general_readable
    snapshot, = details(client, result['run'])
    assert snapshot['request'] == request
    for source in snapshot['sources']:
        if source['kind'] in {'memory_index', 'durable_memory'}:
            content = request['messages'][source['message_index']]['content']
            assert content[source['start']:source['end']] == source['text']


def test_removed_settings_and_status_parameters_are_rejected(client_pair):
    client, _, _ = client_pair
    owner = character(client)
    assert owner['memory_enabled'] is True and 'memory_learning' not in owner
    session = child(client, owner)
    entry = add(client, owner, owner['persona_id'])
    assert client.post('/api/characters', json={'kind': 'normal', 'name': 'Old', 'memory_learning': 'manual'}).status_code == 422
    assert client.patch(f"/api/characters/{owner['id']}", json={'memory_learning': 'automatic'}).status_code == 422
    assert client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'memory_learning': 'manual'}}).status_code == 422
    for status in ['active', 'needs_review']:
        assert client.get('/api/memories', params={'status': status}).status_code == 422
        assert client.patch(f"/api/memories/{entry['id']}", json={'expected_revision': 1,
            'summary': 'Edited', 'body': 'Edited body', 'status': status}).status_code == 422


@pytest.mark.parametrize('operation', ['delete_reply', 'edit_user', 'retry', 'delete_user'])
def test_history_operations_forget_only_model_managed_current_run_memories(client_pair, operation):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[])
    session = child(client, owner)
    upstream.turns = [completion(
        tool_call('memory_write', {'summary': 'deletable-only', 'body': 'Discard this model fact.'}, 'discard'),
        tool_call('memory_write', {'summary': 'adopted-only', 'body': 'Confirm this fact.'}, 'adopt')),
        completion(content='Saved.')]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'Remember these facts.'}))
    run = response['run']
    entries = {entry.summary: entry for entry in state.memory.list().items}
    target, adopted = entries['deletable-only'], entries['adopted-only']
    published = ok(client.post(f'/api/memories/{target.id}/publish', json={'expected_revision': 1}))
    ok(client.patch(f'/api/memories/{adopted.id}', json={'expected_revision': 1,
        'summary': adopted.summary, 'body': 'Manually confirmed.'}))
    manual = add(client, owner, owner['persona_id'], session, source_message_id=run['metadata']['input_message_id'])
    consumer = child(client, owner, harness_enabled=False)
    ok(client.post(f"/api/sessions/{consumer['session_id']}/messages", json={'content': 'Recall deletable-only.'}))
    version = state.sessions.get_session(consumer['session_id']).memory_version
    upstream.turns = [completion(content='Revised answer.')]
    if operation == 'delete_reply':
        ok(client.delete(f"/api/runs/{run['run_id']}"))
    elif operation == 'edit_user':
        ok(client.post(f"/api/messages/{run['metadata']['input_message_id']}/edit", json={'content': 'Changed.', 'attachment_ids': []}))
    elif operation == 'retry':
        ok(client.post(f"/api/runs/{run['run_id']}/retry"))
    else:
        ok(client.delete(f"/api/messages/{run['metadata']['input_message_id']}"))
    assert client.get(f'/api/memories/{target.id}').status_code == 404
    deleted = state.memory.store.get(target.id)
    assert deleted.status == 'deleted' and not deleted.summary and not deleted.body and not deleted.origin.evidence
    assert state.sessions.get_session(consumer['session_id']).memory_version > version
    assert {entry.id for entry in state.memory.list(query='deletable').items} == {published['id']}
    for identifier in [adopted.id, manual['id'], published['id']]:
        assert ok(client.get(f'/api/memories/{identifier}'))['managed_by'] == 'user'


def test_deleting_an_old_run_preserves_a_memory_updated_by_a_later_run(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[])
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}/messages"
    upstream.turns = [write_turn, completion(content='Saved.')]
    first = ok(client.post(path, json={'content': 'Remember oolong.'}))
    entry, = state.memory.list().items
    upstream.turns = [completion(tool_call('memory_write', {'id': entry.id, 'summary': 'Coffee', 'body': 'Now prefers coffee.'})),
        completion(content='Updated.')]
    second = ok(client.post(path, json={'content': 'I now prefer coffee.'}))
    ok(client.delete(f"/api/runs/{first['run']['run_id']}"))
    assert state.memory.get(entry.id).origin.run_id == second['run']['run_id']
    assert state.memory.get(entry.id).body == 'Now prefers coffee.'


def test_history_failure_rolls_back_memory_and_run_removal(client_pair, monkeypatch):
    client, upstream, state = client_pair
    configure_model(client)
    session = child(client, character(client, harness_enabled=True, tools_allowed=[]))
    upstream.turns = [write_turn, completion(content='Saved.')]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'Remember oolong.'}))
    entry, = state.memory.list().items
    prune = state.history.store.prune
    def failing_prune(*args, **kwargs):
        prune(*args, **kwargs)
        raise RuntimeError('Simulated history transaction failure')
    monkeypatch.setattr(state.history.store, 'prune', failing_prune)
    with pytest.raises(RuntimeError, match='Simulated history'):
        state.history.delete_reply(response['run']['run_id'])
    assert state.memory.get(entry.id).revision == entry.revision
    assert state.runs.get_run(response['run']['run_id']).status == 'DONE'
    assert state.memory.list(query='oolong').total == 1


@pytest.mark.parametrize('choice', ['keep', 'delete'])
def test_session_deletion_honors_explicit_memory_choice(client_pair, choice):
    client, upstream, state = client_pair
    configure_model(client)
    session = child(client, character(client, harness_enabled=True, tools_allowed=[]))
    path = f"/api/sessions/{session['session_id']}"
    upstream.turns = [write_turn, completion(content='Saved.')]
    ok(client.post(path + '/messages', json={'content': 'Remember oolong.'}))
    entry, = state.memory.list().items
    preview = ok(client.get(path + '/memory-deletion-preview'))
    ok(client.request('DELETE', path, json={'expected_revision': preview['revision'], 'local': choice}))
    if choice == 'keep':
        kept = state.memory.get(entry.id)
        assert kept.managed_by == 'user' and kept.session_id is None and kept.status == 'active'
    else:
        assert client.get(f'/api/memories/{entry.id}').status_code == 404
