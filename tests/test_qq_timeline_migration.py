"""Timeline and program-queue indexes preserve existing records and storage."""
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine


def test_timeline_indexes_preserve_records_and_bound_pending_work(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'history.db'}")
    migrations.upgrade(engine, "0050_history_retrieval")
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO qq_messages (session_id,external_id,sender_id,sender_name,timestamp,text,references_json,disposition) "
            "VALUES ('s','1','1','member','2026-11-01T00:00:00+00:00','saved message','[]','pending')")
        db.exec_driver_sql("INSERT INTO qq_deliveries (session_id,run_id,tool_call_id,text,status,created_at) "
            "VALUES ('s','run','tool','saved reply','sent',1)")
        before = {table: db.exec_driver_sql(f"SELECT * FROM {table}").all() for table in ("qq_messages", "qq_deliveries")}
    paths = [tmp_path / directory / "retained" for directory in ("models", "attachments", "runtimes")]
    for path in paths:
        path.parent.mkdir()
        path.write_text("retained", encoding="utf-8")
    migrations.upgrade(engine, "head")
    migrations.upgrade(engine, "head")
    with engine.connect() as db:
        assert all(db.exec_driver_sql(f"SELECT * FROM {table}").all() == rows for table, rows in before.items())
        for sql, name in (
            ("SELECT id FROM qq_messages WHERE session_id='s' AND deleted=0 ORDER BY timestamp,id LIMIT 50", "ix_qq_message_timeline"),
            ("SELECT id FROM qq_deliveries WHERE session_id='s' AND deleted=0 AND origin!='model' ORDER BY created_at,id LIMIT 50", "ix_qq_program_timeline"),
            ("SELECT id FROM qq_deliveries WHERE session_id='s' AND status='pending' AND deleted=0 AND origin!='model' ORDER BY id LIMIT 1", "ix_qq_program_delivery_pending"),
        ):
            plan = str(db.exec_driver_sql("EXPLAIN QUERY PLAN " + sql).all())
            assert name in plan and "SCAN qq_" not in plan
    assert all(path.read_text(encoding="utf-8") == "retained" for path in paths)
    engine.dispose()
