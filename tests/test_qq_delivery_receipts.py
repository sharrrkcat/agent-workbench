"""QQ send deadlines, unconfirmed outcomes and exact self-echo correlation."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from ai_workbench.core import qq_protocol
from ai_workbench.core.harness import agent_loop
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.qq_protocol import OneBotConnection
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBinding, QQDelivery, QQMessage
from tests.test_qqbot import qq_client, child, configure_execution, event, ingest
from tests.test_qq_followup import clock, participant
from tests.test_qq_image_tools import favorite, send_image
from tests.test_qq_media import isolated_attachments
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import completion, tool_call


NATIVE_TIMEOUT = ("Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg "
    "ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate EventRet:\n{}\n")


@pytest.mark.parametrize("action,field,diagnostic,code", [
    ("send_group_msg", "message", NATIVE_TIMEOUT, "QQ_SEND_ACK_TIMEOUT"),
    ("send_private_msg", "wording", "Error: " + NATIVE_TIMEOUT, "QQ_SEND_ACK_TIMEOUT"),
    ("get_login_info", "message", NATIVE_TIMEOUT, "QQ_ACTION_FAILED"),
    ("get_image", "wording", NATIVE_TIMEOUT, "QQ_ACTION_FAILED"),
    ("send_group_msg", "message", NATIVE_TIMEOUT.replace("Timeout:", "EventChecker Failed:"), "QQ_ACTION_FAILED"),
    ("send_group_msg", "message", NATIVE_TIMEOUT.replace("sendMsg", "fetchUserDetailInfo"), "QQ_ACTION_FAILED"),
    ("send_group_msg", "message", "Timeout: some other operation", "QQ_ACTION_FAILED"),
    ("send_group_msg", "message", "Quoted user text: " + NATIVE_TIMEOUT, "QQ_ACTION_FAILED"),
])
def test_native_timeout_classification_is_scoped_and_sanitized(action, field, diagnostic, code):
    response = {"status": "failed", "retcode": 1200, "data": None, "message": {"private": "data"},
        field: diagnostic + "private-token base64://private-image"}
    with pytest.raises(ToolExecutionError) as caught:
        OneBotConnection.action_data(response, action=action)
    error = caught.value
    assert error.code == code
    assert error.details == {"action": action, "retcode": 1200,
        "cause": "napcat_send_ack_timeout" if code == "QQ_SEND_ACK_TIMEOUT" else "onebot_action_error"}
    saved = str(error) + json.dumps(error.details)
    assert "private-token" not in saved and "base64://private-image" not in saved


def test_malformed_retcode_is_not_copied_into_error_details():
    with pytest.raises(ToolExecutionError) as caught:
        OneBotConnection.action_data({"status": "failed", "retcode": "private-token"}, action="send_group_msg")
    assert caught.value.details["retcode"] is None
    assert "private-token" not in str(caught.value) + json.dumps(caught.value.details)


class QueueSocket:
    def __init__(self):
        self.requests, self.responses = asyncio.Queue(), asyncio.Queue()

    async def send(self, raw):
        self.requests.put_nowait(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.responses.get())


def test_response_deadlines_and_echo_matching_discard_late_responses(monkeypatch):
    observed = []
    async def wait_for(future, timeout):
        observed.append(timeout)
        return await asyncio.wait_for(future, {20: .02, 90: 1}.get(timeout, timeout))
    monkeypatch.setattr(qq_protocol, "asyncio", SimpleNamespace(
        get_running_loop=asyncio.get_running_loop, wait_for=wait_for))

    async def scenario():
        received = []
        async def receive(value):
            received.append(value)
        connection = OneBotConnection(None, receive)
        socket = connection.socket = QueueSocket()
        connection.ready = True
        reader = asyncio.create_task(connection.read())
        try:
            query = asyncio.create_task(connection.call("get_image", {}))
            old = await socket.requests.get()
            with pytest.raises(asyncio.TimeoutError):
                await query
            assert connection.pending == {}

            send = asyncio.create_task(connection.call("send_group_msg", {}, timeout=90))
            request = await socket.requests.get()
            socket.responses.put_nowait({"echo": old["echo"], "status": "ok", "retcode": 0,
                "data": {"message_id": 9000}})
            await asyncio.sleep(.04)  # Beyond the scaled default, within the send deadline.
            assert not send.done()
            response = {"echo": request["echo"], "status": "ok", "retcode": 0, "data": {"message_id": 1001}}
            socket.responses.put_nowait(response)
            assert await send == {"message_id": 1001}
            socket.responses.put_nowait(response)
            socket.responses.put_nowait({"echo": request["echo"], "status": "failed", "retcode": 1200})

            expired = asyncio.create_task(connection.call("send_group_msg", {}, timeout=.01))
            request = await socket.requests.get()
            with pytest.raises(asyncio.TimeoutError):
                await expired
            socket.responses.put_nowait({**response, "echo": request["echo"]})
            query = asyncio.create_task(connection.call("get_image", {}))
            request = await socket.requests.get()
            socket.responses.put_nowait({**response, "echo": request["echo"], "data": {"file": "image.png"}})
            assert await query == {"file": "image.png"}
            assert connection.pending == {} and received == []
            assert observed == [20, 90, .01, 20]
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
    asyncio.run(scenario())


def test_native_timeout_keeps_image_unconfirmed_even_with_matching_self_messages(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    asset, _ = favorite(state)
    original = connection.call
    own = {**event(1001, sender="12345"), "post_type": "message_sent",
        "message": [{"type": "image", "data": {"file": asset.sha256 + ".gif"}}]}

    async def send(action, params, *, timeout=20):
        await original(action, params, timeout=timeout)
        await state.qq.ingest(p["id"], own)
        return OneBotConnection.action_data({"status": "failed", "retcode": 1200,
            "message": NATIVE_TIMEOUT + "private-token"}, action=action)
    connection.call = send
    upstream.turns = [completion(send_image(asset.id), tool_call("qq_send_message", {"text": "never send"}, "second"))]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status == "failed" and run.error_code == "QQ_SEND_ACK_TIMEOUT"
    assert run.metadata["qq_reply"]["sent_count"] == 0
    binding = state.qq.store.get(QQBinding, session["session_id"])
    assert binding.paused and binding.pause_reason == "QQ_SEND_ACK_TIMEOUT"
    records = lambda: state.qq.store.page(QQDelivery, session["session_id"])["items"]
    before = records()
    assert len(before) == 1 and before[0]["status"] == "unknown" and before[0]["external_id"] is None
    ingest(client, state, p, own, 100)
    state.qq.store.recover()
    client.portal.call(state.qq.execute, batch)
    assert records() == before and len(connection.calls) == 1
    assert state.qq.send_echoes == {}
    events = json.dumps([e.model_dump(mode="json") for e in state.events.list_events()
        if e.run_id == run.run_id and e.type == "tool_result_created"])
    assert "napcat_send_ack_timeout" in events and "1200" in events and "private-token" not in events


@pytest.mark.parametrize("result", [{}, {"message_id": None}, {"message_id": True}, {"message_id": 1.5},
    {"message_id": ""}, {"message_id": "  "}])
def test_invalid_receipt_never_confirms_or_runs_another_send(qq_client, result):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    original = connection.call
    async def send(action, params, *, timeout=20):
        await original(action, params, timeout=timeout)
        return result
    connection.call = send
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "first"}, "first"),
        tool_call("qq_send_message", {"text": "second"}, "second"))]
    batch, run = execute_batch(client, state, p, session)
    delivery, = state.qq.store.page(QQDelivery, session["session_id"])["items"]
    assert delivery["status"] == "unknown" and delivery["external_id"] is None
    assert run.error_code == "QQ_DELIVERY_UNKNOWN" and run.metadata["qq_reply"]["sent_count"] == 0
    assert batch.status == "failed" and state.qq.store.get(QQBinding, session["session_id"]).paused
    assert len(connection.calls) == 1 and state.qq.send_echoes == {}


@pytest.mark.parametrize("mode,private,echoed", [
    ("early", False, True), ("early", True, True), ("late", False, True), ("late", True, True),
    ("other_target", False, False), ("other_account", False, False), ("no_id", False, False),
    ("overflow", False, False),
])
def test_self_echo_order_scope_and_bound_do_not_duplicate_confirmation(qq_client, clock, mode, private, echoed):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    if private:
        session = child(client, p, "9999", "friend")
    other = child(client, p, "8877")
    own = {**event(1001, "same content", sender="12345", kind="private" if private else "group"),
        "post_type": "message_sent", "target_id": 9999}
    original = connection.call
    async def send(action, params, *, timeout=20):
        result = await original(action, params, timeout=timeout)
        if mode == "early":
            await state.qq.ingest(p["id"], own)
            await state.qq.ingest(p["id"], own)
        elif mode == "other_target":
            await state.qq.ingest(p["id"], {**own, "group_id": 8877})
        elif mode == "other_account":
            await state.qq.ingest(p["id"], {**own, "self_id": 54321})
        elif mode == "no_id":
            for invalid in (None, True, "", "  "):
                await state.qq.ingest(p["id"], {**own, "message_id": invalid})
        elif mode == "overflow":
            await state.qq.ingest(p["id"], own)
            for number in range(2000, 2128):
                await state.qq.ingest(p["id"], {**own, "message_id": number})
            assert len(state.qq.send_echoes[session["session_id"]]) == 128
        return {"message_id": str(result["message_id"])}
    connection.call = send
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "same content"}))]
    _, run = execute_batch(client, state, p, session, private=private)
    record = lambda: state.qq.store.page(QQDelivery, session["session_id"])["items"][0]
    assert record()["echoed"] == (echoed and mode != "late")
    before = participant(state, session)
    before = before.model_dump() if before is not None else None
    clock[0] = 1000
    if mode in {"early", "late"}:
        ingest(client, state, p, own, 1000)
        ingest(client, state, p, own, 1000)
    assert record()["status"] == "sent" and record()["echoed"] == echoed
    after = participant(state, session)
    assert (after.model_dump() if after is not None else None) == before
    assert run.status == "DONE" and run.metadata["qq_reply"]["sent_count"] == 1
    assert len(state.qq.store.page(QQDelivery, session["session_id"])["items"]) == 1
    assert len(state.qq.store.page(QQMessage, session["session_id"])["items"]) == 1
    assert state.qq.store.page(QQMessage, other["session_id"])["items"] == []
    context = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    assert sum(m["role"] == "assistant" for m in context.messages) == 1
    assert state.qq.send_echoes == {}


@pytest.mark.parametrize("image", [False, True])
@pytest.mark.parametrize("exhaust_budget", [False, True])
def test_qq_sends_use_response_deadline_but_remain_within_run_budget(qq_client, monkeypatch, image, exhaust_budget):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    call = send_image(favorite(state)[0].id) if image else tool_call("qq_send_message", {"text": "reply"})
    monkeypatch.setattr(agent_loop, "TOOL_TIMEOUT_SECONDS", .01)
    if exhaust_budget:
        monkeypatch.setattr(agent_loop, "ACTIVE_BUDGET_SECONDS", 1)
    original = connection.call
    async def send(action, params, *, timeout=20):
        result = await original(action, params, timeout=timeout)
        if exhaust_budget:
            await asyncio.Event().wait()
        await asyncio.sleep(.04)
        return result
    connection.call = send
    upstream.turns = [completion(call)]
    batch, run = execute_batch(client, state, p, session)
    delivery, = state.qq.store.page(QQDelivery, session["session_id"])["items"]
    assert len(connection.calls) == 1 and connection.timeouts == [90]
    assert delivery["status"] == ("unknown" if exhaust_budget else "sent")
    assert run.error_code == ("TOOL_RUN_TIMEOUT" if exhaust_budget else None)
    assert run.metadata["qq_reply"]["sent_count"] == (0 if exhaust_budget else 1)
    assert state.qq.store.get(QQBinding, session["session_id"]).paused == exhaust_budget
    assert batch.status == ("failed" if exhaust_budget else "done")
    assert state.qq.send_echoes == {}
