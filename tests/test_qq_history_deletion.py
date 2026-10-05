"""QQ local deletion preserves transport outcomes and removes future context."""
import json

import pytest
from sqlalchemy import event as sql_event, inspect, text

from ai_workbench.core.context import message_text
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQDelivery, QQMessage, QQParticipant
from tests.test_qqbot import qq_client, configure_execution, child, event, freeze, ingest
from tests.test_qq_context import assert_pairs
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import completion, ok, tool_call


def replies(upstream):
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "first reply"}, "one"),
        tool_call("qq_send_message", {"text": "second reply"}, "two"), content="PRIVATE"), completion(content="PRIVATE")]


def context(state, sid, **policy):
    return build_qq_context(state.qq.store, state.messages, sid, "next", ContextPolicy(**policy), None).model_dump()["messages"]


def test_incoming_deletion_rebuilds_only_selected_input_and_next_request(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    sid = session["session_id"]
    poison = "bot POISON\nrepeated line"
    ingest(client, state, p, event(1, poison), 1)
    ingest(client, state, p, event(2, "repeated line\nkept"), 2)
    batch = freeze(state, session, 7)
    replies(upstream)
    client.portal.call(state.qq.execute, batch)
    first, second = state.qq.store.batch_messages(batch.id)
    original = state.messages.get_message(batch.input_message_id)
    run_before = state.runs.get_run(batch.run_id).model_dump()
    step = next(s for s in state.runs.list_steps(batch.run_id) if s.kind == "model")
    snapshot = state.runs.get_context_snapshot(step.step_id)
    participant = state.qq.store.get(QQParticipant, (sid, first.sender_id)).model_dump()
    change = ok(client.delete(f"/api/qq/sessions/{sid}/messages/{first.id}"))
    assert change["deleted_qq_message_ids"] == [first.id] and change["deleted_run_ids"] == []
    assert change["history_version"] == 1
    updated = state.messages.get_message(batch.input_message_id)
    assert updated.created_at == original.created_at and updated.message_id == original.message_id
    assert message_text(updated) == f"[{second.timestamp}][{second.sender_name}（QQ:{second.sender_id}）]:{second.text}"
    assert state.runs.get_run(batch.run_id).model_dump() == run_before
    assert state.runs.get_context_snapshot(step.step_id) == snapshot
    assert state.qq.store.get(QQParticipant, (sid, first.sender_id)).model_dump() == participant
    assert state.qq.store.get(QQMessage, second.id).disposition == "batched"
    assert "POISON" not in state.qq.store.get(QQBatch, batch.id).text
    assert len(state.qq.store.page(QQDelivery, sid)["items"]) == 2
    page = ok(client.get(f"/api/qq/sessions/{sid}/messages"))
    assert [r["id"] for r in page["items"]] == [second.id] and page["history_version"] == 1
    assert "deleted" not in page["items"][0]
    ingest(client, state, p, event(1, poison), 8)
    assert len(state.qq.store.page(QQMessage, sid)["items"]) == 1, "Duplicate ingress cannot restore a deleted bubble"
    replies(upstream)
    execute_batch(client, state, p, session, 3)
    assert "POISON" not in json.dumps(upstream.calls[-2]["messages"])
    assert "repeated line" in json.dumps(upstream.calls[-2]["messages"])
    assert len(connection.calls) == 4, "Deletion dispatches no OneBot action"


def test_delivery_and_reply_deletion_preserve_inputs_and_other_statuses(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    sid = session["session_id"]
    replies(upstream)
    batch, run = execute_batch(client, state, p, session)
    incoming = state.qq.store.batch_messages(batch.id)[0].model_dump()
    deliveries = sorted(state.qq.store.page(QQDelivery, sid)["items"], key=lambda r: r["id"])
    first, second = deliveries
    run_before = run.model_dump()
    change = ok(client.delete(f"/api/qq/sessions/{sid}/deliveries/{first['id']}"))
    assert change["deleted_qq_delivery_ids"] == [first["id"]]
    assert len(change["deleted_message_ids"]) == 1 and change["deleted_run_ids"] == []
    assert state.runs.get_run(run.run_id).model_dump() == run_before
    assert state.qq.store.page(QQDelivery, sid)["items"] == [second]
    assert state.qq.store.get(QQMessage, incoming["id"]).model_dump() == incoming
    wire = context(state, sid)
    assert_pairs(wire)
    assert "first reply" not in json.dumps(wire) and "second reply" in json.dumps(wire)
    assert state.qq.store.history_message_count(sid, None) == 2
    assert len(context(state, sid, max_messages=2)) == 4
    change = ok(client.delete(f"/api/runs/{run.run_id}"))
    assert change["deleted_qq_delivery_ids"] == [second["id"]] and change["deleted_run_ids"] == [run.run_id]
    assert change["history_version"] == 2
    assert state.qq.store.page(QQDelivery, sid)["items"] == []
    assert state.qq.store.get(QQBatch, batch.id).run_id is None
    assert state.qq.store.get(QQMessage, incoming["id"]).model_dump() == incoming
    assert state.runs.list_steps(run.run_id) == [] and state.run_events.list_events(run.run_id) == []
    assert client.get(f"/api/runs/{run.run_id}").status_code == 404
    assert client.delete(f"/api/runs/{run.run_id}").status_code == 404
    assert [m["role"] for m in context(state, sid)] == ["user", "user"]
    assert len(connection.calls) == 2
    assert state.events.list_events()[-1].payload == change


def test_empty_submitted_input_keeps_delivery_pairs_and_empty_groups_cost_nothing(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state)
    sid = session["session_id"]
    replies(upstream)
    batch, run = execute_batch(client, state, p, session)
    incoming, = state.qq.store.batch_messages(batch.id)
    ok(client.delete(f"/api/qq/sessions/{sid}/messages/{incoming.id}"))
    wire = context(state, sid, max_messages=2)
    assert [m["role"] for m in wire] == ["assistant", "tool", "assistant", "tool", "user"]
    assert_pairs(wire)
    length = len("next") + sum(len(json.dumps(m, ensure_ascii=False)) for m in wire[:-1])
    assert len(context(state, sid, max_chars=length)) == 5
    assert len(context(state, sid, max_chars=length - 1)) == 1
    assert state.qq.store.history_message_count(sid, None) == 2
    ok(client.delete(f"/api/runs/{run.run_id}"))
    assert context(state, sid, max_messages=1) == [{"role": "user", "content": "next"}]
    assert state.qq.store.history_message_count(sid, None) == 0


@pytest.mark.parametrize("stage", ["pending", "queued", "skipped"])
def test_unsubmitted_deletion_never_executes_removed_content(qq_client, stage):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state)
    sid = session["session_id"]
    ingest(client, state, p, event(1, "bot REMOVE"), 1)
    incoming = state.qq.store.page(QQMessage, sid)["items"][0]
    batch = None
    if stage != "pending":
        if stage == "skipped":
            ingest(client, state, p, event(2, "KEEP"), 2)
        batch = freeze(state, session, 7, limit=1)
    ok(client.delete(f"/api/qq/sessions/{sid}/messages/{incoming['id']}"))
    assert client.delete(f"/api/qq/sessions/{sid}/messages/{incoming['id']}").status_code == 404
    if stage == "pending":
        assert freeze(state, session, 7) is None
    elif stage == "queued":
        assert state.qq.store.get(QQBatch, batch.id).status == "cancelled"
        client.portal.call(state.qq.execute, batch)  # Includes a supervisor's stale queued object.
    else:
        replies(upstream)
        client.portal.call(state.qq.execute, batch)
        assert "REMOVE" not in json.dumps(upstream.calls)
        assert state.qq.store.batch_messages(batch.id)[0].disposition == "batched"
    if stage != "skipped":
        assert upstream.calls == []


def test_deletion_requires_matching_idle_session(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state)
    sid = session["session_id"]
    other = child(client, p, "6677")
    replies(upstream)
    batch, run = execute_batch(client, state, p, session)
    incoming = state.qq.store.batch_messages(batch.id)[0]
    delivery = state.qq.store.page(QQDelivery, sid)["items"][0]
    for kind, key in (("messages", incoming.id), ("deliveries", delivery["id"])):
        assert client.delete(f"/api/qq/sessions/{other['session_id']}/{kind}/{key}").status_code == 404
    paths = [f"/api/qq/sessions/{sid}/messages/{incoming.id}",
        f"/api/qq/sessions/{sid}/deliveries/{delivery['id']}", f"/api/runs/{run.run_id}"]
    for active in ("batch", "run"):
        if active == "batch":
            batch.status = "running"
            state.qq.store.save(batch)
        else:
            batch.status = "done"
            state.qq.store.save(batch)
            active_run = state.runs.create_run("chat", run.persona_id, sid)
        assert ok(client.get(f"/api/qq/sessions/{sid}"))["busy"] is True
        for path in paths:
            response = client.delete(path)
            assert response.status_code == 409 and response.json()["error"]["code"] == "SESSION_BUSY"
    state.runs.update_status(active_run.run_id, RunStatus.DONE)
    assert ok(client.get(f"/api/qq/sessions/{sid}"))["busy"] is False
    assert state.sessions.get_session(sid).history_version == 0
    assert client.delete(f"/api/messages/{batch.input_message_id}").status_code == 409
    assert client.post(f"/api/runs/{run.run_id}/retry").status_code == 409


def test_sql_deletion_rolls_back_and_survives_store_recreation(qq_client):
    client, state, upstream = qq_client
    if not hasattr(state.history.store, "engine"):
        pytest.skip("SQLite transaction boundary")
    p, session, _ = configure_execution(client, state)
    sid = session["session_id"]
    replies(upstream)
    batch, run = execute_batch(client, state, p, session)
    incoming = state.qq.store.batch_messages(batch.id)[0]
    engine = state.qq.store.engine
    def fail_version(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE sessionrecord"):
            raise RuntimeError("injected transaction failure")
    sql_event.listen(engine, "before_cursor_execute", fail_version)
    try:
        with pytest.raises(RuntimeError, match="injected transaction"):
            client.delete(f"/api/qq/sessions/{sid}/messages/{incoming.id}")
        with pytest.raises(RuntimeError, match="injected transaction"):
            client.delete(f"/api/runs/{run.run_id}")
    finally:
        sql_event.remove(engine, "before_cursor_execute", fail_version)
    assert not state.qq.store.get(QQMessage, incoming.id).deleted
    assert state.qq.store.get(QQBatch, batch.id).run_id == run.run_id
    assert len(state.qq.store.page(QQDelivery, sid)["items"]) == 2
    assert state.runs.list_steps(run.run_id)
    assert state.sessions.get_session(sid).history_version == 0
    ok(client.delete(f"/api/qq/sessions/{sid}/messages/{incoming.id}"))
    from ai_workbench.core.qq_store import QQStore
    restarted = QQStore(engine)
    restarted.recover()
    assert restarted.page(QQMessage, sid)["items"] == []
    assert restarted.get(QQMessage, incoming.id).deleted
    assert "bot" not in json.dumps(context(state, sid))


def test_deletion_migration_keeps_existing_records_and_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'deletion.db'}")
    migrations.upgrade(engine, migrations.QQ_FOLLOWUP_REVISION)
    with engine.begin() as db:
        db.execute(text("INSERT INTO qq_messages (session_id, external_id, sender_id, sender_name, timestamp, text, references_json, disposition) "
            "VALUES ('s', '1', '2', 'sender', '2026-10-05', 'keep', '[]', 'batched')"))
    files = [tmp_path / name / "keep.bin" for name in ("models", "attachments", "runtimes")]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"keep")
    migrations.upgrade(engine, "head")
    migrations.upgrade(engine, "head")
    assert migrations.current_revision(engine) == migrations.QQ_HISTORY_DELETION_REVISION
    for table in ("qq_messages", "qq_deliveries"):
        assert "deleted" in {column["name"] for column in inspect(engine).get_columns(table)}
    with engine.connect() as db:
        assert db.execute(text("SELECT text, disposition, deleted FROM qq_messages")).one() == ("keep", "batched", 0)
    assert all(path.read_bytes() == b"keep" for path in files)
