import asyncio
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
    raise AssertionError("A model operation must not check runtime installation integrity or its cache")


class ForbiddenCache(dict):
    get = __getitem__ = __contains__ = __setitem__ = pop = forbidden


def forbid_install_checks(monkeypatch, service):
    monkeypatch.setattr(service, "verify", AsyncMock(side_effect=forbidden))
    monkeypatch.setattr(implementation, "runtime_inventory", forbidden)
    monkeypatch.setattr(implementation, "sha256", forbidden)
    service._verified = ForbiddenCache()


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
        await service.submit("llama-server", "cpu", "install")
        await service.task
        entry = service.entries[0]
        target = service.directory(entry)
        marker = target / "installation.json"
        # A changed file list/hash is intentionally irrelevant to execution.
        data = json.loads(marker.read_text())
        data["files"] = None
        data["artifact_sha256"] = "not-checked-on-load"
        marker.write_text(json.dumps(data))
        (target / "unused.txt").write_text("not part of the manifest")
        forbid_install_checks(monkeypatch, service)
        assert service.executable(entry) == target / "bin/llama-server.exe"
        assert service.installation("llama-server", "cpu").state == "installed"
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("name", [None, 3, "../outside.exe", "C:/outside.exe", "bin/missing.exe", "bin"])
def test_invalid_or_missing_entry_fails_without_full_verification(tmp_path, monkeypatch, name):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("llama-server", "cpu", "install")
        await service.task
        entry = service.entries[0]
        (service.directory(entry) / "installation.json").write_text(json.dumps({"executable": name}))
        forbid_install_checks(monkeypatch, service)
        with pytest.raises(ModelError) as error:
            service.executable(entry)
        assert error.value.code == "RUNTIME_BROKEN"
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("owned", [True, False])
def test_linux_venv_entry_may_only_link_to_owned_shared_python(tmp_path, monkeypatch, owned):
    service = supervisor(tmp_path)
    entry = next(item for item in catalog("linux", "x86_64") if item.variant == "onnx-cpu").model_copy(update={"version": "fixture"})
    service.entries = [entry]
    target = service.directory(entry)
    (target / "worker").mkdir(parents=True)
    (target / "worker/server.py").write_text("# fixture")
    interpreter = (service.base / "python/shared" if owned else tmp_path / "outside")
    interpreter.mkdir(parents=True)
    (interpreter / "python").write_bytes(b"fixture")
    link_directory(target / "bin", interpreter)
    (target / "installation.json").write_text(json.dumps({"executable": "bin/python"}))
    service.store.save_installation(Installation(id="python-worker/onnx-cpu", runtime_id="python-worker",
        variant="onnx-cpu", version="fixture", state="installed"))
    forbid_install_checks(monkeypatch, service)
    if owned:
        assert service.executable(entry) == target / "bin/python"
    else:
        with pytest.raises(ModelError) as error:
            service.executable(entry)
        assert error.value.code == "RUNTIME_BROKEN"


def test_missing_runtime_and_model_failures_are_visible_before_spawn(tmp_path, monkeypatch):
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        state = client.app.state.runtime_state
        value = state.model_profiles.create(ModelProfile(name="local", alias="local", kind="llm",
            runtime_id="llama-server", runtime_variant="cpu", model_ref="llms/missing.gguf"))
        monkeypatch.setattr(ManagedProcess, "start", AsyncMock(side_effect=AssertionError("Unexpected process start")))
        response = client.post(f"/api/models/profiles/{value.id}/load")
        assert response.status_code == 503 and response.json()["error"]["code"] == "RUNTIME_NOT_INSTALLED"
        records = events(client.get(f"/api/models/profiles/{value.id}/log").json()["text"])
        assert terminal(records)[0]["error_code"] == "RUNTIME_NOT_INSTALLED"
        assert terminal(records, "queue_wait")[0]["result"] == "failed"
        service = state.runtime_supervisor
        entry = service.entry("llama-server", "cpu")
        target = service.directory(entry)
        target.mkdir(parents=True)
        (target / "llama-server.exe").write_bytes(b"fixture")
        (target / "installation.json").write_text(json.dumps({"executable": "llama-server.exe"}))
        service.store.save_installation(Installation(id="llama-server/cpu", runtime_id="llama-server",
            variant="cpu", version=entry.version, state="installed"))
        forbid_install_checks(monkeypatch, service)
        response = client.post(f"/api/models/profiles/{value.id}/load")
        assert response.status_code == 404 and response.json()["error"]["code"] == "MODEL_NOT_FOUND"
        records = events(client.get(f"/api/models/profiles/{value.id}/log").json()["text"])
        assert terminal(records)[0]["error_code"] == "MODEL_NOT_FOUND"
        assert terminal(records, "model_resources")[0]["result"] == "failed"


def test_onnx_explicit_auto_shared_and_repeat_loads_never_check_installation(tmp_path, monkeypatch):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        forbid_install_checks(monkeypatch, service)
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
def test_single_model_families_skip_verification_on_health_load_and_reload(tmp_path, monkeypatch, variant):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("llama-server", "cpu", "install")
        await service.task
        original = service.entries[0]
        runtime_id = "python-worker" if variant == "transformers-cuda" else "llama-server"
        entry = original.model_copy(update={"runtime_id": runtime_id, "variant": variant})
        service.entries = [entry]
        target = service.directory(entry)
        target.mkdir(parents=True, exist_ok=True)
        (target / "entry.exe").write_bytes(b"fixture")
        (target / "installation.json").write_text(json.dumps({"executable": "entry.exe"}))
        if runtime_id == "python-worker":
            entry.worker_entrypoint = "transformers_server.py"
            (target / "worker").mkdir()
            (target / "worker/transformers_server.py").write_text("# fixture")
            model = tmp_path / "data/models/llms/local"
            model.mkdir(parents=True)
            (model / "config.json").write_text("{}")
            (model / "model.safetensors").write_bytes(b"fixture")
        else:
            model = tmp_path / "data/models/llms/local.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"fixture")
        service.store.save_installation(Installation(id=f"{runtime_id}/{variant}", runtime_id=runtime_id,
            variant=variant, version=entry.version, state="installed"))
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        profile = manager.profiles.create(ModelProfile(name="local", alias="local", kind="llm", runtime_id=runtime_id,
            runtime_variant=variant, model_ref=model.relative_to(tmp_path / "data/models").as_posix()))
        adapter = manager._managed_slot(profile).adapter
        starts = []
        async def start(*args):
            starts.append(args)
            adapter.state = "ready"
        monkeypatch.setattr(adapter, "_start", start)
        forbid_install_checks(monkeypatch, service)
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
        forbid_install_checks(monkeypatch, service)
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
        forbid_install_checks(monkeypatch, service)
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
        target = service.directory(service.entries[0])
        body = "raise RuntimeError('private model contents')" if failure == "error" else "time.sleep(60)"
        (target / "worker/tts_engine.py").write_text("import time\nclass TTSEngine:\n    def __init__(self, *args):\n        " + body + "\n")
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
                kwargs["env"] = {**kwargs["env"], "WORKBENCH_WORKER_TOKEN": "short"}
                return await start(args, **kwargs)
            monkeypatch.setattr(ManagedProcess, "start", broken_start)
        forbid_install_checks(monkeypatch, service)
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
