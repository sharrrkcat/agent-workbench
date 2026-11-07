"""Durable identity boundaries, publication and explicit deletion destinations."""

import pytest
import json

from ai_workbench.core.schema.memory import MemoryEvidence
from ai_workbench.core.memory_service import message_digest
from tests.test_characters import client_pair, character, child
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ok, completion, tool_call, register_approval_tool


def bound(client, owner, **overrides):
    session = child(client, owner, **overrides)
    ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Start this conversation."}))
    return ok(client.get(f"/api/sessions/{session['session_id']}"))


def add(client, owner, persona, session=None, **values):
    return ok(client.post("/api/memories", json={"character_id": owner["id"], "persona_id": persona,
        "session_id": session["session_id"] if session else None, "summary": "喜欢乌龙茶", "body": "用户喜欢喝乌龙茶。", **values}))


def visible(client, session, **params):
    return ok(client.get(f"/api/sessions/{session['session_id']}/memories", params=params))


def test_memory_visibility_matrix_filters_before_search_counts_and_ids(client_pair):
    client, _, _ = client_pair
    configure_model(client)
    a = ok(client.post("/api/personas", json={"name": "A"}))["id"]
    b = ok(client.post("/api/personas", json={"name": "B"}))["id"]
    ca, cb = character(client, persona_id=a), character(client, persona_id=a)
    source, target = bound(client, ca), bound(client, ca)
    other_persona, other_character = bound(client, ca, persona_id=b), bound(client, cb)
    own = add(client, ca, a, target)
    shared = add(client, ca, a, source)
    authored = add(client, ca, a)
    foreign_persona = add(client, ca, b, other_persona)
    foreign_character = add(client, cb, a, other_character)
    general = ok(client.post(f"/api/memories/{shared['id']}/publish", json={"expected_revision": 1}))
    for mode, imports in (("shared", True), ("block_outgoing", True), ("block_incoming", False), ("isolated", False)):
        ok(client.patch(f"/api/sessions/{target['session_id']}", json={"memory_isolation": mode}))
        for source_mode, exports in (("shared", True), ("block_outgoing", False), ("block_incoming", True), ("isolated", False)):
            ok(client.patch(f"/api/sessions/{source['session_id']}", json={"memory_isolation": source_mode}))
            expected = {own["id"]}
            if imports:
                expected |= {authored["id"], general["id"]}
                if exports:
                    expected.add(shared["id"])
            for query in ("", "乌龙茶", "喜欢 oolong 乌龙茶"):
                page = visible(client, target, q=query)
                assert {entry["id"] for entry in page["items"]} == expected
                assert page["total"] == len(expected)
                paged = visible(client, target, q=query, limit=1)
                assert paged["total"] == len(expected) and len(paged["items"]) == 1
            for entry in (own, shared, authored, general, foreign_persona, foreign_character):
                response = client.get(f"/api/sessions/{target['session_id']}/memories/{entry['id']}")
                assert response.status_code == (200 if entry["id"] in expected else 404)
    ok(client.patch(f"/api/sessions/{target['session_id']}", json={"memory_isolation": "shared"}))
    ok(client.patch(f"/api/sessions/{source['session_id']}", json={"memory_isolation": "shared"}))
    ok(client.patch(f"/api/characters/{ca['id']}", json={"memory_external_isolation": True}))
    assert {entry["id"] for entry in visible(client, target)["items"]} == {own["id"], shared["id"], authored["id"]}
    assert {entry["id"] for entry in visible(client, other_character)["items"]} == {general["id"], foreign_character["id"]}
    assert {entry["id"] for entry in visible(client, other_persona)["items"]} == {foreign_persona["id"]}
    ok(client.patch(f"/api/sessions/{target['session_id']}", json={"overrides": {"memory_enabled": False}}))
    assert visible(client, target)["total"] == 0
    assert ok(client.get("/api/memories"))["total"] == 6


def test_manual_versions_publication_and_forget_are_independent(client_pair):
    client, upstream, state = client_pair
    owner = character(client)
    before = len(upstream.calls)
    entry = add(client, owner, owner["persona_id"])
    payload = {"expected_revision": entry["revision"]}
    published = ok(client.post(f"/api/memories/{entry['id']}/publish", json=payload))
    assert ok(client.post(f"/api/memories/{entry['id']}/publish", json=payload))["id"] == published["id"]
    edited = ok(client.patch(f"/api/memories/{entry['id']}", json={**payload, "summary": "喜欢咖啡", "body": "现在喜欢咖啡。"}))
    assert edited["revision"] == 2 and edited["managed_by"] == "user"
    assert client.patch(f"/api/memories/{entry['id']}", json={**payload, "summary": "stale", "body": "stale"}).status_code == 409
    assert ok(client.get(f"/api/memories/{published['id']}"))["body"] == entry["body"]
    ok(client.request("DELETE", f"/api/memories/{entry['id']}", json={"expected_revision": 2}))
    assert client.get(f"/api/memories/{entry['id']}").status_code == 404
    tombstone = state.memory.store.get(entry["id"])
    assert tombstone.status == "deleted" and tombstone.body == tombstone.summary == ""
    assert ok(client.get("/api/memories", params={"q": "咖啡"}))["total"] == 0
    assert ok(client.get(f"/api/memories/{published['id']}"))["revision"] == 1
    assert len(upstream.calls) == before


def test_deleting_session_requires_choice_and_keeps_private_memories_as_shared(client_pair):
    client, _, state = client_pair
    configure_model(client)
    owner = character(client)
    source, target = bound(client, owner), bound(client, owner)
    path = f"/api/sessions/{source['session_id']}"
    ok(client.patch(path, json={"memory_isolation": "isolated"}))
    entry = add(client, owner, owner["persona_id"], source)
    published = ok(client.post(f"/api/memories/{entry['id']}/publish", json={"expected_revision": 1}))
    assert visible(client, target)["total"] == 1
    assert client.delete(path).status_code == 409
    preview = ok(client.get(path + "/memory-deletion-preview"))
    assert client.request("DELETE", path, json={"expected_revision": preview["revision"], "local": "keep"}).status_code == 409
    ok(client.request("DELETE", path, json={"expected_revision": preview["revision"], "local": "keep", "general": "delete"}))
    kept = ok(client.get(f"/api/memories/{entry['id']}"))
    assert kept["session_id"] is None and kept["origin"]["session_id"] == source["session_id"]
    assert kept["managed_by"] == "user" and kept["persona_id"] == owner["persona_id"]
    assert {item["id"] for item in visible(client, target)["items"]} == {entry["id"]}
    assert state.memory.store.get(published["id"]).status == "deleted"


@pytest.mark.parametrize("action", ["transfer", "publish", "delete"])
def test_character_deletion_destinations_and_separate_general_choice(client_pair, action):
    client, _, _ = client_pair
    configure_model(client)
    owner, destination = character(client), character(client)
    source = bound(client, owner)
    entry = add(client, owner, owner["persona_id"], source)
    published = ok(client.post(f"/api/memories/{entry['id']}/publish", json={"expected_revision": 1}))
    # A later local revision must not overwrite the publication.
    edited = ok(client.patch(f"/api/memories/{entry['id']}", json={"expected_revision": 1, "summary": "New", "body": "New text"}))
    path = f"/api/characters/{owner['id']}"
    preview = ok(client.get(path + "/memory-deletion-preview"))
    assert client.delete(path).status_code == 409
    ok(client.request("DELETE", path, json={"expected_revision": preview["revision"], "local": action,
        "target_character_id": destination["id"] if action == "transfer" else None, "general": "keep"}))
    assert client.get(path).status_code == 404
    assert ok(client.get(f"/api/memories/{published['id']}"))["body"] == entry["body"]
    if action == "transfer":
        moved = ok(client.get(f"/api/memories/{entry['id']}"))
        assert moved["character_id"] == destination["id"] and moved["session_id"] is None
        assert moved["origin"]["character_id"] == owner["id"]
        assert {item['id'] for item in ok(client.get('/api/memories', params={'origin_session_id': source['session_id'], 'pool': 'character'}))['items']} == {entry['id']}
    else:
        assert client.get(f"/api/memories/{entry['id']}").status_code == 404
        general = ok(client.get("/api/memories", params={"pool": "general"}))["items"]
        assert len(general) == (2 if action == "publish" else 1)
        if action == "publish":
            new = next(value for value in general if value["id"] != published["id"])
            assert new["summary"] == edited["summary"] and new["character_id"] == owner["id"]


def test_deletion_preview_conflict_preserves_everything(client_pair):
    client, _, _ = client_pair
    configure_model(client)
    owner = character(client)
    source = bound(client, owner)
    entry = add(client, owner, owner["persona_id"], source)
    path = f"/api/sessions/{source['session_id']}"
    preview = ok(client.get(path + "/memory-deletion-preview"))
    ok(client.patch(f"/api/memories/{entry['id']}", json={"expected_revision": 1, "summary": "Corrected", "body": "Corrected"}))
    assert client.request("DELETE", path, json={"expected_revision": preview["revision"], "local": "delete"}).status_code == 409
    assert client.get(path).status_code == 200 and client.get(f"/api/memories/{entry['id']}").status_code == 200


def test_character_publish_keeps_selected_local_version_when_existing_copy_is_deleted(client_pair):
    client, _, state = client_pair
    owner = character(client)
    entry = add(client, owner, owner['persona_id'])
    published = ok(client.post(f"/api/memories/{entry['id']}/publish", json={'expected_revision': 1}))
    path = f"/api/characters/{owner['id']}"
    preview = ok(client.get(path + '/memory-deletion-preview'))
    ok(client.request('DELETE', path, json={'expected_revision': preview['revision'], 'local': 'publish', 'general': 'delete'}))
    remaining = state.memory.list().items
    assert len(remaining) == 1 and remaining[0].pool == 'general'
    assert remaining[0].id != published['id']
    assert remaining[0].summary == entry['summary']
    assert state.memory.store.get(published['id']).status == 'deleted'


def test_source_edit_invalidates_only_model_managed_dependents(client_pair):
    client, _, state = client_pair
    configure_model(client)
    owner = character(client)
    source = bound(client, owner)
    message = next(m for m in state.messages.list_messages(source["session_id"]) if m.role == "user")
    dependent = add(client, owner, owner["persona_id"], source)
    manual = add(client, owner, owner["persona_id"], source)
    unrelated = add(client, owner, owner["persona_id"])
    record = state.memory.store.get(dependent["id"])
    record.managed_by = "model"
    record.origin.evidence = [MemoryEvidence(message_id=message.message_id, digest=message_digest(message))]
    record.revision += 1
    with state.memory.store.transaction() as db:
        state.memory.store.save(record, 1, transaction=db)
    ok(client.post(f"/api/messages/{message.message_id}/edit", json={"content": "Changed user statement", "attachment_ids": []}))
    assert ok(client.get(f"/api/memories/{dependent['id']}"))["status"] == "needs_review"
    assert ok(client.get(f"/api/memories/{manual['id']}"))["status"] == "active"
    assert ok(client.get(f"/api/memories/{unrelated['id']}"))["status"] == "active"


def write_turn(request):
    return completion(tool_call("memory_write", {"summary": "Prefers oolong tea", "body": "The user prefers oolong tea."}, "remember"))


def test_harness_stages_then_commits_and_cross_session_recalls(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning="automatic")
    session = child(client, owner)
    def finish(request):
        assert state.memory.list().total == 0
        results = [json.loads(m["content"]) for m in request["messages"] if m["role"] == "tool"]
        assert results[-1]["status"] == "success" and set(results[-1]["data"]) == {"id"}
        return completion(content="I will remember your tea preference.")
    upstream.turns = [write_turn, finish]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Please remember that I prefer oolong tea."}))
    assert response["success"], response
    assert response["run"]["metadata"]["memory"] == {"status": "saved", "count": 1}
    tool_result = next(part for message in response['messages'] for part in message['parts'] if part['type'] == 'tool_result')
    assert tool_result['data'] == {'private_context': True, 'count': 0, 'truncated': False, 'pending': True}
    entry = state.memory.store.query()[0][0]
    assert entry.session_id == session["session_id"] and entry.managed_by == "model"
    assert entry.origin.run_id == response["run"]["run_id"] and entry.origin.evidence == []
    assert len([event for event in state.run_events.list_events(response["run"]["run_id"]) if event.type == "run_completed"]) == 1
    second = child(client, owner)
    ok(client.post(f"/api/sessions/{second['session_id']}/messages", json={"content": "Which tea do I prefer?"}))
    assert f"{entry.id}: Prefers oolong tea" in upstream.calls[-1]['messages'][0]['content']
    assert "The user prefers oolong tea." not in json.dumps(upstream.calls[-1])


def test_memory_tools_switch_as_one_group_without_disabling_recall(client_pair):
    from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=['test_echo'], memory_learning='automatic')
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}"
    upstream.turns = [write_turn, completion(content='Remembered.')]
    assert ok(client.post(path + '/messages', json={'content': 'I prefer oolong tea.'}))['success']
    entry = state.memory.list().items[0]
    assert {tool['function']['name'] for tool in upstream.calls[-1]['tools']} == MEMORY_TOOL_NAMES | {'test_echo'}
    settings = ok(client.patch(path, json={'overrides': {'memory_learning': 'manual'}}))
    assert settings['effective']['memory_enabled'] is True
    upstream.turns = [completion(tool_call('memory_write', {'summary': 'Wrong', 'body': 'Wrong'}, 'write'),
        tool_call('memory_forget', {'id': entry.id}, 'forget')), completion(content='Oolong tea.')]
    result = ok(client.post(path + '/messages', json={'content': 'Which tea do I prefer?'}))
    assert result['success'] and state.memory.get(entry.id).revision == 1
    assert {tool['function']['name'] for tool in upstream.calls[-1]['tools']} == {'test_echo'}
    assert f'{entry.id}: Prefers oolong tea' in upstream.calls[-1]['messages'][0]['content']
    assert 'The user prefers oolong tea.' not in upstream.calls[-1]['messages'][0]['content']
    errors = [part['error_code'] for message in result['messages'] for part in message['parts'] if part['type'] == 'tool_result']
    assert errors == ['TOOL_NOT_ALLOWED', 'TOOL_NOT_ALLOWED']
    # Restoring inheritance enables the whole group again without changing ordinary tools.
    ok(client.patch(path, json={'overrides': {'memory_learning': None}}))
    upstream.turns = [completion(tool_call('memory_write', {'id': entry.id, 'summary': 'Coffee', 'body': 'Prefers coffee.'})), completion(content='Updated.')]
    assert ok(client.post(path + '/messages', json={'content': 'I now prefer coffee.'}))['success']
    assert state.memory.get(entry.id).body == 'Prefers coffee.'
    assert {tool['function']['name'] for tool in upstream.calls[-1]['tools']} == MEMORY_TOOL_NAMES | {'test_echo'}


@pytest.mark.parametrize("finish", ["content_filter", "removed_parameter", "approval_cancel"])
def test_unsuccessful_or_unsupported_capture_never_commits(client_pair, finish):
    client, upstream, state = client_pair
    configure_model(client)
    register_approval_tool(state.tool_registry)
    owner = character(client, harness_enabled=True, tools_allowed=["test_approval"], memory_learning="automatic")
    session = child(client, owner)
    if finish == "removed_parameter":
        upstream.turns = [completion(tool_call("memory_write", {"summary": "Guess", "body": "Assistant guess.",
            "source_message_ids": ["invented"]})), completion(content="I cannot save an unsupported fact.")]
    elif finish == "approval_cancel":
        upstream.turns = [write_turn, completion(tool_call("test_approval"))]
    else:
        upstream.turns = [write_turn, completion(content="refused", finish="content_filter")]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "I prefer oolong tea."}))
    assert state.memory.list().total == 0
    if finish == "approval_cancel":
        assert response["run"]["status"] == "WAITING_FOR_USER"
        ok(client.post(f"/api/runs/{response['run']['run_id']}/cancel"))
    assert state.memory.list().total == 0


def test_memory_conflict_preserves_answer_and_discards_entire_batch(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning="automatic")
    session = child(client, owner)
    upstream.turns = [write_turn, completion(content="Saved.")]
    first = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "I prefer oolong tea."}))
    assert first["success"]
    entry = state.memory.store.query()[0][0]
    def propose(request):
        return completion(tool_call("memory_write", {"id": entry.id,
            "summary": "Now coffee", "body": "The user now prefers coffee."}, "update"),
            tool_call("memory_write", {"summary": "Evening drink", "body": "The user drinks tea in the evening."}, "new"))
    def concurrent_edit(_request):
        from ai_workbench.core.schema.memory import MemoryEdit
        state.memory.edit(entry.id, MemoryEdit(expected_revision=entry.revision, summary="Manual truth", body="Manually corrected."))
        return completion(content="Your answer remains available.")
    upstream.turns = [propose, concurrent_edit]
    second = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "I now prefer coffee and drink tea in the evening."}))
    assert second["success"] and second["run"]["metadata"]["memory"]["status"] == "not_saved"
    assert state.memory.list().total == 1 and state.memory.get(entry.id).body == "Manually corrected."


def test_same_fact_staged_twice_commits_once(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    session = child(client, owner)
    def repeat(request):
        response = write_turn(request)
        response['message']['tool_calls'][0]['id'] = 'second-proposal'
        return response
    upstream.turns = [write_turn, repeat, completion(content='Done.')]
    response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer oolong tea.'}))
    assert response['success']
    assert response['run']['metadata']['memory'] == {'status': 'saved', 'count': 1}
    assert state.memory.list().total == 1


def test_recalled_memory_revocation_blocks_approval_resume(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    register_approval_tool(state.tool_registry)
    owner = character(client, harness_enabled=True, tools_allowed=["test_approval"])
    entry = add(client, owner, owner["persona_id"], summary="Private code", body="The private code is SEQUOIA-593.")
    session = child(client, owner)
    upstream.turns = [completion(tool_call("test_approval")), completion(content="Should never be requested.")]
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "What is my private code?"}))
    assert result["run"]["status"] == "WAITING_FOR_USER"
    count = len(upstream.calls)
    state.memory.delete(entry["id"], entry["revision"])
    resumed = ok(client.post(f"/api/tools/approvals/{result['run']['run_id']}", json={"decision": "approve"}))
    assert resumed["run"]["status"] == "FAILED" and resumed["run"]["error_code"] == "MEMORY_VIEW_CHANGED"
    assert len(upstream.calls) == count
    assert state.memory.list().total == 0


def test_acceptance_failure_rolls_back_binding_message_and_run(client_pair, monkeypatch):
    client, _, state = client_pair
    configure_model(client)
    owner = character(client)
    session = child(client, owner)
    original = state.runs.create_run
    def fail_after_insert(**values):
        original(**values)
        raise RuntimeError('injected acceptance failure')
    monkeypatch.setattr(state.runs, 'create_run', fail_after_insert)
    with pytest.raises(RuntimeError, match='injected acceptance'):
        state.chat_service.acceptance.accept(session['session_id'], text='Never accepted')
    assert state.sessions.get_session(session['session_id']).bound_persona_id is None
    assert state.messages.list_messages(session['session_id']) == []
    assert state.runs.list_runs(session['session_id']) == []


def test_commit_storage_failure_rolls_back_whole_batch_and_terminal_event(client_pair, monkeypatch):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    session = child(client, owner)
    original = state.memory.store.save
    count = 0
    def fail_second(entry, expected_revision, *, transaction):
        nonlocal count
        count += 1
        original(entry, expected_revision, transaction=transaction)
        if count == 2:
            raise RuntimeError('injected commit failure')
    monkeypatch.setattr(state.memory.store, 'save', fail_second)
    def propose(request):
        return completion(*(tool_call('memory_write', {'summary': fact, 'body': fact}, str(index))
            for index, fact in enumerate(['I like tea.', 'I like coffee.'])))
    upstream.turns = [propose, completion(content='Your answer.')]
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I like tea and coffee.'}))
    assert not result['success']
    assert state.memory.list().total == 0
    assert state.runs.get_run(result['run']['run_id']).status == 'FAILED'
    assert not any(event.type == 'run_completed' for event in state.run_events.list_events(result['run']['run_id']))


def test_approval_continuation_commits_staged_memory_once(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    register_approval_tool(state.tool_registry)
    owner = character(client, harness_enabled=True, tools_allowed=['test_approval'], memory_learning='automatic')
    session = child(client, owner)
    upstream.turns = [write_turn, completion(tool_call('test_approval')), completion(content='Confirmed.')]
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer oolong tea.'}))
    run_id = result['run']['run_id']
    assert state.memory.list().total == 0
    assert state.runs.get_harness_state(run_id)['memory']['mutations']
    resumed = ok(client.post(f'/api/tools/approvals/{run_id}', json={'decision': 'approve'}))
    assert resumed['run']['status'] == 'DONE'
    assert state.memory.list().total == 1
    assert client.post(f'/api/tools/approvals/{run_id}', json={'decision': 'approve'}).status_code == 409
    assert state.memory.list().total == 1
    from tests.test_memory_model_context import clean_request
    for request in upstream.calls:
        clean_request(request, owner, session)


def test_memory_budget_removes_complete_native_pairs_with_reasoning():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ai_workbench.core.memory_context import memory_units, remove_memory, strip_memory_transcript
    from ai_workbench.core.models.context_budget import ChatContextBudget
    from ai_workbench.core.models.schema import ChatRequest, ModelProfile
    from ai_workbench.core.models.token_counting import ReferenceTokenCounter
    from ai_workbench.core.schema.context_budget import ContextLimits
    from ai_workbench.core.schema.context_snapshot import ContextSource, ContextTrace
    messages = [{'role': 'user', 'content': 'current'},
        {'role': 'assistant', 'content': '<think>private reasoning</think>', 'tool_calls': [
            {'id': 'memory', 'type': 'function', 'function': {'name': 'memory_read', 'arguments': '{"ids":["a"]}'}},
            {'id': 'business', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'memory', 'content': 'remembered data'},
        {'role': 'tool', 'tool_call_id': 'business', 'content': 'business data'},
        {'role': 'assistant', 'content': '<think></think>', 'tool_calls': [
            {'id': 'second', 'type': 'function', 'function': {'name': 'memory_list', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'second', 'content': 'other remembered data'}]
    request = ChatRequest(model='local', messages=messages)
    trace = ContextTrace(sources=[ContextSource(id='current', kind='current_input', message_index=0)])
    facts, calls = memory_units(request, trace)
    bare, _ = remove_memory(request, trace, facts + calls)
    assert [m.role for m in bare.messages] == ['user', 'assistant', 'tool']
    assert [c.id for c in bare.messages[1].tool_calls] == ['business']
    assert [m['role'] for m in strip_memory_transcript(messages)] == ['user', 'assistant', 'tool']
    async def count(payload):
        # Native capacity leaves zero memory allowance; mixed business calls remain intact.
        return 380 + sum(100 for m in payload['messages'] if m.get('tool_call_id') in {'memory', 'second'})
    adapter = SimpleNamespace(context_window=AsyncMock(return_value=512), count_input_tokens=count)
    profile = ModelProfile(name='local', alias='local', kind='llm', model_ref='llms/local', source={'type': 'local'})
    budget = ChatContextBudget(ContextLimits(window_tokens=512, output_tokens=100), trace)
    actual = asyncio.run(budget.prepare(profile, request, adapter, ReferenceTokenCounter()))
    assert actual.messages == bare.messages
    assert budget.stats.input_tokens == budget.stats.input_budget_tokens == 380


def test_restart_preserves_approval_candidates_and_discards_interrupted_work(tmp_path):
    from fastapi.testclient import TestClient
    from ai_workbench.core.schema.run import RunStatus
    from tests.tool_fixtures import ToolOpenAI, create_tool_app
    upstream = ToolOpenAI()
    kwargs = {'root': tmp_path, 'database_url': f"sqlite:///{tmp_path / 'app.db'}", 'adapter_factory': upstream.factory}
    app = create_tool_app(**kwargs)
    register_approval_tool(app.state.runtime_state.tool_registry)
    with TestClient(app) as client:
        configure_model(client)
        owner = character(client, harness_enabled=True, tools_allowed=['test_approval'], memory_learning='automatic')
        sessions = [child(client, owner), child(client, owner)]
        upstream.turns = [write_turn, completion(tool_call('test_approval')),
            write_turn, completion(tool_call('test_approval')), completion(content='Done.')]
        runs = [ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer oolong tea.'}))['run']
            for session in sessions]
        state = app.state.runtime_state
        state.runs.update_status(runs[1]['run_id'], RunStatus.RUNNING)
        assert state.memory.list().total == 0
    restarted = create_tool_app(**kwargs)
    register_approval_tool(restarted.state.runtime_state.tool_registry)
    with TestClient(restarted) as client:
        state = restarted.state.runtime_state
        assert state.memory.list().total == 0
        assert state.runs.get_run(runs[1]['run_id']).status == 'INTERRUPTED'
        assert state.runs.get_harness_state(runs[1]['run_id']) == {}
        result = ok(client.post(f"/api/tools/approvals/{runs[0]['run_id']}", json={'decision': 'approve'}))
        assert result['run']['status'] == 'DONE'
        assert state.memory.list().total == 1
        assert state.memory.list().items[0].session_id == sessions[0]['session_id']
        assert len([e for e in state.run_events.list_events(runs[0]['run_id']) if e.type == 'run_completed']) == 1
        assert client.post(f"/api/tools/approvals/{runs[0]['run_id']}", json={'decision': 'approve'}).status_code == 409


@pytest.mark.parametrize('kind', ['attachment_failure', 'direct_tool'])
def test_first_accepted_nontext_input_binds_persona(client_pair, kind, tmp_path, monkeypatch):
    client, _, state = client_pair
    monkeypatch.setenv('COGITA_ATTACHMENTS_DIR', str(tmp_path / 'attachments'))
    owner = character(client, tools_allowed=['test_echo'])
    session = child(client, owner)
    sid = session['session_id']
    if kind == 'direct_tool':
        result = ok(client.post('/api/tools/test_echo/call', json={'session_id': sid, 'arguments': {'value': 'accepted'}}))
        assert result['run']['status'] == 'DONE'
        assert not any(m.role == 'user' for m in state.messages.list_messages(sid))
    else:
        attachment = ok(client.post('/api/attachments', files={'file': ('fact.txt', b'attachment-only input', 'text/plain')}))
        result = ok(client.post(f'/api/sessions/{sid}/messages', json={'content': '', 'attachments': [attachment]}))
        assert not result['success'] and result['run']['error_code'] == 'MODEL_NOT_CONFIGURED'
    assert ok(client.get(f'/api/sessions/{sid}'))['bound_persona_id'] == owner['persona_id']
    assert client.patch(f'/api/sessions/{sid}', json={'overrides': {'persona_id': None}}).status_code == 409


def test_competing_acceptance_keeps_one_bound_identity(client_pair):
    from concurrent.futures import ThreadPoolExecutor
    from ai_workbench.core.chat_service import ChatError
    client, _, state = client_pair
    owner = character(client)
    session = child(client, owner)
    sid = session['session_id']
    def accept():
        try:
            return state.chat_service.acceptance.accept(sid, text='first')[2]
        except ChatError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: accept(), range(2)))
    assert sum(result == 'SESSION_BUSY' for result in results) == 1
    assert len(state.runs.list_runs(sid)) == 1
    assert len(state.messages.list_messages(sid)) == 1
    assert state.sessions.get_session(sid).bound_persona_id == owner['persona_id']


def test_memory_api_boundaries_and_large_collection_pages(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client)
    session = bound(client, owner)
    from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES, MemoryCreate
    for index in range(25):
        state.memory.create(MemoryCreate(character_id=owner['id'], persona_id=owner['persona_id'],
            summary=f'乌龙茶 oolong {index}', body=f'Fact {index}'))
    page = visible(client, session, q='乌龙茶 OOLONG')
    assert page['total'] == 25 and len(page['items']) == 20 and page['next_offset'] == 20
    second = visible(client, session, q='乌龙茶 OOLONG', offset=20)
    assert second['total'] == 25 and len(second['items']) == 5 and second['next_offset'] is None
    assert not {item['id'] for item in page['items']} & {item['id'] for item in second['items']}
    assert client.get('/api/memories', params={'limit': 21}).status_code == 422
    assert client.get(f"/api/sessions/{session['session_id']}/memories", params={'persona_id': 'foreign'}).status_code == 422
    for name in MEMORY_TOOL_NAMES:
        assert client.post(f'/api/tools/{name}/call', json={'session_id': session['session_id'], 'arguments': {}}).status_code == 400
        assert client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'tools_allowed': [name]}}).status_code == 422
    assert MEMORY_TOOL_NAMES == {tool['name'] for tool in ok(client.get('/api/tools')) if tool['scope'] == 'memory'}
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'harness_enabled': False, 'memory_learning': 'automatic'}}))
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'Recall oolong'}))
    assert result['success'] and 'tools' not in upstream.calls[-1]
    assert '<memory_index>' in upstream.calls[-1]['messages'][0]['content']
    assert 'Remembered fact' not in json.dumps(upstream.calls[-1])


def test_forgetting_invalidates_both_checkpoints_and_rejects_stale_resave(client_pair):
    from ai_workbench.core.schema.compaction import ContextCheckpoint
    from ai_workbench.core.schema.retrieval import SessionRetrievalState, RetrievalCheckpoint
    from ai_workbench.core.time import utc_now
    client, _, state = client_pair
    configure_model(client)
    owner = character(client)
    session = bound(client, owner)
    entry = add(client, owner, owner['persona_id'])
    sid = session['session_id']
    state.memory.store.track(sid, [entry['id']])
    checkpoint = ContextCheckpoint(session_id=sid, summary='consumed memory', boundary_message_id='boundary',
        boundary_created_at=utc_now(), history_version=0, include_attachments='none', covered_messages=1,
        model_profile_id='model', step_id='step', input_tokens_after=1, counting='estimated')
    retrieval = SessionRetrievalState(session_id=sid, history_version=0, include_attachments='none',
        memory=RetrievalCheckpoint(text='consumed memory'))
    assert state.sessions.save_context_checkpoint(checkpoint)
    assert state.sessions.save_retrieval_state(retrieval)
    state.memory.delete(entry['id'], entry['revision'])
    assert state.sessions.get_context_checkpoint(sid) is None
    assert state.sessions.get_retrieval_state(sid) is None
    assert not state.sessions.save_context_checkpoint(checkpoint)
    assert not state.sessions.save_retrieval_state(retrieval)


def test_forgotten_id_and_user_adoption_cannot_be_overwritten(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    session = child(client, owner)
    upstream.turns = [write_turn, completion(content='Confirmed.')]
    ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer oolong tea.'}))
    original = state.memory.list().items[0]
    from ai_workbench.core.schema.memory import MemoryEdit
    adopted = state.memory.edit(original.id, MemoryEdit(expected_revision=original.revision, summary='User-owned', body='User-owned truth'))
    def attempt(request):
        return completion(tool_call('memory_write', {'id': original.id,
            'summary': 'Overwrite', 'body': 'Overwrite'}))
    for forgotten in (False, True):
        if forgotten:
            state.memory.delete(original.id, adopted.revision)
        upstream.turns = [attempt, completion(content='Cannot change it.')]
        result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'I prefer coffee now.'}))
        errors = [p['error_code'] for m in result['messages'] for p in m['parts'] if p['type'] == 'tool_result']
        assert errors == ['MEMORY_NOT_WRITABLE']
        assert state.memory.list().total == (0 if forgotten else 1)
        assert state.memory.store.get(original.id).body == ('' if forgotten else 'User-owned truth')


def test_owner_deletion_failure_rolls_back_memories_and_history(client_pair, monkeypatch):
    from sqlalchemy import event
    from ai_workbench.api.memory_deletion import delete_normal_owner
    from ai_workbench.core.schema.memory import MemoryDeletionChoice
    client, _, state = client_pair
    configure_model(client)
    owner = character(client)
    source = bound(client, owner)
    entry = add(client, owner, owner['persona_id'], source)
    sid = source['session_id']
    preview = state.memory.deletion_preview(character_id=owner['id'])
    before_messages = state.messages.list_messages(sid)
    def fail(*_args, **_kwargs):
        raise RuntimeError('injected owner deletion failure')
    def fail_sql(_db, _cursor, statement, _params, _context, _many):
        if statement.startswith('DELETE FROM characters'):
            fail()
    engine = state.memory.store.engine
    if engine is None:
        monkeypatch.setattr(state.characters, 'delete', fail)
    else:
        event.listen(engine, 'before_cursor_execute', fail_sql)
    try:
        with pytest.raises(RuntimeError, match='injected owner deletion'):
            delete_normal_owner(state, MemoryDeletionChoice(expected_revision=preview.revision, local='delete'), character_id=owner['id'])
    finally:
        if engine is not None:
            event.remove(engine, 'before_cursor_execute', fail_sql)
    assert state.memory.get(entry['id']).revision == 1
    assert state.characters.get(owner['id']).id == owner['id']
    assert state.sessions.get_session(sid).bound_persona_id == owner['persona_id']
    assert state.messages.list_messages(sid) == before_messages
    assert state.runs.list_runs(sid)


@pytest.mark.parametrize('strategy', ['token_budget', 'history_retrieval'])
def test_repeated_memory_reads_are_bounded_before_history_maintenance(client_pair, strategy):
    client, upstream, state = client_pair
    profile = configure_model(client)
    ok(client.patch(f"/api/models/profiles/{profile['id']}", json={'context_window_tokens': 4096, 'parameters': {'max_tokens': 512}}))
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic', context_policy={'strategy': strategy,
        'compaction': {'trigger_percent': 70, 'target_percent': 45}, 'retrieval': {'trigger_percent': 70, 'target_percent': 45}})
    entry = add(client, owner, owner['persona_id'], summary='Large fact', body='detail ' * 280)
    session = child(client, owner)
    upstream.turns = [completion(tool_call('memory_read', {'ids': [entry['id']]}, f'read-{i}')) for i in range(6)] + [completion(content='Done.')]
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'Read the remembered fact.'}))
    assert result['success'], result
    assert len(upstream.calls) == 7
    assert not any(step.kind == 'compaction' or step.metadata.get('operation') == 'reset' for step in state.runs.list_steps(result['run']['run_id']))
    for call in upstream.calls:
        assert len([m for m in call['messages'] if m['role'] == 'tool']) <= 2
