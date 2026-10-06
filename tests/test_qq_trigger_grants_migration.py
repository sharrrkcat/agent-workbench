"""Grant-column migration preserves epochs without touching owned files."""
from sqlalchemy import inspect

from ai_workbench.core.qq_store import QQStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.qq_models import QQParticipant


def test_grant_column_upgrade_preserves_existing_epoch_and_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'grants.db'}")
    migrations.upgrade(engine, migrations.QQ_RESOURCES_REVISION)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO qq_participants (session_id, sender_id, keyword_message_id, expires_at, in_window) "
            "VALUES ('session', '123', 42, 100, 1)")
    paths = [tmp_path / name for name in ("models/model.bin", "attachments/image.png", "runtimes/worker.exe")]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b"untouched")
    migrations.upgrade(engine, "head")
    migrations.upgrade(engine, "head")
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    columns = {column["name"] for column in inspect(engine).get_columns("qq_participants")}
    assert "grant_message_id" in columns and "keyword_message_id" not in columns
    row = QQStore(engine).get(QQParticipant, ("session", "123"))
    assert row.grant_message_id == 42 and row.expires_at == 100 and row.in_window
    assert all(path.read_bytes() == b"untouched" for path in paths)
