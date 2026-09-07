import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event

from ai_workbench.api.main import create_app
from ai_workbench.core.assistant_output import ThinkParser
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.message import MessageSchema
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, ok, tool_call


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def presentation_client(tmp_path, request):
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}",
                     use_memory=request.param, adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream


def configure(client, *, harness=True, streaming=True):
    configure_model(client, capabilities={"streaming": streaming, "tools": True})
    return ok(client.post("/api/sessions", json={"harness_enabled": harness}))


def send(client, session, content="encode and decode"):
    return ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": content}))


def reasoning_turn(*calls, content="<think>tag reasoning</think>answer"):
    turn = completion(*calls, content=content)
    turn["message"]["reasoning_content"] = "structured reasoning; "
    return turn


@pytest.mark.parametrize("value,expected", [
    ("<think>reason</think>answer", [("reasoning", "reason"), ("text", "answer")]),
    ("before <think>reason</think> after", [("text", "before "), ("reasoning", "reason"), ("text", " after")]),
    ("`<think>literal</think>`\n<think>reason</think>a", [("text", "`<think>literal</think>`\n"), ("reasoning", "reason"), ("text", "a")]),
    ("```xml\n<think>literal</think>\n```\n<think>r</think>a", [("text", "```xml\n<think>literal</think>\n```\n"), ("reasoning", "r"), ("text", "a")]),
    ("~~~\n<think>literal</think>\n~~~\n<think>r</think>a", [("text", "~~~\n<think>literal</think>\n~~~\n"), ("reasoning", "r"), ("text", "a")]),
    ("\\<think>literal\\</think> <think>r</think>a", [("text", "\\<think>literal\\</think> "), ("reasoning", "r"), ("text", "a")]),
    ("<think>unclosed", [("reasoning", "unclosed")]),
    ("<thin", [("text", "<thin")]),
    ("    <think>code</think>\n\n<think>r</think>a", [("text", "    <think>code</think>\n\n"), ("reasoning", "r"), ("text", "a")]),
    ("\t<think>code</think>\n<think>r</think>a", [("text", "\t<think>code</think>\n"), ("reasoning", "r"), ("text", "a")]),
    ("<think>r</thi", [("reasoning", "r</thi")]),
])
def test_think_parser_is_independent_of_chunk_boundaries(value, expected):
    for split in range(len(value) + 1):
        parts = []
        def emit(kind, text):
            if parts and parts[-1][0] == kind:
                parts[-1] = (kind, parts[-1][1] + text)
            else:
                parts.append((kind, text))
        parser = ThinkParser(emit)
        parser.feed(value[:split])
        parser.feed(value[split:])
        parser.feed("", final=True)
        assert parts == expected, split


def test_reasoning_part_is_strict_and_assistant_only():
    values = dict(message_id="m", session_id="s", role="assistant", parts=[{"id": "r", "type": "reasoning", "text": "reason"}])
    assert MessageSchema(**values).parts[0]["type"] == "reasoning"
    for change in ({"role": "user"}, {"parts": [{"id": "r", "type": "reasoning", "text": 123}]},
                   {"parts": [{"id": "r", "type": "reasoning", "text": "reason", "extra": True}]}):
        with pytest.raises((ValidationError, ValueError)):
            MessageSchema(**{**values, **change})


@pytest.mark.parametrize("harness", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_reasoning_body_deltas_and_native_tool_transcript(presentation_client, harness, streaming):
    client, upstream = presentation_client
    session = configure(client, harness=harness, streaming=streaming)
    upstream.turns = ([reasoning_turn(tool_call(), content="<think>tool reason</think>working")] if harness else []) + [reasoning_turn()]
    response = send(client, session)
    assert response["success"] and response["data"] == "answer"
    answer = response["messages"][-1]
    assert [(part["type"], part["text"]) for part in answer["parts"]] == [
        ("reasoning", "structured reasoning; tag reasoning"), ("text", "answer")]
    state = client.app.state.runtime_state
    if streaming:
        deltas = [e for e in state.events.list_events() if e.type == "message_delta" and e.message_id == answer["message_id"]]
        assert [e.payload["seq"] for e in deltas] == list(range(1, len(deltas) + 1))
        for part in answer["parts"]:
            chunks = [e.payload for e in deltas if e.payload["part_id"] == part["id"]]
            assert "".join(chunk["delta"] for chunk in chunks) == part["text"]
            assert all(chunk["part_type"] == part["type"] for chunk in chunks)
    if harness:
        native = upstream.calls[-1]["messages"][-2]
        assert native["reasoning_content"] == "structured reasoning; "
        assert native["content"] == "<think>tool reason</think>working"
    history = ContextBuilder(state.messages).build(session["session_id"], "next", ContextPolicy(mode="session"))
    assert "structured reasoning" not in json.dumps(history.messages)
    assert "tag reasoning" not in json.dumps(history.messages)
    assert "answer" in json.dumps(history.messages)


@pytest.mark.parametrize("harness", [False, True])
def test_failed_stream_persists_partial_content(presentation_client, harness):
    client, upstream = presentation_client
    session = configure(client, harness=harness)
    upstream.stream_chunks = [{"reasoning_content": "received reasoning"}, {"content": "partial answer"}, {"refusal": "refused"}]
    response = send(client, session)
    assert response["run"]["status"] == "FAILED"
    partial = response["messages"][-1]
    assert partial["metadata"]["incomplete"] is True and not partial["metadata"].get("streaming")
    assert [p["text"] for p in partial["parts"]] == ["received reasoning", "partial answer"]
    history = ok(client.get(f"/api/sessions/{session['session_id']}/messages"))
    assert history[-1]["message_id"] == partial["message_id"] and history[-1]["metadata"]["incomplete"]
    state = client.app.state.runtime_state
    context = ContextBuilder(state.messages).build(session["session_id"], "next", ContextPolicy(mode="session"))
    assert "partial answer" not in json.dumps(context.messages)
    events = state.events.list_events()
    saved = next(i for i, e in enumerate(events) if e.type == "message_completed" and e.message_id == partial["message_id"])
    failed = next(i for i, e in enumerate(events) if e.type == "run_failed")
    assert saved < failed


def test_general_processing_preference_is_strict_and_persisted(presentation_client):
    client, _ = presentation_client
    path = "/api/settings/general"
    assert ok(client.get(path))["show_full_processing"] is False
    assert ok(client.patch(path, json={"show_full_processing": True}))["show_full_processing"] is True
    assert ok(client.get(path))["show_full_processing"] is True
    for value in (None, "true", 1):
        assert client.patch(path, json={"show_full_processing": value}).status_code == 422
    assert ok(client.get(path))["show_full_processing"] is True


def test_delete_reply_and_user_prune_all_owned_records(presentation_client):
    client, upstream = presentation_client
    session = configure(client)
    upstream.turns = [completion(tool_call()), completion(content="answer")]
    first = send(client, session)
    later = send(client, session, "later")
    first_id = first["run"]["run_id"]
    deleted = ok(client.delete(f"/api/runs/{first_id}"))
    assert deleted["deleted_run_ids"] == [first_id]
    assert set(deleted["deleted_message_ids"]) == {m["message_id"] for m in first["messages"] if m["role"] != "user"}
    state = client.app.state.runtime_state
    with pytest.raises(KeyError):
        state.runs.get_config_snapshot(first_id)
    assert state.runs.list_steps(first_id) == [] and state.run_events.list_events(first_id) == []
    assert not any(e.run_id == first_id for e in state.events.list_events())
    assert state.messages.get_message(first["messages"][0]["message_id"]).role == "user"
    user_id = later["messages"][0]["message_id"]
    change = ok(client.delete(f"/api/messages/{user_id}"))
    assert change["deleted_run_ids"] == [later["run"]["run_id"]]
    assert ok(client.get(f"/api/sessions/{session['session_id']}/runs")) == []
    assert [m["message_id"] for m in ok(client.get(f"/api/sessions/{session['session_id']}/messages"))] == [first["messages"][0]["message_id"]]


def test_retry_and_edit_prune_old_tools_and_later_runs(presentation_client):
    client, upstream = presentation_client
    session = configure(client)
    upstream.turns = [completion(tool_call(), content="old process"), completion(content="old answer")]
    first = send(client, session)
    later = send(client, session, "later")
    replacement = ok(client.post(f"/api/runs/{first['run']['run_id']}/retry"))
    assert set(replacement["deleted_run_ids"]) == {first["run"]["run_id"], later["run"]["run_id"]}
    assert "old process" not in json.dumps(upstream.calls[-1]["messages"])
    assert "tool_calls" not in json.dumps(upstream.calls[-1]["messages"])
    assert client.post(f"/api/messages/{first['messages'][-1]['message_id']}/retry").status_code == 404
    history = ok(client.get(f"/api/sessions/{session['session_id']}/messages"))
    assert [m["role"] for m in history] == ["user", "assistant"]
    edited = ok(client.post(f"/api/messages/{history[0]['message_id']}/edit", json={"content": "edited", "rerun": False}))
    assert edited["deleted_run_ids"] == [replacement["run"]["run_id"]]
    assert ok(client.get(f"/api/sessions/{session['session_id']}/runs")) == []
    assert ok(client.get(f"/api/sessions/{session['session_id']}/messages"))[0]["parts"][0]["text"] == "edited"


def test_sql_history_prune_rolls_back_on_write_failure(presentation_client):
    client, _ = presentation_client
    state = client.app.state.runtime_state
    if not hasattr(state.history.store, "engine"):
        return
    session = configure(client)
    first = send(client, session)
    engine = state.history.store.engine
    def fail_steps(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("DELETE FROM runsteprecord"):
            raise RuntimeError("injected rollback")
    event.listen(engine, "before_cursor_execute", fail_steps)
    try:
        with pytest.raises(RuntimeError, match="injected rollback"):
            state.history.delete_reply(first["run"]["run_id"])
    finally:
        event.remove(engine, "before_cursor_execute", fail_steps)
    assert state.runs.get_run(first["run"]["run_id"]).status == "DONE"
    assert len(state.messages.list_messages(session["session_id"])) == 2
    assert state.runs.list_steps(first["run"]["run_id"])
    assert state.run_events.list_events(first["run"]["run_id"])


@pytest.mark.parametrize("use_memory", [True, False], ids=["memory", "sqlite"])
@pytest.mark.parametrize("harness", [False, True])
def test_cancelled_stream_retains_received_content(tmp_path, use_memory, harness):
    async def scenario():
        received = asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"index":0,"delta":{"content":"<think>reason</think>partial"},"finish_reason":null}]}\n\n'
                received.set()
                await asyncio.Event().wait()
        class Upstream(ToolOpenAI):
            async def handle(self, request):
                if request.url.path.endswith("/chat/completions"):
                    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())
                return await super().handle(request)
        upstream = Upstream()
        app = create_app(root=tmp_path, database_url=f"sqlite:///{tmp_path / 'cancel.db'}",
                         use_memory=use_memory, adapter_factory=upstream.factory)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            provider = ok(await client.post("/api/models/providers", json={"name": "p", "base_url": "http://provider.test/v1"}))
            profile = ok(await client.post("/api/models/profiles", json={"name": "m", "alias": "model", "kind": "llm", "model_ref": "fake", "provider_profile_id": provider["id"], "capabilities": {"tools": True, "streaming": True}}))
            session = ok(await client.post("/api/sessions", json={"model_profile_id": profile["id"], "harness_enabled": harness}))
            task = asyncio.create_task(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "go"}))
            try:
                await asyncio.wait_for(received.wait(), 3)
                state = app.state.runtime_state
                started = next(e for e in state.events.list_events() if e.type == "message_started")
                ok(await client.post(f"/api/runs/{started.run_id}/cancel"))
                cancelled = ok(await asyncio.wait_for(task, 3))
                assert cancelled["run"]["status"] == "CANCELLED" and not cancelled["success"]
                history = ok(await client.get(f"/api/sessions/{session['session_id']}/messages"))
                assert history[-1]["message_id"] == started.message_id
                assert history[-1]["metadata"]["incomplete"] is True
                assert [p["text"] for p in history[-1]["parts"]] == ["reason", "partial"]
                assert state.runs.get_run(started.run_id).status == "CANCELLED"
                assert state.model_manager.status(profile["id"]).active == 0
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
