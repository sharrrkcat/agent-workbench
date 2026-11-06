"""Run-local summaries retain execution identities and approval continuations."""
import asyncio
import json
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ai_workbench.core.compaction_generation import RUN_SUMMARY_INSTRUCTION, SUMMARY_INSTRUCTION
from ai_workbench.core.harness.schema import HarnessState
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.web_schemas import WebSource
from tests.test_phase4_harness import harness_client, configure, send
from tests.test_chat_request_options import DEFAULTS, install_fake_worker
from tests.tool_fixtures import completion, ok, tool_call, create_tool_app, register_approval_tool, ToolOpenAI


def setup(client, *, history=True, enabled=True, strategy="token_budget", streaming=False, summary=512):
    session, _, profile = configure(client, tools=["test_echo", "test_approval"], streaming=streaming)
    ok(client.patch(f"/api/models/profiles/{profile['id']}", json={"context_window_tokens": 4096}))
    policy = ContextPolicy(history_enabled=history, strategy=strategy,
        compaction={"enabled": enabled, "trigger_percent": 70, "target_percent": 45, "max_summary_tokens": summary})
    session = ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {"context_policy": policy.model_dump()}}))
    state = client.app.state.runtime_state
    executed = []
    async def result(arguments, context):
        executed.append(context.tool_call_id)
        return {"content": f"FACT_{arguments['value']}=value{arguments['value']}; " + "padding " * 900}
    state.tool_registry._tools["test_echo"] = replace(state.tool_registry.get("test_echo"), handler=result)
    return session, state, executed


def is_summary(request):
    return request["messages"][0]["content"] in {SUMMARY_INSTRUCTION, RUN_SUMMARY_INSTRUCTION}


def summary(request):
    facts = list(dict.fromkeys(re.findall(r"FACT_\d+=value\d+;", request["messages"][1]["content"])))
    evidence = " [W1] https://example.com/evidence" if "[W1]" in request["messages"][1]["content"] else ""
    return {**completion(content="Facts: " + " ".join(facts) + evidence),
        "usage": {"prompt_tokens": 1000, "completion_tokens": 30, "total_tokens": 1030}}


def drive(upstream, count=4, *, final=None, summarize=summary, content="<think>PRIVATE_REASONING</think>Working"):
    answers = []
    def respond(request):
        if is_summary(request):
            return summarize(request)
        number = len(answers)
        answers.append(request)
        if number < count:
            result = completion(tool_call("test_echo", {"value": str(number)}, f"call_{number}"),
                content=content)
            result["message"]["reasoning_content"] = "STRUCTURED_PRIVATE_REASONING"
            return result
        return final(request) if final else completion(content="Done")
    upstream.turns = [respond] * 30
    return answers


def summaries(state, run_id):
    return [step for step in state.runs.list_steps(run_id) if step.kind == "compaction"]


@pytest.mark.parametrize("streaming", [False, True])
def test_three_loop_compactions_keep_raw_records_and_private_sources(harness_client, streaming):
    client, upstream, _ = harness_client
    session, state, executed = setup(client, history=False, streaming=streaming)
    answers = drive(upstream)
    result = send(client, session, "CURRENT INPUT MUST REMAIN")
    assert result["success"], result
    run_id = result["run"]["run_id"]
    steps = summaries(state, run_id)
    assert len(steps) == 3 and all(step.status == "completed" for step in steps)
    assert executed == [f"call_{i}" for i in range(4)]
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None
    assert state.runs.get_harness_state(run_id) == {}
    raw = state.messages.messages_for_run(run_id)
    assert len([m for m in raw if m.role == "tool"]) == 4
    assert sum("padding" in json.dumps(m.parts) for m in raw) == 4
    for request in answers:
        assert "CURRENT INPUT MUST REMAIN" in json.dumps(request["messages"])
    final = json.dumps(answers[-1]["messages"])
    for number in range(4):
        assert f"FACT_{number}=value{number};" in final
    assert [m["tool_call_id"] for m in answers[-1]["messages"] if m["role"] == "tool"] == ["call_3"]
    for index, step in enumerate(steps):
        metadata = step.metadata
        assert metadata["scope"] == "run" and metadata["llm"]["message_id"] is None
        assert metadata["input_tokens_after"] < metadata["input_tokens_before"]
        assert metadata["run_compaction"]["through_round"] == index + 1
        snapshot = state.runs.get_context_snapshot(step.step_id)
        assert snapshot.request.tools is None and snapshot.request.stream is False
        assert "CURRENT INPUT MUST REMAIN" not in snapshot.request.messages[1].content
        assert "PRIVATE_REASONING" not in snapshot.request.messages[1].content
        assert "Working" in snapshot.request.messages[1].content
    answer_step = [s for s in state.runs.list_steps(run_id) if s.kind == "model"][-1]
    detail = ok(client.get(f"/api/runs/{run_id}/steps/{answer_step.step_id}/context"))
    source = next(s for s in detail["sources"] if s["run_compaction"])
    assert source["run_compaction"]["run_id"] == run_id
    assert source["run_compaction"]["covered_tool_calls"] == 3
    assert source["compaction"] is None and source["kind"] == "summary"
    assert source["text"] not in client.get(f"/api/runs/{run_id}").text


@pytest.mark.parametrize('engine', ['llama-server', 'transformers'])
def test_native_tool_compaction_keeps_literal_content_and_excludes_reasoning(harness_client, monkeypatch, engine):
    client, _, tmp_path = harness_client
    session, state, executed = setup(client, history=False)
    profile, _, upstream = install_fake_worker(client.app, client, tmp_path, monkeypatch, engine=engine,
        alias='native', tools=True, options={**DEFAULTS, 'streaming': False})
    session = ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {'model_profile_id': profile['id']}}))
    literal = 'Working <think>literal tool text</think>'
    drive(upstream, count=4, content=literal)
    result = send(client, session)
    assert result['success'] and executed == [f'call_{index}' for index in range(4)]
    steps = summaries(state, result['run']['run_id'])
    assert steps and all(step.status == 'completed' for step in steps)
    inputs = [state.runs.get_context_snapshot(step.step_id).request.messages[1].content for step in steps]
    assert any(literal in value for value in inputs)
    assert all('STRUCTURED_PRIVATE_REASONING' not in value for value in inputs)
    compacted = [step for step in steps if step.metadata.get('run_compaction')]
    assert compacted and all(step.metadata['input_tokens_after'] < step.metadata['input_tokens_before'] for step in compacted)


@pytest.mark.parametrize("strategy,enabled", [("message_window", True), ("token_budget", False)])
def test_disabled_paths_never_summarize_active_rounds(harness_client, strategy, enabled):
    client, upstream, _ = harness_client
    session, state, executed = setup(client, strategy=strategy, enabled=enabled)
    drive(upstream)
    result = send(client, session)
    assert not result["success"] and result["error_code"] == "CONTEXT_WINDOW_EXCEEDED"
    assert summaries(state, result["run"]["run_id"]) == []
    assert len(executed) >= 2 and not any(is_summary(call) for call in upstream.calls)


def test_single_oversized_round_compacts_whole_pair(harness_client):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    async def huge(arguments, context):
        executed.append(context.tool_call_id)
        return {"content": "FACT_0=value0; " + "padding " * 3600 + " FACT_1=value1;"}
    state.tool_registry._tools["test_echo"] = replace(state.tool_registry.get("test_echo"), handler=huge)
    answers = drive(upstream, count=1)
    result = send(client, session)
    assert result["success"], result
    steps = summaries(state, result["run"]["run_id"])
    assert len(steps) >= 2 and len(steps) <= 4
    assert steps[-1].metadata["run_compaction"]["through_round"] == 1
    assert not any(m["role"] == "tool" or m.get("tool_calls") for m in answers[-1]["messages"])
    assert "FACT_0=value0;" in json.dumps(answers[-1]) and "FACT_1=value1;" in json.dumps(answers[-1])
    assert executed == ["call_0"]


def test_approval_keeps_summary_and_original_ids_without_replaying(harness_client):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    handler = state.tool_registry.get("test_echo").handler
    source = WebSource(source_id="W1", title="Evidence", url="https://example.com/evidence")
    async def evidence(arguments, context):
        if arguments["value"] == "0":
            context.web_sources["W1"] = source
            context.web_budget.searches_used = 1
        else:
            assert context.web_sources == {"W1": source} and context.web_budget.searches_used == 1
        result = await handler(arguments, context)
        result["content"] += " [W1] https://example.com/evidence"
        return result
    state.tool_registry._tools["test_echo"] = replace(state.tool_registry.get("test_echo"), handler=evidence)
    answers = drive(upstream, count=2, final=lambda _: completion(
        tool_call("test_approval", {"value": "approve"}, "approval"),
        tool_call("test_echo", {"value": "2"}, "after_approval")))
    result = send(client, session)
    assert result["run"]["status"] == "WAITING_FOR_USER", result
    run_id = result["run"]["run_id"]
    saved = state.runs.get_harness_state(run_id)
    assert saved["compaction"]["through_round"] == 1
    assert [call["id"] for call in saved["pending_calls"]] == ["approval", "after_approval"]
    assert len(saved["transcript"]) == 5 and len(executed) == 2
    checkpoint = saved["compaction"]
    assert saved["web_sources"] == {"W1": source.model_dump()}
    assert saved["web_budget"]["searches_used"] == 1 and "[W1]" in checkpoint["summary"]
    # Persisted continuations reject a boundary through an incomplete tool batch.
    corrupted = {**saved, "compaction": {**checkpoint, "transcript_end": 3}}
    with pytest.raises(ValueError, match="complete tool-round"):
        HarnessState.model_validate(corrupted)
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={'overrides': {"context_policy": {"strategy": "message_window"}}}))
    def resumed(request):
        return summary(request) if is_summary(request) else completion(content="Approved")
    upstream.turns = [resumed] * 8
    resumed_result = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert resumed_result["run"]["status"] == "DONE", resumed_result
    assert executed == ["call_0", "call_1", "after_approval"]
    assert state.runs.get_config_snapshot(run_id)["context_policy"]["strategy"] == "token_budget"
    assert len(summaries(state, run_id)) == 2


def test_restart_restores_run_summary_and_approval_once(tmp_path):
    upstream = ToolOpenAI()
    arguments = {"root": tmp_path, "database_url": f"sqlite:///{tmp_path / 'restart.db'}",
        "use_memory": False, "adapter_factory": upstream.factory}
    app = create_tool_app(**arguments)
    register_approval_tool(app.state.runtime_state.tool_registry)
    with TestClient(app) as client:
        session, state, executed = setup(client)
        drive(upstream, count=2, final=lambda _: completion(tool_call("test_approval", {"value": "once"}, "approval")))
        result = send(client, session)
        run_id = result["run"]["run_id"]
        assert result["run"]["status"] == "WAITING_FOR_USER"
        saved = state.runs.get_harness_state(run_id)
        snapshot = state.runs.get_context_snapshot(summaries(state, run_id)[0].step_id)
        assert executed == ["call_0", "call_1"]
    restarted = create_tool_app(**arguments)
    state = restarted.state.runtime_state
    register_approval_tool(state.tool_registry)
    approvals = []
    async def approve(arguments, context):
        approvals.append(context.tool_call_id)
        return {"content": "Approved once"}
    state.tool_registry._tools["test_approval"] = replace(state.tool_registry.get("test_approval"), handler=approve)
    upstream.turns = [completion(content="Restored")]
    with TestClient(restarted) as client:
        assert state.runs.get_harness_state(run_id) == saved
        assert state.runs.get_context_snapshot(snapshot.step_id) == snapshot
        response = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
        assert response["run"]["status"] == "DONE", response
        assert approvals == ["approval"] and len(summaries(state, run_id)) == 1
        assert saved["compaction"]["summary"] in json.dumps(upstream.calls[-1])
        assert client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}).status_code == 409
        assert state.runs.get_harness_state(run_id) == {}


def test_duplicate_id_in_compacted_prefix_still_fails(harness_client):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    drive(upstream, count=2, final=lambda _: completion(tool_call("test_echo", {"value": "repeat"}, "call_0")))
    result = send(client, session)
    assert result["error_code"] == "MODEL_PROTOCOL_ERROR"
    assert len(summaries(state, result["run"]["run_id"])) == 1
    assert executed == ["call_0", "call_1"]


@pytest.mark.parametrize("failure", ["empty", "length", "tools", "nonshrinking"])
def test_failed_summary_does_not_replace_memory(harness_client, failure):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    def fail(request):
        if failure == "empty":
            return completion(content=" ")
        if failure == "length":
            return completion(content="partial", finish="length")
        if failure == "tools":
            return completion(tool_call())
        return completion(content=request["messages"][1]["content"] * 2)
    answers = drive(upstream, count=2, summarize=fail)
    result = send(client, session)
    run_id = result["run"]["run_id"]
    assert len(summaries(state, run_id)) == 1
    assert not any(step.metadata.get("run_compaction") for step in summaries(state, run_id))
    # Two raw rounds still fit, so failed automatic compaction is diagnostic.
    assert result["success"], result
    assert summaries(state, run_id)[0].status == "failed"
    assert len([m for m in answers[-1]["messages"] if m["role"] == "tool"]) == 2
    assert executed == ["call_0", "call_1"]


def test_failed_summary_of_oversized_round_stops_before_answer(harness_client):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    async def huge(arguments, context):
        executed.append(context.tool_call_id)
        return {"content": "padding " * 3500}
    state.tool_registry._tools["test_echo"] = replace(state.tool_registry.get("test_echo"), handler=huge)
    answers = drive(upstream, count=1, summarize=lambda _: completion(content="bad", finish="length"))
    result = send(client, session)
    assert not result["success"] and result["error_code"] == "CONTEXT_COMPACTION_FAILED"
    assert len(answers) == 1 and executed == ["call_0"]


def test_history_and_tool_rounds_share_four_call_limit(harness_client):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    for number in range(2):
        user = state.messages.add_message(session["session_id"], "user", f"OLD_{number} " + "padding " * 1000)
        state.messages.add_message(session["session_id"], "assistant", "Recorded", parent_message_id=user.message_id)
    drive(upstream, count=6)
    result = send(client, session)
    assert result["error_code"] == "CONTEXT_COMPACTION_FAILED", result
    calls = summaries(state, result["run"]["run_id"])
    assert len(calls) == 4
    assert calls[0].metadata["scope"] == "history"
    assert any(step.metadata["scope"] == "run" for step in calls[1:])
    assert len([call for call in upstream.calls if is_summary(call)]) == 4
    assert 3 <= len(executed) <= 6


def test_cancel_during_summary_keeps_raw_calls_and_no_approval_replay(harness_client, monkeypatch):
    client, upstream, _ = harness_client
    session, state, executed = setup(client)
    drive(upstream)
    handle = upstream.handle
    async def scenario():
        reached = asyncio.Event()
        async def hold(request):
            if request.url.path.endswith("/chat/completions") and is_summary(json.loads(request.content)):
                reached.set()
                await asyncio.Event().wait()
            return await handle(request)
        monkeypatch.setattr(upstream, "handle", hold)
        task = asyncio.create_task(state.chat_runner.run(session_id=session["session_id"], text="cancel"))
        await asyncio.wait_for(reached.wait(), 10)
        run = state.runs.list_runs(session["session_id"])[-1]
        assert state.runs.get_harness_state(run.run_id)["compaction"] is None
        task.cancel()
        result = await task
        assert not result.success and result.error_code == "RUN_CANCELLED"
        assert state.runs.get_run(run.run_id).status == "CANCELLED"
        assert len(summaries(state, run.run_id)) == 1
        assert summaries(state, run.run_id)[0].status == "failed"
    client.portal.call(scenario)
    assert executed == ["call_0", "call_1"]
