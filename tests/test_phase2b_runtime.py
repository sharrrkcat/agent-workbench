from ai_workbench.core.models.schema import ExternalConnection
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import threading
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
from ai_workbench.core.models.runtimes.schema import NativeRuntime, RuntimeArtifact, DownloadSettings, Installation, RuntimeJob
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor, extract_archive, sha256
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import LocalRuntimeSettingsStore, ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.workers.server import Worker
from ai_workbench.workers.common import publish_ready
from ai_workbench.workers.protocol import WorkerError
from ai_workbench.workers.protocol import local_model
from tests.model_fixtures import MockOpenAI
from ai_workbench.core.models.schema import ChatRequest, ProviderProfile, SpeechRequest
from tests.test_tts import model_tree, wav_bytes


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
    native = NativeRuntime(artifact=RuntimeArtifact(url="https://runtime.test/native.zip",
        sha256=hashlib.sha256(data).hexdigest(), archive_format="zip"))
    release = catalog("windows", "x86_64").model_copy(update={"version": "fixture", "native_cpu": native, "native_cuda": native})
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=data))
    settings = LocalRuntimeSettingsStore(store.engine if store else None)
    service = RuntimeSupervisor(tmp_path, store or RuntimeStore(), settings, EventBus(), release, transport)
    async def install(entry, target, job, log):
        (target / "env").mkdir(parents=True)
        (target / "env/python.exe").write_bytes(b"test interpreter")
    async def command(args, env, cwd, log):
        assert args[1:] == ["--version"] and Path(args[0]).is_file()
    service._install_python = install
    service._command = command
    return service


def test_catalog_is_one_pinned_windows_release():
    release = catalog("windows", "amd64")
    assert release.supported and release.python_version == "3.12.11"
    assert release.python_artifact.sha256 and release.requirements_sha256
    assert release.native_cpu.artifact.sha256 and release.native_cuda.dependencies[0].sha256
    for system, machine in (("linux", "x86_64"), ("windows", "arm64"), ("darwin", "arm64")):
        assert not catalog(system, machine).supported


@pytest.mark.parametrize('existing', [None, {'protocol_version': 1, 'port': 12345}])
def test_ready_readers_never_observe_partial_publication(tmp_path, monkeypatch, existing):
    ready = tmp_path / 'ready.json'
    value = {'protocol_version': 1, 'error_code': 'MODEL_UNAVAILABLE'}
    if existing:
        ready.write_text(json.dumps(existing), encoding='utf-8')
    writing, finish = threading.Event(), threading.Event()
    def interrupted_write(path, text, encoding):
        with path.open('w', encoding=encoding) as stream:
            stream.write(text[:5])
            stream.flush()
            writing.set()
            assert finish.wait(5)
            stream.write(text[5:])
    monkeypatch.setattr(Path, 'write_text', interrupted_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(publish_ready, ready, value)
        try:
            assert writing.wait(5)
            if existing:
                assert json.loads(ready.read_text(encoding='utf-8')) == existing
            else:
                assert not ready.exists()
        finally:
            finish.set()
            task.result(timeout=5)
    assert json.loads(ready.read_text(encoding='utf-8')) == value


@pytest.mark.parametrize("patch", [
    {"runtime_variant": "cpu"}, {"runtime_id": "llama-server"}, {"provider_profile_id": "external"},
    {"model_ref": "../outside"}, {"model_ref": "C:/weights"}, {"model_ref": "vision\\file"},
    {"model_ref": "/abs/model"}, {"model_ref": "https://hf.co/model"},
    {"source": {"type": "local", "execution_options": {"command": "arbitrary"}}},
    {"source": {"type": "local", "execution_options": {"max_batch_size": 0}}},
])
def test_managed_profile_rejects_unsafe_and_removed_fields(patch):
    values = dict(name="local", alias="local", kind="llm", model_ref="llms/local.gguf", source={'type': 'local'})
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


def test_install_entry_checks_explicit_repair_idempotence_and_uninstall(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        job = await service.submit('install')
        await service.task
        assert service.store.job(job.id).state == "completed"
        target = service.directory()
        service.assert_available()
        executable = service.executable("llama-server", "cpu")
        assert executable.read_bytes() == b"test executable"
        again = await service.submit('install')
        assert again.stage == "already_installed"
        assert service.active_job is None
        executable.unlink()
        with pytest.raises(ModelError) as error:
            service.assert_available()
        assert error.value.code == "RUNTIME_BROKEN"
        with pytest.raises(ModelError) as error:
            await service.submit('install')
        assert error.value.code == "RUNTIME_BROKEN" and error.value.details["action"] == "repair"
        retry = await service.submit('repair')
        await service.task
        assert retry.id != job.id
        assert service.store.job(retry.id).state == "completed"
        protected = tmp_path / "data/models/llms/keep.gguf"
        protected.parent.mkdir(parents=True)
        protected.write_bytes(b"untouched")
        uninstall = await service.submit('uninstall')
        await service.task
        assert service.store.job(uninstall.id).state == "completed"
        assert not target.exists()
        assert protected.read_bytes() == b"untouched"
        assert service.installation().state == "not_installed"
        assert {event.type for event in service.events.list_events()} >= {"runtime_job_updated", "runtime_status"}
        await service.close()
    asyncio.run(scenario())


def test_bad_checksum_and_https_downgrade_are_terminal_failures(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        service.release.native_cpu.artifact.sha256 = "0" * 64
        job = await service.submit('install')
        await service.task
        assert service.store.job(job.id).error_code == "RUNTIME_CHECKSUM_MISMATCH"
        assert not service.directory().exists()
        assert "RUNTIME_CHECKSUM_MISMATCH" in service.log_text(job.id)
        service.transport = httpx.MockTransport(lambda request: httpx.Response(302, headers={"Location": "http://unsafe.test/"}))
        retry = await service.submit('repair')
        await service.task
        assert service.store.job(retry.id).error_code == "RUNTIME_BROKEN"
        await service.close()
    asyncio.run(scenario())


def test_repair_reuses_checked_native_cache_and_redownloads_corruption(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        calls = []
        data = archive_bytes()
        def download(request):
            calls.append(request.url)
            return httpx.Response(200, content=data)
        service.transport = httpx.MockTransport(download)
        for operation in ("install", "repair"):
            await service.submit(operation)
            await service.task
            assert service.installation().state == "installed"
        assert len(calls) == 1
        archive = service.base / ".cache/cogita-artifacts" / service.release.native_cpu.artifact.sha256
        archive.write_bytes(b"broken cache")
        await service.submit("repair")
        await service.task
        assert service.installation().state == "installed" and len(calls) == 2
        assert archive.read_bytes() == data
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
        job = await service.submit('install')
        await started.wait()
        with pytest.raises(ModelError) as busy:
            await service.submit('uninstall')
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
    job = RuntimeJob(version='fixture', operation='install', state='running')
    store.save_job(job)
    store.save_installation(Installation(version='fixture', state='installing', job_id=job.id))
    LocalRuntimeSettingsStore(engine).patch( {"download": {"http_proxy": "http://127.0.0.1:9999"}})
    service = supervisor(tmp_path, store=RuntimeStore(engine))
    assert service.store.job(job.id).state == "interrupted"
    assert service.installation().state == "interrupted"
    assert service.settings.get().download.http_proxy == "http://127.0.0.1:9999"
    engine.dispose()


def test_api_install_actions_global_events_and_missing_runtime_details(tmp_path):
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        model = client.post("/api/models/profiles", json={'name': 'managed', 'alias': 'managed', 'kind': 'llm', 'model_ref': 'llms/missing.gguf', 'source': {'type': 'local', 'execution_options': {'device': 'cpu'}}}).json()
        response = client.post(f"/api/models/profiles/{model['id']}/load")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RUNTIME_NOT_INSTALLED"
        assert response.json()["error"]["details"]["action"] == "install"
        assert client.post("/api/models/local-runtime/llama-server/vulkan/install").status_code == 404
        with client.websocket_connect("/api/models/events") as socket:
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
import io
import struct
import wave
class TTSEngine:
    def __init__(self, path, kind, params, options, *, models_root):
        self.kind, self.params, self.options = kind, params, options
    def speech(self, text, voice, speed, response_format, language):
        if text == "crash": os._exit(7)
        if text == "wait": time.sleep(60)
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(struct.pack("<h", 1000) * 200)
        return stream.getvalue(), "audio/wav"
'''


async def installed_worker(tmp_path):
    service = supervisor(tmp_path)
    service.release.python_executable = "env/Scripts/python.exe" if os.name == "nt" else "env/bin/python"
    source = service.worker_root
    service.worker_root = tmp_path / "application package/workers"
    shutil.copytree(source, service.worker_root, ignore=shutil.ignore_patterns("__pycache__"))
    (service.worker_root / "tts_engine.py").write_text(FAKE_ENGINE, encoding="utf-8")
    async def install(entry, target, job, log):
        await asyncio.to_thread(venv.EnvBuilder(with_pip=False, symlinks=False).create, target / "env")
    service._install_python = install
    await service.submit('install')
    await service.task
    assert service.installation().state == "installed"
    profiles = ModelProfileStore()
    manager = ModelManager(profiles, ProviderProfileStore(), ModelSettingsStore(), service.events, runtime_supervisor=service)
    model_tree(tmp_path)
    profile = profiles.create(ModelProfile(name='speech', alias='speech', kind='tts', model_ref='tts/kokoro', source={'type': 'local'}))
    return service, manager, profile


def test_real_worker_process_rpc_auth_crash_and_explicit_reload(tmp_path):
    async def scenario():
        service, manager, profile = await installed_worker(tmp_path)
        try:
            assert (await manager.health(profile.id)).residency == "unloaded"
            request = SpeechRequest(model=profile.alias, input="hello", voice="af_heart", response_format="wav")
            result = await manager.speech(profile.id, request)
            assert result.data == wav_bytes()
            adapter = manager._slots[manager.execution_key(profile)].adapter
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(str(adapter.client.base_url) + "/health")
                assert response.status_code == 401
            before_pid = adapter.process.process.pid
            other = manager.profiles.create(ModelProfile(name='other', alias='other', kind='tts', model_ref='tts/kokoro', source={'type': 'local'}))
            assert (await manager.speech(other.id, request.model_copy(update={"model": other.alias}))).data == wav_bytes()
            assert adapter.process.process.pid == before_pid
            assert len(manager._slots) == 1
            unused = manager.profiles.create(ModelProfile(name='unused', alias='unused', kind='tts', model_ref='tts/kokoro', source={'type': 'local'}))
            await manager.unload(unused.id)
            assert adapter.process.process.pid == before_pid
            assert manager.status(profile.id).residency == "loaded"
            assert len(adapter.loaded) == 2
            with pytest.raises(ModelError):
                await manager.speech(profile.id, request.model_copy(update={"input": "crash"}))
            assert manager.status(profile.id).runtime.process_state == "failed"
            with pytest.raises(ModelError):
                await manager.speech(profile.id, request)
            await manager.load(profile.id)
            assert (await manager.speech(profile.id, request)).data == wav_bytes()
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
        task = asyncio.create_task(manager.speech(profile.id, SpeechRequest(model=profile.alias, input="wait", voice="af_heart", response_format="wav")))
        try:
            for _ in range(100):
                if manager.status(profile.id).active:
                    break
                await asyncio.sleep(0.01)
            with pytest.raises(ModelError):
                await service.submit('uninstall')
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
    job = RuntimeJob(version='fixture', operation='install')
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


def test_unlisted_installed_code_does_not_change_availability(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit('install')
        await service.task
        (service.directory() / "unexpected.dll").write_bytes(b"extra")
        service.assert_available()
        assert (await service.submit('install')).stage == "already_installed"
        await service.close()
    asyncio.run(scenario())


def test_managed_llama_aliases_share_state_and_forward_openai_model_id(tmp_path, monkeypatch):
    from ai_workbench.core.models.runtimes.adapters import LlamaServerAdapter
    async def scenario():
        service = supervisor(tmp_path)
        await service.submit('install')
        await service.task
        path = tmp_path / "data/models/llms/fixture.gguf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"local fixture")
        upstream = MockOpenAI()
        starts = []
        async def start(adapter, profile, path, executable):
            starts.append(profile.id)
            adapter.openai = upstream.factory(ExternalConnection(base_url='http://worker.test/v1'))
            adapter.state = "ready"
        monkeypatch.setattr(LlamaServerAdapter, "_start", start)
        profiles = ModelProfileStore()
        manager = ModelManager(profiles, ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        first = profiles.create(ModelProfile(name='first', alias='first', kind='llm', model_ref='llms/fixture.gguf', capabilities={'streaming': True}, parameters={'temperature': 0.4}, source={'type': 'local', 'execution_options': {'device': 'cpu'}}))
        alias = profiles.create(ModelProfile(name='alias', alias='alias', kind='llm', model_ref=first.model_ref, capabilities={'streaming': True}, source={'type': 'local', 'execution_options': first.source.execution_options}))
        bad = alias.model_copy(update={"source": alias.source.model_copy(update={"execution_options": {**alias.source.execution_options, "threads": 8}})})
        with pytest.raises(ModelError, match="identical execution options"):
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
        job = RuntimeJob(version='fixture', operation='install', state='completed')
        job.log_path = job.id + ".log"
        RuntimeLog(service.logs / job.log_path, tmp_path).write(str(index))
        service.store.save_job(job)
    service._prune_logs(cache=False)
    assert len(list(service.logs.glob("*.log"))) == 20


def test_python_installer_uses_pinned_artifact_and_offline_checks_without_models(tmp_path, monkeypatch):
    import tarfile
    async def scenario():
        service = supervisor(tmp_path)
        service.release = catalog("windows", "x86_64")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo("python/python.exe")
            info.size = 7
            archive.addfile(info, io.BytesIO(b"fixture"))
        data = buffer.getvalue()
        service.release.python_artifact = RuntimeArtifact(url="https://runtime.test/python.tar.gz",
            sha256=hashlib.sha256(data).hexdigest(), archive_format="tar.gz")
        service.transport = httpx.MockTransport(lambda _: httpx.Response(200, content=data))
        calls = []
        async def command(args, env, cwd, log):
            calls.append((list(map(str, args)), dict(env)))
        service._command = command
        monkeypatch.setattr(service, "_uv", lambda: "bundled-uv")
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
        job = RuntimeJob(version=service.release.version, operation="install")
        await RuntimeSupervisor._install_python(service, service.release, tmp_path / "payload", job, RuntimeLog(tmp_path / "log", tmp_path))
        assert not (tmp_path / "data/models").exists()
        install = next(args for args, _ in calls if "sync" in args)
        assert "--require-hashes" in install and "--no-deps" not in install
        assert "--build-constraints" in install and "--find-links" in install
        assert set(install[install.index("--no-binary") + 1].split(",")) == {"docopt", "jieba", "unidic-lite", "antlr4-python3-runtime", "sox"}
        assert any(args[1:3] == ["pip", "check"] for args, _ in calls)
        commands = [args for args, _ in calls]
        python = str(tmp_path / "payload/env/python.exe")
        site_packages = str(tmp_path / "payload/env/Lib/site-packages")
        patch = [python, "-I", "-B", "-X", "utf8", str(service.worker_root / "patch_transformers.py")]
        compile_bytecode = [python, "-I", "-B", "-X", "utf8", "-m", "compileall", "-q", "-j", "4", "-o", "0",
            "--invalidation-mode", "timestamp", "-e", site_packages, site_packages]
        check_packages = next(args for args in commands if args[1:3] == ["pip", "check"])
        assert commands.count(patch) == commands.count(compile_bytecode) == 1
        assert commands.index(install) < commands.index(check_packages) < commands.index(patch) < commands.index(compile_bytecode)
        assert "--compile-bytecode" not in install
        checks = [(args, env) for args, env in calls if "require_offline" in " ".join(args)]
        assert len(checks) == 5
        assert all(commands.index(compile_bytecode) < commands.index(args) for args, _ in checks)
        assert all(env["CUDA_VISIBLE_DEVICES"] == "" and env["HF_HUB_OFFLINE"] == "1" for _, env in checks)
        assert ["ChatterboxTTS" in " ".join(args) for args, _ in checks].count(True) == 1
        assert ["Qwen3TTSModel" in " ".join(args) for args, _ in checks].count(True) == 1
        assert not (tmp_path / "payload/worker").exists()
        assert all(args[-1] == str(service.worker_root) for args, _ in checks)
        assert (tmp_path / "payload/env/python.exe").read_bytes() == b"fixture"
        assert not any("en_core_web_sm" in " ".join(args) for args, _ in calls)
        await service.close()
    asyncio.run(scenario())
