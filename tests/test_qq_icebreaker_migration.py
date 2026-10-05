"""Icebreaker cooldown migration leaves all data directories untouched."""
from sqlalchemy import inspect

from ai_workbench.core.qq_store import QQStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.qq_models import QQBinding


def test_cooldown_upgrade_and_repeated_upgrade(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'icebreaker.db'}")
    migrations.upgrade(engine, migrations.QQ_IMAGE_GENERATION_REVISION)
    files = [tmp_path / path for path in ("models/model.bin", "attachments/image.png", "runtimes/worker.exe")]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"untouched")
    migrations.upgrade(engine, "head")
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    column = next(c for c in inspect(engine).get_columns("qq_bindings") if c["name"] == "icebreaker_cooldown_until")
    assert column["nullable"]
    store = QQStore(engine)
    store.save(QQBinding(session_id="s", project_id="p", target_kind="group", target_id="123", icebreaker_cooldown_until=999))
    migrations.upgrade(engine, "head")
    assert store.get(QQBinding, "s").icebreaker_cooldown_until == 999
    assert all(path.read_bytes() == b"untouched" for path in files)
