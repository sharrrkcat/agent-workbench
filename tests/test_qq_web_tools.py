"""QQ web tools reuse global settings, round budgets and citation-free results."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from ai_workbench.core.anysearch import AnySearchProvider
from ai_workbench.core.harness import agent_loop
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.db.qq_models import QQBinding
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest
from tests.test_qq_followup import clock, execute, followup
from tests.test_qq_icebreaker import queued
from tests.test_qq_reply_policy import execute_batch
from tests.test_web_tools import AnySearchFixture, URL, response
from tests.tool_fixtures import completion, ok, tool_call


@pytest.fixture
def qq_web(qq_client):
    client, state, _ = qq_client
    network = AnySearchFixture()
    state.web_tools.provider = AnySearchProvider(transport=httpx.MockTransport(network.handle))
    ok(client.patch("/api/tools/web/settings", json={"api_key": "shared-web-key", "max_results": 3,
        "zone": "intl", "language": "en"}))
    return network


def results(state, run):
    return [part for message in state.messages.messages_for_run(run.run_id) for part in message.parts
            if part["type"] == "tool_result"]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("private", [False, True])
def test_shared_settings_requests_snapshots_and_history(qq_client, qq_web, monkeypatch, streaming, private):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming)
    if private:
        session = child(client, p, "9999", "friend")
    assert {"web_search", "web_fetch"}.issubset(session["effective"]["tools_allowed"])
    day = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(agent_loop, "utc_now", lambda: day)
    upstream.turns = [completion(tool_call("web_search", {"query": "current facts"}, "search")),
        completion(tool_call("web_fetch", {"url": URL}, "fetch")),
        completion(tool_call("qq_send_message", {"text": "Here are the current facts."}, "send")),
        completion(content="Internal completion")]
    batch, run = execute_batch(client, state, p, session, private=private)
    assert batch.status == "done" and run.status == "DONE"
    assert run.metadata["qq_reply"]["sent_count"] == len(connection.calls) == 1
    assert json.loads(qq_web.calls[0].content) == {"query": "current facts", "max_results": 3,
        "zone": "intl", "language": "en", "format": "markdown"}
    assert json.loads(qq_web.calls[1].content) == {"url": URL}
    assert all(request.headers["authorization"] == "Bearer shared-web-key" for request in qq_web.calls)
    steps = state.runs.list_steps(run.run_id)
    assert not any(step.kind == "approval" for step in steps)
    model_steps = [step for step in steps if step.kind == "model"]
    assert [request["tool_choice"] for request in upstream.calls] == ["required", "auto", "auto", "auto"]
    for step, request in zip(model_steps, upstream.calls):
        assert {tool["function"]["name"] for tool in request["tools"]} == {"qq_send_message", "web_fetch", "web_search"}
        for tool in request["tools"]:
            if tool["function"]["name"].startswith("web_"):
                description = tool["function"]["description"]
                assert "untrusted evidence" in description
                assert "source_id" not in description and "[W1]" not in description
        snapshot = state.runs.get_context_snapshot(step.step_id)
        instruction = next(source for source in snapshot.sources if source.kind == "instruction")
        assert "Current date:" in snapshot.request.messages[instruction.message_index].content[instruction.start:instruction.end]
        assert day.astimezone().date().isoformat() in request["messages"][0]["content"]
        assert snapshot.request.model_dump(mode="json", exclude_unset=True, by_alias=True) == request
    assert {"web_search", "web_fetch"}.issubset(state.runs.get_config_snapshot(run.run_id)["tools_allowed"])
    web_results = [part for part in results(state, run) if part["tool_name"].startswith("web_")]
    assert len(web_results) == 2 and all(part["status"] == "success" for part in web_results)
    assert "source_id" not in json.dumps(web_results)
    live_results = [json.loads(message["content"]) for message in upstream.calls[2]["messages"] if message["role"] == "tool"]
    assert "source_id" not in json.dumps(live_results) and "Evidence" in json.dumps(live_results)
    history = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None).model_dump_json()
    assert "Here are the current facts." in history
    assert all(value not in history for value in ("web_search", "web_fetch", "Untrusted page", "Internal completion"))


@pytest.mark.parametrize("streaming", [False, True])
def test_four_web_rounds_leave_four_sends_and_mixed_calls_count_once(qq_client, qq_web, streaming):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming)
    upstream.turns = [completion(tool_call("web_search", {"query": "facts"}, f"search{n}")) for n in range(4)]
    upstream.turns += [completion(tool_call("web_fetch", {"url": URL}, f"fetch{n}"),
        tool_call("qq_send_message", {"text": f"reply {n}"}, f"send{n}")) for n in range(4)]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "done" and len(upstream.calls) == len(qq_web.calls) == 8
    assert len(connection.calls) == 4 and run.metadata["qq_reply"]["limit_reached"]
    assert [step.metadata["round"] for step in state.runs.list_steps(run.run_id) if step.kind == "model"] == list(range(1, 9))
    assert all("confirmed sends=0/4" in request["messages"][0]["content"] for request in upstream.calls[:5])


@pytest.mark.parametrize("last_tool", ["web_search", "qq_send_message"])
def test_ninth_tool_round_is_rejected_even_when_no_send_slot_was_used(qq_client, qq_web, last_tool):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    upstream.turns = [completion(tool_call("web_search", {"query": "facts"}, f"search{n}")) for n in range(8)]
    upstream.turns.append(completion(tool_call(last_tool, {"query": "again"} if last_tool == "web_search" else {"text": "too late"}, "ninth")))
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "failed" and run.error_code == "TOOL_LOOP_LIMIT"
    assert len(qq_web.calls) == 8 and len(upstream.calls) == 9 and not connection.calls
    assert run.metadata["qq_reply"]["sent_count"] == 0


@pytest.mark.parametrize("failure", ["missing_key", "rate_limit", "empty", "invalid_url"])
def test_web_errors_and_empty_results_allow_a_reply(qq_client, qq_web, failure):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    call = tool_call("web_search", {"query": "facts"}, "search")
    if failure == "missing_key":
        ok(client.patch("/api/tools/web/settings", json={"api_key": ""}))
    elif failure == "rate_limit":
        qq_web.reply = response(None, status=429)
    elif failure == "empty":
        qq_web.reply = response({"results": []})
    else:
        call = tool_call("web_fetch", {"url": "http://127.0.0.1/private"}, "fetch")
    upstream.turns = [completion(call), completion(tool_call("qq_send_message", {"text": "A useful reply."}, "send"),
        tool_call("web_search", {"query": "must not execute"}, "after_limit"))]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "done" and len(connection.calls) == 1
    assert not state.qq.store.get(QQBinding, session["session_id"]).paused
    first, _, last = results(state, run)
    expected = {"missing_key": "WEB_NOT_CONFIGURED", "rate_limit": "WEB_RATE_LIMITED",
        "empty": None, "invalid_url": "NETWORK_ADDRESS_FORBIDDEN"}[failure]
    assert first.get("error_code") == expected
    assert last["error_code"] == "QQ_REPLY_LIMIT_REACHED"
    assert len(qq_web.calls) == int(failure in {"rate_limit", "empty"})


@pytest.mark.parametrize("optional", ["followup", "icebreaker"])
@pytest.mark.parametrize("streaming", [False, True])
def test_web_failure_allows_optional_skip(qq_client, qq_web, clock, optional, streaming):
    client, state, upstream = qq_client
    _, session, connection, batch = (followup if optional == "followup" else queued)(qq_client, clock, streaming=streaming)
    sent_before = len(connection.calls)
    qq_web.reply = response(None, status=429)
    upstream.turns = [completion(tool_call("web_search", {"query": "facts"}, "search")),
        completion(tool_call("qq_skip_reply", "{}", "skip"), tool_call("web_fetch", {"url": URL}, "after_skip"))]
    batch, run = execute(qq_client, batch)
    assert batch.status == "done" and run.metadata["qq_reply"]["skipped"]
    assert len(connection.calls) == sent_before and len(qq_web.calls) == 1
    assert not state.qq.store.get(QQBinding, session["session_id"]).paused
    assert results(state, run)[-1]["error_code"] == "QQ_REPLY_SKIPPED"


@pytest.mark.parametrize("ending", ["no_reply", "delivery_failure"])
def test_web_success_does_not_satisfy_reply_or_hide_delivery_failure(qq_client, qq_web, ending):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    connection.failure = ToolExecutionError("QQ_ACTION_FAILED", "Rejected")
    upstream.turns = [completion(tool_call("web_search", {"query": "facts"}, "search")),
        completion(content="Internal answer") if ending == "no_reply" else
        completion(tool_call("qq_send_message", {"text": "reply"}, "send"))]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "failed"
    assert run.error_code == ("QQ_REPLY_REQUIRED" if ending == "no_reply" else "QQ_ACTION_FAILED")
    assert run.metadata["qq_reply"]["sent_count"] == 0
    assert state.qq.store.get(QQBinding, session["session_id"]).paused


@pytest.mark.parametrize("mode", ["tool_timeout", "run_timeout", "cancel"])
def test_web_timeouts_and_cancellation_keep_qq_lifecycle(qq_client, qq_web, monkeypatch, mode):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    upstream.turns = [completion(tool_call("web_search", {"query": "facts"}, "search")),
        completion(tool_call("qq_send_message", {"text": "Search timed out."}, "send"))]

    async def scenario():
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def hold(_request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        state.web_tools.provider = AnySearchProvider(transport=httpx.MockTransport(hold))
        if mode != "cancel":
            monkeypatch.setattr(agent_loop, "TOOL_TIMEOUT_SECONDS", .02)
        if mode == "run_timeout":
            monkeypatch.setattr(agent_loop._Budget, "remaining", lambda _: 0 if started.is_set() else 30)
        task = asyncio.create_task(state.qq.execute(batch))
        await asyncio.wait_for(started.wait(), 5)
        if mode == "cancel":
            state.runs.update_status(batch.run_id, RunStatus.RUNNING, cancel_requested=True)
            assert state.active_runs.cancel(batch.run_id)
        await asyncio.wait_for(task, 5)
        assert cancelled.is_set() and state.active_runs.active_count() == 0
    client.portal.call(scenario)
    run = state.runs.get_run(batch.run_id)
    assert run.status == {"tool_timeout": "DONE", "run_timeout": "FAILED", "cancel": "CANCELLED"}[mode]
    assert results(state, run)[0]["error_code"] == {
        "tool_timeout": "TOOL_TIMEOUT", "run_timeout": "TOOL_RUN_TIMEOUT", "cancel": "RUN_CANCELLED"}[mode]
    assert len(connection.calls) == int(mode == "tool_timeout")
    assert state.qq.store.get(QQBinding, session["session_id"]).paused == (mode != "tool_timeout")
