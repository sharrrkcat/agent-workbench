import asyncio
import base64
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.manager import ProviderSlot
from ai_workbench.core.models.schema import ModelProfile, Qwen3TTSParameters, SpeechRequest
from ai_workbench.core.models.voice_references import VoiceReferences, credential_id
from ai_workbench.workers.audio_catalog import QWEN3TTS_DEFAULTS, QWEN3TTS_LANGUAGES, QWEN3TTS_SUBTALKER, audio_model, qwen3tts_files
from ai_workbench.workers.audio_engine import QwenTTSEngine
from ai_workbench.workers.audio_server import AudioWorker
from ai_workbench.workers.common import WorkerError
from tests.audio_fixtures import qwen_model
from tests.test_audio import Adapter, Clock, api, make_manager
from tests.test_openapi import validate_response
from tests.test_tts import HEADERS, wav_bytes


def qwen_profile(**values):
    return ModelProfile(**{**dict(name="Qwen", alias="qwen", kind="tts", model_ref="tts/qwen",
        runtime_id="python-worker", runtime_variant="audio-cuda", external_enabled=True,
        parameters={"architecture": "qwen3tts", "response_format": "wav"}), **values})


@pytest.fixture
def qwen_api(api, tmp_path):
    client, manager, _, _ = api
    qwen_model(tmp_path / "data/models/tts/qwen")
    response = client.post("/api/models/profiles", json=qwen_profile().model_dump(exclude={"id", "created_at", "updated_at"}))
    assert response.status_code == 200, response.text
    profile = manager.profiles.get(response.json()["id"])
    adapter = Adapter(manager)
    manager._slots[manager.backend_key(profile)] = ProviderSlot(adapter, asyncio.Semaphore(1))
    return client, manager, profile, adapter


def upload(client, transcript=None, alias="qwen"):
    return client.post("/v1/audio/voice-references", headers=HEADERS,
        data={"model": alias, **({"reference_text": transcript} if transcript is not None else {})},
        files={"file": ("reference.wav", wav_bytes())})


def inline(transcript=None):
    return {"format": "wav", "data_base64": base64.b64encode(wav_bytes()).decode(),
            **({"reference_text": transcript} if transcript is not None else {})}


@pytest.mark.parametrize("options", [
    {"do_sample": 1}, {"temperature": 0}, {"temperature": True}, {"temperature": float("nan")},
    {"top_p": 0}, {"top_p": 1.01}, {"top_k": -1}, {"top_k": 1.5}, {"top_k": True},
    {"repetition_penalty": 0}, {"repetition_penalty": float("inf")}, {"max_new_tokens": 0},
    {"max_new_tokens": 8193}, {"max_new_tokens": True}, {"exaggeration": None},
    {"cfg_weight": 0.5}, {"subtalker_temperature": 0.5}, {"reference_text": "transcript"},
])
def test_strict_qwen_profile_options(options):
    with pytest.raises(ValidationError):
        qwen_profile(parameters={"architecture": "qwen3tts", **options})


def test_qwen_defaults_and_binding():
    profile = qwen_profile()
    assert profile.parameters == {"architecture": "qwen3tts", "speed": 1, "response_format": "wav", **QWEN3TTS_DEFAULTS}
    assert profile.runtime_options == {"device": "cuda", "intraop_threads": 4}
    assert profile.lifecycle.unload == "manual"
    assert Qwen3TTSParameters(top_k=0, repetition_penalty=0.5, temperature=6, max_new_tokens=8192).top_k == 0
    for patch in ({"runtime_variant": "onnx-cpu"}, {"provider_profile_id": "external"},
                  {"parameters": {"architecture": "custom_voice"}}, {"parameters": {"architecture": "voice_design"}}):
        with pytest.raises(ValidationError):
            qwen_profile(**patch)


def test_qwen_inventory_requires_complete_base_and_ignores_nested_tokenizer(tmp_path):
    root = tmp_path / "data/models"
    path = qwen_model(root / "tts/qwen")
    qwen_model(root / "tts/custom")
    (root / "tts/custom/config.json").write_text(json.dumps({"model_type": "qwen3_tts", "tts_model_type": "custom_voice"}))
    qwen_model(root / "tts/missing-tokenizer")
    (root / "tts/missing-tokenizer/speech_tokenizer/model.safetensors").unlink()
    assert [item["model_ref"] for item in inventory(tmp_path, "tts")] == ["tts/qwen"]
    assert audio_model(root, "tts/qwen", "qwen3tts") == path
    with pytest.raises(WorkerError) as unsupported:
        audio_model(root, "tts/custom", "qwen3tts")
    assert unsupported.value.code == "UNSUPPORTED_CAPABILITY"
    for name in ("generation_config.json", "merges.txt", "speech_tokenizer/preprocessor_config.json", "model.safetensors"):
        saved = (path / name).read_bytes()
        (path / name).write_bytes(b"")
        assert not qwen3tts_files(path)
        (path / name).write_bytes(saved)
    index = path / "model.safetensors.index.json"
    index.write_text(json.dumps({"weight_map": {"layer": "../other.safetensors"}}))
    assert not qwen3tts_files(path)
    index.write_text(json.dumps({"weight_map": {"layer": "model.safetensors"}}))
    assert qwen3tts_files(path)


@pytest.mark.parametrize("source", ["temporary", "inline"])
@pytest.mark.parametrize("transcript", [None, "The reference says hello."])
def test_qwen_cloning_sources_forward_transcripts_and_overrides(qwen_api, source, transcript):
    client, manager, profile, adapter = qwen_api
    tts = {"language": "zh-CN", "model_options": {"do_sample": False, "top_k": 0, "max_new_tokens": 128}}
    payload = {"model": profile.alias, "input": "你好，世界。" * 60, "speed": 0.8, "tts": tts}
    if source == "temporary":
        created = upload(client, transcript)
        assert created.status_code == 200, created.text
        payload["voice"] = created.json()["voice_id"]
        entry = manager.voice_references._entries[payload["voice"]]
        assert entry.reference_text == transcript
        listed = client.get("/v1/audio/voices?model=qwen", headers=HEADERS)
        assert listed.json()["data"][0]["language"] is None
        assert "reference_text" not in listed.text and "reference_text" not in created.text
        assert client.get("/v1/audio/voices?model=qwen&source=preset", headers=HEADERS).json()["data"] == []
        validate_response(client.get("/openapi.json").json(), "/v1/audio/voices", "get", listed)
    else:
        tts["reference_audio"] = inline(transcript)
    result = client.post("/v1/audio/speech", headers=HEADERS, json=payload)
    assert result.status_code == 200 and result.content == wav_bytes(), result.text
    args, kwargs = adapter.calls[-1]
    assert args[1] == payload["input"] and args[3:6] == (0.8, "wav", "zh-CN")
    assert kwargs["reference_text"] == transcript
    assert kwargs["model_options"] == {**QWEN3TTS_DEFAULTS, **tts["model_options"]}
    if source == "temporary":
        assert entry.active == 0 and entry.path.exists()
        assert client.delete(f"/v1/audio/voice-references/{entry.id}", headers=HEADERS).status_code == 200
    assert not list(manager.voice_references.base.iterdir())


@pytest.mark.parametrize("tts", [
    {"language": "hi-IN"}, {"model_options": {"cfg_weight": 0.5}}, {"model_options": {"exaggeration": None}},
    {"model_options": {"top_k": True}}, {"model_options": {"max_new_tokens": 8193}},
    {"model_options": {"subtalker_top_k": 0}},
])
def test_invalid_qwen_request_does_not_enter_queue_or_renew(qwen_api, monkeypatch, tts):
    client, manager, _, adapter = qwen_api
    identifier = upload(client).json()["voice_id"]
    entry = manager.voice_references._entries[identifier]
    expiry = entry.expires_at
    manager.voice_references.clock = lambda: expiry - timedelta(minutes=5)
    monkeypatch.setattr(manager, "_lease", MagicMock(side_effect=AssertionError("Unexpected queue admission")))
    result = client.post("/v1/audio/speech", headers=HEADERS,
        json={"model": "qwen", "input": "Hello", "voice": identifier, "tts": tts})
    assert result.status_code == 400, result.text
    assert entry.expires_at == expiry and entry.active == 0 and not adapter.calls


@pytest.mark.parametrize("transcript", ["", "   ", "x" * 4097])
def test_invalid_transcripts_do_not_stage_files(qwen_api, monkeypatch, transcript):
    client, manager, _, _ = qwen_api
    monkeypatch.setattr(manager, "_stage_reference", MagicMock(side_effect=AssertionError("Unexpected staging")))
    assert upload(client, transcript).status_code == 400
    result = client.post("/v1/audio/speech", headers=HEADERS,
        json={"model": "qwen", "input": "Hello", "tts": {"reference_audio": inline(transcript)}})
    assert result.status_code == 400, result.text


def test_qwen_fields_rejected_by_chatterbox_and_voices_are_profile_bound(qwen_api):
    client, _, _, _ = qwen_api
    assert upload(client, "transcript", "chatterbox").status_code == 400
    identifier = upload(client).json()["voice_id"]
    for tts, voice in (({}, identifier), ({"model_options": {"top_k": None}}, identifier),
                       ({"reference_audio": inline("transcript")}, None)):
        result = client.post("/v1/audio/speech", headers=HEADERS,
            json={"model": "chatterbox", "input": "Hello", "tts": tts, **({"voice": voice} if voice else {})})
        assert result.status_code == (404 if not tts else 400), result.text
    duplicate = client.post("/v1/audio/voice-references", headers=HEADERS,
        files=[("model", (None, "qwen")), ("reference_text", (None, "one")),
               ("reference_text", (None, "two")), ("file", ("voice.wav", wav_bytes()))])
    assert duplicate.status_code == 400


@pytest.mark.parametrize("language,expected", [(None, "Auto"), *QWEN3TTS_LANGUAGES.items()])
@pytest.mark.parametrize("transcript", [None, "Reference text"])
def test_qwen_engine_uses_decoded_audio_full_text_and_language(monkeypatch, language, expected, transcript):
    import ai_workbench.workers.audio_engine as module
    decoded = ([0.1, 0.2], 16000)
    monkeypatch.setattr(module, "decode_audio", lambda _: decoded)
    encoded = MagicMock(return_value=(b"encoded", "audio/wav"))
    monkeypatch.setattr(module, "encode_waveform", encoded)
    engine = QwenTTSEngine.__new__(QwenTTSEngine)
    generate = MagicMock(return_value=([[0.2, 0.3]], 24000))
    engine.model = SimpleNamespace(generate_voice_clone=generate)
    text = "没有空格的长文本。" * 100
    result = engine.speech(text, "reference.wav", 0.8, "wav", {"max_new_tokens": 128}, language=language, reference_text=transcript)
    assert result == (b"encoded", "audio/wav")
    assert generate.call_args.kwargs == {"text": text, "language": expected, "ref_audio": decoded,
        "ref_text": transcript, "x_vector_only_mode": transcript is None,
        **QWEN3TTS_DEFAULTS, "max_new_tokens": 128, **QWEN3TTS_SUBTALKER}
    encoded.assert_called_once_with([0.2, 0.3], 24000, 0.8, "wav")


def test_qwen_worker_is_public_and_validates_before_engine_calls(tmp_path):
    qwen_model(tmp_path / "tts/qwen")
    (tmp_path / "voice.wav").write_bytes(wav_bytes())
    engine = SimpleNamespace(device="cpu", device_name="CPU", speech=MagicMock(return_value=(wav_bytes(), "audio/wav")))
    factory = MagicMock(return_value=engine)
    worker = AudioWorker(tmp_path, tmp_path, engine_factory=factory)
    profile = qwen_profile()
    load = {"profile_id": profile.id, "kind": "tts", "model_ref": profile.model_ref,
            "parameters": profile.parameters, "options": profile.runtime_options}
    assert worker.dispatch("/load", load)["loaded"] == [profile.id]
    body = {"profile_id": profile.id, "input": "你好", "reference": "voice.wav", "reference_text": "Hello",
            "speed": 1, "response_format": "wav", "language": "zh-CN", "model_options": {"top_k": 0}}
    assert worker.dispatch("/speech", body)[0] == wav_bytes()
    assert engine.speech.call_args.kwargs == {"language": "zh-CN", "reference_text": "Hello"}
    for patch in ({"language": "hi-IN"}, {"language": []}, {"reference_text": " "},
                  {"model_options": {"cfg_weight": 0.5}}, {"model_options": {"do_sample": 1}},
                  {"model_options": {"max_new_tokens": 8193}}, {"extra": True}):
        with pytest.raises(WorkerError):
            worker.dispatch("/speech", {**body, **patch})
    assert engine.speech.call_count == 1
    blocked = AudioWorker(tmp_path, tmp_path, engine_factory=MagicMock(side_effect=AssertionError("Unexpected load")))
    (tmp_path / "tts/qwen/speech_tokenizer/model.safetensors").unlink()
    with pytest.raises(WorkerError):
        blocked.dispatch("/load", load)


def test_qwen_reference_queue_expiry_and_cancellation_keep_transcript_scoped(tmp_path):
    async def scenario():
        manager = make_manager(tmp_path)
        clock = Clock()
        manager._voice_references = VoiceReferences(tmp_path, clock=clock)
        profile = manager.profiles.create(qwen_profile())
        adapter = Adapter(manager)
        slot = ProviderSlot(adapter, asyncio.Semaphore(1))
        manager._slots[manager.backend_key(profile)] = slot
        manager._slot = lambda *args: (SimpleNamespace(concurrency=1, queue_size=1, queue_timeout_seconds=0.05), slot)
        store = manager.voice_references
        entry = store.publish(store.stage(wav_bytes(), "wav", "Kept only for this reference"),
            profile.id, manager.voice_binding(profile), credential_id("test-key"))
        started, stopped = asyncio.Event(), asyncio.Event()
        async def speech(*args, **kwargs):
            assert kwargs["reference_text"] == entry.reference_text
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                assert entry.path.exists() and slot.active == 1
                stopped.set()
        adapter.speech = speech
        request = SpeechRequest(model="qwen", input="Hello", voice=entry.id)
        pending = asyncio.create_task(manager.speech(profile.id, request))
        await started.wait()
        clock.now += timedelta(minutes=20)
        waiting = asyncio.create_task(manager.speech(profile.id, request))
        while not slot.queued:
            await asyncio.sleep(0)
        expiry = clock.now + timedelta(minutes=15)
        assert entry.expires_at == expiry and entry.active == 2
        with pytest.raises(ModelError):
            await manager.speech(profile.id, request)
        assert entry.expires_at == expiry
        with pytest.raises(ModelError):
            await waiting
        clock.now = expiry
        assert manager.temporary_voice_list(profile.id, None) == [] and entry.path.exists()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stopped.is_set() and not entry.path.exists() and not store._entries and entry.reference_text is None
        assert slot.active == slot.queued == 0
        await manager.close()
        await manager.runtime_supervisor.close()
    asyncio.run(scenario())


def test_qwen_openapi_explains_defaults_transcripts_and_overrides(qwen_api):
    client, _, profile, _ = qwen_api
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    parameters = schemas["Qwen3TTSParameters"]["properties"]
    for name, default in QWEN3TTS_DEFAULTS.items():
        assert parameters[name]["default"] == default and parameters[name]["description"]
    options = schemas["Documented__Qwen3TTSRequestOptions"]
    assert options["additionalProperties"] is False and "inherit" in options["description"]
    assert "reference_text" in schemas["Documented__ReferenceAudio"]["properties"]
    assert "reference_text" in schemas["Documented__VoiceReferenceUpload"]["properties"]
    response = client.get(f"/api/models/profiles/{profile.id}")
    validate_response(document, "/api/models/profiles/{profile_id}", "get", response)


@pytest.mark.parametrize("change", ["key", "service", "enabled", "external_enabled", "architecture", "binding", "delete"])
def test_qwen_reference_invalidation_discards_transcript(qwen_api, change):
    client, manager, profile, _ = qwen_api
    identifier = upload(client, "Private reference words").json()["voice_id"]
    entry = manager.voice_references._entries[identifier]
    if change == "key":
        result = client.patch("/api/models/settings", json={"external_api_key": "new-key"})
    elif change == "service":
        result = client.patch("/api/models/settings", json={"external_enabled": False})
    elif change == "delete":
        result = client.delete(f"/api/models/profiles/{profile.id}")
    else:
        patch = {"parameters": {"architecture": "chatterbox"}} if change == "architecture" else (
            {"model_ref": "tts/other"} if change == "binding" else {change: False})
        result = client.patch(f"/api/models/profiles/{profile.id}", json=patch)
    assert result.status_code == 200, result.text
    assert not entry.path.exists() and entry.reference_text is None and identifier not in manager.voice_references._entries
