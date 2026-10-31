"""QQ command schema changes retain existing records and never touch owned files."""
from sqlalchemy import inspect

from ai_workbench.core.qq_store import QQStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.qq_models import QQDelivery, QQMessage, QQNotification


def test_command_upgrade_retains_history_and_supports_program_deliveries(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'commands.db'}")
    migrations.upgrade(engine, migrations.WEB_FILTERS_REVISION)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO qq_messages (id,session_id,external_id,sender_id,sender_name,timestamp,text,references_json,disposition) "
            "VALUES (1,'session','1','123','member','2026-10-30T00:00:00Z','/cogita check','[]','pending')")
        db.exec_driver_sql("INSERT INTO qq_deliveries (id,session_id,run_id,tool_call_id,text,status,created_at) "
            "VALUES (1,'session','run','tool','old reply','sent',0)")
    paths = [tmp_path / name for name in ("models/model.bin", "attachments/image.png", "runtimes/worker.exe")]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b"untouched")
    migrations.upgrade(engine, "head")
    store = QQStore(engine)
    assert store.get(QQMessage, 1).kind == "chat", "Old text is not reinterpreted as executable commands"
    assert store.get(QQMessage, 1).command_status is None
    assert store.get(QQDelivery, 1).origin == "model"
    reply = store.save(QQDelivery(session_id="session", origin="command", command_message_id=1, text="report", created_at=1))
    event = store.save(QQNotification(project_id="project", event_key="test", kind="connection",
        error_code="QQ_AUTH_FAILED", created_at=1, last_at=2))
    migrations.upgrade(engine, "head")
    assert store.get(QQDelivery, reply.id).run_id is None
    assert store.get(QQNotification, event.id).error_code == "QQ_AUTH_FAILED"
    indexes = {item["name"] for item in inspect(engine).get_indexes("qq_messages")}
    assert "ix_qq_command_queue" in indexes
    assert all(path.read_bytes() == b"untouched" for path in paths)
