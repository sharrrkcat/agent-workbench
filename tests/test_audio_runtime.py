import asyncio
import base64
import csv
from email.parser import BytesParser
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
import venv
import zipfile

import httpx
import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.catalog import CATALOG_ROOT, catalog, worker_digest
from ai_workbench.core.models.runtimes.process import RuntimeLog
from ai_workbench.core.models.runtimes.schema import RuntimeJob
from ai_workbench.core.models.schema import SpeechRequest
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.core.models.voice_references import credential_id
from ai_workbench.workers import audio_engine
from ai_workbench.workers.audio_catalog import CHATTERBOX_FILES, audio_model, reference_path
from ai_workbench.workers.audio_server import AudioWorker
from ai_workbench.workers.common import WorkerError
from scripts.build_audio_wheel import VERSION, patched_wheel
from tests.test_audio import profile
from tests.test_phase2b_runtime import supervisor
from tests.test_tts import wav_bytes


def test_audio_catalog_lock_and_patched_artifact_are_auditable(tmp_path):
    entries = {entry.variant: entry for entry in catalog("windows", "x86_64")}
    entry = entries["audio-cuda"]
    assert entry.supported and entry.python_version == "3.12.11" and entry.kinds == ["tts"]
    assert entry.python_artifact.sha256 and entry.worker_entrypoint == "audio_server.py"
    assert entry.pytorch_index_url == "https://download.pytorch.org/whl/cu124"
    assert not next(e for e in catalog("linux", "x86_64") if e.variant == "audio-cuda").supported
    assert not set(entries["onnx-cpu"].worker_files) & {"audio_catalog.py", "audio_engine.py", "audio_server.py"}
    for name in entry.worker_files:
        (tmp_path / name).write_text(name)
    digest = worker_digest(entry.worker_files, tmp_path)
    (tmp_path / "transformers_engine.py").write_text("unrelated")
    assert worker_digest(entry.worker_files, tmp_path) == digest
    (tmp_path / "audio_engine.py").write_text("changed")
    assert worker_digest(entry.worker_files, tmp_path) != digest
    lock = (CATALOG_ROOT / entry.requirements).read_text(encoding="utf-8")
    packages, current = {}, None
    for line in lock.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            assert current and line.strip().startswith("--hash=sha256:")
            packages[current][1].append(line.strip().removeprefix("--hash=sha256:").rstrip(" \\"))
        else:
            current, version = line.rstrip(" \\").split("==")
            packages[current] = (version, [])
    expected = {"torch": "2.6.0+cu124", "torchaudio": "2.6.0+cu124", "transformers": "4.57.3", "numpy": "1.26.4",
                "chatterbox-tts": VERSION, "qwen-tts": "0.1.1"}
    assert {name: packages[name][0] for name in expected} == expected
    assert all(hashes and all(len(value) == 64 for value in hashes) for _, hashes in packages.values())
    assert {"conformer", "diffusers", "omegaconf", "pykakasi", "resemble-perth", "s3tokenizer", "spacy-pkuseg",
            "pyloudnorm", "librosa", "soundfile", "onnxruntime", "setuptools", "wheel"} <= packages.keys()
    wheel = CATALOG_ROOT / "wheels" / f"chatterbox_tts-{VERSION}-py3-none-any.whl"
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in packages["chatterbox-tts"][1]
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"chatterbox_tts-{VERSION}.dist-info/METADATA"))
        assert metadata["Version"] == VERSION
        assert "transformers==4.57.3" in metadata.get_all("Requires-Dist")
        patch = json.loads(archive.read(f"chatterbox_tts-{VERSION}.dist-info/WORKBENCH_PATCH.json"))
        assert patch["upstream_sha256"] and not patch["source_changes"]
        record = archive.read(f"chatterbox_tts-{VERSION}.dist-info/RECORD").decode()
        for name, digest, size in csv.reader(StringIO(record)):
            if not digest:
                continue
            data = archive.read(name)
            assert len(data) == int(size)
            assert digest == "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
    with pytest.raises(ValueError, match="checksum"):
        patched_wheel(b"unverified input")


def test_audio_installer_checks_dependencies_and_offline_imports(tmp_path, monkeypatch):
    async def scenario():
        service = supervisor(tmp_path)
        service.entries = catalog("windows", "x86_64")
        entry = service.entry("python-worker", "audio-cuda")
        calls = []

        async def command(args, env, cwd, log):
            args = list(map(str, args))
            calls.append((args, dict(env)))
            if "venv" in args:
                Path(args[-1]).mkdir(parents=True)

        service._command = command
        monkeypatch.setattr(service, "_uv", lambda: "bundled-uv")
        job = RuntimeJob(runtime_id="python-worker", variant="audio-cuda", version=entry.version, operation="install")
        await service._install_python(entry, tmp_path / "payload", job, RuntimeLog(tmp_path / "log", tmp_path))
        assert len(calls) == 5
        install = calls[2][0]
        assert "--require-hashes" in install and install[install.index("--only-binary") + 1] == ":all:"
        assert set(install[install.index("--no-binary") + 1].split(",")) == {"antlr4-python3-runtime", "sox"}
        assert install[install.index("--find-links") + 1] == str(CATALOG_ROOT / "wheels")
        assert install[install.index("--build-constraints") + 1] == str(CATALOG_ROOT / entry.requirements)
        assert calls[3][0][1:3] == ["pip", "check"]
        assert calls[4][1]["HF_HUB_OFFLINE"] == calls[4][1]["TRANSFORMERS_OFFLINE"] == "1"
        assert all(name in calls[4][0][-2] for name in ("require_offline", "ChatterboxTTS", "Qwen3TTSModel", "WhisperProcessor"))
        assert set(path.name for path in (tmp_path / "payload/worker").iterdir()) == set(entry.worker_files)
        await service.close()
    asyncio.run(scenario())


def fake_decoder(monkeypatch, frames, *, rate=16000, file_format="WAV", finite=True):
    monkeypatch.setattr(audio_engine, "require_offline", lambda: None)

    class Block:
        def __init__(self, size):
            self.size = size

        def __len__(self):
            return self.size

        def mean(self, **kwargs):
            return [0] * self.size

    class Source:
        channels, samplerate, format = 1, rate, file_format
        # Misleading metadata must never override the count of decoded frames.
        frames = 1
        remaining = frames

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, count, **kwargs):
            count = min(count, self.remaining)
            self.remaining -= count
            return Block(count)

    source = Source()
    source.remaining = frames
    numpy = SimpleNamespace(float32="float32", isfinite=lambda _: SimpleNamespace(all=lambda: finite),
        concatenate=lambda values: sum(values, []))
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(SoundFile=lambda _: source))
    return source


@pytest.mark.parametrize("frames,success", [(29 * 16000, True), (30 * 16000, True), (30 * 16000 + 1, False)])
def test_whisper_duration_guard_counts_decoded_samples_before_features(monkeypatch, frames, success):
    fake_decoder(monkeypatch, frames)
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace())
    from contextlib import nullcontext
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    engine = audio_engine.WhisperEngine.__new__(audio_engine.WhisperEngine)
    engine.device, engine.dtype = "cpu", "float32"
    engine.processor, engine.model = MagicMock(), MagicMock()
    engine.processor.batch_decode.return_value = ["complete transcript"]
    if success:
        assert engine.transcribe(Path("reference.wav")) == {"text": "complete transcript"}
        assert len(engine.processor.call_args.args[0]) == frames
        engine.model.generate.assert_called_once()
    else:
        with pytest.raises(WorkerError) as rejected:
            engine.transcribe(Path("reference.wav"))
        assert rejected.value.code == "AUDIO_TOO_LONG"
        engine.processor.assert_not_called()
        engine.model.generate.assert_not_called()


@pytest.mark.parametrize("frames,kwargs,path", [(0, {}, "reference.wav"), (1, {"file_format": "FLAC"}, "reference.wav"),
    (1, {"rate": 4000}, "reference.wav"), (1, {"finite": False}, "reference.wav"),
    (1, {}, "reference.mp3")])
def test_reference_decoder_rejects_invalid_format_empty_and_nonfinite(monkeypatch, frames, kwargs, path):
    fake_decoder(monkeypatch, frames, **kwargs)
    with pytest.raises(WorkerError) as rejected:
        audio_engine.decode_audio(Path(path))
    assert rejected.value.code == "INVALID_AUDIO"


def test_device_selection_never_falls_back_to_cpu(monkeypatch):
    torch = MagicMock()
    torch.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", torch)
    with pytest.raises(WorkerError) as error:
        audio_engine.device_for({"device": "cuda", "intraop_threads": 2})
    assert error.value.code == "RUNTIME_DEVICE_UNAVAILABLE"
    torch.empty.assert_not_called()
    assert audio_engine.device_for({"device": "cpu", "intraop_threads": 2}) == ("cpu", "CPU")


def test_network_is_blocked_and_api_schema_imports_no_heavy_engines(tmp_path):
    code = """
import socket
from ai_workbench.workers.audio_engine import require_offline
require_offline()
for call in (lambda: socket.getaddrinfo('example.test', 443), lambda: socket.socket().connect(('127.0.0.1', 1))):
    try: call()
    except RuntimeError: pass
    else: raise AssertionError('Network access was permitted')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    code = """
import sys
from ai_workbench.api.main import create_app
create_app(use_memory=True, root=sys.argv[1]).openapi()
assert not {'torch', 'torchaudio', 'transformers', 'onnxruntime', 'chatterbox', 'qwen_tts'} & set(sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_private_worker_rejects_unsupported_engines_and_fields_before_loading(tmp_path):
    factory = MagicMock(side_effect=AssertionError("No engine loading"))
    worker = AudioWorker(tmp_path, tmp_path, engine_factory=factory)
    body = {"profile_id": "test", "kind": "tts", "model_ref": "tts/chatterbox", "parameters": {"architecture": "chatterbox"},
            "options": {"device": "cpu", "intraop_threads": 4}}
    for patch in ({"extra": True}, {"model_ref": "../outside"}, {"parameters": {"architecture": "whisper"}},
                  {"parameters": {"architecture": "chatterbox", "temperature": 0}}, {"options": {"device": "auto", "intraop_threads": 4}}):
        with pytest.raises(WorkerError):
            worker.dispatch("/load", {**body, **patch})
    assert worker.health()["loaded"] == []
    factory.assert_not_called()
    with pytest.raises(WorkerError):
        reference_path(tmp_path, "../voice.wav")


FAKE_AUDIO = '''
import io
import os
import struct
import time
import wave
def decode_audio(path):
    with wave.open(str(path), 'rb') as source:
        return [0] * source.getnframes(), source.getframerate()
class ChatterboxEngine:
    device = 'cpu'
    device_name = 'CPU'
    dtype = 'torch.float32'
    def __init__(self, path, options): pass
    def speech(self, text, reference, speed, response_format, model_options):
        if text == 'wait': time.sleep(60)
        if text == 'crash': os._exit(7)
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as source:
            source.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            source.writeframes(struct.pack('<h', 1000) * 200)
        return stream.getvalue(), 'audio/wav'
QwenTTSEngine = WhisperEngine = ChatterboxEngine
'''


def test_real_audio_processes_have_separate_queues_cancellation_and_crash_scope(tmp_path):
    async def scenario():
        service = supervisor(tmp_path)
        entry = next(item for item in catalog("windows", "x86_64") if item.variant == "audio-cuda").model_copy(update={"version": "fixture"})
        service.entries = [entry]

        async def install(entry, target, job, log):
            await asyncio.to_thread(venv.EnvBuilder(with_pip=False, symlinks=False).create, target)
            source = Path(__file__).parents[1] / "ai_workbench/workers"
            shutil.copytree(source, target / "worker", ignore=shutil.ignore_patterns("__pycache__"))
            (target / "worker/audio_engine.py").write_text(FAKE_AUDIO, encoding="utf-8")

        service._install_python = install
        await service.submit("python-worker", "audio-cuda", "install")
        await service.task
        assert service.installation("python-worker", "audio-cuda").state == "installed"
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        manager.settings.patch({"external_enabled": True, "external_api_key": "test-key"})
        path = tmp_path / "data/models/tts/chatterbox"
        path.mkdir(parents=True)
        for name in CHATTERBOX_FILES:
            (path / name).write_bytes(b"fixture")
        assert audio_model(tmp_path / "data/models", "tts/chatterbox", "chatterbox") == path
        first = manager.profiles.create(profile(runtime_options={"device": "cpu"}))
        second = manager.profiles.create(profile(alias="second", runtime_options={"device": "cpu"}))
        try:
            voices = [await manager.create_voice_reference(value.id, wav_bytes(), "wav", credential_id("test-key")) for value in (first, second)]
            for value in (first, second):
                await manager.load(value.id)
            left, right = [manager._slots[manager.backend_key(value)].adapter for value in (first, second)]
            assert left.process.process.pid != right.process.process.pid
            right_process = right.process
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.get(str(left.client.base_url) + "/health")).status_code == 401
            request = SpeechRequest(model=first.alias, input="wait", voice=voices[0]["voice_id"], response_format="wav")
            pending = asyncio.create_task(manager.speech(first.id, request))
            while not manager.status(first.id).active:
                await asyncio.sleep(0.01)
            with pytest.raises(ModelError) as busy:
                await service.submit("python-worker", "audio-cuda", "uninstall")
            assert busy.value.code == "MODEL_BUSY"
            old_process = left.process
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert old_process.process.returncode is not None and manager.status(first.id).active == 0
            assert right.process is right_process and right.process.process.returncode is None
            assert (await manager.speech(second.id, request.model_copy(update={"input": "hello", "voice": voices[1]["voice_id"]}))).data == wav_bytes()
            await manager.load(first.id)
            with pytest.raises(ModelError):
                await manager.speech(first.id, request.model_copy(update={"input": "crash"}))
            with pytest.raises(ModelError):
                await manager.speech(first.id, request.model_copy(update={"input": "hello"}))
            assert right.process is right_process and right.process.process.returncode is None
            await manager.load(first.id)
            await manager.unload(first.id)
            assert left.process is None and right.process is right_process
            await manager.invalidate_runtime("python-worker", "audio-cuda")
            assert right.process is None and right_process.process.returncode is not None
        finally:
            await manager.close()
            await service.close()
        assert not list((service.base / ".processes").iterdir())
    asyncio.run(scenario())
