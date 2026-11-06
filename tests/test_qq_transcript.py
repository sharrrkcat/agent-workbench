"""Unified QQ paging must not leave holes between incoming messages and replies."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, insert, update
from sqlmodel import SQLModel, create_engine

from ai_workbench.core.history_page import HistoryQuery
from ai_workbench.core.qq_transcript import QQTranscriptReader
from ai_workbench.db.models import RunRecord, RunStepRecord, SessionRecord
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQDelivery
from ai_workbench.db.stores import SqlSessionStore, SqlRunStore


@pytest.fixture
def transcript():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    sessions, runs = SqlSessionStore(engine), SqlRunStore(engine)
    session = sessions.create_session(kind="qqbot", character_id="p", target_kind="group", target_id="7788")
    state = SimpleNamespace(sessions=sessions, runs=runs)
    reader = QQTranscriptReader(state, SimpleNamespace(engine=engine))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with engine.begin() as db:
        db.execute(insert(QQBinding), dict(session_id=session.session_id, character_id="p", target_kind="group", target_id="7788"))
        db.execute(insert(QQMessage), [dict(id=i, session_id=session.session_id, external_id=str(i), sender_id="7",
            sender_name="Participant", timestamp=(start + timedelta(seconds=i)).isoformat(), text=f"input-{i}",
            disposition="batched", batch_id=(i - 1) // 10 + 1) for i in range(1, 1001)])
        db.execute(insert(RunRecord), [dict(run_id=f"r{i:03}", session_id=session.session_id, kind="chat", character_id="p", persona_id=None,
            status="DONE", created_at=start + timedelta(seconds=i * 10, microseconds=500_000),
            config_snapshot_json='{"private":"not for lists"}', harness_state_json='{"private":"not for lists"}') for i in range(1, 101)])
        db.execute(insert(QQDelivery), [dict(id=i, session_id=session.session_id, run_id=f"r{i:03}", tool_call_id=f"c{i}",
            text=f"reply-{i}", status="sent", created_at=(start + timedelta(seconds=i * 10 + 1)).timestamp()) for i in range(1, 101)])
    yield reader, engine, session.session_id, start
    engine.dispose()


def test_shared_time_range_and_bidirectional_paging(transcript):
    reader, _, sid, _ = transcript
    tail, _, _ = reader.page(sid, HistoryQuery())
    assert len(tail["items"]) == 50
    assert sum(row["kind"] == "reply" for row in tail["items"]) == 5
    pages = [tail]
    while pages[-1]["has_before"]:
        pages.append(reader.page(sid, HistoryQuery(before=pages[-1]["before_cursor"]))[0])
    items = [row for page in reversed(pages) for row in page["items"]]
    assert len(items) == len({row["id"] for row in items}) == 1100
    assert [row["kind"] for row in items] == (["incoming"] * 10 + ["reply"]) * 100
    assert all(len(row["deliveries"]) == 1 for row in items if row["kind"] == "reply")
    restored, _, _ = reader.page(sid, HistoryQuery(after=pages[1]["after_cursor"]))
    assert restored["items"] == tail["items"]
    around, _, _ = reader.page(sid, HistoryQuery(around=tail["items"][20]["cursor"]))
    assert tail["items"][20] in around["items"]


def test_snapshot_reads_are_bounded_and_exclude_processing(transcript):
    reader, engine, sid, _ = transcript
    with engine.begin() as db:
        db.execute(insert(RunStepRecord), dict(step_id="private-step", run_id="r100", kind="model", status="completed",
            message="private processing", context_snapshot_json='{"private":"input"}'))
    statements = []
    def capture(conn, cursor, sql, args, context, many):
        statements.append(sql)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page, _, _ = reader.page(sid, HistoryQuery())
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) < 25
    assert not any(term in sql for sql in statements for term in (
        "config_snapshot_json", "harness_state_json", "context_snapshot_json", "parts_json", "count("))
    assert "private processing" not in str(page)
    assert page["items"][-1]["run"]["steps"][0]["step_id"] == "private-step"


def test_deleted_anchor_programs_and_equal_times(transcript):
    reader, engine, sid, start = transcript
    last = start + timedelta(seconds=2000)
    with engine.begin() as db:
        db.execute(insert(QQMessage), dict(id=2001, session_id=sid, external_id="same", sender_id="7", sender_name="P",
            timestamp=last.isoformat(), text="command", kind="command", disposition="command", command_status="done"))
        db.execute(insert(RunRecord), dict(run_id="z-run", session_id=sid, kind="chat", character_id="p", persona_id=None, status="FAILED", created_at=last))
        db.execute(insert(QQDelivery), dict(id=2002, session_id=sid, origin="command", command_message_id=2001,
            text="result", status="sent", created_at=last.timestamp()))
    tail, _, _ = reader.page(sid, HistoryQuery(limit=3))
    assert [row["kind"] for row in tail["items"]] == ["incoming", "reply", "program"]
    anchor = tail["items"][0]["cursor"]
    with engine.begin() as db:
        db.execute(update(QQMessage).where(QQMessage.id == 2001).values(deleted=True))
        db.execute(update(SessionRecord).where(SessionRecord.session_id == sid).values(history_version=1))
    fresh, _, _ = reader.page(sid, HistoryQuery(around=anchor, limit=4))
    assert fresh["history_version"] == fresh["binding"]["history_version"] == 1
    assert not any(row["id"] == "qq-message-2001" for row in fresh["items"])
    with pytest.raises(ValueError):
        reader.page("other-session", HistoryQuery(before=anchor))


def test_cursor_candidates_seek_time_ranges_and_active_lookup_uses_status(transcript):
    reader, engine, sid, _ = transcript
    tail = reader.page(sid, HistoryQuery())[0]
    statements = []
    def capture(conn, cursor, sql, args, context, many):
        statements.append((sql, args))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        reader.page(sid, HistoryQuery(before=tail["before_cursor"]))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    with engine.connect() as db:
        candidates = [(sql, args) for sql, args in statements if sql.startswith((
            "SELECT qq_messages.id, qq_messages.timestamp", "SELECT runrecord.run_id, runrecord.created_at", "SELECT qq_deliveries.id, qq_deliveries.created_at"))]
        assert len(candidates) == 9
        for sql, args in candidates:
            plan = str(db.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, args).all())
            assert "SEARCH" in plan and ("<?" in plan or ">?" in plan or "<(?,?)" in plan or ">(?,?)" in plan)
        active, = [(sql, args) for sql, args in statements if "runrecord.status IN" in sql]
        assert "ix_run_session_status" in str(db.exec_driver_sql("EXPLAIN QUERY PLAN " + active[0], active[1]).all())


def test_unequal_inputs_multiple_sends_and_interleaved_sessions(transcript):
    reader, engine, sid, start = transcript
    expected = []
    with engine.begin() as db:
        for i in range(20):
            moment = start + timedelta(seconds=3000 + i // 3)
            for session_id in (sid, "unrelated"):
                run_id = f"mixed-{session_id}-{i:02}"
                db.execute(insert(RunRecord), dict(run_id=run_id, session_id=session_id, kind="chat", character_id="p", persona_id=None,
                    status=("DONE", "FAILED", "CANCELLED", "RUNNING")[i % 4], created_at=moment,
                    metadata_json='{"qq_reply":{"skipped":true}}' if i % 4 == 0 else '{}'))
                if session_id == sid:
                    expected.append((moment.timestamp(), 1, run_id, f"qq-run-{run_id}"))
                for j in range(i % 7):
                    result = db.execute(insert(QQMessage), dict(session_id=session_id, external_id=f"{i}-{j}", sender_id="7",
                        sender_name="P", timestamp=moment.isoformat(), text=f"{i}/{j}", disposition="skipped" if j % 2 else "pending"))
                    if session_id == sid:
                        identity = result.inserted_primary_key[0]
                        expected.append((moment.timestamp(), 0, identity, f"qq-message-{identity}"))
                for j in range(i % 3):
                    db.execute(insert(QQDelivery), dict(session_id=session_id, run_id=run_id, tool_call_id=f"c{j}",
                        text=f"send {j}", status="unknown" if j else "sent", created_at=moment.timestamp() + .001))
                result = db.execute(insert(QQDelivery), dict(session_id=session_id, text="program", status="sent",
                    origin="command" if i % 2 else "notification", created_at=moment.timestamp()))
                if session_id == sid:
                    identity = result.inserted_primary_key[0]
                    expected.append((moment.timestamp(), 2, identity, f"qq-delivery-{identity}"))
    expected_ids = [key[3] for key in sorted(expected)]
    wanted = set(expected_ids)
    page = reader.page(sid, HistoryQuery(limit=7))[0]
    selected = []
    while any(row["id"] in wanted for row in page["items"]):
        selected = page["items"] + selected
        if not page["has_before"]:
            break
        page = reader.page(sid, HistoryQuery(before=page["before_cursor"], limit=7))[0]
    selected = [row for row in selected if row["id"] in wanted]
    assert [row["id"] for row in selected] == expected_ids
    assert all("unrelated" not in row["id"] for row in selected)
    replies = [row for row in selected if row["kind"] == "reply"]
    assert len(replies) == 20
    assert {row["run"]["status"] for row in replies} == {"DONE", "FAILED", "CANCELLED", "RUNNING"}
    assert {len(row["deliveries"]) for row in replies} == {0, 1, 2}
    assert reader.page(sid, HistoryQuery(limit=1))[0]["active_run"]["status"] == "RUNNING"
