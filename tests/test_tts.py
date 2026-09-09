import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import json
from pathlib import Path
import struct
import socket
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
import wave

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.adapters import PythonWorkerAdapter
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.schema import AudioOutput, ModelInput, SpeechRequest
from ai_workbench.workers.audio import validate_audio
from ai_workbench.workers.protocol import WorkerError, local_model, speech_request
from ai_workbench.workers.tts_catalog import MAX_AUDIO_BYTES, VOICE_BYTES, VOICE_IDS, valid_voice
from ai_workbench.workers.tts_engine import phoneme_chunks


def wav_bytes():
    stream = BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(struct.pack("<h", 1000) * 200)
    return stream.getvalue()


def model_tree(root):
    path = root / "data/models/tts/kokoro"
    (path / "voices").mkdir(parents=True)
    (path / "config.json").write_text(json.dumps({"model_type": "style_text_to_speech_2"}))
    for name in ("tokenizer.json", "tokenizer_config.json"):
        (path / name).write_text("{}")
    (path / "model.onnx").write_bytes(b"fixture")
    (path / "voices/af_heart.bin").write_bytes(struct.pack("<f", 0.5) * (VOICE_BYTES // 4))
    (path / "voices/af.bin").write_bytes(b"ignored")
    return path


@pytest.fixture
def api(tmp_path):
    path = model_tree(tmp_path)
    with TestClient(create_app(use_memory=True, root=tmp_path), client=("127.0.0.1", 40001)) as client:
        response = client.post("/api/models/profiles", json={"name": "Kokoro", "alias": "kokoro", "kind": "tts",
            "runtime_id": "python-worker", "runtime_variant": "onnx-cpu", "model_ref": "tts/kokoro", "external_enabled": True})
        assert response.status_code == 200, response.text
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"})
        yield client, response.json(), path


HEADERS = {"Authorization": "Bearer test-key"}
PAYLOAD = {"model": "kokoro", "input": "Hello", "voice": "af_heart"}


def test_voice_discovery_is_readonly_and_fixed(api):
    client, profile, path = api
    manager = client.app.state.runtime_state.model_manager
    manager.load = AsyncMock(side_effect=AssertionError("No model loading"))
    before = set(sys.modules)
    response = client.get("/v1/audio/voices?model=kokoro", headers=HEADERS)
    assert response.json() == {"object": "list", "data": [{"id": "af_heart", "model": "kokoro", "source": "preset", "language": "en-US", "expires_at": None}]}
    assert not {"torch", "onnxruntime", "spacy", "numpy"} & (set(sys.modules) - before)
    private = client.get(f"/api/models/profiles/{profile['id']}/voices").json()
    assert len(private) == len(VOICE_IDS) == 54
    assert sum(row["available"] for row in private) == 1
    assert client.get("/v1/audio/voices?source=temporary", headers=HEADERS).json()["data"] == []
    assert client.get("/v1/models", headers=HEADERS).json()["data"][0]["id"] == "kokoro"
    (path / "voices/af_heart.bin").unlink()
    assert client.get("/v1/audio/voices", headers=HEADERS).json()["data"] == []
    assert client.get("/v1/audio/voices").status_code == 401
    client.patch(f"/api/models/profiles/{profile['id']}", json={"external_enabled": False})
    assert client.get("/v1/audio/voices?model=kokoro", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("patch", [{"input": " "}, {"input": "a" * 4097}, {"voice": {"id": "x"}}, {"speed": 0.2},
    {"speed": 4.1}, {"speed": True}, {"response_format": "pcm"}, {"stream_format": "sse"}, {"instructions": "softly"},
    {"tts": {"reference_audio": {}}}, {"tts": {"language": "unknown"}}, {"unknown": True}])
def test_invalid_speech_is_rejected_before_inference(api, patch):
    client, _, _ = api
    manager = client.app.state.runtime_state.model_manager
    manager.speech = AsyncMock(side_effect=AssertionError("No inference"))
    response = client.post("/v1/audio/speech", headers=HEADERS, json={**PAYLOAD, **patch})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    manager.speech.assert_not_called()


def test_speech_binary_defaults_validation_and_statelessness(api):
    client, profile, _ = api
    manager = client.app.state.runtime_state.model_manager
    calls = []
    class Adapter:
        async def speech(self, *values):
            calls.append(values)
            return AudioOutput(data=wav_bytes(), response_format="wav")
    @asynccontextmanager
    async def lease(_profile):
        yield Adapter()
    manager._lease = lease
    client.patch(f"/api/models/profiles/{profile['id']}", json={"parameters": {"speed": 0.8, "response_format": "wav"}})
    response = client.post("/v1/audio/speech", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 200, response.text
    assert response.content == wav_bytes()
    assert response.headers["content-type"] == "audio/wav"
    assert int(response.headers["content-length"]) == len(response.content)
    assert response.headers["x-request-id"]
    assert calls[-1][3:5] == (0.8, "wav")
    client.post("/v1/audio/speech", headers=HEADERS, json={**PAYLOAD, "speed": 1.2})
    assert calls[-1][3] == 1.2
    assert client.app.state.runtime_state.runs.list_all_runs() == []
    assert client.post("/v1/audio/speech", headers=HEADERS, json={**PAYLOAD, "voice": "af"}).status_code == 404
    assert client.post("/v1/audio/speech", headers=HEADERS, json={**PAYLOAD, "tts": {"language": "zh-CN"}}).status_code == 400


def test_voice_validation_and_model_paths(tmp_path):
    path = model_tree(tmp_path)
    assert valid_voice(path, "af_heart")
    assert not valid_voice(path, "af")
    file = path / "voices/af_heart.bin"
    file.write_bytes(struct.pack("<f", float("nan")) * (VOICE_BYTES // 4))
    assert not valid_voice(path, "af_heart")
    file.write_bytes(b"short")
    assert not valid_voice(path, "af_heart")
    assert local_model(tmp_path / "data/models", "tts/kokoro", tts=True) == path
    with pytest.raises(WorkerError):
        local_model(tmp_path / "data/models", "../outside", tts=True)


def test_long_phonemes_are_complete_and_bounded():
    encode = lambda value: [0, *[ord(c) for c in value], 0]
    text = "word " * 350
    chunks = list(phoneme_chunks(text, encode))
    assert len(chunks) > 1
    assert all(len(chunk) <= 512 for chunk in chunks)
    assert "".join(chr(code) for chunk in chunks for code in chunk[1:-1]) == text
    assert list(phoneme_chunks("a", encode)) == [[0, 97, 0]]
    assert len(list(phoneme_chunks("a" * 510, encode))[0]) == 512
    with pytest.raises(WorkerError):
        list(phoneme_chunks("a" * 511, encode))


def test_tts_backend_and_catalog_constraints():
    values = dict(name="TTS", alias="tts", kind="tts", model_ref="tts/kokoro")
    assert ModelInput(**values).parameters == {"architecture": "kokoro", "speed": 1.0, "response_format": "mp3"}
    for binding in ({"provider_profile_id": "external"}, {"runtime_id": "python-worker", "runtime_variant": "torch-cpu"},
                    {"runtime_id": "python-worker", "runtime_variant": "onnx-gpu"},
                    {"runtime_id": "python-worker", "runtime_variant": "audio-cuda"}):
        with pytest.raises(ValidationError):
            ModelInput(**values, **binding)
    for system in ("windows", "linux"):
        entry = next(item for item in catalog(system, "x86_64") if item.variant == "onnx-cpu")
        assert entry.supported and entry.kinds == ["tts"]
    speech_request({"input": "Hello", "voice": "af_heart", "speed": 0.25, "response_format": "wav", "language": "en-US"})
    with pytest.raises(WorkerError):
        speech_request({"input": "Hello", "voice": "af_heart", "speed": True, "response_format": "wav", "language": None})


def test_binary_validation():
    validate_audio(wav_bytes(), "wav")
    with pytest.raises(ValueError):
        validate_audio(wav_bytes()[:-1], "wav")
    with pytest.raises(ValueError):
        validate_audio(b"x" * (MAX_AUDIO_BYTES + 1), "mp3")
    with pytest.raises(ValueError):
        validate_audio(b"not mp3", "mp3")


def test_worker_binary_transport_and_cancellation():
    async def scenario():
        entry = next(item for item in catalog() if item.variant == "onnx-cpu")
        adapter = PythonWorkerAdapter(SimpleNamespace(entry=lambda *args: entry),
            SimpleNamespace(runtime_id="python-worker", runtime_variant="onnx-cpu"), lambda: None)
        started = asyncio.Event()
        release = asyncio.Event()
        async def handle(request):
            if json.loads(request.content).get("input") == "slow":
                started.set()
                await release.wait()
            return httpx.Response(200, content=wav_bytes(), headers={"Content-Type": "audio/wav"})
        adapter.client = httpx.AsyncClient(base_url="http://worker.test", transport=httpx.MockTransport(handle))
        result = await adapter.speech(SimpleNamespace(id="id"), "hello", "af_heart", 1, "wav", None)
        assert result.data == wav_bytes()
        adapter._stop = AsyncMock()
        task = asyncio.create_task(adapter.speech(SimpleNamespace(id="id"), "slow", "af_heart", 1, "wav", None))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        adapter._stop.assert_awaited_once()
        await adapter.client.aclose()
    asyncio.run(scenario())


def test_real_http_disconnect_cancels_speech_before_lease_release(tmp_path):
    from urllib.parse import urlsplit
    from tests.test_phase2a_transport import serve, wait_until
    model_tree(tmp_path)
    app = create_app(use_memory=True, root=tmp_path)
    manager = app.state.runtime_state.model_manager
    started, cancelled, released = threading.Event(), threading.Event(), threading.Event()
    class Adapter:
        async def speech(self, *args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    @asynccontextmanager
    async def lease(profile):
        try:
            yield Adapter()
        finally:
            assert cancelled.is_set()
            released.set()
    manager._lease = lease
    with serve(app) as base:
        with httpx.Client(base_url=base) as client:
            client.patch('/api/models/settings', json={"external_enabled": True, "external_api_key": "test-key"}).raise_for_status()
            client.post('/api/models/profiles', json={"name": "Kokoro", "alias": "kokoro", "kind": "tts", "model_ref": "tts/kokoro",
                "runtime_id": "python-worker", "runtime_variant": "onnx-cpu", "external_enabled": True}).raise_for_status()
        body = json.dumps(PAYLOAD).encode()
        with socket.create_connection(('127.0.0.1', urlsplit(base).port), timeout=5) as connection:
            connection.sendall((f'POST /v1/audio/speech HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer test-key\r\n'
                f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body)
            assert started.wait(5)
        assert released.wait(5)
        log = tmp_path / "data/logs/inference/inference.jsonl"
        wait_until(lambda: log.exists() and "REQUEST_CANCELLED" in log.read_text())
        record = json.loads(log.read_text().splitlines()[-1])
        assert record["status_code"] == 499 and record["error_code"] == "REQUEST_CANCELLED"


def test_tts_migration_preserves_profiles_and_files(tmp_path):
    from ai_workbench.db import migrations
    from ai_workbench.db.database import get_engine
    from ai_workbench.core.models.store import ModelProfileStore
    from ai_workbench.core.models.schema import ModelProfile
    engine = get_engine(f'sqlite:///{tmp_path / "migration.db"}')
    migrations.upgrade(engine, migrations.RUNTIME_MAINTENANCE_REVISION)
    store = ModelProfileStore(engine)
    original = store.create(ModelProfile(name="Existing", alias="existing", kind="llm", model_ref="existing"))
    original = store.get(original.id)
    file = tmp_path / 'protected.bin'
    file.write_bytes(b'preserved')
    before = file.stat().st_mtime_ns
    migrations.upgrade(engine)
    assert store.get(original.id) == original
    tts = store.create(ModelProfile(name="TTS", alias="tts", kind="tts", model_ref="tts/kokoro"))
    tts = store.get(tts.id)
    migrations.upgrade(engine)
    assert store.get(tts.id) == tts
    assert file.read_bytes() == b'preserved' and file.stat().st_mtime_ns == before
    engine.dispose()
