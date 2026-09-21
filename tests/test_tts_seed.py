"""Speech seed contracts, request isolation and complete engine scope."""
from contextlib import nullcontext
from datetime import timedelta
import random
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.workers import audio_engine
from ai_workbench.workers.audio_server import generation_options
from ai_workbench.workers.common import WorkerError
from tests.test_audio import api, upload
from tests.test_qwen_tts import inline, qwen_api
from tests.test_tts import HEADERS


@pytest.fixture(params=["api", "qwen_api"])
def seed_api(request):
    return request.getfixturevalue(request.param)


def test_seed_profile_save_clear_and_openapi(seed_api):
    client, manager, profile, _ = seed_api
    assert profile.parameters["seed"] is None
    for seed in (0, 4294967295, None):
        saved = client.patch(f"/api/models/profiles/{profile.id}", json={"parameters": {**profile.parameters, "seed": seed}})
        assert saved.status_code == 200, saved.text
        assert saved.json()["parameters"]["seed"] == seed
        assert client.get(f"/api/models/profiles/{profile.id}").json()["parameters"]["seed"] == seed
        assert manager.profiles.get(profile.id).parameters["seed"] == seed
        assert generation_options({"seed": seed}, profile.parameters["architecture"])["seed"] == seed
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("ChatterboxParameters", "Qwen3TTSParameters", "Documented__ChatterboxRequestOptions", "Documented__Qwen3TTSRequestOptions"):
        field = schemas[name]["properties"]["seed"]
        assert {"type": "null"} in field["anyOf"]
        assert "seed" not in schemas[name].get("required", [])
        assert {"type": "integer", "minimum": 0, "maximum": 4294967295} in field["anyOf"]
        assert "identical audio" in field["description"]


@pytest.mark.parametrize("profile_seed", [None, 37])
@pytest.mark.parametrize("source", ["temporary", "inline"])
def test_seed_request_override_and_null_inheritance(seed_api, profile_seed, source):
    client, manager, profile, adapter = seed_api
    manager.profiles.update(profile.id, {"parameters": {**profile.parameters, "seed": profile_seed}})
    payload = {"model": profile.alias, "input": "Hello"}
    tts = {}
    if source == "temporary":
        payload["voice"] = upload(client, alias=profile.alias).json()["voice_id"]
    else:
        tts["reference_audio"] = inline()
    for options, expected in (({}, profile_seed), ({"seed": None}, profile_seed), ({"seed": 0}, 0), ({"seed": 4294967295}, 4294967295)):
        result = client.post("/v1/audio/speech", headers=HEADERS,
            json={**payload, "tts": {**tts, "model_options": options}})
        assert result.status_code == 200, result.text
        assert adapter.calls[-1][1]["model_options"]["seed"] == expected
    assert manager.profiles.get(profile.id).parameters["seed"] == profile_seed


@pytest.mark.parametrize("seed", [-1, 4294967296, 1.0, 1.5, True, "0"])
def test_invalid_seed_rejected_before_staging_admission_or_renewal(seed_api, monkeypatch, seed):
    client, manager, profile, adapter = seed_api
    result = client.patch(f"/api/models/profiles/{profile.id}", json={"parameters": {**profile.parameters, "seed": seed}})
    assert result.status_code == 422, result.text
    assert manager.profiles.get(profile.id).parameters["seed"] is None
    with pytest.raises(WorkerError):
        generation_options({"seed": seed}, profile.parameters["architecture"])
    voice = upload(client, alias=profile.alias).json()["voice_id"]
    entry = manager.voice_references._entries[voice]
    expiry = entry.expires_at
    manager.voice_references.clock = lambda: expiry - timedelta(minutes=5)
    monkeypatch.setattr(manager, "_lease", MagicMock(side_effect=AssertionError("Unexpected admission")))
    monkeypatch.setattr(manager, "_stage_reference", MagicMock(side_effect=AssertionError("Unexpected staging")))
    for source in ({"voice": voice}, {"tts": {"reference_audio": inline()}}):
        result = client.post("/v1/audio/speech", headers=HEADERS, json={"model": profile.alias,
            "input": "Hello", **source, "tts": {**source.get("tts", {}), "model_options": {"seed": seed}}})
        assert result.status_code == 400 and result.json()["error"]["code"] == "INVALID_REQUEST", result.text
    assert entry.expires_at == expiry and entry.active == 0 and not adapter.calls


def test_kokoro_and_other_request_locations_reject_seed(api):
    client, manager, _, _ = api
    profile = ModelProfile(name="Kokoro", alias="kokoro", kind="tts", model_ref="tts/kokoro",
        backend_profile_id="local", external_enabled=True)
    manager.profiles.create(profile)
    for seed in (None, 0):
        with pytest.raises(ValidationError):
            ModelProfile.model_validate({**profile.model_dump(), "parameters": {**profile.parameters, "seed": seed}})
        for extra in ({"seed": seed}, {"tts": {"seed": seed}}, {"tts": {"model_options": {"seed": seed}}}):
            result = client.post("/v1/audio/speech", headers=HEADERS,
                json={"model": profile.alias, "input": "Hello", "voice": "af_heart", **extra})
            assert result.status_code == 400, result.text


@pytest.fixture
def random_sources(monkeypatch):
    """Real independent PRNGs stand in for libraries absent from the API environment."""
    python_state = random.getstate()
    numpy_rng, cpu_rng, cuda_rng = (random.Random(seed) for seed in (11, 12, 13))
    cuda = SimpleNamespace(get_rng_state=MagicMock(side_effect=cuda_rng.getstate),
        set_rng_state=MagicMock(side_effect=cuda_rng.setstate), manual_seed=MagicMock(side_effect=cuda_rng.seed))
    torch = SimpleNamespace(get_rng_state=cpu_rng.getstate, set_rng_state=cpu_rng.setstate,
        random=SimpleNamespace(default_generator=SimpleNamespace(manual_seed=cpu_rng.seed)),
        cuda=cuda, inference_mode=nullcontext)
    numpy = SimpleNamespace(random=SimpleNamespace(get_state=numpy_rng.getstate,
        set_state=numpy_rng.setstate, seed=numpy_rng.seed), concatenate=lambda parts: parts)
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "torch", torch)
    def draw(device):
        return (random.random(), numpy_rng.random(), cpu_rng.random(), *([cuda_rng.random()] if device == "cuda" else []))
    def snapshot():
        return random.getstate(), numpy_rng.getstate(), cpu_rng.getstate(), cuda_rng.getstate()
    yield SimpleNamespace(draw=draw, snapshot=snapshot, cuda=cuda)
    random.setstate(python_state)


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_seed_sequences_restore_state_and_unfixed_requests_advance(random_sources, device):
    initial = random_sources.snapshot()
    sequences = []
    for seed in (0, 123, 0):
        with audio_engine.speech_random_state(seed, device):
            sequences.append([random_sources.draw(device) for _ in range(3)])
        assert random_sources.snapshot() == initial
    assert sequences[0] == sequences[2] and sequences[0] != sequences[1]
    with pytest.raises(RuntimeError, match="synthesis failed"):
        with audio_engine.speech_random_state(0, device):
            random_sources.draw(device)
            raise RuntimeError("synthesis failed")
    assert random_sources.snapshot() == initial
    with audio_engine.speech_random_state(None, device):
        first = random_sources.draw(device)
    with audio_engine.speech_random_state(None, device):
        second = random_sources.draw(device)
    assert first != second and random_sources.snapshot() != initial
    if device == "cpu":
        random_sources.cuda.get_rng_state.assert_not_called()
        random_sources.cuda.manual_seed.assert_not_called()
        random_sources.cuda.set_rng_state.assert_not_called()


def test_unfixed_seed_needs_no_runtime_imports(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    with audio_engine.speech_random_state(None, "cuda"):
        pass


@pytest.mark.parametrize("architecture", ["chatterbox", "qwen3tts"])
def test_engine_seeds_whole_request_without_forwarding_seed(random_sources, monkeypatch, architecture):
    events = []
    def record(stage):
        events.append((stage, random_sources.draw("cpu")))
    def decode(_reference):
        record("reference")
        return [0.1], 24000
    def encode(*_args):
        record("encoding")
        return b"encoded", "audio/wav"
    def generate(*args, **options):
        assert "seed" not in options
        record(args[0] if args else "generation")
        if architecture == "qwen3tts":
            assert options["do_sample"] is False and options["subtalker_dosample"] is True
            return [[0.1]], 24000
        tensor = MagicMock()
        tensor.detach.return_value.cpu.return_value.numpy.return_value.reshape.return_value = SimpleNamespace(size=1)
        return tensor
    monkeypatch.setattr(audio_engine, "decode_audio", decode)
    monkeypatch.setattr(audio_engine, "encode_waveform", encode)
    cls = audio_engine.ChatterboxEngine if architecture == "chatterbox" else audio_engine.QwenTTSEngine
    engine = cls.__new__(cls)
    engine.device = "cpu"
    engine.model = SimpleNamespace(conds=None, sr=24000, generate=generate, generate_voice_clone=generate,
        prepare_conditionals=lambda *_args, **_kwargs: record("conditioning"))
    initial = random_sources.snapshot()
    sequences = []
    for seed in (0, 123, 0):
        events.clear()
        options = {"seed": seed}
        if architecture == "qwen3tts":
            options["do_sample"] = False
        assert engine.speech("First sentence. Second sentence.", "reference.wav", 1, "wav", options) == (b"encoded", "audio/wav")
        assert options["seed"] == seed and random_sources.snapshot() == initial
        sequences.append(list(events))
    assert sequences[0] == sequences[2] and sequences[0] != sequences[1]
    expected = ["reference", "conditioning", "First sentence.", "Second sentence.", "encoding"] if architecture == "chatterbox" else ["reference", "generation", "encoding"]
    assert [stage for stage, _ in sequences[0]] == expected
    assert len({draw for _, draw in sequences[0]}) == len(expected)
    assert engine.model.conds is None
