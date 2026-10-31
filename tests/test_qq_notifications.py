"""Terminal QQ failures notify administrators without re-entering model history."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_service import QQService
from ai_workbench.db.qq_models import QQBinding, QQBatch, QQDelivery, QQMessage, QQNotification
from tests.test_qqbot import qq_client, configure_execution, event, ingest, freeze, FakeConnection
from tests.test_qq_commands import commands, replies
from tests.tool_fixtures import create_tool_app, ToolOpenAI, completion, ok


def notices(state):
    with Session(state.qq.store.engine) as db:
        return db.exec(select(QQNotification).order_by(QQNotification.id)).all()


def prepare(client, state, p):
    state.qq.programs.connection_restored(p["id"])
    state.qq.programs.prepare_notifications(state.projects.get(p["id"]))
    client.portal.call(state.qq.programs.send_pending, p["id"])


def test_final_failure_pause_is_one_private_notification_and_never_model_history(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, admin_qq="9999")
    upstream.turns = [completion(content="no required reply")]
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    batch = state.qq.store.get(QQBatch, batch.id)
    assert batch.status == "failed" and state.qq.store.get(QQBinding, session["session_id"]).paused
    state.qq.programs.batch_finished(batch)
    assert len(notices(state)) == 1
    admin = state.qq.store.binding(p["id"], "friend", "9999")
    assert admin is not None
    state.qq.store.pause(admin.session_id, "QQ_PAUSED")
    prepare(client, state, p)
    action, params = connection.calls[-1]
    assert action == "send_private_msg" and params["user_id"] == 9999
    assert "QQ_REPLY_REQUIRED" in params["message"][0]["data"]["text"]
    assert "/cogita resume group:7788" in params["message"][0]["data"]["text"]
    row = replies(state, {"session_id": admin.session_id})[0]
    assert row["origin"] == "notification" and row["run_id"] is None and row["status"] == "sent"
    assert state.messages.list_messages(admin.session_id) == []
    assert state.qq.store.get(QQBinding, admin.session_id).deadline is None
    assert len(upstream.calls) == 1
    prepare(client, state, p)
    assert len(connection.calls) == 1


def test_connection_episode_merges_and_pending_recipient_tracks_admin_setting(qq_client):
    client, state, _ = qq_client
    p, _, connection = configure_execution(client, state, admin_qq="9999")
    connection.ready = False
    for code in ("QQ_AUTH_FAILED", "QQ_CONNECTION_FAILED", "QQ_ACCOUNT_MISMATCH"):
        state.qq.programs.connection_failed(p["id"], code)
    first = notices(state)[0]
    assert first.occurrences == 3 and first.resolved_at is None
    assert len(notices(state)) == 1 and not connection.calls
    connection.ready = True
    state.qq.programs.connection_restored(p["id"])
    state.qq.programs.prepare_notifications(state.projects.get(p["id"]))
    old_admin = state.qq.store.binding(p["id"], "friend", "9999")
    delivery = replies(state, {"session_id": old_admin.session_id})[0]
    assert "失败次数：3" in delivery["text"] and "连接已恢复" in delivery["text"]
    ok(client.patch(f"/api/projects/{p['id']}", json={"admin_qq": "8888"}))
    new_admin = state.qq.store.binding(p["id"], "friend", "8888")
    assert replies(state, {"session_id": old_admin.session_id}) == []
    assert replies(state, {"session_id": new_admin.session_id})[0]["id"] == delivery["id"]
    client.portal.call(state.qq.programs.send_pending, p["id"])
    assert connection.calls[-1][1]["user_id"] == 8888
    state.qq.programs.connection_failed(p["id"], "QQ_CONNECTION_FAILED")
    assert len(notices(state)) == 2
    state.qq.programs.connection_restored(p["id"])
    state.qq.programs.prepare_notifications(state.projects.get(p["id"]))
    ok(client.patch(f"/api/projects/{p['id']}", json={"admin_qq": None}))
    client.portal.call(state.qq.programs.send_pending, p["id"])
    assert len(connection.calls) == 1
    assert replies(state, {"session_id": new_admin.session_id})[-1]["status"] == "cancelled"
    state.qq.programs.connection_failed(p["id"], "QQ_AUTH_FAILED")
    assert len(notices(state)) == 2


@pytest.mark.parametrize("failure,status", [
    (ToolExecutionError("QQ_ACTION_FAILED", "sensitive raw failure"), "failed"),
    (ToolExecutionError("QQ_SEND_ACK_TIMEOUT", "sensitive raw timeout"), "unknown"),
    (ConnectionError("private address"), "unknown"),
])
def test_notification_send_failure_never_pauses_retries_or_recurses(qq_client, failure, status):
    client, state, _ = qq_client
    p, _, connection = configure_execution(client, state, admin_qq="9999")
    state.qq.programs.connection_failed(p["id"], "QQ_CONNECTION_FAILED")
    connection.failure = failure
    prepare(client, state, p)
    admin = state.qq.store.binding(p["id"], "friend", "9999")
    row = replies(state, {"session_id": admin.session_id})[0]
    assert row["status"] == status and "sensitive" not in json.dumps(row)
    assert not state.qq.store.get(QQBinding, admin.session_id).paused
    connection.failure = None
    prepare(client, state, p)
    assert len(connection.calls) == 1 and len(notices(state)) == 1


def test_intentional_stop_disable_and_icebreaker_cancellation_do_not_notify(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, admin_qq="9999")
    upstream.turns = [completion({"id": "one", "type": "function", "function": {
        "name": "qq_send_message", "arguments": '{"text":"reply"}'}})]
    ingest(client, state, p, event(1), 1)
    batch = freeze(state, session, 6)
    async def scenario():
        started = asyncio.Event()
        async def blocked(*args, **kwargs):
            started.set()
            await asyncio.Future()
        connection.call = blocked
        task = asyncio.create_task(state.qq.execute(batch))
        state.qq.workers[p["id"]] = task
        await asyncio.wait_for(started.wait(), 5)
        await state.qq.control(session["session_id"], "stop")
        await task
    client.portal.call(scenario)
    assert notices(state) == []
    for code in ("QQ_ICEBREAKER_CANCELLED", "QQ_DISABLED"):
        row = state.qq.store.save(QQBatch(session_id=session["session_id"], project_id=p["id"],
            status="failed", text="", created_at=0, error_code=code))
        state.qq.programs.batch_finished(row)
    assert notices(state) == []


def test_restart_preserves_unsent_work_and_never_replays_completed_commands_or_submitted_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(QQService, "start", lambda self: None)
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    def app():
        return create_tool_app(root=tmp_path, database_url=url, adapter_factory=ToolOpenAI().factory)
    with TestClient(app()) as client:
        state = client.app.state.runtime_state
        p, session, _ = configure_execution(client, state, admin_qq="9999")
        ingest(client, state, p, event(1, "/cogita pause"), 1)
        commands(client, state, p)
        first = state.qq.store.get(QQDelivery, replies(state, session)[0]["id"])
        first.status = "sending"
        state.qq.store.save(first)
        first_id = first.id
        ingest(client, state, p, event(2, "/cogita resume"), 2)
        running = state.qq.store.save(QQBatch(session_id=session["session_id"], project_id=p["id"],
            status="running", text="interrupted", created_at=0))
        running_id = running.id
        state.qq.programs.connection_failed(p["id"], "QQ_CONNECTION_FAILED")
    with TestClient(app()) as client:
        state = client.app.state.runtime_state
        assert state.qq.store.get(QQDelivery, first_id).status == "unknown"
        assert state.qq.store.get(QQBatch, running_id).status == "interrupted"
        assert len(notices(state)) == 2
        state.qq.connections[p["id"]] = connection = FakeConnection()
        commands(client, state, p)
        assert not state.qq.store.get(QQBinding, session["session_id"]).paused
        prepare(client, state, p)
        assert len(connection.calls) == 3  # Resume response, outage summary, interrupted batch.
        assert state.qq.store.get(QQDelivery, first_id).status == "unknown"
        assert len(replies(state, session)) == 2
    with TestClient(app()) as client:
        state = client.app.state.runtime_state
        state.qq.connections[p["id"]] = connection = FakeConnection()
        commands(client, state, p)
        prepare(client, state, p)
        assert not connection.calls and len(notices(state)) == 2


def test_source_deletion_cancels_unsent_alerts_and_project_removal_cleans_events(qq_client):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, admin_qq="9999")
    failed = state.qq.store.save(QQBatch(session_id=session["session_id"], project_id=p["id"],
        status="failed", text="", created_at=0, error_code="QQ_RUN_FAILED"))
    state.qq.programs.batch_finished(failed)
    state.qq.programs.prepare_notifications(state.projects.get(p["id"]))
    ok(client.delete(f"/api/sessions/{session['session_id']}"))
    prepare(client, state, p)
    assert not connection.calls
    ok(client.delete(f"/api/projects/{p['id']}"))
    assert notices(state) == []
