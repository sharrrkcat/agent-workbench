"""Icebreaker cooldown migration leaves all data directories untouched."""
from sqlalchemy import inspect, text
from tests.migration_fixtures import insert_historical_row

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
    migrations.upgrade(engine, migrations.QQ_ICEBREAKER_REVISION)
    assert migrations.current_revision(engine) == migrations.QQ_ICEBREAKER_REVISION
    column = next(c for c in inspect(engine).get_columns("qq_bindings") if c["name"] == "icebreaker_cooldown_until")
    assert column["nullable"]
    with engine.begin() as db:
        insert_historical_row(db, "qq_bindings", session_id="s", project_id="p", target_kind="group", target_id="123", icebreaker_cooldown_until=999)
    migrations.upgrade(engine, migrations.QQ_ICEBREAKER_REVISION)
    with engine.connect() as db:
        assert db.execute(text("SELECT icebreaker_cooldown_until FROM qq_bindings WHERE session_id='s'")).scalar() == 999
    assert all(path.read_bytes() == b"untouched" for path in files)
