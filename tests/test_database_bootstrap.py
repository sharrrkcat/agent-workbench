"""The server's file database is migrated by an independent, terminating process."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ai_workbench.db import database, migrations

ROOT = Path(__file__).resolve().parents[1]


def test_file_bootstrap_resolves_relative_paths_and_preserves_existing_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = "sqlite:///folder with spaces/app.db"
    engine = database.get_initialized_engine(url)
    try:
        assert Path(engine.url.database) == tmp_path / "folder with spaces/app.db"
        assert migrations.current_revision(engine) == migrations.HEAD_REVISION
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE preserved (value TEXT)")
            connection.exec_driver_sql("INSERT INTO preserved VALUES ('keep')")
    finally:
        engine.dispose()
    engine = database.get_initialized_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT value FROM preserved").scalar_one() == "keep"
    finally:
        engine.dispose()


def test_file_bootstrap_upgrades_old_revision(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = database.get_engine(url)
    migrations.upgrade(engine, migrations.HISTORY_RETRIEVAL_REVISION)
    engine.dispose()
    engine = database.get_initialized_engine(url)
    try:
        assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    finally:
        engine.dispose()


def test_unversioned_database_fails_without_deleting_it(tmp_path):
    url = f"sqlite:///{tmp_path / 'unversioned.db'}"
    engine = database.get_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE preserved (value TEXT)")
    engine.dispose()
    with pytest.raises(subprocess.CalledProcessError):
        database.get_initialized_engine(url)
    engine = database.get_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM preserved").scalar_one() == 0
    finally:
        engine.dispose()


def test_failed_migration_never_creates_server_engine(monkeypatch, tmp_path):
    attempts = []

    def fail(command, **kwargs):
        attempts.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(database.subprocess, "run", fail)
    monkeypatch.setattr(database, "get_engine", lambda *_: pytest.fail("server engine opened after failed migration"))
    with pytest.raises(subprocess.CalledProcessError):
        database.get_initialized_engine(f"sqlite:///{tmp_path / 'app.db'}")
    assert len(attempts) == 1
    assert attempts[0][:4] == [sys.executable, "-B", "-m", "ai_workbench.db.bootstrap"]


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:"])
def test_in_memory_database_keeps_its_initializing_connection(url, monkeypatch):
    monkeypatch.setattr(database.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("memory DB moved to child"))
    engine = database.get_initialized_engine(url)
    try:
        assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    finally:
        engine.dispose()


def test_application_startup_keeps_migration_and_unused_image_token_libraries_out(tmp_path):
    code = '''
import asyncio, json, sys
from pathlib import Path
from ai_workbench.core import web_filters
async def offline(_url):
    return ''
web_filters.download_subscription = offline
from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.processing import prepare_process_image
root = Path(sys.argv[1])
app = create_app(root=root, database_url=f'sqlite:///{root / "app.db"}')
counter = app.state.runtime_state.model_manager.reference_tokens
async def scenario():
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        forbidden = ('alembic', 'mako', 'PIL', 'tiktoken', 'ai_workbench.db.migrations')
        assert not [name for name in sys.modules if any(name == p or name.startswith(p + '.') for p in forbidden)]
        assert counter.count_text('hello world') == 2
        assert 'tiktoken' in sys.modules and 'PIL' not in sys.modules
        try:
            prepare_process_image(b'invalid image')
        except ModelError as exc:
            assert exc.code == 'INVALID_IMAGE'
        else:
            raise AssertionError('invalid image accepted')
        assert 'PIL.Image' in sys.modules
    try:
        counter.count_text('after shutdown')
    except RuntimeError:
        pass
    else:
        raise AssertionError('counter remained open')
asyncio.run(scenario())
print(json.dumps({'passed': True}))
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["passed"]
