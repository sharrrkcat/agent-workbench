import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.adapters import PythonWorkerAdapter
from ai_workbench.core.models.runtimes.catalog import CATALOG_ROOT, catalog
from ai_workbench.core.models.runtimes.process import RuntimeLog
from ai_workbench.core.models.runtimes.schema import RuntimeJob
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.workers import tts_engine
from ai_workbench.workers.protocol import WorkerError
from tests.test_tts import HEADERS, PAYLOAD, api, model_tree, wav_bytes


def inference_spy(tmp_path):
    engine = tts_engine.TTSEngine.__new__(tts_engine.TTSEngine)
    engine.path = model_tree(tmp_path)
    engine.voices = {"af_heart": [object() for _ in range(510)]}
    engine.processors = {"a": lambda text: (text, None)}
    engine.tokenizer = SimpleNamespace(encode=lambda text, **kwargs: SimpleNamespace(ids=[ord(c) for c in text]))
    engine.np = MagicMock()
    engine.np.asarray.side_effect = lambda values, dtype: SimpleNamespace(values=values, dtype=dtype)
    engine.np.isfinite.return_value.all.return_value = True
    engine.np.clip.return_value.__mul__.return_value.astype.return_value.tobytes.return_value = b"\x01\x00" * 4
    engine.model = MagicMock()
    engine.model.run.return_value = [MagicMock(ndim=2, shape=(1, 4), size=4)]
    engine.lameenc = MagicMock()
    engine.lameenc.Encoder.return_value.encode.return_value = b"x" * 20
    engine.lameenc.Encoder.return_value.flush.return_value = b""
    return engine


@pytest.mark.parametrize("length", [1, 510])
def test_engine_pads_tokens_selects_unpadded_voice_row_and_preserves_fractional_speed(tmp_path, length):
    engine = inference_spy(tmp_path)
    data, mime = engine.speech("a" * length, "af_heart", 0.85, "wav", "en-US")
    assert mime == "audio/wav" and len(data) == 52
    feeds = engine.model.run.call_args.args[1]
    assert feeds["input_ids"].values == [[0, *([97] * length), 0]]
    assert feeds["input_ids"].dtype is engine.np.int64
    assert feeds["style"] is engine.voices["af_heart"][length - 1]
    assert feeds["speed"].values == [0.85] and feeds["speed"].dtype is engine.np.float32


@pytest.mark.parametrize("text, limit, response_format", [("a. a.", 12, "wav"), ("a", 51, "wav"), ("a", 12, "mp3")])
def test_engine_bounds_accumulated_pcm_and_encoded_audio(tmp_path, monkeypatch, text, limit, response_format):
    engine = inference_spy(tmp_path)
    monkeypatch.setattr(tts_engine, "MAX_AUDIO_BYTES", limit)
    with pytest.raises(WorkerError) as error:
        engine.speech(text, "af_heart", 1, response_format, None)
    assert (error.value.code, error.value.status) == ("AUDIO_TOO_LARGE", 413)


def test_engine_rejects_nonfinite_waveforms(tmp_path):
    engine = inference_spy(tmp_path)
    engine.np.isfinite.return_value.all.return_value = False
    with pytest.raises(WorkerError) as error:
        engine.speech("a", "af_heart", 1, "wav", None)
    assert error.value.code == "MODEL_UNAVAILABLE"
    engine.np.clip.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "bad-mime", "truncated", "large", "error-list", "error-value", "error-code"])
def test_worker_audio_failures_stop_execution_and_sanitize_errors(monkeypatch, failure):
    from ai_workbench.core.models.runtimes import adapters

    async def scenario():
        adapter = PythonWorkerAdapter(SimpleNamespace(release=catalog("windows", "x86_64")),
            ModelProfile(name="speech", alias="speech", kind="tts", model_ref="tts/kokoro", backend_profile_id="local"), lambda: None)
        adapter._stop = AsyncMock()

        async def handle(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("private worker detail", request=request)
            if failure.startswith("error-"):
                value = {"error-list": [], "error-value": {"error": "private worker detail"},
                         "error-code": {"error": {"code": ["private worker detail"]}}}[failure]
                return httpx.Response(503, json=value)
            data = wav_bytes()[:-1] if failure == "truncated" else wav_bytes()
            return httpx.Response(200, content=data, headers={"Content-Type": "text/plain" if failure == "bad-mime" else "audio/wav"})

        if failure == "large":
            monkeypatch.setattr(adapters, "MAX_AUDIO_BYTES", len(wav_bytes()) - 1)
        adapter.client = httpx.AsyncClient(base_url="http://worker.test", transport=httpx.MockTransport(handle))
        try:
            with pytest.raises(ModelError) as error:
                await adapter.speech(SimpleNamespace(id="id"), "hello", "af_heart", 1, "wav", None)
            assert error.value.code == ("MODEL_TIMEOUT" if failure == "timeout" else "MODEL_UNAVAILABLE")
            assert "private worker detail" not in str(error.value.payload())
            adapter._stop.assert_awaited_once()
        finally:
            await adapter.client.aclose()
    asyncio.run(scenario())


def test_speech_rejects_escaped_model_and_voice_directories(api, tmp_path):
    from tests.test_runtime_maintenance import link_directory
    client, profile, path = api
    manager = client.app.state.runtime_state.model_manager
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "af_heart.bin").write_bytes((path / "voices/af_heart.bin").read_bytes())
    linked_model = path.parent / "voice-escape"
    linked_model.mkdir()
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "model.onnx"):
        (linked_model / name).write_bytes((path / name).read_bytes())
    link_directory(linked_model / "voices", outside)
    manager.profiles.update(profile["id"], {"model_ref": "tts/voice-escape"})
    assert not any(voice["available"] for voice in client.get(f"/api/models/profiles/{profile['id']}/voices").json())
    assert client.post("/v1/audio/speech", headers=HEADERS, json=PAYLOAD).status_code == 404
    link_directory(path.parent / "escaped-model", outside)
    manager.profiles.update(profile["id"], {"model_ref": "tts/escaped-model"})
    response = client.post("/v1/audio/speech", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


def test_invalid_audio_remains_json_before_success_headers(api):
    from ai_workbench.core.models.schema import AudioOutput
    client, _, _ = api
    manager = client.app.state.runtime_state.model_manager

    @asynccontextmanager
    async def lease(_profile):
        yield SimpleNamespace(speech=AsyncMock(return_value=AudioOutput(data=b"private worker detail", response_format="mp3")))

    manager._lease = lease
    response = client.post("/v1/audio/speech", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 502 and response.headers["content-type"] == "application/json"
    assert response.headers["x-request-id"]
    assert response.json()["error"]["code"] == "PROVIDER_PROTOCOL_ERROR"
    assert "private worker detail" not in response.text
