from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel

from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.history_page import HistoryQuery, MemoryHistoryReader
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import SessionStore, MessageStore, RunStore
from ai_workbench.db.database import get_engine
from ai_workbench.db.history_page import SqlHistoryReader
from ai_workbench.db.stores import SqlSessionStore, SqlMessageStore, SqlRunStore


@pytest.fixture(params=["memory", "sqlite"])
def history_stores(request, tmp_path):
    if request.param == "memory":
        sessions, runs = SessionStore(), RunStore()
        messages = MessageStore(sessions)
        reader = MemoryHistoryReader(sessions, messages, runs)
        engine = None
    else:
        engine = get_engine(f"sqlite:///{tmp_path / 'history.db'}")
        SQLModel.metadata.create_all(engine)
        sessions, messages, runs = SqlSessionStore(engine), SqlMessageStore(engine), SqlRunStore(engine)
        reader = SqlHistoryReader(engine)
    return SimpleNamespace(sessions=sessions, messages=messages, runs=runs, reader=reader, engine=engine)


def test_history_pages_keep_replies_whole_and_number_globally(history_stores):
    state = history_stores
    session = state.sessions.create_session()
    sid = session.session_id
    for index in range(61):
        user = state.messages.add_message(sid, "user", f"input-{index}", message_id=f"user-{index:03}")
        run = state.runs.create_run("chat", "persona", sid, {"input_message_id": user.message_id})
        state.messages.add_message(sid, "assistant", "reasoning", run_id=run.run_id)
        state.messages.add_message(sid, "assistant", "final", run_id=run.run_id)
        state.runs.update_status(run.run_id, RunStatus.DONE)
    last = state.reader.page(sid, HistoryQuery())
    assert len(last["items"]) == 50 and last["items"][-1]["number"] == 122
    assert last["has_before"] and not last["has_after"]
    older = state.reader.page(sid, HistoryQuery(before=last["before_cursor"]))
    assert older["items"][-1]["number"] == 72
    restored = state.reader.page(sid, HistoryQuery(after=older["after_cursor"]))
    assert restored["items"] == last["items"]
    for item in older["items"] + last["items"]:
        if item["kind"] == "reply":
            assert len(item["messages"]) == 2
    users = state.reader.page(sid, HistoryQuery(), users=True)
    assert len(users["items"]) == 50 and all(item["kind"] == "user" for item in users["items"])
    anchor = users["items"][20]
    around = state.reader.page(sid, HistoryQuery(around=anchor["cursor"]))
    assert next(i for i in around["items"] if i["id"] == anchor["id"])["number"] == anchor["number"]
    with pytest.raises(ValueError):
        state.reader.page(state.sessions.create_session().session_id, HistoryQuery(before=anchor["cursor"]))


def test_bounded_context_does_not_call_full_history_and_preserves_parent(history_stores, monkeypatch):
    state = history_stores
    sid = state.sessions.create_session().session_id
    parent = state.messages.add_message(sid, "user", "question", message_id="000-parent")
    for index in range(150):
        state.messages.add_message(sid, "assistant", str(index), run_id="run", parent_message_id=parent.message_id,
                                   message_id=f"answer-{index:03}")
    for index in range(5):
        state.messages.add_message(sid, "assistant", "skip", metadata={"incomplete": True})
    if state.engine:
        monkeypatch.setattr(state.messages, "list_messages", lambda _: pytest.fail("Full history read"))
    built = ContextBuilder(state.messages).build(sid, "current", ContextPolicy(max_messages=2))
    assert [m["content"] for m in built.messages] == ["148", "149", "current"]
    assert {s.turn_id for s in built.trace.sources if s.kind == "history"} == {parent.message_id}
    assert {e.reason: e.count for e in built.trace.exclusions} == {"message_limit": 149, "ineligible_history": 5}
    monkeypatch.setattr(state.messages, "context_history_counts", lambda *_: pytest.fail("Zero limit queried history"))
    assert ContextBuilder(state.messages).build(sid, "current", ContextPolicy(max_messages=0)).messages == [{"role": "user", "content": "current"}]


def test_sql_reads_are_limited_and_do_not_select_private_snapshots(history_stores):
    state = history_stores
    if not state.engine:
        pytest.skip("SQL shape")
    sid = state.sessions.create_session().session_id
    run = state.runs.create_run("chat", "persona", sid)
    state.runs.create_step(run.run_id, "model")
    state.messages.add_message(sid, "user", "input")
    captured = []
    def capture(_connection, _cursor, statement, parameters, *_):
        captured.append((statement, parameters))
    event.listen(state.engine, "before_cursor_execute", capture)
    try:
        state.reader.page(sid, HistoryQuery(limit=1))
        state.runs.get_run(run.run_id)
        state.runs.list_steps(run.run_id)
        ContextBuilder(state.messages).build(sid, "next")
    finally:
        event.remove(state.engine, "before_cursor_execute", capture)
    assert any("LIMIT" in sql and "messagerecord" in sql for sql, _ in captured)
    assert not any(name in sql for sql, _ in captured for name in ("context_snapshot_json", "config_snapshot_json", "harness_state_json"))
    with state.engine.connect() as connection:
        plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN SELECT message_id FROM messagerecord WHERE session_id = ? ORDER BY created_at DESC, message_id DESC LIMIT 128", (sid,)).all()
    assert any("ix_message_session_order" in str(row) for row in plan)


def test_character_only_window_aggregates_empty_history(history_stores):
    state = history_stores
    sid = state.sessions.create_session().session_id
    state.messages.add_message(sid, "user", "retained")
    for index in range(260):
        state.messages.add_message(sid, "assistant", parts=[{"id": "r", "type": "reasoning", "text": "private"}])
    result = ContextBuilder(state.messages).build(sid, "current", ContextPolicy(max_messages=None, max_chars=100))
    assert [message["content"] for message in result.messages] == ["retained", "current"]
    assert [(item.reason, item.count, item.reference_id) for item in result.trace.exclusions] == [("empty", 260, None)]


def test_same_timestamp_pages_and_deleted_cursor_remain_stable(history_stores):
    from datetime import datetime, timezone
    from sqlalchemy import update
    from sqlmodel import Session as DbSession
    from ai_workbench.core.conversation_history import HistoryPruned, MemoryHistoryStore
    from ai_workbench.db.stores import SqlHistoryStore
    from ai_workbench.db.models import MessageRecord
    state = history_stores
    sid = state.sessions.create_session().session_id
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for id in ("b", "a", "c"):
        message = state.messages.add_message(sid, "user", id, message_id=id)
        if state.engine:
            with DbSession(state.engine) as db:
                db.exec(update(MessageRecord).where(MessageRecord.message_id == id).values(created_at=stamp))
                db.commit()
        else:
            state.messages.update_message(message.model_copy(update={"created_at": stamp}))
    page = state.reader.page(sid, HistoryQuery(limit=2))
    assert [i["id"] for i in page["items"]] == ["b", "c"]
    change = HistoryPruned(deleted_message_ids=["b"])
    if state.engine:
        SqlHistoryStore(state.engine).prune(sid, change)
    else:
        from ai_workbench.core.stores import RunEventStore
        MemoryHistoryStore(state.sessions, state.messages, state.runs, RunEventStore()).prune(sid, change)
    newer = state.reader.page(sid, HistoryQuery(around=page["before_cursor"], limit=2))
    assert [(i["id"], i["number"]) for i in newer["items"]] == [("a", 1), ("c", 2)]
    assert newer["history_version"] == page["history_version"] + 1
    assert state.reader.reference_numbers(sid, {"a", "b", "c"}) == {"a": 1, "c": 2}
