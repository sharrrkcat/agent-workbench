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
from ai_workbench.workers import tts_engine
from ai_workbench.workers.protocol import WorkerError
from tests.test_tts import HEADERS, PAYLOAD, api, model_tree, wav_bytes


def onnx_entry(system=None):
    return next(entry for entry in catalog(system, "x86_64") if entry.variant == "onnx-cpu")


@pytest.mark.parametrize("resource, code", [
    ("missing", "MODEL_NOT_FOUND"),
    ("corrupt", "RUNTIME_CHECKSUM_MISMATCH"),
    ("corrupt-lock", "RUNTIME_BROKEN"),
])
def test_onnx_install_rejects_missing_or_changed_resources_before_commands(tmp_path, resource, code):
    async def scenario():
        entry = onnx_entry()
        service = RuntimeSupervisor(tmp_path, RuntimeStore(), entries=[entry])
        service._uv = lambda: "fixture-uv"
        service._command = AsyncMock()
        if resource == "corrupt":
            wheel = tmp_path / "data/models/_auxiliary/en_core_web_sm/en_core_web_sm-any-py3-none-any.whl"
            wheel.parent.mkdir(parents=True)
            wheel.write_bytes(b"incorrect auxiliary wheel")
        elif resource == "corrupt-lock":
            entry.sha256 = "0" * 64
        job = RuntimeJob(runtime_id="python-worker", variant="onnx-cpu", version=entry.version, operation="install")
        try:
            with pytest.raises(ModelError) as error:
                await service._install_python(entry, tmp_path / "payload", job, RuntimeLog(tmp_path / "log", tmp_path))
            assert error.value.code == code
            service._command.assert_not_awaited()
        finally:
            await service.close()
    asyncio.run(scenario())


def test_onnx_install_uses_verified_local_wheel_and_bounded_source_builds(tmp_path, monkeypatch):
    from ai_workbench.core.models.runtimes import supervisor as implementation

    async def scenario():
        entry = onnx_entry()
        service = RuntimeSupervisor(tmp_path, RuntimeStore(), entries=[entry])
        service._uv = lambda: "fixture-uv"
        wheel = tmp_path / "data/models/_auxiliary/en_core_web_sm/en_core_web_sm-any-py3-none-any.whl"
        wheel.parent.mkdir(parents=True)
        wheel.write_bytes(b"verified local wheel fixture")
        digest = AsyncMock(return_value="86cc141f63942d4b2c5fcee06630fd6f904788d2f0ab005cce45aadb8fb73889")
        monkeypatch.setattr(implementation, "file_digest", digest)
        calls = []

        async def command(args, env, cwd, log):
            args = list(map(str, args))
            calls.append((args, dict(env)))
            if "venv" in args:
                Path(args[-1]).mkdir(parents=True)
            if "--no-index" in args:
                staged = Path(args[-1])
                assert staged.name == "en_core_web_sm-3.7.1-py3-none-any.whl"
                assert staged.read_bytes() == wheel.read_bytes()

        service._command = command
        job = RuntimeJob(runtime_id="python-worker", variant="onnx-cpu", version=entry.version, operation="install")
        try:
            await service._install_python(entry, tmp_path / "payload", job, RuntimeLog(tmp_path / "log", tmp_path))
            digest.assert_awaited_once_with(wheel)
            packages = next(args for args, _ in calls if "--require-hashes" in args)
            assert "--no-deps" in packages
            assert packages[packages.index("--only-binary") + 1] == ":all:"
            assert set(packages[packages.index("--no-binary") + 1].split(",")) == {"docopt", "jaconv", "jieba", "unidic-lite"}
            assert packages[packages.index("--build-constraints") + 1] == str(CATALOG_ROOT / entry.requirements)
            local = next(args for args, _ in calls if "--no-index" in args)
            assert "--no-deps" in local and not Path(local[-1]).exists()
            assert wheel.read_bytes() == b"verified local wheel fixture"
            assert calls[-1][1]["HF_HUB_OFFLINE"] == "1"
            assert (tmp_path / "payload/worker/tts_engine.py").is_file()
        finally:
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("system", ["windows", "linux"])
def test_onnx_locks_pin_the_cpu_stack_without_torch(system):
    lock = (CATALOG_ROOT / onnx_entry(system).requirements).read_text(encoding="utf-8")
    packages = {}
    current = None
    for line in lock.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            assert current and line.strip().startswith("--hash=sha256:")
            packages[current][1] += 1
        else:
            current, version = line.rstrip(" \\").split("==")
            packages[current] = [version, 0]
    assert all(hashes for _, hashes in packages.values())
    assert {name: packages[name][0] for name in ("onnxruntime", "numpy", "misaki", "spacy")} == {
        "onnxruntime": "1.23.2", "numpy": "1.26.4", "misaki": "0.9.4", "spacy": "3.7.5",
    }
    assert not {"torch", "torchvision", "transformers", "kokoro", "kokoro-onnx"} & packages.keys()


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
        adapter = PythonWorkerAdapter(SimpleNamespace(entry=lambda *args: onnx_entry()),
            SimpleNamespace(runtime_id="python-worker", runtime_variant="onnx-cpu"), lambda: None)
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
