import asyncio
import os
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import inspect

from ai_workbench.api.main import create_app
from ai_workbench.core.events import EventBus
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import CacheCleanupResult, Installation, RuntimeJob, StorageUsage
from ai_workbench.core.models.runtimes.storage import scan_storage
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db


def put(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def link_directory(link, target):
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def test_storage_deduplicates_links_and_excludes_external_references(tmp_path, monkeypatch):
    base = tmp_path / "data/runtimes"
    shared = put(base / ".cache/shared", b"0123456789")
    os.link(shared, base / ".cache/shared-again")
    worker = base / "py/torch-cpu/test/Lib/shared"
    worker.parent.mkdir(parents=True)
    os.link(shared, worker)
    put(base / ".cache/only", b"only")
    outside = put(tmp_path / "outside", b"external")
    os.link(outside, base / ".cache/outside-reference")
    monkeypatch.setattr(Path, "read_bytes", lambda _: pytest.fail("Storage must not read file contents"))
    value = scan_storage(base)
    assert value.complete
    cache = next(group for group in value.groups if group.id == ".cache")
    assert (cache.file_count, cache.logical_bytes, cache.unique_bytes, cache.shared_bytes, cache.exclusive_bytes) == (4, 32, 22, 18, 4)
    runtime = next(group for group in value.groups if group.category == "runtime")
    assert (runtime.runtime_id, runtime.variant, runtime.version) == ("python-worker", "torch-cpu", "test")
    assert runtime.unique_bytes == runtime.shared_bytes == 10
    assert runtime.exclusive_bytes == 0
    total = value.totals
    assert (total.file_count, total.logical_bytes, total.unique_bytes, total.shared_bytes, total.exclusive_bytes) == (5, 42, 22, 8, 14)


def test_storage_empty_roots_and_environment_directories(tmp_path):
    base = tmp_path / "data/runtimes"
    assert scan_storage(base).totals == StorageUsage()
    (base / "llama-server/version/cuda").mkdir(parents=True)
    put(base / "python/shared/python", b"python")
    put(base / ".staging/job/part", b"part")
    put(base / ".processes/process/ready", b"ready")
    put(base / "misc", b"misc")
    value = scan_storage(base)
    assert value.complete
    assert {group.category for group in value.groups} == {"runtime", "python", "cache", "staging", "processes", "other"}
    runtime = next(group for group in value.groups if group.category == "runtime")
    assert (runtime.runtime_id, runtime.variant, runtime.version, runtime.file_count) == ("llama-server", "cuda", "version", 0)


def test_storage_does_not_follow_symlinks_or_junctions(tmp_path):
    base = tmp_path / "data/runtimes"
    outside = tmp_path / "outside"
    marker = put(outside / "large", b"outside data")
    put(base / ".cache/only", b"only")
    link_directory(base / ".cache/link", outside)
    value = scan_storage(base)
    assert value.complete
    assert value.skipped_links == 1
    assert value.totals.logical_bytes == 4
    redirected = tmp_path / "redirected"
    link_directory(redirected, base)
    value = scan_storage(redirected)
    assert not value.complete and value.totals.logical_bytes is None
    assert marker.read_bytes() == b"outside data"


def test_storage_marks_unreadable_directories_unknown(tmp_path, monkeypatch):
    base = tmp_path / "data/runtimes"
    cache = put(base / ".cache/only").parent
    original = os.scandir

    def scandir(path):
        if Path(path) == cache:
            raise PermissionError()
        return original(path)

    monkeypatch.setattr(os, "scandir", scandir)
    value = scan_storage(base)
    group = next(group for group in value.groups if group.id == ".cache")
    assert not value.complete and not group.complete
    assert group.file_count is None and group.exclusive_bytes is None
    assert value.totals.logical_bytes is None
    assert value.warnings[0].code == "STORAGE_UNREADABLE"


def test_storage_detects_file_replacement_during_scan(tmp_path, monkeypatch):
    base = tmp_path / "data/runtimes"
    victim = put(base / ".cache/changed", b"first")
    original = Path.lstat
    calls = 0

    def lstat(path, *args, **kwargs):
        nonlocal calls
        if path == victim:
            calls += 1
            if calls == 2:
                victim.write_bytes(b"changed length")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    value = scan_storage(base)
    assert not value.complete and value.totals.unique_bytes is None
    assert any(warning.code == "STORAGE_CHANGED" for warning in value.warnings)


@pytest.mark.parametrize("mode", ["prune", "clean"])
def test_cache_jobs_preserve_installed_hardlinks_and_use_scoped_uv(tmp_path, mode):
    async def scenario():
        events = EventBus()
        store = RuntimeStore()
        service = RuntimeSupervisor(tmp_path, store, events, entries=[])
        cached = put(service.base / ".cache/package", b"immutable package")
        installed = service.base / "py/torch-cpu/test/Lib/package"
        installed.parent.mkdir(parents=True)
        os.link(cached, installed)
        put(service.base / ".cache/exclusive", b"cache")
        protected = put(tmp_path / "data/models/keep", b"weights")
        store.save_installation(Installation(id="python-worker/torch-cpu", runtime_id="python-worker",
            variant="torch-cpu", version="test", state="installed", manifest_sha256="a" * 64))
        before = store.installations()
        calls = []

        async def command(args, env, cwd, log):
            calls.append(list(map(str, args)))
            assert not any(key.upper().startswith("UV_") for key in env)
            assert cwd == tmp_path
            for path in cached.parent.iterdir():
                path.unlink()

        service._command = command
        job = await service.submit_cache(mode)
        await service.task
        value = store.job(job.id)
        assert value.state == "completed" and value.operation == f"cache_{mode}"
        assert value.runtime_id is value.variant is value.version is None
        assert value.result.before.exclusive_bytes == 5
        assert value.result.after.logical_bytes == 0
        assert installed.read_bytes() == b"immutable package" and protected.read_bytes() == b"weights"
        assert store.installations() == before
        assert calls[0][1:] == ["cache", mode, "--cache-dir", str(service.base / ".cache"), "--no-config", "--offline"]
        assert "Cache accounting" in service.log_text(job.id)
        assert {event.type for event in events.list_events()} == {"runtime_job_updated"}
        assert service.active_job is None and service.blocked is None
        await service.close()

    asyncio.run(scenario())


def test_cache_partial_failure_and_cancel_release_global_slot(tmp_path):
    async def scenario():
        service = RuntimeSupervisor(tmp_path, RuntimeStore(), entries=[])
        first = put(service.base / ".cache/first", b"first")
        second = put(service.base / ".cache/second", b"second")

        async def fail(*args):
            first.unlink()
            raise ModelError("RUNTIME_INSTALL_FAILED", "A file is in use", 503)

        service._command = fail
        job = await service.submit_cache("clean")
        await service.task
        result = service.store.job(job.id)
        assert result.state == "failed" and result.error_code == "RUNTIME_CLEANUP_FAILED"
        assert result.result.before.logical_bytes == 11 and result.result.after.logical_bytes == 6
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def block(*args):
            second.unlink()
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        service._command = block
        cancelled = await service.submit_cache("prune")
        await started.wait()
        with pytest.raises(ModelError) as busy:
            await service.submit("llama-server", "cpu", "install")
        assert busy.value.status == 409
        with pytest.raises(ModelError):
            await service.submit_cache("clean")
        result = await service.cancel(cancelled.id)
        assert result.state == "cancelled" and result.cancel_requested
        assert result.result.before.logical_bytes == 6 and result.result.after.logical_bytes == 0
        assert stopped.is_set() and service.active_job is None
        await service.close()

    asyncio.run(scenario())


def test_native_uv_cache_clean_preserves_the_installed_file(tmp_path):
    async def scenario():
        service = RuntimeSupervisor(tmp_path, RuntimeStore(), entries=[])
        cached = put(service.base / ".cache/archive-v0/fixture/module.py", b"VALUE = 42\n")
        installed = service.base / "py/fixture/1.0.0/module.py"
        installed.parent.mkdir(parents=True)
        os.link(cached, installed)
        before = installed.stat()
        job = await service.submit_cache("clean")
        await service.task
        value = service.store.job(job.id)
        assert value.state == "completed", service.log_text(job.id)
        assert not cached.exists() and installed.read_bytes() == b"VALUE = 42\n"
        assert (installed.stat().st_size, installed.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)
        assert value.result.after.logical_bytes == 0
        assert service.active_job is None
        await service.close()
    asyncio.run(scenario())


def test_shutdown_waits_for_an_already_requested_cache_cancellation(tmp_path):
    async def scenario():
        service = RuntimeSupervisor(tmp_path, RuntimeStore(), entries=[])
        started, accounting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0

        async def usage():
            nonlocal calls
            calls += 1
            if calls == 2:
                accounting.set()
                await release.wait()
            return StorageUsage()

        async def command(*args):
            started.set()
            await asyncio.Event().wait()

        service._cache_usage = usage
        service._command = command
        job = await service.submit_cache("clean")
        await started.wait()
        cancelled = asyncio.create_task(service.cancel(job.id))
        await accounting.wait()
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await asyncio.gather(cancelled, closing)
        assert service.store.job(job.id).state == "cancelled"
        assert service.active_job is None
    asyncio.run(scenario())


@pytest.mark.parametrize("root_link", [False, True])
def test_cache_rejects_redirected_roots_and_escaping_links(tmp_path, root_link):
    async def scenario():
        service = RuntimeSupervisor(tmp_path, RuntimeStore(), entries=[])
        cache = service.base / ".cache"
        outside = put(tmp_path / "outside/keep", b"protected").parent
        cache.parent.mkdir(parents=True)
        if root_link:
            link_directory(cache, outside)
        else:
            cache.mkdir()
            link_directory(cache / "link", outside)

        async def command(*args):
            pytest.fail("uv must never receive a redirected cache")

        service._command = command
        job = await service.submit_cache("clean")
        await service.task
        assert service.store.job(job.id).error_code == "RUNTIME_BROKEN"
        assert (outside / "keep").read_bytes() == b"protected"
        await service.close()

    asyncio.run(scenario())


def test_cache_result_persistence_restart_and_job_targets(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    init_db(engine)
    store = RuntimeStore(engine)
    job = RuntimeJob(operation="cache_clean", state="running",
                     result=CacheCleanupResult(before=StorageUsage(logical_bytes=19)))
    store.save_job(job)
    service = RuntimeSupervisor(tmp_path, RuntimeStore(engine), entries=[])
    restored = service.store.job(job.id)
    assert restored.state == "interrupted" and restored.result.before.logical_bytes == 19
    assert service.store.installations() == []
    for values in ({"operation": "install"}, {"operation": "cache_clean", "runtime_id": "cache"},
                   {"operation": "uninstall", "runtime_id": "x", "variant": "y", "version": "z", "result": {}}):
        with pytest.raises(ValidationError):
            RuntimeJob(**values)
    engine.dispose()


def test_storage_api_and_cleanup_request_are_strict(tmp_path):
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        response = client.get("/api/models/runtimes/storage")
        assert response.status_code == 200 and response.json()["complete"]
        for payload in ({}, {"mode": "unknown"}, {"mode": None}, {"mode": "clean", "path": "outside"}):
            assert client.post("/api/models/runtimes/cache/cleanup", json=payload).status_code == 422
        assert client.get("/api/models/runtimes/jobs").json() == []


def test_runtime_revision_resets_only_jobs_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.PET_FOUNDATION_REVISION)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO runtime_installations (id,runtime_id,variant,version,state,job_id,manifest_sha256,updated_at) "
                           "VALUES ('llama-server/cpu','llama-server','cpu','test','installed','old','digest',CURRENT_TIMESTAMP)")
        db.exec_driver_sql("INSERT INTO runtime_jobs (id,runtime_id,variant,version,operation,state,stage,progress_current,"
                           "cancel_requested,log_path,revision,created_at,updated_at) VALUES "
                           "('old','llama-server','cpu','test','install','completed','completed',0,0,'old.log',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")

    def rows():
        with engine.connect() as db:
            return {table: db.exec_driver_sql(f'SELECT * FROM "{table}"').fetchall()
                    for table in inspect(engine).get_table_names() if table not in {"alembic_version", "runtime_jobs", "runtime_installations"}}

    files = [put(tmp_path / "data" / folder / "keep", b"protected")
             for folder in ("runtimes", "models", "attachments", "knowledge", "logs")]
    before_files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    before_rows = rows()
    migrations.upgrade(engine)
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    store = RuntimeStore(engine)
    assert store.jobs() == []
    installation = store.installations()[0]
    assert installation.job_id is None and installation.state == "installed" and installation.manifest_sha256 == "digest"
    assert rows() == before_rows
    job = RuntimeJob(operation="cache_prune", state="completed", result=CacheCleanupResult(after=StorageUsage()))
    store.save_job(job)
    persisted = store.job(job.id)
    migrations.upgrade(engine)
    assert store.job(job.id) == persisted
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == before_files
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        assert db.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()
