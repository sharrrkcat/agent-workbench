import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session as DbSession, select

from ai_workbench.api.main import create_app
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_service import QQService
from ai_workbench.core.qq_protocol import OneBotConnection, normalize
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery, QQParticipant
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, tool_call, ok


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def qq_client(tmp_path, monkeypatch, request):
    monkeypatch.setattr(QQService, "start", lambda self: None)
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param, database_url=f"sqlite:///{tmp_path / 'qq.db'}",
        adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, app.state.runtime_state, upstream


def project(client, **values):
    return ok(client.post("/api/projects", json={"kind": "qqbot", "name": "QQ test", "context_policy": {},
        "bot_account": "12345", "websocket_url": "ws://127.0.0.1:3001", **values}))


def child(client, p, target="7788", kind="group"):
    return ok(client.post(f"/api/projects/{p['id']}/sessions", json={"target_kind": kind, "target_id": target}))


def event(number=1, text="bot", target="7788", kind="group", sender="9999"):
    return {"post_type": "message", "message_type": kind, "self_id": 12345, "message_id": number,
        "user_id": int(sender), "group_id": int(target), "time": 1700000000 + number,
        "sender": {"nickname": "Nick", "card": "Group name"},
        "message": [{"type": "text", "data": {"text": text}}]}


def ingest(client, state, p, data, now):
    async def receive():
        await state.qq.ingest(p["id"], data, now=now)
    client.portal.call(receive)


def freeze(state, session, now=100, limit=20):
    return state.qq.store.freeze(session["session_id"], limit, now)


def test_project_identity_resources_and_write_only_token(qq_client):
    client, state, _ = qq_client
    p = project(client, access_token="private-token", keywords=[" BOT ", "bot"])
    assert "access_token" not in p and p["has_access_token"]
    assert p["keywords"] == ["bot"]
    assert "private-token" not in client.get("/api/projects").text
    assert client.patch(f"/api/projects/{p['id']}", json={"name": "renamed"}).status_code == 200
    assert state.projects.get(p["id"]).access_token == "private-token"
    assert ok(client.patch(f"/api/projects/{p['id']}", json={"access_token": ""}))["has_access_token"] is False
    assert client.post("/api/projects", json={"kind": "qqbot", "name": "duplicate", "context_policy": {},
        "bot_account": "12345", "websocket_url": "ws://localhost:3001"}).status_code == 409
    for patch in ({"kind": "workspace"}, {"knowledge_base_ids": []}, {"worldbook_ids": []},
                  {"cogita_persona_id": USER_PERSONA_ID}, {"harness_enabled": False}, {"tools_allowed": []},
                  {"group_reply_mode": "mention"}, {"batch_message_limit": 0}, {"keywords": [""]},
                  {"websocket_url": "ws://localhost:3001?access_token=secret"}):
        assert client.patch(f"/api/projects/{p['id']}", json=patch).status_code == 422
    session = child(client, p)
    assert session["user_persona"] is None
    assert session["effective"]["knowledge_base_ids"] == []
    assert session["effective"]["persona_id"] == ""
    assert session["effective"]["tools_allowed"] == ["qq_send_message", "qq_skip_reply"]
    assert session["effective"]["harness_enabled"]
    assert client.post(f"/api/projects/{p['id']}/sessions", json={}).status_code == 422
    assert client.post(f"/api/projects/{p['id']}/sessions", json={"target_kind": "group", "target_id": "7788"}).status_code == 409
    for patch in ({"target_id": "100"}, {"overrides": {}}, {"model_profile_id": None}):
        assert client.patch(f"/api/sessions/{session['session_id']}", json=patch).status_code == 422
    assert client.patch(f"/api/projects/{p['id']}", json={"bot_account": "45678"}).status_code == 409
    for path in (f"/api/projects/{p['id']}/knowledge-bases", f"/api/projects/{p['id']}/worldbooks",
                 f"/api/sessions/{session['session_id']}/knowledge-bases"):
        assert client.get(path).status_code == 422
    assert client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/read_file hello"}).status_code == 409
    assert client.post("/api/tools/qq_send_message/call", json={"session_id": session["session_id"], "arguments": {"text": "hi"}}).status_code == 409
    ordinary = ok(client.post("/api/sessions", json={}))
    assert "qq_send_message" not in ordinary["tools_allowed"]
    assert client.patch(f"/api/sessions/{ordinary['session_id']}", json={"tools_allowed": ["qq_send_message"]}).status_code == 422
    assert ok(client.get(f"/api/projects/{p['id']}/sessions"))[0]["session_id"] == session["session_id"]


def test_debounce_dedup_cutoff_fifo_and_private_media(qq_client):
    client, state, _ = qq_client
    p = project(client, keywords=["BOT"])
    session = child(client, p)
    for i in range(1, 25):
        ingest(client, state, p, event(i, "context"), i / 100)
    ingest(client, state, p, event(25, "hello BoT"), 1)
    ingest(client, state, p, event(26, "BOT again"), 5)
    ingest(client, state, p, event(27, "tail", sender="8888"), 9)
    assert freeze(state, session, 9.99) is None
    batch = freeze(state, session, 10)
    assert batch.text.count("[Group name]") == 20
    assert "tail" in batch.text and "BoT" in batch.text
    assert "+00:00" in batch.text
    assert freeze(state, session, 11) is None
    ingest(client, state, p, event(26, "BOT again"), 12)  # Redelivery does not rearm.
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline is None
    for data in (event(40, target="8765"), event(41, sender="12345"), {**event(42), "self_id": 555}):
        ingest(client, state, p, data, 13)
    with DbSession(state.qq.store.engine) as db:
        rows = db.exec(select(QQMessage).where(QQMessage.session_id == session["session_id"])).all()
        assert len(rows) == 27
        assert sum(r.disposition == "skipped" for r in rows) == 7
    ingest(client, state, p, event(28, "bot"), 15)
    second = freeze(state, session, 20)
    assert second.id > batch.id and second.text.count("[Group name]") == 1
    assert state.qq.store.next_batch(p["id"]).id == batch.id
    private = child(client, p, "9999", "friend")
    media = event(50, kind="private")
    media["message"] = [{"type": "image", "data": {"url": "https://do-not-fetch.test/a"}},
        {"type": "face", "data": {}}, {"type": "record", "data": {}}]
    ingest(client, state, p, media, 30)
    assert freeze(state, private, 35).text.endswith("[图片][表情包][语音]")


class FakeConnection:
    ready = True
    def __init__(self, failure=None):
        self.calls, self.failure = [], failure
    async def call(self, action, params):
        self.calls.append((action, params))
        if self.failure:
            raise self.failure
        return {"message_id": 1000 + len(self.calls)}


def configure_execution(client, state, *, streaming=False, **values):
    model = configure_model(client, request_options={"streaming": streaming})
    p = project(client, model_profile_id=model["id"], connection_enabled=True, keywords=["bot"], **values)
    session = child(client, p)
    connection = FakeConnection()
    state.qq.connections[p["id"]] = connection
    return p, session, connection


def test_harness_multiple_sends_and_context_excludes_private_prose(qq_client):
    client, state, upstream = qq_client
    agent = ok(client.post("/api/personas", json={"collection": "agent", "name": "Agent", "system_prompt": "AGENT_PROMPT"}))
    embedding = configure_model(client, kind="embedding", alias="embedding")
    knowledge = ok(client.post("/api/knowledge/bases", json={"name": "Private knowledge", "embedding_model_profile_id": embedding["id"]}))
    for persona_id in (agent["id"], USER_PERSONA_ID):
        ok(client.patch(f"/api/personas/{persona_id}/knowledge-bases", json={"knowledge_base_ids": [knowledge["id"]]}))
    ok(client.patch(f"/api/personas/{USER_PERSONA_ID}", json={"system_prompt": "PRIVATE_USER_PROMPT"}))
    p, session, connection = configure_execution(client, state, agent_persona_id=agent["id"], system_prompt="PROJECT_PROMPT")
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "first"}, "one"),
        tool_call("qq_send_message", {"text": "[CQ:at,qq=all]"}, "two"), content="PRIVATE_THOUGHT"),
        completion(content="PRIVATE_FINAL")]
    ingest(client, state, p, event(1, "/read_file bot"), 1)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    batch = state.qq.store.get(QQBatch, batch.id)
    assert batch.status == "done", batch.error_code
    assert len(connection.calls) == 2
    assert connection.calls[1] == ("send_group_msg", {"group_id": 7788,
        "message": [{"type": "text", "data": {"text": "[CQ:at,qq=all]"}}]})
    assert [t["function"]["name"] for t in upstream.calls[0]["tools"]] == ["qq_send_message"]
    request = json.dumps(upstream.calls[0], ensure_ascii=False)
    assert "AGENT_PROMPT" in request and "PROJECT_PROMPT" in request and "PRIVATE_USER_PROMPT" not in request
    assert upstream.calls[0]["messages"][-1]["role"] == "user"
    assert "/read_file bot" in upstream.calls[0]["messages"][-1]["content"]
    context = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    contents = context.model_dump_json()
    assert "first" in contents and "[CQ:at,qq=all]" in contents
    assert "PRIVATE_THOUGHT" not in contents and "PRIVATE_FINAL" not in contents
    assert "tool_calls" in contents
    assert [m["role"] for m in context.messages] == ["user", "assistant", "tool", "assistant", "tool", "user"]
    assert state.chat_service.resolve(state.sessions.get_session(session["session_id"])).knowledge_base_ids == []
    ingest(client, state, p, {**event(1001, sender="12345"), "post_type": "message_sent"}, 20)
    records = state.qq.store.page(QQDelivery, session["session_id"])["items"]
    assert next(row for row in records if row["external_id"] == "1001")["echoed"]
    assert len(state.qq.store.page(QQMessage, session["session_id"])["items"]) == 1
    assert client.post(f"/api/runs/{batch.run_id}/retry").status_code in (404, 409)
    assert client.delete(f"/api/messages/{batch.input_message_id}").status_code == 409
    assert ok(client.get(f"/api/qq/sessions/{session['session_id']}/deliveries"))["items"][0]["status"] == "sent"
    ok(client.delete(f"/api/projects/{p['id']}"))
    assert state.qq.store.get(QQBinding, session["session_id"]) is None
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"] == []


@pytest.mark.parametrize("failure,status", [(ToolExecutionError("QQ_ACTION_FAILED", "Rejected"), "failed"), (TimeoutError(), "unknown")])
def test_failed_delivery_pauses_and_never_runs_second_tool(qq_client, failure, status):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    connection.failure = failure
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "first"}, "one"),
        tool_call("qq_send_message", {"text": "second"}, "two"))]
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    ingest(client, state, p, event(2), 7)
    queued = freeze(state, session, 12)
    client.portal.call(state.qq.execute, batch)
    assert len(connection.calls) == 1
    assert state.qq.store.get(QQBatch, batch.id).status == "failed"
    assert state.qq.store.get(QQBinding, session["session_id"]).paused
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"][0]["status"] == status
    assert state.qq.store.next_batch(p["id"]) is None
    ok(client.post(f"/api/qq/sessions/{session['session_id']}/control", json={"action": "resume"}))
    assert state.qq.store.next_batch(p["id"]).id == queued.id


def test_restart_preserves_queue_and_debounce_without_replaying(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    ingest(client, state, p, event(1), 1)
    interrupted = freeze(state, session, 6)
    interrupted.status = "running"
    state.qq.store.save(interrupted)
    ingest(client, state, p, event(2), 7)
    queued = freeze(state, session, 12)
    ingest(client, state, p, event(3), 13)
    state.qq.store.save(QQDelivery(session_id=session["session_id"], run_id="interrupted", tool_call_id="one",
        text="unknown", status="sending", created_at=0))
    state.qq.store.recover()
    assert state.qq.store.get(QQBatch, interrupted.id).status == "interrupted"
    assert state.qq.store.get(QQBatch, queued.id).status == "queued"
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline == 18
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"][0]["status"] == "unknown"
    assert connection.calls == [] and upstream.calls == []


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("content", ["Private final answer", "", None])
def test_missing_reply_fails_and_pauses_without_replaying(qq_client, streaming, content):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming)
    upstream.turns = [completion(content=content)]
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    ingest(client, state, p, event(2), 7)
    queued = freeze(state, session, 12)
    client.portal.call(state.qq.execute, batch)
    batch = state.qq.store.get(QQBatch, batch.id)
    run = state.runs.get_run(batch.run_id)
    code = "PROVIDER_PROTOCOL_ERROR" if content is None and not streaming else "QQ_REPLY_REQUIRED"
    assert batch.status == "failed" and batch.error_code == code
    assert run.status == "FAILED" and run.error_code == code
    assert run.metadata["qq_reply"] == {"sent_count": 0, "message_limit": 4, "limit_reached": False, "skipped": False}
    assert all(row.status != "running" for row in state.runs.list_steps(run.run_id))
    assert not any(row.type == "run_completed" and row.run_id == run.run_id for row in state.events.list_events())
    assert len(upstream.calls) == 1 and upstream.calls[0]["tool_choice"] == "required"
    assert connection.calls == []
    binding = state.qq.store.get(QQBinding, session["session_id"])
    assert binding.paused and binding.pause_reason == code
    assert state.qq.store.next_batch(p["id"]) is None
    if content:
        messages = state.messages.list_messages(session["session_id"])
        assert any(m.metadata.get("qq_internal") and content in json.dumps(m.parts) for m in messages)
        assert content not in build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None).model_dump_json()
    ok(client.post(f"/api/qq/sessions/{session['session_id']}/control", json={"action": "resume"}))
    assert state.qq.store.next_batch(p["id"]).id == queued.id


def test_onebot_websocket_identity_and_plain_text_roundtrip():
    from websockets.asyncio.server import serve
    async def scenario():
        received, sent = [], []
        async def server(socket):
            async for raw in socket:
                request = json.loads(raw)
                sent.append(request)
                data = {"user_id": 12345} if request["action"] == "get_login_info" else {"message_id": 987}
                await socket.send(json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": request["echo"]}))
                if request["action"] == "get_login_info":
                    await socket.send(json.dumps(event()))
        async with serve(server, "127.0.0.1", 0) as host:
            async def receive(value):
                received.append(value)
            p = SimpleNamespace(websocket_url=f"ws://127.0.0.1:{host.sockets[0].getsockname()[1]}", access_token="", bot_account="12345")
            connection = OneBotConnection(p, receive)
            task = asyncio.create_task(connection.run())
            try:
                async def ready():
                    while not connection.ready:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 5)
                response = await connection.call("send_group_msg", {"group_id": 7788, "message": [{"type": "text", "data": {"text": "hi"}}]})
                assert response["message_id"] == 987
                assert sent[-1]["params"]["message"][0]["type"] == "text"
                assert received == [event()]
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            p.bot_account = "54321"
            wrong = OneBotConnection(p, receive)
            with pytest.raises(ToolExecutionError, match="Connected account"):
                await wrong.run()
    asyncio.run(scenario())


def test_exact_deadline_references_media_and_pagination(qq_client):
    client, state, _ = qq_client
    p = project(client, keywords=["bot"])
    session = child(client, p)
    sid = session["session_id"]
    ingest(client, state, p, event(1), 0)
    ingest(client, state, p, event(2, "tail", sender="8888"), 4.99)
    ingest(client, state, p, event(3), 5)  # Expiry precedes this new trigger.
    first = state.qq.store.next_batch(p["id"])
    assert first.text.count("[Group name]") == 2 and "tail" in first.text
    ingest(client, state, p, event(3), 6)
    assert state.qq.store.get(QQBinding, sid).deadline == 10
    data = event(4, sender="8888")
    data["message"] = "[CQ:at,qq=7777][CQ:reply,id=bot][CQ:image,url=https://bot.test/a]literal &#91;ok&#93;"
    ingest(client, state, p, data, 8)
    assert state.qq.store.get(QQBinding, sid).deadline == 10
    normalized, keyword_text, media = normalize(data)
    assert normalized["text"] == "@7777[引用:bot][图片]literal [ok]"
    assert keyword_text == "@7777literal [ok]"
    ingest(client, state, p, {**event(5), "message": [{"data": {}}]}, 9)
    second = freeze(state, session, 10)
    assert second.text.count("[Group name]") == 2
    page = ok(client.get(f"/api/qq/sessions/{sid}/messages?limit=2"))
    assert [r["external_id"] for r in page["items"]] == ["4", "3"]
    assert page["items"][0]["references"] == [
        {"type": "at", "id": "7777", "name": None, "is_self": False},
        {"type": "reply", "id": "bot", "name": None, "is_self": False}]
    older = ok(client.get(f"/api/qq/sessions/{sid}/messages?limit=2&before={page['next_cursor']}"))
    assert [r["external_id"] for r in older["items"]] == ["2", "1"] and older["next_cursor"] is None
    ok(client.patch(f"/api/projects/{p['id']}", json={"keywords": []}))
    ingest(client, state, p, event(6, sender="8888"), 11)
    assert freeze(state, session, 20) is None
    friend = child(client, p, "9999", "friend")
    ingest(client, state, p, {**event(7, kind="private"), "message": "[CQ:record,file=voice]"}, 12)
    assert freeze(state, friend, 17).text.endswith("[语音]")


def test_stop_during_send_keeps_confirmed_reply_and_queued_windows(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "confirmed"}, "one"),
        tool_call("qq_send_message", {"text": "uncertain"}, "two"))]
    sid = session["session_id"]
    async def scenario():
        sending = asyncio.Event()
        original = connection.call
        async def hold(action, params):
            if connection.calls:
                connection.calls.append((action, params))
                sending.set()
                await asyncio.Event().wait()
            return await original(action, params)
        connection.call = hold
        await state.qq.ingest(p["id"], event(1), now=0)
        batch = freeze(state, session, 5)
        task = asyncio.create_task(state.qq.execute(batch))
        state.qq.workers[p["id"]] = task
        await asyncio.wait_for(sending.wait(), 5)
        state.qq.control(sid, "pause")
        for number, now in ((2, 7), (3, 13)):
            await state.qq.ingest(p["id"], event(number), now=now)
            freeze(state, session, now + 5)
        assert not task.done()
        with pytest.raises(ChatError, match="Stop the active QQ batch"):
            state.qq.assert_idle(sid)
        state.qq.control(sid, "stop")
        await asyncio.wait_for(task, 5)
        assert state.qq.store.get(QQBatch, batch.id).status == "cancelled"
        run = state.runs.get_run(state.qq.store.get(QQBatch, batch.id).run_id)
        assert run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 4, "limit_reached": False, "skipped": False}
        records = state.qq.store.page(QQDelivery, sid)["items"]
        assert [row["status"] for row in records] == ["unknown", "sent"]
        assert state.qq.store.get(QQBinding, sid).paused
        state.qq.control(sid, "resume")
        queued = state.qq.store.next_batch(p["id"])
        assert queued.id == batch.id + 1
        connection.call = original
        upstream.turns = [completion(tool_call("qq_send_message", {"text": "next batch"})), completion(content="")]
        await state.qq.execute(queued)
        assert state.qq.store.next_batch(p["id"]).id == batch.id + 2
    client.portal.call(scenario)
    context = build_qq_context(state.qq.store, state.messages, sid, "next", ContextPolicy(), None).model_dump_json()
    assert "confirmed" in context and "uncertain" not in context
    assert len(connection.calls) == 3


def test_unsupported_tools_fail_without_ordinary_chat(qq_client, monkeypatch):
    from ai_workbench.core.models.chat_support import ChatSupport, Support
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    @asynccontextmanager
    async def unsupported(*args, **kwargs):
        yield ChatSupport(tools=Support("unsupported"))
    monkeypatch.setattr(state.model_manager, "check_chat_inputs", unsupported)
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    assert state.qq.store.get(QQBatch, batch.id).error_code == "UNSUPPORTED_CAPABILITY"
    assert not upstream.calls and not connection.calls
    assert state.qq.store.get(QQBinding, session["session_id"]).paused


def test_disabled_connection_does_not_start_reserved_batch(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    ok(client.patch(f"/api/projects/{p['id']}", json={"connection_enabled": False}))
    client.portal.call(state.qq.execute, batch)
    assert state.qq.store.get(QQBatch, batch.id).status == "queued"
    assert not upstream.calls and not connection.calls
    assert state.messages.list_messages(session["session_id"]) == []


def test_echo_migration_preserves_confirmed_delivery(tmp_path):
    from sqlalchemy import text
    from ai_workbench.db.database import get_engine
    from ai_workbench.db import migrations
    engine = get_engine(f"sqlite:///{tmp_path / 'echo.db'}")
    migrations.upgrade(engine, migrations.QQBOT_REVISION)
    with engine.begin() as db:
        db.execute(text("INSERT INTO qq_deliveries (session_id,run_id,tool_call_id,text,status,created_at) "
            "VALUES ('s','r','c','confirmed','sent',1)"))
    migrations.upgrade(engine, migrations.QQ_DELIVERY_ECHO_REVISION)
    with engine.connect() as db:
        assert db.execute(text("SELECT text, status, echoed FROM qq_deliveries")).one() == ("confirmed", "sent", 0)


def test_sqlite_restart_reconciles_runs_deliveries_and_keeps_queues(tmp_path, monkeypatch):
    from ai_workbench.core.schema.run import RunStatus
    monkeypatch.setattr(QQService, "start", lambda self: None)
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    app = create_app(root=tmp_path, database_url=database_url, adapter_factory=ToolOpenAI().factory)
    with TestClient(app) as client:
        state = app.state.runtime_state
        p, session, _ = configure_execution(client, state)
        ingest(client, state, p, event(1), 1)
        running = freeze(state, session, 6)
        config = state.chat_service.resolve(state.sessions.get_session(session["session_id"]))
        run = state.runs.create_run(kind="chat", session_id=session["session_id"], persona_id="",
            config_snapshot=config.model_dump(mode="json"))
        state.runs.update_status(run.run_id, RunStatus.RUNNING)
        running.status, running.run_id = "running", run.run_id
        state.qq.store.save(running)
        ingest(client, state, p, event(2), 7)
        queued = freeze(state, session, 12)
        ingest(client, state, p, event(3), time.time() + 100)
        deadline = state.qq.store.get(QQBinding, session["session_id"]).deadline
        participant = state.qq.store.get(QQParticipant, (session["session_id"], "9999"))
        state.qq.store.save(QQDelivery(session_id=session["session_id"], run_id=run.run_id, tool_call_id="lost",
            status="sending", text="Unconfirmed", created_at=0))
    restarted = create_app(root=tmp_path, database_url=database_url, adapter_factory=ToolOpenAI().factory)
    with TestClient(restarted) as client:
        state = restarted.state.runtime_state
        assert state.runs.get_run(run.run_id).status == RunStatus.INTERRUPTED
        assert state.qq.store.get(QQBatch, running.id).status == "interrupted"
        assert state.qq.store.get(QQBinding, session["session_id"]).deadline == deadline
        restored = state.qq.store.get(QQParticipant, (session["session_id"], "9999"))
        assert restored.expires_at == participant.expires_at and restored.in_window
        assert restored.keyword_message_id == participant.keyword_message_id
        assert state.qq.store.get(QQBatch, queued.id).participants == queued.participants
        assert state.qq.store.page(QQDelivery, session["session_id"])["items"][0]["status"] == "unknown"
        assert state.qq.store.next_batch(p["id"]) is None
        ok(client.post(f"/api/qq/sessions/{session['session_id']}/control", json={"action": "resume"}))
        assert state.qq.store.next_batch(p["id"]).id == queued.id


def test_authentication_failure_and_transport_reconnect(qq_client):
    from websockets.asyncio.server import serve
    client, state, _ = qq_client
    p = project(client)
    async def scenario():
        attempts = 0
        def authorize(socket, request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return socket.respond(401, "Unauthorized")
        async def server(socket):
            async for raw in socket:
                request = json.loads(raw)
                await socket.send(json.dumps({"status": "ok", "retcode": 0, "data": {"user_id": 12345}, "echo": request["echo"]}))
        async with serve(server, "127.0.0.1", 0, process_request=authorize) as host:
            saved = state.project_service.update(p["id"], {"websocket_url": f"ws://127.0.0.1:{host.sockets[0].getsockname()[1]}"})
            connection = OneBotConnection(saved, lambda _: None)
            task = asyncio.create_task(state.qq.connect(connection))
            async def until(predicate):
                while not predicate():
                    await asyncio.sleep(.01)
            try:
                await asyncio.wait_for(until(lambda: connection.status == "QQ_AUTH_FAILED"), 3)
                await asyncio.wait_for(until(lambda: connection.ready), 5)
                await connection.socket.close()
                await asyncio.wait_for(until(lambda: not connection.ready), 3)
                await asyncio.wait_for(until(lambda: attempts >= 3 and connection.ready), 5)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    client.portal.call(scenario)


def test_real_service_with_fake_onebot_and_model(qq_client):
    from websockets.asyncio.server import serve
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, access_token="local-test-token")
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "literal [CQ:at,qq=all]"})), completion(content="Private")]
    async def scenario():
        sent, authorized = [], []
        async def server(socket):
            authorized.append(socket.request.headers.get("Authorization"))
            async for raw in socket:
                request = json.loads(raw)
                login = request["action"] == "get_login_info"
                if not login:
                    sent.append(request)
                data = {"user_id": 12345} if login else {"message_id": 88}
                await socket.send(json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": request["echo"]}))
                if login:
                    await socket.send(json.dumps(event(1, "/read_file bot")))
        async with serve(server, "127.0.0.1", 0) as host:
            state.project_service.update(p["id"], {"websocket_url": f"ws://127.0.0.1:{host.sockets[0].getsockname()[1]}"})
            state.qq.supervisor = asyncio.create_task(state.qq.run())
            async def finished():
                while True:
                    rows = state.qq.store.page(QQBatch, session["session_id"])["items"]
                    if rows and rows[0]["status"] == "done":
                        return rows[0]
                    await asyncio.sleep(.05)
            try:
                batch = await asyncio.wait_for(finished(), 12)
                assert authorized == ["Bearer local-test-token"]
                assert len(sent) == 1 and sent[0]["action"] == "send_group_msg"
                assert sent[0]["params"]["message"] == [{"type": "text", "data": {"text": "literal [CQ:at,qq=all]"}}]
                assert len(upstream.calls) == 2 and batch["run_id"]
            finally:
                await state.qq.close()
    client.portal.call(scenario)
