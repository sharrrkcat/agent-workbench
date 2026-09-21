import asyncio
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import SpeechRequest
from tests.test_phase2b_runtime import installed_worker, supervisor
from tests.test_tts import wav_bytes


def save_metadata(service, data):
    marker = service.directory() / "installation.json"
    marker.write_text(json.dumps(data), encoding="utf-8")
    value = service.installation(check=False)
    value.manifest_sha256 = hashlib.sha256(marker.read_bytes()).hexdigest()
    service.store.save_installation(value)


def test_install_restart_and_repeat_install_access_only_fixed_files(tmp_path, monkeypatch):
    async def scenario():
        service = supervisor(tmp_path)
        target = service.directory()
        reads = []
        original_open, original_scan = Path.open, os.scandir

        def environment_path(path):
            path = Path(path)
            if path.is_relative_to(target):
                return True
            if path.is_relative_to(service.base / ".staging") and "payload" in path.parts:
                parts = path.parts[path.parts.index("payload") + 1:]
                return not parts or parts[0] != "native"
            return False

        def open_file(path, mode="r", *args, **kwargs):
            if "r" in mode and environment_path(path):
                assert path.name == "installation.json", f"Unexpected installed-file read: {path}"
                reads.append(path.name)
            return original_open(path, mode, *args, **kwargs)

        def scan(path):
            assert not environment_path(path), f"Unexpected environment traversal: {path}"
            return original_scan(path)

        monkeypatch.setattr(Path, "open", open_file)
        monkeypatch.setattr(os, "scandir", scan)
        await service.submit("install")
        await service.task
        assert service.installation().state == "installed"
        assert set(json.loads((target / "installation.json").read_bytes())) == {"dependencies", "executables"}
        stages = [event.payload["job"]["stage"] for event in service.events.list_events()
                  if event.type == "runtime_job_updated"]
        assert "finalizing" in stages and "verifying" not in stages

        def inspect():
            reads.clear()
            service.assert_available()
            service.executable("llama-server", "cuda")
            assert service.installation().state == "installed"
            return list(reads)

        baseline = inspect()
        unrelated = target / "env/Lib/third_party"
        unrelated.mkdir(parents=True)
        for number in range(128):
            (unrelated / f"module_{number}.py").write_bytes(b"unrelated dependency")
        assert inspect() == baseline == ["installation.json"] * 3
        (unrelated / "module_0.py").write_bytes(b"changed")
        (unrelated / "module_1.py").unlink()
        assert inspect() == baseline

        restarted = RuntimeSupervisor(tmp_path, service.store, service.settings, release=service.release)
        restarted._install_python = AsyncMock(side_effect=AssertionError("Unexpected reinstall"))
        reads.clear()
        job = await restarted.submit("install")
        assert job.stage == "already_installed" and reads == ["installation.json"]
        restarted._install_python.assert_not_called()
        assert restarted.executable("kokoro") == target / "env/python.exe"
        await restarted.close()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["old_files", "old_release", "digest", "json", "dependencies", "python", "cpu", "cuda", "marker"])
def test_invalid_installation_is_broken_on_restart_and_requires_explicit_repair(tmp_path, damage):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("install")
        await service.task
        target = service.directory()
        marker = target / "installation.json"
        data = json.loads(marker.read_bytes())
        if damage == "old_files":
            data["files"] = {"env/python.exe": "0" * 64}
            save_metadata(service, data)
        elif damage == "old_release":
            data.pop("dependencies")
            data["release"] = service.release.model_dump()
            save_metadata(service, data)
        elif damage == "dependencies":
            data["dependencies"]["requirements_sha256"] = "0" * 64
            save_metadata(service, data)
        elif damage in {"digest", "json"}:
            marker.write_bytes(b"{" if damage == "json" else marker.read_bytes() + b" ")
            if damage == "json":
                value = service.installation(check=False)
                value.manifest_sha256 = hashlib.sha256(marker.read_bytes()).hexdigest()
                service.store.save_installation(value)
        else:
            name = "installation.json" if damage == "marker" else data["executables"][damage]
            (target / name).unlink()
        restarted = supervisor(tmp_path, store=service.store)
        assert restarted.installation(check=False).state == "broken"
        assert restarted.store.installations()[0].state == "installed"
        count = len(restarted.store.jobs())
        with pytest.raises(ModelError) as error:
            await restarted.submit("install")
        assert error.value.code == "RUNTIME_BROKEN" and error.value.details["action"] == "repair"
        assert len(restarted.store.jobs()) == count and target.is_dir()
        job = await restarted.submit("repair")
        await restarted.task
        assert restarted.store.job(job.id).state == "completed"
        assert restarted.installation().state == "installed"
        assert "files" not in json.loads(marker.read_bytes())
        await restarted.close()
        await service.close()
    asyncio.run(scenario())


def test_missing_interpreter_prevents_installation_promotion(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        install = service._install_python
        async def incomplete(entry, target, job, log):
            await install(entry, target, job, log)
            (target / "env/python.exe").unlink()
        service._install_python = incomplete
        job = await service.submit("install")
        await service.task
        assert service.store.job(job.id).state == "failed"
        assert not service.directory().exists()
        await service.close()
    asyncio.run(scenario())


def test_installation_query_and_install_route_report_repair_without_rebuilding(tmp_path):
    service = supervisor(tmp_path)
    async def install():
        await service.submit("install")
        await service.task
    asyncio.run(install())
    marker = service.directory() / "installation.json"
    data = json.loads(marker.read_bytes())
    data["files"] = {}
    save_metadata(service, data)
    count = len(service.store.jobs())
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        state = client.app.state.runtime_state
        state.runtime_supervisor = state.model_manager.runtime_supervisor = service
        response = client.get("/api/models/local-runtime")
        assert response.json()["state"] == "broken" and "manifest_sha256" not in response.json()
        response = client.post("/api/models/local-runtime/install")
        assert response.status_code == 503 and response.json()["error"]["details"]["action"] == "repair"
        assert len(service.store.jobs()) == count and marker.is_file()


def test_loaded_inference_and_model_status_do_not_read_installation_metadata(tmp_path, monkeypatch):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        try:
            await manager.load(profile.id)
            original = Path.open
            def open_file(path, *args, **kwargs):
                assert path.name != "installation.json", "Loaded inference read installation metadata"
                return original(path, *args, **kwargs)
            monkeypatch.setattr(Path, "open", open_file)
            assert manager.status(profile.id).residency == "loaded"
            result = await manager.speech(profile.id, SpeechRequest(model=profile.alias, input="hello", voice="af_heart", response_format="wav"))
            assert result.data == wav_bytes()
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())
