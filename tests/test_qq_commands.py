"""Direct commands remain durable and never become model input or history."""
import asyncio
import json
import time

import pytest
from sqlmodel import Session, select

from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery, QQParticipant, QQNotification
from tests.test_qqbot import qq_client, configure_execution, project, child, event, ingest, freeze
from tests.tool_fixtures import completion, tool_call, ok


def commands(client, state, p):
    client.portal.call(state.qq.programs.process_commands, p["id"])


def replies(state, session):
    return sorted(state.qq.store.page(QQDelivery, session["session_id"], limit=100)["items"], key=lambda row: row["id"])


def resources(monkeypatch, state):
    monkeypatch.setattr(state.runtime_resources, "resources", lambda: {
        "memory": {"used_bytes": 1024**3, "total_bytes": 4 * 1024**3, "percent": 25},
        "process": {"backend_memory_bytes": 64 * 1024**2}, "cpu": {"percent": 12.5}})


def test_admin_schema_is_optional_strict_and_not_the_bot(qq_client):
    client, state, _ = qq_client
    p = project(client)
    assert p["admin_qq"] is None
    for value in (123, True, "", "0", "01", "-3", "1.0", "12345", "1" * 21):
        assert client.patch(f"/api/projects/{p['id']}", json={"admin_qq": value}).status_code == 422
    assert ok(client.patch(f"/api/projects/{p['id']}", json={"admin_qq": "9999"}))["admin_qq"] == "9999"
    assert state.qq.store.bindings(p["id"]) == [], "Settings alone do not create a conversation"
    assert ok(client.patch(f"/api/projects/{p['id']}", json={"name": "renamed"}))["admin_qq"] == "9999"
    assert ok(client.patch(f"/api/projects/{p['id']}", json={"admin_qq": None}))["admin_qq"] is None


def test_prefix_uses_only_actual_leading_text(qq_client):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state, keywords=["cogita"])
    values = [
        ("/cogita", True), ("/cogita check", True), ("/cogita\tcheck", True),
        ("/cogita wrong", True), ("/cogita check extra", True),
        ("/cogitabot check", False), (" /cogita check", False), ("/Cogita check", False),
        ("hello /cogita check", False), ("[CQ:reply,id=1]/cogita check", False),
        ("[CQ:at,qq=12345]/cogita check", False),
        ([{"type": "json", "data": {"data": {"meta": {"news": {"title": "/cogita pause"}}}}}], False),
        ([{"type": "text", "data": {"text": "/cog"}}, {"type": "text", "data": {"text": "ita check"}}], True),
    ]
    for number, (body, expected) in enumerate(values, 1):
        message = event(number)
        message["message"] = body
        ingest(client, state, p, message, number)
        row = state.qq.store.page(QQMessage, session["session_id"])["items"][0]
        assert (row["kind"] == "command") == expected, body
        assert (row["command_status"] == "pending") == expected, body


def test_pause_check_resume_are_visible_but_excluded_from_batches_and_context(qq_client, monkeypatch):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, admin_qq="9999", keywords=["cogita", "bot"], reply_message_limit=1)
    resources(monkeypatch, state)
    ingest(client, state, p, event(1, "/cogita pause"), 1)
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline is None
    assert state.qq.store.get(QQParticipant, (session["session_id"], "9999")) is None
    commands(client, state, p)
    assert state.qq.store.get(QQBinding, session["session_id"]).paused
    ingest(client, state, p, event(2, "bot ordinary input"), 2)
    old = freeze(state, session, 7)
    ingest(client, state, p, event(3, "/cogita check"), 8)
    commands(client, state, p)
    check = replies(state, session)[-1]
    assert "64.0 MiB" in check["text"] and "待执行批次：1" in check["text"]
    assert "最近模型调用：暂无" in check["text"] and "connected" in check["text"]
    client.portal.call(state.qq.programs.send_pending, p["id"])
    assert len(connection.calls) == 2 and not upstream.calls
    assert state.messages.list_messages(session["session_id"]) == []
    ingest(client, state, p, event(4, "/cogita resume"), 9)
    commands(client, state, p)
    merged = state.qq.store.next_batch(p["id"])
    assert merged and merged.id > old.id
    assert [m.external_id for m in state.qq.store.batch_messages(merged.id)] == ["2"]
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "ordinary reply"}, "one"))]
    client.portal.call(state.qq.execute, merged)
    context = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    for payload in (context.model_dump_json(), json.dumps(upstream.calls, ensure_ascii=False)):
        assert "/cogita" not in payload and "health: ok" not in payload
        assert "ordinary input" in payload
    assert "ordinary reply" in context.model_dump_json()
    rows = state.qq.store.page(QQMessage, session["session_id"])["items"]
    assert len(rows) == 4 and all(r["batch_id"] is None for r in rows if r["kind"] == "command")
    assert sum(r["origin"] == "command" and r["run_id"] is None for r in replies(state, session)) == 3


def test_permissions_targets_and_duplicate_commands(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, admin_qq="9999")
    friend = child(client, p, "7788", "friend")
    for number, text, sender, expected in [
        (1, "/cogita pause", "5555", "仅本项目"),
        (2, "/cogita pause 7788", "9999", "多个会话"),
        (3, "/cogita pause 7777", "9999", "不存在"),
        (4, "/cogita pause friend:7788", "9999", "friend:7788 已暂停"),
        (5, "/cogita resume friend:7788", "9999", "friend:7788 已恢复"),
        (6, "/cogita resume friend:7788", "9999", "friend:7788 已恢复"),
        (7, "/cogita check extra", "9999", "用法"),
        (8, "/cogita unknown", "9999", "用法"),
        (9, "/cogita", "9999", "用法"),
        (10, "/cogita pause group:7788 extra", "9999", "用法"),
    ]:
        data = event(number, text, sender=sender)
        data["sender"].update(role="owner", nickname="9999")
        ingest(client, state, p, data, number)
        commands(client, state, p)
        assert expected in replies(state, session)[-1]["text"]
        ingest(client, state, p, data, number + 0.1)
        commands(client, state, p)
        assert len(replies(state, session)) == number
    assert not state.qq.store.get(QQBinding, session["session_id"]).paused
    assert not state.qq.store.get(QQBinding, friend["session_id"]).paused
    assert not upstream.calls


def test_admin_first_command_bootstraps_private_session_and_ordinary_chat_stays_normal(qq_client, monkeypatch):
    client, state, upstream = qq_client
    p, _, connection = configure_execution(client, state, admin_qq="9999", reply_message_limit=1)
    resources(monkeypatch, state)
    ingest(client, state, p, event(1, "/cogita check", sender="5555", kind="private"), 1)
    ingest(client, state, p, event(2, "ordinary", kind="private"), 2)
    assert len(state.qq.store.bindings(p["id"])) == 1
    ingest(client, state, p, event(3, "/cogita check", kind="private"), 3)
    binding = state.qq.store.binding(p["id"], "friend", "9999")
    assert binding is not None
    commands(client, state, p)
    client.portal.call(state.qq.programs.send_pending, p["id"])
    assert connection.calls[-1][0] == "send_private_msg"
    ingest(client, state, p, event(4, "ordinary private question", kind="private"), 4)
    batch = state.qq.store.freeze(binding.session_id, 20, 9)
    assert batch.trigger_kind == "private" and "ordinary private question" in batch.text
    assert "/cogita" not in batch.text
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "normal"}, "one"))]
    client.portal.call(state.qq.execute, batch)
    assert len(upstream.calls) == 1


def test_control_and_command_reply_commit_together(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state, admin_qq="9999")
    ingest(client, state, p, event(1, "/cogita pause"), 1)
    message = state.qq.programs.next_command(p["id"])
    def fail(db, message, text):
        raise RuntimeError("reply transaction failed")
    with monkeypatch.context() as patch:
        patch.setattr(state.qq.programs, "finish", fail)
        with pytest.raises(RuntimeError, match="reply transaction"):
            client.portal.call(lambda: state.qq.control(session["session_id"], "pause", command=message))
    assert not state.qq.store.get(QQBinding, session["session_id"]).paused
    assert state.qq.programs.next_command(p["id"]).id == message.id
    assert replies(state, session) == []
    commands(client, state, p)
    assert state.qq.store.get(QQBinding, session["session_id"]).paused
    assert len(replies(state, session)) == 1


def test_pause_does_not_interrupt_model_send_and_program_sends_serialize(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, admin_qq="9999", reply_message_limit=1)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "model first"}, "one"))]
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        original = connection.call
        async def send(action, params, **kwargs):
            if params["message"][0]["data"]["text"] == "model first":
                started.set()
                await release.wait()
            result = await original(action, params, **kwargs)
            echo = event(result["message_id"], sender="12345")
            await state.qq.ingest(p["id"], echo)
            return result
        connection.call = send
        task = asyncio.create_task(state.qq.execute(batch))
        await asyncio.wait_for(started.wait(), 5)
        await state.qq.ingest(p["id"], event(2, "/cogita pause"), now=7)
        await state.qq.programs.process_commands(p["id"])
        assert state.qq.store.get(QQBinding, session["session_id"]).paused and not task.done()
        await state.qq.ingest(p["id"], event(3, "/cogita resume"), now=8)
        await state.qq.programs.process_commands(p["id"])
        assert "仍有任务" in replies(state, session)[-1]["text"]
        sender = asyncio.create_task(state.qq.programs.send_pending(p["id"]))
        await asyncio.sleep(0)
        assert connection.calls == []
        assert state.qq.history.busy(session["session_id"])
        release.set()
        await asyncio.gather(task, sender)
    client.portal.call(scenario)
    rows = replies(state, session)
    assert len(rows) == 3 and all(row["echoed"] and row["status"] == "sent" for row in rows)
    assert connection.calls[0][1]["message"][0]["data"]["text"] == "model first"
    assert state.runs.get_run(state.qq.store.get(QQBatch, batch.id).run_id).metadata["qq_reply"]["sent_count"] == 1
    with Session(state.qq.store.engine) as db:
        assert db.exec(select(QQNotification)).all() == []
    assert not state.qq.send_echoes


def test_program_history_deletion_retains_dedup_and_blocks_active_processing(qq_client):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state, admin_qq="9999")
    ingest(client, state, p, event(1, "/cogita pause"), 1)
    message = state.qq.programs.next_command(p["id"])
    state.qq.programs.active_commands[message.id] = session["session_id"]
    path = f"/api/qq/sessions/{session['session_id']}"
    assert client.delete(f"{path}/messages/{message.id}").status_code == 409
    state.qq.programs.active_commands.clear()
    commands(client, state, p)
    reply = replies(state, session)[0]
    state.qq.programs.active_sends[reply["id"]] = session["session_id"]
    assert client.delete(f"{path}/deliveries/{reply['id']}").status_code == 409
    state.qq.programs.active_sends.clear()
    ok(client.delete(f"{path}/deliveries/{reply['id']}"))
    ok(client.delete(f"{path}/messages/{message.id}"))
    ingest(client, state, p, event(1, "/cogita pause"), 2)
    commands(client, state, p)
    assert replies(state, session) == []
    assert state.qq.programs.next_command(p["id"]) is None


def test_check_reports_latest_model_usage_without_calling_it_again(qq_client, monkeypatch):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=1)
    resources(monkeypatch, state)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "hello"}, "one"))]
    ingest(client, state, p, event(1), 1)
    client.portal.call(state.qq.execute, freeze(state, session, 6))
    ingest(client, state, p, event(2, "/cogita check", sender="5555"), 7)
    commands(client, state, p)
    assert "裁剪 0 轮" in replies(state, session)[-1]["text"]
    assert len(upstream.calls) == 1
    ok(client.patch(f"/api/models/profiles/{p['model_profile_id']}", json={"context_window_tokens": 65536}))
    ingest(client, state, p, event(3, "/cogita check"), 8)
    commands(client, state, p)
    assert "暂无（当前模型配置）" in replies(state, session)[-1]["text"]
    assert len(upstream.calls) == 1


def test_socket_reader_keeps_receiving_command_acknowledgements(qq_client, monkeypatch):
    from websockets.asyncio.server import serve
    client, state, upstream = qq_client
    resources(monkeypatch, state)
    p, _, _ = configure_execution(client, state, admin_qq="9999")
    async def scenario():
        received = asyncio.Event()
        sent = []
        async def socket(ws):
            request = json.loads(await ws.recv())
            await ws.send(json.dumps({"status": "ok", "retcode": 0, "echo": request["echo"],
                "data": {"user_id": 12345, "nickname": "Bot"}}))
            await ws.send(json.dumps(event(1, "/cogita check")))
            async for wire in ws:
                request = json.loads(wire)
                sent.append(request)
                await ws.send(json.dumps({"status": "ok", "retcode": 0, "echo": request["echo"], "data": {"message_id": 88}}))
                received.set()
        async with serve(socket, "127.0.0.1", 0) as server:
            state.project_service.update(p["id"], {"websocket_url": f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"})
            state.qq.supervisor = asyncio.create_task(state.qq.run())
            try:
                await asyncio.wait_for(received.wait(), 5)
                for _ in range(50):
                    rows = state.qq.store.page(QQDelivery, state.qq.store.bindings(p["id"])[0].session_id)["items"]
                    if rows and rows[0]["status"] == "sent":
                        break
                    await asyncio.sleep(0.01)
                assert rows[0]["status"] == "sent" and rows[0]["external_id"] == "88"
            finally:
                await state.qq.close()
        assert len(sent) == 1 and sent[0]["action"] == "send_group_msg"
    client.portal.call(scenario)
    assert upstream.calls == []
