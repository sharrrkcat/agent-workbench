"""QQ reply requirements and per-batch limits through the real harness and stores."""

import json

import httpx
import pytest

from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQDelivery
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project
from tests.tool_fixtures import completion, ok, tool_call


def execute_batch(client, state, p, session, number=1, *, private=False):
    ingest(client, state, p, event(number, kind="private" if private else "group"), number * 10)
    batch = freeze(state, session, number * 10 + 5)
    client.portal.call(state.qq.execute, batch)
    batch = state.qq.store.get(QQBatch, batch.id)
    return batch, state.runs.get_run(batch.run_id)


def test_reply_limit_configuration_and_http_contract(qq_client):
    client, state, _ = qq_client
    p = project(client)
    assert p["reply_message_limit"] == 4
    for limit in (1, 20):
        p = ok(client.patch(f"/api/projects/{p['id']}", json={"reply_message_limit": limit}))
        assert p["reply_message_limit"] == limit
    ok(client.patch(f"/api/projects/{p['id']}", json={"name": "Renamed"}))
    assert ok(client.get(f"/api/projects/{p['id']}"))["reply_message_limit"] == 20
    assert ok(client.get("/api/projects"))[0]["reply_message_limit"] == 20
    session = child(client, p)
    assert session["effective"]["qq_reply_message_limit"] == 20
    for value in (None, True, False, 0, 21, 1.5, "4"):
        assert client.patch(f"/api/projects/{p['id']}", json={"reply_message_limit": value}).status_code == 422
        assert client.post("/api/projects", json={"kind": "qqbot", "name": "Invalid limit", "context_policy": {},
            "bot_account": "98765", "websocket_url": "ws://localhost:3001", "reply_message_limit": value}).status_code == 422
    assert state.projects.get(p["id"]).reply_message_limit == 20
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    limit_schema = schemas["QQBotProjectResponse"]["properties"]["reply_message_limit"]
    assert (limit_schema["type"], limit_schema["minimum"], limit_schema["maximum"], limit_schema["default"]) == ("integer", 1, 20, 4)
    assert "no_reply" not in schemas["QQBatchResponse"]["properties"]["status"]["enum"]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("private", [False, True])
def test_each_batch_forces_its_first_tool_call_and_then_allows_stop(qq_client, streaming, private):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming)
    if private:
        session = child(client, p, "9999", "friend")
    for number in range(1, 4):
        upstream.turns = [completion(tool_call("qq_send_message", {"text": f"reply {number}"})),
                          completion(content="Private ending")]
        batch, run = execute_batch(client, state, p, session, number, private=private)
        assert batch.status == "done" and run.status == "DONE"
        assert run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 4, "limit_reached": False}
        requests = upstream.calls[-2:]
        assert [r["tool_choice"] for r in requests] == ["required", "auto"]
        system = requests[0]["messages"][0]["content"]
        assert f"QQ {'private' if private else 'group'} conversation" in system
        assert "This batch needs a reply" in system and "confirmed sends=0/4" in system
        assert system.count("Current batch=") == 1
        assert "confirmed sends=1/4" in requests[1]["messages"][0]["content"]
        assert requests[1]["messages"][-1]["role"] == "tool"
        if number > 1:
            assert any(json.loads(call["function"]["arguments"])["text"] == f"reply {number - 1}"
                       for m in requests[0]["messages"] for call in m.get("tool_calls", []))
            assert not any(m.get("content") == f"reply {number - 1}" for m in requests[0]["messages"])
        model_steps = [s for s in state.runs.list_steps(run.run_id) if s.kind == "model"]
        assert len(model_steps) == 2
        assert [state.runs.get_context_snapshot(s.step_id).request.tool_choice for s in model_steps] == ["required", "auto"]
        for index, step in enumerate(model_steps):
            snapshot = state.runs.get_context_snapshot(step.step_id)
            runtime = next(source for source in snapshot.sources if source.kind == "qq_runtime")
            assert f"confirmed sends={index}/4" in snapshot.request.messages[runtime.message_index].content[runtime.start:runtime.end]
    assert len(connection.calls) == 3


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("limit", [1, 4, 20])
def test_single_round_limit_rejects_unsent_calls_and_completes(qq_client, streaming, limit):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming, reply_message_limit=limit)
    upstream.turns = [completion(*(tool_call("qq_send_message", {"text": str(n)}, f"call_{n}") for n in range(limit + 2))),
                      completion(content="Must not request another model round")]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "done" and run.status == "DONE" and run.error_code is None
    assert run.metadata["qq_reply"] == {"sent_count": limit, "message_limit": limit, "limit_reached": True}
    assert len(upstream.calls) == 1 and len(upstream.turns) == 1
    assert [params["message"][0]["data"]["text"] for _, params in connection.calls] == list(map(str, range(limit)))
    deliveries = state.qq.store.page(QQDelivery, session["session_id"])["items"]
    assert len(deliveries) == limit and all(d["status"] == "sent" for d in deliveries)
    tool_steps = [s for s in state.runs.list_steps(run.run_id) if s.kind == "tool"]
    assert [s.status for s in tool_steps] == ["completed"] * limit + ["skipped"] * 2
    assert all(s.error_code == "QQ_REPLY_LIMIT_REACHED" and s.metadata["result_status"] == "rejected" for s in tool_steps[-2:])
    assert not state.qq.store.get(QQBinding, session["session_id"]).paused
    assert state.runs.get_harness_state(run.run_id) == {}


@pytest.mark.parametrize("streaming", [False, True])
def test_limit_spans_model_rounds_and_new_batch_resets_count(qq_client, streaming):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": str(n)}, f"call_{n}")) for n in range(4)]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "done" and run.metadata["qq_reply"]["limit_reached"]
    assert [r["tool_choice"] for r in upstream.calls] == ["required", "auto", "auto", "auto"]
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "next batch"})), completion(content="")]
    next_batch, next_run = execute_batch(client, state, p, session, 2)
    assert next_batch.status == "done"
    assert next_run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 4, "limit_reached": False}
    assert len(connection.calls) == 5 and len(upstream.calls) == 6
    assert upstream.calls[-2]["tool_choice"] == "required"


def test_running_limit_is_snapshotted_and_progress_retains_confirmed_count(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=2)
    original = connection.call
    async def change_limit(action, params):
        run_id = state.qq.store.active_batch(session["session_id"]).run_id
        if not connection.calls:
            state.project_service.update(p["id"], {"reply_message_limit": 1})
        else:
            assert state.runs.get_run(run_id).metadata["qq_reply"] == {"sent_count": 1, "message_limit": 2, "limit_reached": False}
            assert state.runs.get_harness_state(run_id)["qq_sent_count"] == 1
        return await original(action, params)
    connection.call = change_limit
    upstream.turns = [completion(tool_call("qq_send_message", {"text": str(n)}, f"call_{n}")) for n in range(2)]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "done" and run.metadata["qq_reply"]["sent_count"] == 2
    assert state.runs.get_config_snapshot(run.run_id)["qq_reply_message_limit"] == 2
    assert all(f"confirmed sends={i}/2" in r["messages"][0]["content"] for i, r in enumerate(upstream.calls))
    connection.call = original
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "next"}))]
    _, next_run = execute_batch(client, state, p, session, 2)
    assert next_run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 1, "limit_reached": True}


@pytest.mark.parametrize("recover", [False, True])
def test_invalid_arguments_do_not_satisfy_reply_or_consume_send_limit(qq_client, recover):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    upstream.turns = [completion(tool_call("qq_send_message", "{}", "invalid")),
        completion(tool_call("qq_send_message", {"text": "valid"}, "valid")) if recover else completion(content="")]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == ("done" if recover else "failed")
    assert run.error_code == (None if recover else "QQ_REPLY_REQUIRED")
    assert run.metadata["qq_reply"]["sent_count"] == len(connection.calls) == int(recover)
    result = json.loads(upstream.calls[1]["messages"][-1]["content"])
    assert result["error_code"] == "TOOL_INVALID_ARGUMENTS"
    assert upstream.calls[1]["tool_choice"] == "auto"


@pytest.mark.parametrize("send_reply", [False, True])
def test_other_tool_success_does_not_count_as_qq_delivery(qq_client, monkeypatch, send_reply):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    monkeypatch.setattr(state.chat_runner.harness_loop, "allowed_tools", lambda _: ["base64_encode", "qq_send_message"])
    upstream.turns = [completion(tool_call("base64_encode", {"value": "hello"})),
        completion(tool_call("qq_send_message", {"text": "reply"}, "reply")) if send_reply else completion(content="")]
    batch, run = execute_batch(client, state, p, session)
    assert upstream.calls[0]["tool_choice"] == "required"
    assert run.metadata["qq_reply"]["sent_count"] == len(connection.calls) == int(send_reply)
    assert batch.status == ("done" if send_reply else "failed")
    assert run.error_code == (None if send_reply else "QQ_REPLY_REQUIRED")


@pytest.mark.parametrize("failure,status", [(ToolExecutionError("QQ_ACTION_FAILED", "Rejected"), "failed"), (TimeoutError(), "unknown")])
def test_partial_delivery_failure_preserves_count_and_stops(qq_client, failure, status):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=2)
    original = connection.call
    async def fail_second(action, params):
        if connection.calls:
            connection.failure = failure
        return await original(action, params)
    connection.call = fail_second
    upstream.turns = [completion(*(tool_call("qq_send_message", {"text": str(n)}, f"call_{n}") for n in range(3)))]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "failed" and run.error_code == ("QQ_ACTION_FAILED" if status == "failed" else "QQ_DELIVERY_UNKNOWN")
    assert run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 2, "limit_reached": False}
    assert len(connection.calls) == 2
    assert [d["status"] for d in state.qq.store.page(QQDelivery, session["session_id"])["items"]] == [status, "sent"]
    assert state.qq.store.get(QQBinding, session["session_id"]).paused


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("after_send", [False, True])
def test_provider_error_does_not_retry_or_hide_confirmed_sends(qq_client, streaming, after_send):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming)
    def reject(data):
        raise httpx.HTTPStatusError("Provider rejected the request", request=httpx.Request("POST", "http://provider.test/v1/chat/completions"),
                                   response=httpx.Response(400 if not after_send else 500))
    upstream.turns = ([completion(tool_call("qq_send_message", {"text": "confirmed"}))] if after_send else []) + [reject]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "failed" and run.error_code == "PROVIDER_ERROR"
    assert run.metadata["qq_reply"] == {"sent_count": int(after_send), "message_limit": 4, "limit_reached": False}
    assert len(upstream.calls) == 1 + int(after_send) and upstream.calls[0]["tool_choice"] == "required"
    assert len(connection.calls) == int(after_send)
    assert state.qq.store.get(QQBinding, session["session_id"]).paused


def test_cancellation_wins_over_reaching_limit(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    original = connection.call
    async def cancel_with_receipt(action, params):
        receipt = await original(action, params)
        run_id = state.qq.store.active_batch(session["session_id"]).run_id
        state.runs.update_status(run_id, RunStatus.RUNNING, cancel_requested=True)
        return receipt
    connection.call = cancel_with_receipt
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "confirmed"}, "one"),
                                 tool_call("qq_send_message", {"text": "never sent"}, "two"))]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "cancelled" and run.error_code == "RUN_CANCELLED"
    assert run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 1, "limit_reached": False}
    assert len(connection.calls) == 1 and state.qq.store.get(QQBinding, session["session_id"]).paused


def test_shared_tool_round_limit_still_applies(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=20)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": str(n)}, f"call_{n}")) for n in range(9)]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "failed" and run.error_code == "TOOL_LOOP_LIMIT"
    assert run.metadata["qq_reply"] == {"sent_count": 8, "message_limit": 20, "limit_reached": False}
    assert len(upstream.calls) == 9 and len(connection.calls) == 8
    assert state.qq.store.get(QQBinding, session["session_id"]).paused
