"""Participant schema upgrades without resetting records or touching stored files."""
from sqlalchemy import inspect

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
    migrations.upgrade(engine, "head")
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    assert {c["name"] for c in inspect(engine).get_columns("qq_participants")} == {
        "session_id", "sender_id", "grant_message_id", "expires_at", "in_window"}
    store = QQStore(engine)
    store.save(QQBinding(session_id="s", project_id="p", target_kind="group", target_id="123",
        deadline=64, window_kind="followup"))
    store.save(QQParticipant(session_id="s", sender_id="456", grant_message_id=1, expires_at=60, in_window=True))
    batch = store.save(QQBatch(session_id="s", project_id="p", text="frozen", created_at=5,
        trigger_kind="followup", participants_json='{"456": 1}'))
    migrations.upgrade(engine, "head")
    assert store.get(QQBinding, "s").deadline == 64
    assert store.get(QQParticipant, ("s", "456")).model_dump() == {
        "session_id": "s", "sender_id": "456", "grant_message_id": 1, "expires_at": 60, "in_window": True}
    assert store.get(QQBatch, batch.id).participants == {"456": 1}
    assert all(path.read_bytes() == b"unchanged" for path in files)
