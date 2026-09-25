import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes import supervisor as implementation
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
from ai_workbench.core.models.runtimes.schema import Installation
from ai_workbench.core.models.schema import ModelProfile, SpeechRequest
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from tests.test_load_timing import events
from tests.test_phase2b_runtime import installed_worker, supervisor
from tests.test_runtime_maintenance import link_directory
from tests.test_tts import wav_bytes


def forbidden(*_args, **_kwargs):
    raise AssertionError("A model operation must not scan or hash the installed environment")


def forbid_install_scans(monkeypatch, service):
    original = Path.rglob
    target = service.directory()
    def rglob(path, *args, **kwargs):
        if path.is_relative_to(target):
            forbidden()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "rglob", rglob)
    monkeypatch.setattr(implementation, "sha256", forbidden)


def save_manifest(service, data):
    marker = service.directory() / "installation.json"
    marker.write_text(json.dumps(data), encoding="utf-8")
    service.store.save_installation(Installation(version=service.release.version, state="installed",
        manifest_sha256=hashlib.sha256(marker.read_bytes()).hexdigest()))
    service.installation()


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 5)


def terminal(records, stage="load_total", scope="host"):
    return [item for item in records if item["stage"] == stage and item["scope"] == scope and item["result"] != "started"]


def test_entry_resolution_reads_only_execution_metadata_and_preserves_nested_paths(tmp_path, monkeypatch):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit('install')
        await service.task
        target = service.directory()
        (target / "unused.txt").write_text("not part of the manifest")
        forbid_install_scans(monkeypatch, service)
        assert service.executable("llama-server", "cpu") == target / "native/cpu/bin/llama-server.exe"
        assert service.installation().state == "installed"
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("name", [None, 3, "../outside.exe", "C:/outside.exe", "bin/missing.exe", "bin"])
def test_invalid_or_missing_entry_fails_without_full_verification(tmp_path, monkeypatch, name):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit('install')
        await service.task
        data = json.loads((service.directory() / "installation.json").read_text())
        data["executables"]["cpu"] = name
        save_manifest(service, data)
        forbid_install_scans(monkeypatch, service)
        with pytest.raises(ModelError) as error:
            service.executable("llama-server", "cpu")
        assert error.value.code == "RUNTIME_BROKEN"
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("owned", [True, False])
def test_entry_links_cannot_escape_the_release(tmp_path, monkeypatch, owned):
    service = supervisor(tmp_path)
    async def install():
        await service.submit('install')
        await service.task
    asyncio.run(install())
    target = service.directory()
    interpreter = service.base / "python/shared" if owned else tmp_path / "outside"
    interpreter.mkdir(parents=True)
    (interpreter / "python.exe").write_bytes(b"fixture")
    link_directory(target / "bin", interpreter)
    data = json.loads((target / "installation.json").read_text())
    data["executables"]["cpu"] = "bin/python.exe"
    save_manifest(service, data)
    forbid_install_scans(monkeypatch, service)
    with pytest.raises(ModelError) as error:
        service.executable("llama-server", "cpu")
    assert error.value.code == "RUNTIME_BROKEN"


def test_missing_runtime_and_model_failures_are_visible_before_spawn(tmp_path, monkeypatch):
    missing = tmp_path / 'data/models/llms/missing'
    missing.mkdir(parents=True)
    (missing / 'mmproj.gguf').write_bytes(b'projector without a main model')
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        state = client.app.state.runtime_state
        value = state.model_profiles.create(ModelProfile(name='local', alias='local', kind='llm', model_ref='llms/missing', source={'type': 'local', 'execution_options': {'device': 'cpu'}}))
        monkeypatch.setattr(ManagedProcess, "start", AsyncMock(side_effect=AssertionError("Unexpected process start")))
        response = client.post(f"/api/models/profiles/{value.id}/load")
        assert response.status_code == 503 and response.json()["error"]["code"] == "RUNTIME_NOT_INSTALLED"
        records = events(client.get(f"/api/models/profiles/{value.id}/log").json()["text"])
        assert terminal(records)[0]["error_code"] == "RUNTIME_NOT_INSTALLED"
        assert terminal(records, "queue_wait")[0]["result"] == "failed"
        service = state.runtime_supervisor
        entry = service.release
        target = service.directory()
        target.mkdir(parents=True)
        (target / "llama-server.exe").write_bytes(b"fixture")
        save_manifest(service, {"dependencies": entry.dependency_identity().model_dump(),
            "executables": dict.fromkeys(["cpu", "cuda", "python"], "llama-server.exe")})
        forbid_install_scans(monkeypatch, service)
        response = client.post(f"/api/models/profiles/{value.id}/load")
        assert response.status_code == 404 and response.json()["error"]["code"] == "MODEL_NOT_FOUND"
        records = events(client.get(f"/api/models/profiles/{value.id}/log").json()["text"])
        assert terminal(records)[0]["error_code"] == "MODEL_NOT_FOUND"
        assert terminal(records, "model_resources")[0]["result"] == "failed"


def test_onnx_explicit_auto_shared_and_repeat_loads_never_scan_installation(tmp_path, monkeypatch):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        forbid_install_scans(monkeypatch, service)
        try:
            assert (await manager.health(profile.id)).residency == "unloaded"
            assert (await manager.load(profile.id)).residency == "loaded"
            adapter = manager._managed_slot(profile).adapter
            process = adapter.process
            assert (await manager.health(profile.id)).residency == "loaded"
            await manager.load(profile.id)
            record = terminal(events(manager.process_log(profile)))[0]
            assert record["process_reused"] and record["model_reused"]
            assert adapter.process is process
            other = manager.profiles.create(profile.model_copy(update={"id": "other", "alias": "other", "name": "other"}))
            request = SpeechRequest(model=other.alias, input="hello", voice="af_heart", response_format="wav")
            assert (await manager.speech(other.id, request)).data == wav_bytes()
            await until(lambda: terminal(events(manager.process_log(other)), "worker_load", "worker"))
            records = events(manager.process_log(other))
            assert {item["scope"] for item in records} == {"host", "worker"}
            assert all(0 <= item["cpu_duration_ms"] <= item["cpu_elapsed_ms"] for item in records)
            assert len(terminal(records)) == 1 and terminal(records)[0]["trigger"] == "autoload"
            assert {item["load_id"] for item in records} == {terminal(records)[0]["load_id"]}
            assert terminal(records)[0]["process_reused"] and not terminal(records)[0]["model_reused"]
            assert {item["stage"] for item in records} >= {"queue_wait", "execution_entry", "model_resources", "worker_load_rpc", "engine_init"}
            await manager.unload(other.id)
            await manager.unload(profile.id)
            assert process.process.returncode is not None
            assert (await manager.speech(profile.id, request.model_copy(update={"model": profile.alias}))).data == wav_bytes()
            assert adapter.process is not process
            assert not terminal(events(manager.process_log(profile)))[0]["process_reused"]
            assert not adapter._trace_logs
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("variant", ["cpu", "cuda", "transformers-cuda"])
def test_single_model_families_use_only_fast_checks_on_health_load_and_reload(tmp_path, monkeypatch, variant):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit('install')
        await service.task
        if variant == "transformers-cuda":
            model = tmp_path / "data/models/llms/local"
            model.mkdir(parents=True)
            (model / "config.json").write_text("{}")
            (model / "model.safetensors").write_bytes(b"fixture")
        else:
            model = tmp_path / "data/models/llms/local"
            model.mkdir(parents=True)
            (model / 'model.gguf').write_bytes(b"fixture")
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        profile = manager.profiles.create(ModelProfile(name='local', alias='local', kind='llm', model_ref=model.relative_to(tmp_path / 'data/models').as_posix(), source={'type': 'local', 'execution_options': {'device': 'cpu' if variant == 'cpu' else 'cuda'}}))
        adapter = manager._managed_slot(profile).adapter
        starts = []
        async def start(*args):
            starts.append(args)
            adapter.state = "ready"
        monkeypatch.setattr(adapter, "_start", start)
        forbid_install_scans(monkeypatch, service)
        try:
            assert (await manager.health(profile.id)).residency == "unloaded"
            assert (await manager.load(profile.id)).residency == "loaded"
            await manager.unload(profile.id)
            assert (await manager.load(profile.id)).residency == "loaded"
            assert len(starts) == 2
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())


def test_queue_timeout_is_timed_without_starting_worker(tmp_path, monkeypatch):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        slot = manager._managed_slot(profile)
        await slot.semaphore.acquire()
        monkeypatch.setattr("ai_workbench.core.models.manager.ManagedQueue",
                            lambda: SimpleNamespace(concurrency=1, queue_size=1, queue_timeout_seconds=0.05))
        forbid_install_scans(monkeypatch, service)
        try:
            pending = asyncio.create_task(manager.load(profile.id))
            await until(lambda: bool(events(manager.process_log(profile))))
            assert events(manager.process_log(profile))[0]["result"] == "started"
            with pytest.raises(ModelError) as error:
                await pending
            assert error.value.code == "MODEL_BUSY"
            records = events(manager.process_log(profile))
            assert len(terminal(records)) == 1 and terminal(records)[0]["error_code"] == "MODEL_BUSY"
            assert terminal(records, "queue_wait")[0]["result"] == "failed"
            assert not any(item["stage"] == "process_spawn" for item in records)
            assert not slot.active and not slot.queued
        finally:
            slot.semaphore.release()
            await manager.close()
            await service.close()
    asyncio.run(scenario())


def test_autoload_finishes_before_inference_and_later_cancel_does_not_rewrite_it(tmp_path, monkeypatch):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        forbid_install_scans(monkeypatch, service)
        pending = asyncio.create_task(manager.speech(profile.id, SpeechRequest(model=profile.alias,
            input="wait", voice="af_heart", response_format="wav")))
        try:
            await until(lambda: bool(terminal(events(manager.process_log(profile)))))
            before = terminal(events(manager.process_log(profile)))
            assert len(before) == 1 and before[0]["result"] == "completed" and not pending.done()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert terminal(events(manager.process_log(profile))) == before
            assert manager.status(profile.id).active == 0
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await manager.close()
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["error", "timeout", "cancel", "startup"])
def test_load_failures_record_cleanup_and_one_terminal_result(tmp_path, monkeypatch, failure):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        body = "raise RuntimeError('private model contents')" if failure == "error" else "time.sleep(60)"
        (service.worker_root / "tts_engine.py").write_text("import time\nclass TTSEngine:\n    def __init__(self, *args, **kwargs):\n        " + body + "\n")
        adapter = manager._managed_slot(profile).adapter
        if failure == "timeout":
            rpc = adapter._rpc
            async def timed_rpc(method, operation, body=None, **kwargs):
                if operation == "/load":
                    adapter.client.timeout = httpx.Timeout(0.05)
                return await rpc(method, operation, body, **kwargs)
            monkeypatch.setattr(adapter, "_rpc", timed_rpc)
        if failure == "startup":
            start = ManagedProcess.start
            async def broken_start(args, **kwargs):
                kwargs["env"] = {**kwargs["env"], "COGITA_WORKER_TOKEN": "short"}
                return await start(args, **kwargs)
            monkeypatch.setattr(ManagedProcess, "start", broken_start)
        forbid_install_scans(monkeypatch, service)
        pending = asyncio.create_task(manager.load(profile.id))
        try:
            if failure == "cancel":
                await until(lambda: any(item["stage"] == "engine_init" and item["result"] == "started"
                                        for item in events(manager.process_log(profile))))
                pending.cancel()
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else ModelError):
                await pending
            records = events(manager.process_log(profile))
            totals = terminal(records)
            assert len(totals) == 1
            assert totals[0]["result"] == {"cancel": "cancelled", "timeout": "timeout"}.get(failure, "failed")
            assert len(terminal(records, "failure_cleanup")) == 1
            assert adapter.process is None and adapter.run_dir is None
            assert manager.status(profile.id).active == 0 and not adapter._trace_logs
            assert "private model contents" not in manager.process_log(profile)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await manager.close()
            await service.close()
    asyncio.run(scenario())
