import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time
import venv
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_workbench.api.main import create_app
from ai_workbench.core.events import EventBus
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
from ai_workbench.core.models.runtimes.schema import CatalogEntry, DownloadSettings, Installation, RuntimeJob
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor, extract_archive, sha256
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.workers.server import Worker
from ai_workbench.workers.protocol import WorkerError
from ai_workbench.workers.protocol import local_model
from tests.model_fixtures import MockOpenAI
from ai_workbench.core.models.schema import ChatRequest, ProviderProfile


def archive_bytes(files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in (files or {"bin/llama-server.exe": b"test executable"}).items():
            member = zipfile.ZipInfo()
            member.filename = name
            archive.writestr(member, content)
    return output.getvalue()


def supervisor(tmp_path, *, data=None, store=None):
    data = data if data is not None else archive_bytes()
    entry = CatalogEntry(runtime_id="llama-server", variant="cpu", version="fixture", platform="windows",
        supported=True, url="https://runtime.test/cpu.zip", sha256=hashlib.sha256(data).hexdigest(),
        archive_format="zip", executable="llama-server.exe", kinds=["llm"])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=data))
    return RuntimeSupervisor(tmp_path, store or RuntimeStore(), EventBus(), [entry], transport)


def test_catalog_pins_supported_platforms_and_defers_remaining_accelerators():
    for system in ("windows", "linux"):
        entries = catalog(system, "x86_64")
        assert {entry.variant for entry in entries if entry.supported} == ({"cpu", "cuda", "torch-cpu", "onnx-cpu"} if system == "windows" else {"cpu", "torch-cpu", "onnx-cpu"})
        assert all(entry.sha256 for entry in entries if entry.supported)
    assert not any(entry.supported for entry in catalog("darwin", "arm64"))
    with pytest.raises(ValidationError):
        CatalogEntry(runtime_id="llama-server", variant="cpu", version="x", platform="windows", supported=True,
                     archive_format="zip", executable="x", kinds=["llm"], url="https://example.com/file")


@pytest.mark.parametrize("patch", [
    {"runtime_variant": "torch-cpu"}, {"runtime_id": "llama-server", "runtime_variant": "cpu"},
    {"provider_profile_id": "external"}, {"model_ref": "../outside"}, {"model_ref": "C:/weights"},
    {"model_ref": "vision\\file"}, {"model_ref": "/abs/model"}, {"model_ref": "https://hf.co/model"},
    {"runtime_options": {"command": "arbitrary"}}, {"runtime_options": {"max_batch_size": 0}},
])
def test_managed_profile_rejects_unsafe_and_incompatible_bindings(patch):
    values = dict(name="local", alias="local", kind="embedding", model_ref="embeddings/local", runtime_id="python-worker", runtime_variant="torch-cpu")
    if patch == {"runtime_variant": "torch-cpu"}:
        values["runtime_id"] = None
    with pytest.raises(ValidationError):
        ModelProfile(**{**values, **patch})


@pytest.mark.parametrize("settings", [
    {"pypi_index_url": "http://pypi.org/simple"}, {"http_proxy": "http://user:password@localhost:8888"},
    {"github_release_proxy_url": "https://example.com/?key=secret"}, {"removed": True},
])
def test_download_settings_are_strict(settings):
    with pytest.raises(ValidationError):
        DownloadSettings(**settings)


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "/absolute", "bin/../../escape", "bin\\escape"])
def test_archive_traversal_never_writes_outside_staging(tmp_path, name):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(archive_bytes({name: b"unsafe"}))
    with pytest.raises(ModelError):
        extract_archive(archive, tmp_path / "payload", "zip")
    assert not (tmp_path / "escape").exists()


def test_install_checksum_integrity_retry_idempotence_and_uninstall(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        job = await service.submit("llama-server", "cpu", "install")
        await service.task
        assert service.store.job(job.id).state == "completed"
        target = service.directory(service.entries[0])
        executable = await service.verify(service.entries[0])
        assert executable.read_bytes() == b"test executable"
        again = await service.submit("llama-server", "cpu", "install")
        assert again.stage == "already_installed"
        assert service.active_job is None
        executable.write_bytes(b"corrupt")
        with pytest.raises(ModelError) as error:
            await service.verify(service.entries[0])
        assert error.value.code == "RUNTIME_BROKEN"
        retry = await service.submit("llama-server", "cpu", "install")
        await service.task
        assert retry.id != job.id
        assert service.store.job(retry.id).state == "completed"
        protected = tmp_path / "data/models/llms/keep.gguf"
        protected.parent.mkdir(parents=True)
        protected.write_bytes(b"untouched")
        uninstall = await service.submit("llama-server", "cpu", "uninstall")
        await service.task
        assert service.store.job(uninstall.id).state == "completed"
        assert not target.exists()
        assert protected.read_bytes() == b"untouched"
        assert service.installation("llama-server", "cpu").state == "not_installed"
        assert {event.type for event in service.events.list_events()} >= {"runtime_job_updated", "runtime_status"}
        await service.close()
    asyncio.run(scenario())


def test_bad_checksum_and_https_downgrade_are_terminal_failures(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        service.entries[0].sha256 = "0" * 64
        job = await service.submit("llama-server", "cpu", "install")
        await service.task
        assert service.store.job(job.id).error_code == "RUNTIME_CHECKSUM_MISMATCH"
        assert not service.directory(service.entries[0]).exists()
        assert "RUNTIME_CHECKSUM_MISMATCH" in service.log_text(job.id)
        service.transport = httpx.MockTransport(lambda request: httpx.Response(302, headers={"Location": "http://unsafe.test/"}))
        retry = await service.submit("llama-server", "cpu", "install")
        await service.task
        assert service.store.job(retry.id).error_code == "RUNTIME_BROKEN"
        await service.close()
    asyncio.run(scenario())


def test_cancel_mutual_exclusion_and_shutdown_release_installation(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def download(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        service._download = download
        job = await service.submit("llama-server", "cpu", "install")
        await started.wait()
        with pytest.raises(ModelError) as busy:
            await service.submit("llama-server", "cpu", "uninstall")
        assert busy.value.code == "RUNTIME_INSTALLING"
        await service.close()
        assert cancelled.is_set()
        assert service.active_job is None
        assert service.store.job(job.id).state == "cancelled"
        assert not list((service.base / ".staging").iterdir())
    asyncio.run(scenario())


def test_sql_jobs_settings_and_interrupted_recovery(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    init_db(engine)
    store = RuntimeStore(engine)
    job = RuntimeJob(runtime_id="llama-server", variant="cpu", version="fixture", operation="install", state="running")
    store.save_job(job)
    store.save_installation(Installation(id="llama-server/cpu", runtime_id="llama-server", variant="cpu", version="fixture", state="installing", job_id=job.id))
    store.patch_settings({"http_proxy": "http://127.0.0.1:9999"})
    service = supervisor(tmp_path, store=RuntimeStore(engine))
    assert service.store.job(job.id).state == "interrupted"
    assert service.installation("llama-server", "cpu").state == "interrupted"
    assert service.store.settings().http_proxy == "http://127.0.0.1:9999"
    engine.dispose()


def test_api_install_actions_global_events_and_missing_runtime_details(tmp_path):
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        model = client.post("/api/models/profiles", json={"name": "managed", "alias": "managed", "kind": "llm", "model_ref": "llms/missing.gguf", "runtime_id": "llama-server", "runtime_variant": "cpu"}).json()
        response = client.post(f"/api/models/profiles/{model['id']}/load")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RUNTIME_NOT_INSTALLED"
        assert response.json()["error"]["details"]["action"] == "install"
        assert client.post("/api/models/runtimes/llama-server/vulkan/install").status_code == 422
        with client.websocket_connect("/api/models/runtimes/events") as socket:
            socket.send_json({"type": "next_event"})
            client.app.state.runtime_state.events.emit("runtime_job_updated", session_id="", payload={"job": {"id": "example"}})
            assert socket.receive_json()["payload"]["job"]["id"] == "example"
        assert client.get("/api/sessions").json() == []
        assert not client.app.state.runtime_state.runs.list_all_runs()


def test_worker_validates_private_rpc_before_importing_engines(tmp_path):
    worker = Worker(tmp_path)
    assert worker.health() == {"protocol_version": 1, "loaded": []}
    with pytest.raises(WorkerError):
        worker.dispatch("/load", {"profile_id": "test", "kind": "embedding", "model_ref": "../outside", "parameters": {}, "options": {"device": "cpu", "intraop_threads": 1, "max_batch_size": 2}})
    with pytest.raises(WorkerError):
        worker.dispatch("/embed", {"profile_id": "missing", "texts": ["text"]})


FAKE_ENGINE = '''
import os
import time
class Engine:
    def __init__(self, path, kind, params, options):
        self.kind, self.params, self.options = kind, params, options
    def embed(self, texts):
        if texts[0] == "crash": os._exit(7)
        if texts[0] == "wait": time.sleep(60)
        return {"vectors": [[3.0, 4.0] for _ in texts]}
    def rerank(self, query, documents):
        return {"scores": [float(index) for index in range(len(documents))]}
    def image_embed(self, images):
        return {"vectors": [[3.0, 4.0] for _ in images]}
    def vision(self, images):
        return {"outputs": [{"text": "caption"} for _ in images]}
'''


async def installed_worker(tmp_path):
    service = supervisor(tmp_path)
    entry = CatalogEntry(runtime_id="python-worker", variant="torch-cpu", version="fixture", platform="windows" if os.name == "nt" else "linux",
        archive_format="venv", executable="Scripts/python.exe" if os.name == "nt" else "bin/python", requirements="test.lock",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}", sha256="0" * 64, supported=True, kinds=["embedding", "reranker", "image_embedding", "vision"])
    service.entries = [entry]
    async def install(entry, target, job, log):
        await asyncio.to_thread(venv.EnvBuilder(with_pip=False, symlinks=False).create, target)
        source = Path(__file__).parents[1] / "ai_workbench/workers"
        shutil.copytree(source, target / "worker", ignore=shutil.ignore_patterns("__pycache__"))
        (target / "worker/engines.py").write_text(FAKE_ENGINE, encoding="utf-8")
    service._install_python = install
    await service.submit("python-worker", "torch-cpu", "install")
    await service.task
    assert service.installation("python-worker", "torch-cpu").state == "installed"
    profiles = ModelProfileStore()
    manager = ModelManager(profiles, ProviderProfileStore(), ModelSettingsStore(), service.events, runtime_supervisor=service)
    path = tmp_path / "data/models/embeddings/fixture"
    path.mkdir(parents=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"fixture")
    profile = profiles.create(ModelProfile(name="embedding", alias="embedding", kind="embedding", runtime_id="python-worker", runtime_variant="torch-cpu", model_ref="embeddings/fixture"))
    return service, manager, profile


def test_real_worker_process_rpc_auth_all_kinds_crash_and_explicit_reload(tmp_path):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        try:
            assert (await manager.health(profile.id)).residency == "unloaded"
            result = await manager.embed(profile.id, ["one", "two"])
            assert result.vectors == [[0.6, 0.8], [0.6, 0.8]]
            adapter = manager._slots[manager.backend_key(profile)].adapter
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(str(adapter.client.base_url) + "/health")
                assert response.status_code == 401
            before_pid = adapter.process.process.pid
            for kind in ("reranker", "image_embedding", "vision"):
                other = manager.profiles.create(ModelProfile(name=kind, alias=kind, kind=kind, runtime_id="python-worker", runtime_variant="torch-cpu", model_ref="embeddings/fixture"))
                if kind == "reranker":
                    assert (await manager.rerank(other.id, "q", ["a", "b"])).scores == [0, 1]
                elif kind == "image_embedding":
                    assert (await manager.image_embed(other.id, ["image"])).vectors == [[0.6, 0.8]]
                else:
                    assert (await manager.vision(other.id, ["image"])).outputs == [{"text": "caption"}]
            assert adapter.process.process.pid == before_pid
            assert len(manager._slots) == 1
            unused = manager.profiles.create(ModelProfile(name="unused", alias="unused", kind="embedding", runtime_id="python-worker", runtime_variant="torch-cpu", model_ref="embeddings/fixture"))
            await manager.unload(unused.id)
            assert adapter.process.process.pid == before_pid
            assert manager.status(profile.id).residency == "loaded"
            assert len(adapter.loaded) == 4
            with pytest.raises(ModelError):
                await manager.embed(profile.id, ["crash"])
            assert manager.status(profile.id).runtime.process_state == "failed"
            with pytest.raises(ModelError):
                await manager.embed(profile.id, ["one"])
            await manager.load(profile.id)
            assert (await manager.embed(profile.id, ["one"])).vectors == [[0.6, 0.8]]
            await manager.unload(profile.id)
            assert manager.status(profile.id).residency == "unloaded"
        finally:
            await manager.close()
            await service.close()
        assert not list((service.base / ".processes").iterdir())
    asyncio.run(scenario())


def test_cancelling_worker_inference_stops_process_before_releasing_queue(tmp_path):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        await manager.load(profile.id)
        task = asyncio.create_task(manager.embed(profile.id, ["wait"]))
        try:
            for _ in range(100):
                if manager.status(profile.id).active:
                    break
                await asyncio.sleep(0.01)
            with pytest.raises(ModelError):
                await service.submit("python-worker", "torch-cpu", "uninstall")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert manager.status(profile.id).active == 0
            assert manager.status(profile.id).runtime.process_state == "stopped"
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())


def test_runtime_logs_are_bounded_and_redacted(tmp_path):
    path = tmp_path / "log.txt"
    log = RuntimeLog(path, tmp_path, ("private-key",))
    log.write(f"{tmp_path} Authorization: private-key https://example.com/?token=secret")
    assert "private-key" not in path.read_text()
    assert str(tmp_path) not in path.read_text()
    assert "secret" not in path.read_text()
    for _ in range(12):
        log.write("x" * 1024 * 1024)
    assert path.stat().st_size == 10 * 1024 * 1024


def test_cancel_and_progress_writers_keep_job_revisions_monotonic():
    store = RuntimeStore()
    job = RuntimeJob(runtime_id="llama-server", variant="cpu", version="fixture", operation="install")
    store.save_job(job)
    cancellation = store.job(job.id)
    store.save_job(cancellation)
    job.state = "cancelled"
    store.save_job(job)
    assert job.revision > cancellation.revision
    assert store.job(job.id).state == "cancelled"


def test_weight_preflight_accepts_wd14_without_transformers_config(tmp_path):
    model = tmp_path / "vision/wd14"
    model.mkdir(parents=True)
    (model / "model.onnx").write_bytes(b"fixture")
    (model / "selected_tags.csv").write_text("name,category\nexample,0", encoding="utf-8")
    assert local_model(tmp_path, "vision/wd14", wd14=True) == model
    with pytest.raises(WorkerError) as missing:
        local_model(tmp_path, "vision/wd14")
    assert missing.value.code == "MODEL_NOT_FOUND"


def test_unlisted_installed_code_fails_integrity_check(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("llama-server", "cpu", "install")
        await service.task
        (service.directory(service.entries[0]) / "unexpected.dll").write_bytes(b"extra")
        with pytest.raises(ModelError) as broken:
            await service.verify(service.entries[0])
        assert broken.value.code == "RUNTIME_BROKEN"
    asyncio.run(scenario())


def test_managed_llama_aliases_share_state_and_forward_openai_model_id(tmp_path, monkeypatch):
    from ai_workbench.core.models.runtimes.adapters import LlamaServerAdapter
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit("llama-server", "cpu", "install")
        await service.task
        path = tmp_path / "data/models/llms/fixture.gguf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"local fixture")
        upstream = MockOpenAI()
        starts = []
        async def start(adapter, profile, path, executable):
            starts.append(profile.id)
            adapter.openai = upstream.factory(ProviderProfile(name="managed", base_url="http://worker.test/v1"))
            adapter.state = "ready"
        monkeypatch.setattr(LlamaServerAdapter, "_start", start)
        profiles = ModelProfileStore()
        manager = ModelManager(profiles, ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        first = profiles.create(ModelProfile(name="first", alias="first", kind="llm", model_ref="llms/fixture.gguf", runtime_id="llama-server", runtime_variant="cpu", capabilities={"streaming": True}, parameters={"temperature": 0.4}))
        alias = profiles.create(ModelProfile(name="alias", alias="alias", kind="llm", model_ref=first.model_ref, runtime_id=first.runtime_id, runtime_variant=first.runtime_variant, capabilities={"streaming": True}))
        bad = alias.model_copy(update={"runtime_options": {**alias.runtime_options, "threads": 8}})
        with pytest.raises(ModelError, match="identical runtime options"):
            manager.validate_binding(bad)
        request = ChatRequest(model="first", messages=[{"role": "user", "content": "hello"}])
        result = await manager.chat(first.id, request)
        assert result.message.content == "reply"
        chunks = [chunk async for chunk in manager.chat_stream(alias.id, request.model_copy(update={"stream": True}))]
        assert chunks[-2].finish_reason == "stop"
        assert all(call["model"] == "managed" for call in upstream.calls)
        assert upstream.calls[0]["temperature"] == 0.4
        assert len(starts) == len(manager._slots) == 1
        assert manager.status(alias.id).residency == manager.status(first.id).residency == "loaded"
        await manager.unload(first.id)
        assert manager.status(alias.id).residency == "unloaded"
        await manager.close()
        await service.close()
    asyncio.run(scenario())


def test_logs_retain_twenty_terminal_jobs(tmp_path):
    service = supervisor(tmp_path)
    for index in range(25):
        job = RuntimeJob(runtime_id="llama-server", variant="cpu", version="fixture", operation="install", state="completed")
        job.log_path = job.id + ".log"
        RuntimeLog(service.logs / job.log_path, tmp_path).write(str(index))
        service.store.save_job(job)
    service._prune_logs("llama-server")
    assert len(list(service.logs.glob("*.log"))) == 20


def test_python_installer_uses_only_managed_paths_and_hashed_lock(tmp_path, monkeypatch):
    from ai_workbench.core.models.runtimes import supervisor as implementation
    async def scenario():
        service = supervisor(tmp_path)
        service.entries = catalog()
        entry = service.entry("python-worker", "torch-cpu")
        calls = []
        async def command(args, env, cwd, log):
            calls.append((list(map(str, args)), env))
            if "venv" in args:
                Path(args[-1]).mkdir(parents=True)
        service._command = command
        uv_dir = tmp_path / "app/Scripts"
        uv_dir.mkdir(parents=True)
        (uv_dir / ("uv.exe" if os.name == "nt" else "uv")).write_bytes(b"fixture")
        monkeypatch.setattr(implementation.sysconfig, "get_path", lambda _: str(uv_dir))
        job = RuntimeJob(runtime_id="python-worker", variant="torch-cpu", version=entry.version, operation="install")
        await service._install_python(entry, tmp_path / "payload", job, RuntimeLog(tmp_path / "log", tmp_path))
        assert len(calls) == 4
        assert "--no-bin" in calls[0][0] and "--no-registry" in calls[0][0]
        assert "--require-hashes" in calls[2][0] and "--no-deps" in calls[2][0]
        assert all(call[0][0].startswith(str(uv_dir)) for call in calls[:3])
        assert all("sync" not in call[0] for call in calls)
        assert calls[0][1]["UV_PYTHON_INSTALL_DIR"] == str(service.base / "python")
    asyncio.run(scenario())
