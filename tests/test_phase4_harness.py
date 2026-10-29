import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from ai_workbench.api.main import create_app
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core import chat_runner
from ai_workbench.core.harness import agent_loop
from ai_workbench.core.harness.schema import ToolSpec
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, ok, register_approval_tool, tool_call


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def harness_client(tmp_path, request):
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}",
                     use_memory=request.param, adapter_factory=upstream.factory)
    register_approval_tool(app.state.runtime_state.tool_registry)
    with TestClient(app) as client:
        yield client, upstream, tmp_path


def configure(client, *, tools=None, enabled=True, streaming=True, model=True):
    profile = configure_model(client, request_options={"streaming": streaming}) if model else None
    persona = ok(client.post("/api/personas", json={'collection': 'agent', 'name': 'Original persona', 'system_prompt': 'PRIVATE_TOOL_PROMPT'}))
    session = ok(client.post("/api/sessions", json={'persona_id': persona['id'], 'harness_enabled': enabled, 'tools_allowed': tools if tools is not None else ['base64_encode', 'base64_decode'], 'generation': {'temperature': 0.25}}))
    return session, persona, profile


def send(client, session, content="use a tool"):
    return ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": content}))


def results(payload):
    return [part for message in payload["messages"] for part in message["parts"] if part["type"] == "tool_result"]


@pytest.mark.parametrize("streaming", [True, False])
def test_disabled_harness_does_not_send_or_execute_tools(harness_client, streaming):
    client, upstream, _ = harness_client
    session, _, _ = configure(client, enabled=False, streaming=streaming)
    upstream.turns = [completion(tool_call())]
    response = send(client, session)
    assert response["run"]["error_code"] == "UNEXPECTED_TOOL_CALL"
    assert "tools" not in upstream.calls[0]
    assert [m["role"] for m in response["messages"]] == ["user"]


@pytest.mark.parametrize("streaming", [True, False])
def test_multi_call_round_and_stream_fragments(harness_client, streaming):
    client, upstream, _ = harness_client
    session, _, _ = configure(client, streaming=streaming)
    upstream.turns = [completion(tool_call(arguments={"value": "中文"}),
        tool_call("base64_decode", {"value": "aGk="}, "call_2"), content="working"), completion(content="final answer")]
    response = send(client, session)
    assert response["success"] and response["run"]["status"] == "DONE"
    assert response["data"] == "final answer"
    assert all("tool_choice" not in request for request in upstream.calls)
    assert "qq_reply" not in response["run"]["metadata"]
    tool_results = results(response)
    assert [part["tool_call_id"] for part in tool_results] == ["call_1", "call_2"]
    assert [part["data"]["value"] for part in tool_results] == ["5Lit5paH", "hi"]
    transcript = upstream.calls[-1]["messages"][-3:]
    assert [item["role"] for item in transcript] == ["assistant", "tool", "tool"]
    assert [item["tool_call_id"] for item in transcript[1:]] == ["call_1", "call_2"]
    assert all(json.loads(item["content"])["status"] == "success" for item in transcript[1:])
    calls_message = next(m for m in response["messages"] if m["metadata"].get("tool_calls"))
    assert len({part["id"] for part in calls_message["parts"]}) == len(calls_message["parts"])
    state = client.app.state.runtime_state
    assert state.runs.get_harness_state(response["run"]["run_id"]) == {}
    events = ok(client.get(f"/api/runs/{response['run']['run_id']}/events"))["items"]
    assert "PRIVATE_TOOL_PROMPT" not in json.dumps(events)
    if streaming:
        final_id = response["messages"][-1]["message_id"]
        assert [e.payload["seq"] for e in state.events.list_events() if e.type == "message_delta" and e.message_id == final_id] == [1, 2]


@pytest.mark.parametrize("call,code", [
    (tool_call("unknown"), "TOOL_NOT_FOUND"), (tool_call("test_approval", {"value": "approval input"}), "TOOL_NOT_ALLOWED"),
    (tool_call(arguments="not json"), "TOOL_INVALID_ARGUMENTS"), (tool_call(arguments='{"value":"a","value":"b"}'), "TOOL_INVALID_ARGUMENTS"),
    (tool_call(arguments='{"value":NaN}'), "TOOL_INVALID_ARGUMENTS"), (tool_call(arguments={"value": 5}), "TOOL_INVALID_ARGUMENTS"),
    (tool_call("base64_decode", {"value": "???"}), "CODEC_INVALID_BASE64"),
])
def test_tool_errors_are_data_and_model_can_continue(harness_client, call, code):
    client, upstream, _ = harness_client
    session, _, _ = configure(client)
    upstream.turns = [completion(call), completion(content="recovered")]
    response = send(client, session)
    assert response["success"]
    assert results(response)[0]["error_code"] == code
    assert json.loads(upstream.calls[-1]["messages"][-1]["content"])["error_code"] == code
    assert any(step["kind"] == "tool" and step["error_code"] == code for step in response["run"]["steps"])


def test_provider_tool_support_is_not_prechecked_and_empty_allowlist(harness_client):
    client, upstream, _ = harness_client
    session, _, _ = configure(client)
    response = send(client, session)
    assert response["success"] and upstream.calls[0]["tools"]
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={"tools_allowed": []}))
    assert send(client, session)["success"]
    assert "tools" not in upstream.calls[-1]


@pytest.mark.parametrize("repeated_round", [False, True])
def test_duplicate_call_ids_fail_before_execution(harness_client, repeated_round):
    client, upstream, _ = harness_client
    session, _, _ = configure(client)
    upstream.turns = ([completion(tool_call()), completion(tool_call())] if repeated_round else
                      [completion(tool_call(), tool_call())])
    response = send(client, session)
    assert response["run"]["error_code"] == "MODEL_PROTOCOL_ERROR"
    assert len(results(response)) == (1 if repeated_round else 0)


def test_approval_retains_queue_snapshot_and_original_input(harness_client):
    client, upstream, root = harness_client
    session, persona, model = configure(client, tools=["test_approval", "base64_encode"])
    upstream.turns = [completion(tool_call("test_approval", {"value": "approval input"}, "first"),
        tool_call(call_id="middle"), tool_call("test_approval", {"value": "approval input"}, "last")), completion(content="answer")]
    response = send(client, session, "original question")
    run_id = response["run"]["run_id"]
    state = client.app.state.runtime_state
    saved = state.runs.get_harness_state(run_id)
    assert response["run"]["status"] == "WAITING_FOR_USER" and saved["rounds"] == 1
    assert len(saved["pending_calls"]) == 3 and not results(response)
    assert state.active_runs.active_count() == 0 and state.model_manager.status(model["id"]).active == 0
    assert "PRIVATE_TOOL_PROMPT" not in json.dumps(response)
    assert client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "approve"}).json()["error"]["code"] == "RUN_WAITING_FOR_APPROVAL"
    assert client.post("/api/tools/base64_encode/call", json={"session_id": session["session_id"], "arguments": {"value": "x"}}).status_code == 409
    ok(client.patch(f"/api/personas/{persona['id']}", json={"name": "Changed", "system_prompt": "CHANGED_PROMPT"}))
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={"persona_id": COGITA_PERSONA_ID, "tools_allowed": [], "generation": {"temperature": 0.9}}))
    approved = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert approved["run"]["status"] == "WAITING_FOR_USER"
    assert [p["tool_call_id"] for p in results(approved)] == ["first", "middle"]
    assert state.runs.get_harness_state(run_id)["awaiting_approval"] == "last"
    assert len(upstream.calls) == 1
    rejected = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "reject"}))
    assert rejected["run"]["status"] == "DONE" and rejected["session"]["waiting_run_id"] is None
    assert results(rejected)[-1]["status"] == "rejected"
    assert rejected["messages"][-1]["speaker_name"] is None
    assert upstream.calls[-1]["temperature"] == 0.25
    assert "PRIVATE_TOOL_PROMPT" in json.dumps(upstream.calls[-1]) and "CHANGED_PROMPT" not in json.dumps(upstream.calls[-1])
    assert [m["role"] for m in upstream.calls[-1]["messages"][-4:]] == ["assistant", "tool", "tool", "tool"]
    assert state.runs.get_harness_state(run_id) == {}
    assert client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}).status_code == 409
    assert ok(client.get(f"/api/tools/runs/{run_id}"))["run"]["status"] == "DONE"


def test_restart_preserves_only_pending_approval(tmp_path):
    upstream = ToolOpenAI(
        {**completion(tool_call("test_approval", {"value": "approval input"})), "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        {**completion(content="read completed"), "usage": {"prompt_tokens": 20, "completion_tokens": 3}})
    kwargs = {"root": tmp_path, "database_url": f"sqlite:///{tmp_path / 'app.db'}", "adapter_factory": upstream.factory}
    app = create_app(**kwargs)
    register_approval_tool(app.state.runtime_state.tool_registry)
    with TestClient(app) as client:
        session, _, _ = configure(client, tools=["test_approval"])
        ok(client.patch(f"/api/sessions/{session['session_id']}", json={"reasoning": False}))
        response = send(client, session)
        ok(client.patch(f"/api/sessions/{session['session_id']}", json={"reasoning": True}))
        run_id = response["run"]["run_id"]
        first_statistics = next(step["metadata"]["llm"] for step in response["run"]["steps"] if step["kind"] == "model")
        assert first_statistics["usage"]["total_tokens"] == 15
        first_step = next(step for step in response["run"]["steps"] if step["kind"] == "model")
        first_context = ok(client.get(f"/api/runs/{run_id}/steps/{first_step['step_id']}/context"))
        state = app.state.runtime_state
        orphan_session = state.sessions.create_session()
        orphan = state.runs.create_run(kind="tool", persona_id=COGITA_PERSONA_ID, session_id=orphan_session.session_id)
        state.runs.update_status(orphan.run_id, RunStatus.RUNNING)
    restarted = create_app(**kwargs)
    register_approval_tool(restarted.state.runtime_state.tool_registry)
    with TestClient(restarted) as client:
        saved_run = ok(client.get(f"/api/runs/{run_id}"))
        assert saved_run["status"] == "WAITING_FOR_USER"
        assert ok(client.get(f"/api/runs/{run_id}/steps/{first_step['step_id']}/context")) == first_context
        assert next(step["metadata"]["llm"] for step in saved_run["steps"] if step["kind"] == "model") == first_statistics
        assert ok(client.get(f"/api/runs/{orphan.run_id}"))["status"] == "INTERRUPTED"
        response = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
        assert response["run"]["status"] == "DONE"
        assert results(response)[0]["data"]["content"] == "approved"
        calls = [step["metadata"]["llm"] for step in response["run"]["steps"] if step["kind"] == "model"]
        assert len(calls) == 2 and calls[0] == first_statistics
        assert sum(call["usage"]["total_tokens"] for call in calls) == 38
        assert [call["reasoning_effort"] for call in upstream.calls] == ["none", "none"]
        snapshots = [ok(client.get(f"/api/runs/{run_id}/steps/{step['step_id']}/context"))
                     for step in response["run"]["steps"] if step["kind"] == "model"]
        assert snapshots[0] == first_context
        assert snapshots[1]["request"] == upstream.calls[1]
        assert any(source["kind"] == "agent_persona" and source["text"] == "PRIVATE_TOOL_PROMPT" for source in snapshots[1]["sources"])


def test_direct_rest_and_slash_share_permissions_results_and_errors(harness_client):
    client, upstream, _ = harness_client
    session, _, _ = configure(client, enabled=False, model=False)
    response = ok(client.post("/api/tools/base64_encode/call", json={"session_id": session["session_id"], "arguments": {"value": " hello "}}))
    assert response["run"]["kind"] == "tool" and response["run"]["status"] == "DONE"
    assert results(response)[0]["data"]["value"] == "IGhlbGxvIA=="
    slash = send(client, session, "/base64_encode  hello ")
    assert results(slash)[0]["data"] == results(response)[0]["data"]
    bad = send(client, session, "/base64_decode ?")
    assert not bad["success"] and bad["run"]["error_code"] == "CODEC_INVALID_BASE64"
    assert results(bad)[0]["error_code"] == "CODEC_INVALID_BASE64" and upstream.calls == []
    count = len(client.app.state.runtime_state.runs.list_runs(session["session_id"]))
    for url, payload in (("/api/tools/test_approval/call", {"session_id": session["session_id"], "arguments": {"value": "x"}}),
                         (f"/api/sessions/{session['session_id']}/messages", {"content": "/test_approval x"})):
        denied = client.post(url, json=payload)
        assert denied.status_code == 400 and denied.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert len(client.app.state.runtime_state.runs.list_runs(session["session_id"])) == count
    assert client.post("/api/tools/missing/call", json={"session_id": session["session_id"]}).status_code == 404
    unknown = send(client, session, "/not_registered example")
    assert unknown["messages"][0]["parts"][0]["text"] == "/not_registered example"


@pytest.mark.parametrize("decision", ["reject", "cancel"])
def test_direct_approval_rejection_and_cancellation(harness_client, decision):
    client, upstream, _ = harness_client
    session, _, _ = configure(client, tools=["test_approval"], enabled=False, model=False)
    response = ok(client.post("/api/tools/test_approval/call", json={"session_id": session["session_id"], "arguments": {"value": "approval input"}}))
    run_id = response["run"]["run_id"]
    assert response["run"]["status"] == "WAITING_FOR_USER"
    if decision == "reject":
        response = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "reject"}))
        assert response["run"]["status"] == "FAILED" and results(response)[0]["status"] == "rejected"
    else:
        ok(client.post(f"/api/runs/{run_id}/cancel"))
        response = ok(client.get(f"/api/tools/runs/{run_id}"))
        assert response["run"]["status"] == "CANCELLED" and results(response)[0]["status"] == "cancelled"
        assert not ok(client.post(f"/api/runs/{run_id}/cancel"))["cancelled"]
    assert response["session"]["waiting_run_id"] is None
    assert not upstream.calls
    events = ok(client.get(f"/api/runs/{run_id}/events"))["items"]
    assert "harness_state" not in json.dumps(events)


@pytest.mark.parametrize("finish", [True, False])
def test_eight_tool_round_limit_allows_final_answer(harness_client, finish):
    client, upstream, _ = harness_client
    session, _, _ = configure(client, streaming=False)
    upstream.turns = [completion(tool_call(call_id=f"call_{i}")) for i in range(8)]
    upstream.turns.append(completion(content="answer") if finish else completion(tool_call(call_id="ninth")))
    response = send(client, session)
    assert len(results(response)) == 8 and len(upstream.calls) == 9
    assert response["run"]["status"] == ("DONE" if finish else "FAILED")
    if not finish:
        assert response["run"]["error_code"] == "TOOL_LOOP_LIMIT"


def test_tool_timeout_is_returned_to_model_and_direct_run_fails(harness_client, monkeypatch):
    client, upstream, _ = harness_client
    async def slow(*_args):
        await asyncio.sleep(10)
    registry = client.app.state.runtime_state.tool_registry
    registry.register(ToolSpec("slow", "slow", {"type": "object", "additionalProperties": False}, slow))
    monkeypatch.setattr(agent_loop, "TOOL_TIMEOUT_SECONDS", 0.02)
    session, _, _ = configure(client, tools=["slow"])
    upstream.turns = [completion(tool_call("slow", "{}")), completion(content="timeout handled")]
    response = send(client, session)
    assert response["success"] and results(response)[0]["error_code"] == "TOOL_TIMEOUT"
    direct = ok(client.post("/api/tools/slow/call", json={"session_id": session["session_id"], "arguments": {}}))
    assert direct["run"]["status"] == "FAILED" and direct["run"]["error_code"] == "TOOL_TIMEOUT"


def test_active_budget_includes_approved_tool_execution(harness_client, monkeypatch):
    client, upstream, _ = harness_client
    async def slow(*_args):
        await asyncio.sleep(10)
    registry = client.app.state.runtime_state.tool_registry
    registry._tools["test_approval"] = replace(registry.get("test_approval"), handler=slow)
    session, _, _ = configure(client, tools=["test_approval"])
    upstream.turns = [completion(tool_call("test_approval", {"value": "approval input"}))]
    response = send(client, session)
    run_id = response["run"]["run_id"]
    runs = client.app.state.runtime_state.runs
    saved = runs.get_harness_state(run_id)
    saved["active_seconds"] = 299.98
    runs.update_harness_state(run_id, saved)
    response = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert response["run"]["error_code"] == "TOOL_RUN_TIMEOUT" and results(response)[0]["error_code"] == "TOOL_RUN_TIMEOUT"
    assert len(upstream.calls) == 1 and runs.get_harness_state(run_id) == {}


@pytest.mark.parametrize("entry", ["chat", "direct", "approval"])
def test_cancel_registered_execution_and_claim_approval_once(tmp_path, entry):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def blocking(*_args):
            calls.append("handler")
            entered.set()
            await release.wait()
            return {"result": "done"}
        upstream = ToolOpenAI(completion(tool_call("blocking", "{}")))
        app = create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory)
        state = app.state.runtime_state
        state.tool_registry.register(ToolSpec("blocking", "Blocking", {"type": "object"}, blocking, requires_approval=entry == "approval"))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            provider = ok(await client.post("/api/models/providers", json={'name': 'provider', 'connection': {'base_url': 'http://provider.test/v1'}}))
            profile = ok(await client.post("/api/models/profiles", json={"name": "model", "alias": "model", "kind": "llm", "model_ref": "fake", "context_window_tokens": 32768, "request_options": {"streaming": False}, 'source': {'type': 'provider', 'provider_profile_id': provider["id"]}}))
            persona = ok(await client.post("/api/personas", json={'collection': 'agent', 'name': 'persona'}))
            session = ok(await client.post("/api/sessions", json={'persona_id': persona['id'], 'model_profile_id': profile['id'], 'harness_enabled': True, 'tools_allowed': ['blocking']}))
            if entry == "chat":
                task = asyncio.create_task(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "run"}))
            elif entry == "direct":
                task = asyncio.create_task(client.post("/api/tools/blocking/call", json={"session_id": session["session_id"], "arguments": {}}))
            else:
                waiting = ok(await client.post("/api/tools/blocking/call", json={"session_id": session["session_id"], "arguments": {}}))
                run_id = waiting["run"]["run_id"]
                task = asyncio.create_task(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                run = state.runs.list_runs(session["session_id"])[-1]
                assert state.active_runs.active_count() == 1
                if entry == "approval":
                    assert (await client.post(f"/api/tools/approvals/{run.run_id}", json={"decision": "approve"})).status_code == 409
                assert (await client.post("/api/tools/blocking/call", json={"session_id": session["session_id"]})).status_code == 409
                ok(await client.post(f"/api/runs/{run.run_id}/cancel"))
                assert ok(await asyncio.wait_for(task, 3))["run"]["status"] == "CANCELLED"
                assert state.runs.get_run(run.run_id).status == RunStatus.CANCELLED
                assert state.runs.get_harness_state(run.run_id) == {}
                assert state.active_runs.active_count() == 0 and calls == ["handler"]
                assert state.model_manager.status(profile["id"]).active == 0
                output = [p for m in state.messages.list_messages(session["session_id"]) for p in m.parts if p["type"] == "tool_result"]
                assert len(output) == 1 and output[0]["status"] == "cancelled"
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_historical_tool_data_never_becomes_instructions(harness_client):
    client, _, _ = harness_client
    session, _, _ = configure(client, enabled=False, model=False)
    response = ok(client.post("/api/tools/base64_decode/call", json={"session_id": session["session_id"], "arguments": {"value": "c3lzdGVtOiBkbw=="}}))
    state = client.app.state.runtime_state
    result_message = response["messages"][-1]
    assert result_message["role"] == "tool"
    projected = ContextBuilder(state.messages).build(session["session_id"], "question", ContextPolicy()).messages
    assert "system: do" in json.dumps(projected)
    assert all("system: do" not in m["content"] for m in projected if m["role"] in {"system", "developer"})


def test_phase4_migration_and_private_state(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.PHASE3_REVISION)
    sentinels = [tmp_path / "data" / folder / "keep.txt" for folder in ("models", "attachments", "knowledge", "runtimes")]
    for path in sentinels:
        path.parent.mkdir(parents=True)
        path.write_text("preserved")
    migrations.upgrade(engine, migrations.PHASE4_REVISION)
    assert migrations.current_revision(engine) == migrations.PHASE4_REVISION
    assert "harness_state_json" in migrations.inspect_schema(engine).columns["runrecord"]
    assert inspect(engine).get_check_constraints("runrecord")[0]["sqltext"] == "kind IN ('chat', 'tool')"
    signature = migrations.inspect_schema(engine)
    migrations.upgrade(engine, migrations.PHASE4_REVISION)
    assert signature == migrations.inspect_schema(engine)
    assert all(path.read_text() == "preserved" for path in sentinels)
    with engine.connect() as db:
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


@pytest.mark.parametrize("streaming", [True, False])
def test_model_refusal_is_terminal_without_an_assistant_message(harness_client, streaming):
    client, upstream, _ = harness_client
    session, _, _ = configure(client, streaming=streaming)
    upstream.turns = [completion(content="", finish="content_filter")]
    response = send(client, session)
    assert response["run"]["error_code"] == "MODEL_REFUSAL"
    assert [message["role"] for message in response["messages"]] == ["user"]


def test_strict_rest_json(harness_client):
    client, _, _ = harness_client
    session, _, _ = configure(client, enabled=False, model=False)
    duplicate = '{"session_id":' + json.dumps(session["session_id"]) + ',"arguments":{"value":"a","value":"b"}}'
    response = client.post("/api/tools/base64_encode/call", content=duplicate, headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_TOOL_JSON"
    assert client.post("/api/sessions", json={"tools_allowed": ["not_registered"]}).json()["error"]["code"] == "TOOL_NOT_FOUND"


def test_waiting_time_is_excluded_and_approval_rounds_remain_bounded(harness_client, monkeypatch):
    client, upstream, _ = harness_client
    state = client.app.state.runtime_state
    clock = [0.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(agent_loop, "time", timer)
    monkeypatch.setattr(chat_runner, "time", timer)
    budget_type = agent_loop._Budget
    monkeypatch.setattr(agent_loop, "_Budget", lambda spent: budget_type(spent, started=clock[0]))
    async def read(*_args):
        clock[0] += .1
        return {"value": "approval input", "content": "read"}
    state.tool_registry._tools["test_approval"] = replace(state.tool_registry.get("test_approval"), handler=read)
    session, _, _ = configure(client, tools=["test_approval"])
    upstream.turns = [completion(tool_call("test_approval", {"value": "approval input"}, f"call_{i}")) for i in range(9)]
    waiting = send(client, session)
    run_id = waiting["run"]["run_id"]
    monkeypatch.setattr(agent_loop, "ACTIVE_BUDGET_SECONDS", 1)
    clock[0] += 1.1
    approved = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert approved["run"]["status"] == "WAITING_FOR_USER"
    assert state.runs.get_harness_state(run_id)["active_seconds"] == pytest.approx(.1)
    monkeypatch.setattr(agent_loop, "ACTIVE_BUDGET_SECONDS", 300)
    for _ in range(7):
        approved = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert approved["run"]["status"] == "FAILED" and approved["run"]["error_code"] == "TOOL_LOOP_LIMIT"
    assert len(results(approved)) == 8


def test_multi_parameter_slash_json_uses_the_same_registry(harness_client):
    client, _, _ = harness_client
    async def combine(arguments, _context):
        return {"value": arguments["a"] + arguments["b"]}
    registry = client.app.state.runtime_state.tool_registry
    registry.register(ToolSpec("combine", "Combine", {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"], "additionalProperties": False}, combine))
    session, _, _ = configure(client, tools=["combine"], enabled=False, model=False)
    assert results(send(client, session, '/combine {"a":"1","b":"2"}'))[0]["data"]["value"] == "12"
    path = f"/api/sessions/{session['session_id']}/messages"
    for value in ('/combine a=1 b=2', '/combine []', '/combine {"a":"1","a":"2","b":"3"}'):
        assert client.post(path, json={"content": value}).json()["error"]["code"] == "TOOL_INVALID_ARGUMENTS"


def test_harness_stream_is_visible_before_completion_and_cancels_model(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        class LiveStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"index":0,"delta":{"content":"live"},"finish_reason":null}]}\n\n'
                entered.set()
                await release.wait()
                yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        class Upstream(ToolOpenAI):
            async def handle(self, request):
                if request.url.path.endswith("/chat/completions") and self.calls:
                    self.calls.append(json.loads(request.content))
                    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=LiveStream())
                return await super().handle(request)
        upstream = Upstream(completion(tool_call()))
        app = create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            provider = ok(await client.post("/api/models/providers", json={'name': 'p', 'connection': {'base_url': 'http://provider.test/v1'}}))
            profile = ok(await client.post("/api/models/profiles", json={"name": "m", "alias": "model", "kind": "llm", "model_ref": "fake", "context_window_tokens": 32768, "request_options": {"streaming": True}, 'source': {'type': 'provider', 'provider_profile_id': provider["id"]}}))
            session = ok(await client.post("/api/sessions", json={"model_profile_id": profile["id"], "harness_enabled": True, "tools_allowed": ["base64_encode"]}))
            task = asyncio.create_task(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "go"}))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                state = app.state.runtime_state
                assert not task.done()
                delta = next(e for e in state.events.list_events() if e.type == "message_delta")
                assert delta.payload["delta"] == "live"
                assert not any(m.message_id == delta.message_id for m in state.messages.list_messages(session["session_id"]))
                ok(await client.post(f"/api/runs/{delta.run_id}/cancel"))
                assert ok(await asyncio.wait_for(task, 3))["run"]["status"] == "CANCELLED"
                assert state.model_manager.status(profile["id"]).active == 0
                assert state.runs.get_run(delta.run_id).status == RunStatus.CANCELLED
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_context_construction_consumes_active_budget(harness_client, monkeypatch):
    from ai_workbench.core import chat_runner
    client, upstream, _ = harness_client
    session, _, _ = configure(client)
    async def blocked_context(*_args):
        await asyncio.sleep(10)
    monkeypatch.setattr(chat_runner, "ACTIVE_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(client.app.state.runtime_state.chat_runner, "_build_context", blocked_context)
    response = send(client, session)
    assert response["run"]["error_code"] == "TOOL_RUN_TIMEOUT"
    assert response["run"]["steps"][0]["status"] == "failed" and not upstream.calls
