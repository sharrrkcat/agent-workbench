"""Dependency identity and application-owned worker regression coverage."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.catalog import WORKER_ROOT, catalog, requirements_digest
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import SpeechRequest
from tests.test_phase2b_runtime import FAKE_ENGINE, installed_worker, supervisor
from tests.test_runtime_maintenance import link_directory


def pin(name="example", version="1.0", hashes=("a",)):
    return f"{name}=={version} " + " ".join(f"--hash=sha256:{value * 64}" for value in hashes)


def test_lock_identity_ignores_comments_layout_package_spelling_and_order(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(pin("Example_Package", hashes=("a", "b")) + "\n" + pin("second", "2.0"))
    expected = requirements_digest(lock)
    lock.write_text("# Formatting only\n" + pin("second", "2.0") + " # A comment\n"
        + "example.package == 1.0 \\\n    --hash=sha256:" + "b" * 64 + " \\\n"
        + "# Continuation comment\n    --hash=sha256:" + "a" * 64 + "\n\n")
    assert requirements_digest(lock) == expected
    for changed in (pin("example-package", "1.1", ("a", "b")), pin("example-package", hashes=("a", "c"))):
        lock.write_text(changed + "\n" + pin("second", "2.0"))
        assert requirements_digest(lock) != expected


@pytest.mark.parametrize("contents", [
    "", "# No dependencies", "example>=1.0", "example==1.0", "example==1.0 --hash=sha256:short",
    "--index-url https://example.test/simple\n" + pin(), pin() + " --no-deps",
    pin("Example_Package") + "\n" + pin("example-package"), pin() + " \\",
])
def test_lock_identity_rejects_unpinned_unsupported_or_incomplete_input(tmp_path, contents):
    lock = tmp_path / "requirements.lock"
    lock.write_text(contents)
    with pytest.raises(ValueError, match="Runtime requirements"):
        requirements_digest(lock)


def test_catalog_never_reads_worker_sources(monkeypatch):
    original = Path.open
    def open_file(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(WORKER_ROOT), "Catalog read application worker code"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    assert catalog("windows", "x86_64").supported


def test_native_dependency_order_and_download_metadata_are_not_identity():
    release = catalog("windows", "x86_64")
    native = release.native_cuda.model_copy(deep=True)
    native.dependencies.append(native.dependencies[0].model_copy(update={"sha256": "a" * 64}))
    expected = native.dependency_identity()
    native.dependencies.reverse()
    native.artifact.url = "https://example.test/mirror.zip"
    native.dependencies[0].size_bytes = 123
    assert native.dependency_identity() == expected
    native.dependencies[0].sha256 = "b" * 64
    assert native.dependency_identity() != expected


def test_release_metadata_changes_reuse_installed_entries_without_rebuilding(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("install")
        await service.task
        target = service.directory()
        original = service.store.installations()
        release = service.release.model_copy(deep=True)
        release.version = "new-label"
        release.requirements = "renamed.lock"
        release.python_executable = "renamed/python.exe"
        release.pytorch_index_url = "https://example.test/packages"
        for artifact in (release.python_artifact, release.native_cpu.artifact, release.native_cuda.artifact):
            artifact.url = "https://example.test/mirror"
            artifact.size_bytes = 123
        release.native_cpu.executable = "renamed-native.exe"
        restarted = RuntimeSupervisor(tmp_path, service.store, service.backends, release=release)
        restarted._install_python = AsyncMock(side_effect=AssertionError("Unexpected installation"))
        assert restarted.installation().state == "installed"
        assert restarted.directory() == target
        assert restarted.executable("kokoro") == target / "env/python.exe"
        assert restarted.executable("llama-server") == target / "native/cpu/bin/llama-server.exe"
        job = await restarted.submit("install")
        assert job.stage == "already_installed" and job.version == original[0].version
        restarted._install_python.assert_not_called()
        assert service.store.installations() == original
        await restarted.close()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("dependency", ["python_version", "python_artifact", "requirements", "native_cpu", "native_cuda"])
def test_dependency_changes_require_repair_and_reverting_restores_availability(tmp_path, dependency):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("install")
        await service.task
        original = service.store.installations()
        release = service.release.model_copy(deep=True)
        if dependency == "python_version":
            release.python_version = "3.12.12"
        elif dependency == "requirements":
            release.requirements_sha256 = "0" * 64
        elif dependency == "python_artifact":
            release.python_artifact.sha256 = "0" * 64
        else:
            getattr(release, dependency).artifact.sha256 = "0" * 64
        restarted = RuntimeSupervisor(tmp_path, service.store, service.backends, release=release)
        assert restarted.installation(check=False).state == "broken"
        with pytest.raises(ModelError) as error:
            await restarted.submit("install")
        assert error.value.code == "RUNTIME_BROKEN" and error.value.details["action"] == "repair"
        with pytest.raises(ModelError):
            restarted.assert_available(check=False)
        assert restarted.store.installations() == original
        restarted.release = service.release
        assert restarted.installation().state == "installed"
        assert restarted.installation(check=False).state == "installed"
        assert len(service.store.jobs()) == 1
        await restarted.close()
        await service.close()
    asyncio.run(scenario())


def test_restored_entry_recovers_but_failed_repair_stays_broken(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("install")
        await service.task
        entry = service.executable("kokoro")
        contents = entry.read_bytes()
        entry.unlink()
        assert service.installation().state == "broken"
        assert service.installation(check=False).state == "broken"
        entry.write_bytes(contents)
        assert service.installation().state == "installed"
        service._install_python = AsyncMock(side_effect=ModelError("RUNTIME_INSTALL_FAILED", "Fixture failure", 503))
        await service.submit("repair")
        await service.task
        assert entry.is_file()
        assert service.installation().state == "broken"
        restarted = RuntimeSupervisor(tmp_path, service.store, service.backends, release=service.release)
        assert restarted.installation().state == "broken"
        await restarted.close()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["repair", "uninstall"])
def test_explicit_maintenance_targets_recorded_version_and_preserves_other_directories(tmp_path, operation):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("install")
        await service.task
        previous = service.directory()
        unrelated = service.base / "local/unrelated/keep"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("unrelated")
        service.release.version = "next"
        job = await service.submit(operation)
        await service.task
        assert service.store.job(job.id).state == "completed"
        assert not previous.exists() and unrelated.read_text() == "unrelated"
        if operation == "repair":
            assert job.version == "next" and service.installation().version == "next"
            assert service.executable("kokoro").is_relative_to(service.base / "local/next")
        else:
            assert job.version == "fixture" and service.installation().state == "not_installed"
            assert not service.directory().exists()
        await service.close()
    asyncio.run(scenario())


def test_worker_code_updates_take_effect_on_reload_without_installation(tmp_path):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        try:
            original = service.store.installations()
            request = SpeechRequest(model=profile.alias, input="hello", voice="af_heart", response_format="wav")
            first = await manager.speech(profile.id, request)
            await manager.unload(profile.id)
            (service.worker_root / "tts_engine.py").write_text(FAKE_ENGINE.replace("1000", "2000"), encoding="utf-8")
            assert service.installation().state == "installed"
            second = await manager.speech(profile.id, request)
            assert first.data != second.data
            assert service.store.installations() == original and len(service.store.jobs()) == 1
            assert not (service.directory() / "worker").exists()
            marker = json.loads((service.directory() / "installation.json").read_bytes())
            assert set(marker) == {"dependencies", "executables"}
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())


def test_uninstall_rejects_escaping_recorded_version_and_finishes_job(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("install")
        await service.task
        value = service.store.installations()[0]
        value.version = "../../models"
        service.store.save_installation(value)
        protected = tmp_path / "data/models/keep"
        protected.parent.mkdir(parents=True)
        protected.write_text("protected")
        assert service.installation().state == "broken"
        job = await service.submit("uninstall")
        await service.task
        result = service.store.job(job.id)
        assert result.state == "failed" and result.error_code == "RUNTIME_BROKEN"
        assert service.active_job is None and not service.blocked
        assert protected.read_text() == "protected"
        await service.close()
    asyncio.run(scenario())


def test_installation_directory_rejects_redirected_local_root(tmp_path):
    service = supervisor(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    service.base.mkdir(parents=True)
    link_directory(service.base / "local", outside)
    with pytest.raises(ModelError, match="escapes its installation directory"):
        service.directory()
    assert not list(outside.iterdir())


def test_missing_application_worker_fails_load_without_breaking_runtime(tmp_path):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        try:
            original = service.store.installations()
            service.worker_entrypoint("kokoro").unlink()
            with pytest.raises(ModelError) as error:
                await manager.load(profile.id)
            assert error.value.code == "MODEL_UNAVAILABLE"
            assert service.installation().state == "installed" and service.store.installations() == original
            assert "load_total" in manager.process_log(profile)
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())
