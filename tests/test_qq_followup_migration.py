"""Participant schema upgrades without resetting records or touching stored files."""
from sqlalchemy import inspect, text
from tests.migration_fixtures import insert_historical_row, historical_row

from ai_workbench.core.qq_store import QQStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQParticipant


def test_followup_schema_and_repeated_upgrade_preserve_runtime_state(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'followup.db'}")
    migrations.upgrade(engine, migrations.QQ_DELIVERY_ECHO_REVISION)
    files = [tmp_path / path for path in ("models/model.bin", "attachments/image.png", "runtimes/worker.exe")]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"unchanged")
    migrations.upgrade(engine, migrations.QQ_FOLLOWUP_REVISION)
    assert migrations.current_revision(engine) == migrations.QQ_FOLLOWUP_REVISION
    assert {c["name"] for c in inspect(engine).get_columns("qq_participants")} == {
        "session_id", "sender_id", "keyword_message_id", "expires_at", "in_window"}
    with engine.begin() as db:
        insert_historical_row(db, "qq_bindings", session_id="s", project_id="p", target_kind="group", target_id="123", deadline=64, window_kind="followup")
        insert_historical_row(db, "qq_participants", session_id="s", sender_id="456", keyword_message_id=1, expires_at=60, in_window=True)
        insert_historical_row(db, "qq_batches", id=1, session_id="s", project_id="p", status="queued", text="frozen", created_at=5, trigger_kind="followup", participants_json='{"456":1}')
    migrations.upgrade(engine, migrations.QQ_FOLLOWUP_REVISION)
    with engine.connect() as db:
        assert historical_row(db, "qq_bindings", "session_id", "s")["deadline"] == 64
        assert historical_row(db, "qq_participants", "session_id", "s")["keyword_message_id"] == 1
        assert historical_row(db, "qq_batches", "id", 1)["participants_json"] == '{"456":1}'
    assert all(path.read_bytes() == b"unchanged" for path in files)
