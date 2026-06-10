from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.inference.multimodal_runtime import (
    MultimodalEmbeddingInput,
    MultimodalEmbeddingResult,
    MultimodalRuntimeCache,
    MultimodalRuntimeError,
    MultimodalRuntimeUnavailable,
    clear_multimodal_embedding_runtime_factories,
    clear_multimodal_runtime_cache,
    embed_multimodal_inputs,
    get_multimodal_embedding_runtime,
    register_multimodal_embedding_runtime_factory,
)
from ai_workbench.core.multimodal_profiles import MultimodalEmbeddingModelProfile
from tests.test_prompt_agent_execution import FakeLLMRuntime
from tests.test_stateless_inference_skeleton import auth_headers, enable_inference


class FakeRuntime:
    def __init__(self, profile) -> None:
        self.profile_id = profile.id
        self.calls = []
        self.unloaded = False

    def embed(self, *, profile, inputs, normalize: bool) -> MultimodalEmbeddingResult:
        self.calls.append({"profile_id": profile.id, "input_types": [item.input_type for item in inputs], "normalize": normalize})
        return MultimodalEmbeddingResult(vectors=[[float(index), float(index + 1)] for index, _ in enumerate(inputs)])

    def unload(self) -> None:
        self.unloaded = True


class NonNumericRuntime(FakeRuntime):
    def embed(self, *, profile, inputs, normalize: bool) -> MultimodalEmbeddingResult:
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[["not-a-number"] for _ in inputs])


class WrongCountRuntime(FakeRuntime):
    def embed(self, *, profile, inputs, normalize: bool) -> MultimodalEmbeddingResult:
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[[1.0, 2.0]])


class RaggedRuntime(FakeRuntime):
    def embed(self, *, profile, inputs, normalize: bool) -> MultimodalEmbeddingResult:
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[[1.0, 2.0], [3.0]])


class NonFiniteRuntime(FakeRuntime):
    def __init__(self, profile, value: float) -> None:
        super().__init__(profile)
        self.value = value

    def embed(self, *, profile, inputs, normalize: bool) -> MultimodalEmbeddingResult:
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[[self.value, 2.0] for _ in inputs])


def make_profile(**overrides) -> MultimodalEmbeddingModelProfile:
    payload = {
        "id": "runtime-profile",
        "name": "Runtime Profile",
        "provider_model_id": "image_embedding/runtime",
        "architecture": "clip",
        "backend": "auto",
        "external_inference_enabled": True,
    }
    payload.update(overrides)
    return MultimodalEmbeddingModelProfile.model_validate(payload)


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True, root=tmp_path))


def create_profile(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Runtime API Profile",
        "provider_model_id": "image_embedding/runtime-api",
        "architecture": "clip",
        "backend": "auto",
        "supported_input_types": ["image", "text"],
        "external_inference_enabled": True,
    }
    payload.update(overrides)
    response = client.post("/api/inference/multimodal-embedding-models", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def teardown_function() -> None:
    clear_multimodal_embedding_runtime_factories()
    clear_multimodal_runtime_cache()


def test_fake_runtime_can_be_registered_and_returns_deterministic_vectors() -> None:
    cache = MultimodalRuntimeCache()
    profile = make_profile()
    register_multimodal_embedding_runtime_factory("clip", FakeRuntime)

    result = embed_multimodal_inputs(
        profile,
        [MultimodalEmbeddingInput(input_type="image", image_base64="AAAA"), MultimodalEmbeddingInput(input_type="text", text="red")],
        normalize=True,
        cache=cache,
    )

    assert result.vectors == [[0.0, 1.0], [1.0, 2.0]]
    runtime = get_multimodal_embedding_runtime(profile, cache=cache)
    assert runtime.calls == [{"profile_id": "runtime-profile", "input_types": ["image", "text"], "normalize": True}]


def test_runtime_cache_reuses_same_fingerprint_and_invalidates_when_profile_changes() -> None:
    cache = MultimodalRuntimeCache()
    register_multimodal_embedding_runtime_factory("clip", FakeRuntime)
    first = make_profile()
    changed = make_profile(backend="transformers")

    runtime_1 = get_multimodal_embedding_runtime(first, cache=cache)
    runtime_2 = get_multimodal_embedding_runtime(first, cache=cache)
    runtime_3 = get_multimodal_embedding_runtime(changed, cache=cache)

    assert runtime_1 is runtime_2
    assert runtime_3 is not runtime_1
    assert cache.status() == {"runtime_count": 2, "profile_count": 1, "architecture_counts": {"clip": 2}}


def test_runtime_cache_clear_by_profile_and_clear_all_unload_runtimes() -> None:
    cache = MultimodalRuntimeCache()
    register_multimodal_embedding_runtime_factory("clip", FakeRuntime)
    register_multimodal_embedding_runtime_factory("siglip2", FakeRuntime)
    clip = make_profile(id="clip-profile", architecture="clip")
    siglip = make_profile(id="siglip-profile", architecture="siglip2")
    clip_runtime = get_multimodal_embedding_runtime(clip, cache=cache)
    siglip_runtime = get_multimodal_embedding_runtime(siglip, cache=cache)

    assert cache.clear_profile("clip-profile") == 1
    assert clip_runtime.unloaded is True
    assert siglip_runtime.unloaded is False
    assert cache.status() == {"runtime_count": 1, "profile_count": 1, "architecture_counts": {"siglip2": 1}}
    assert cache.clear() == 1
    assert siglip_runtime.unloaded is True
    assert cache.status() == {"runtime_count": 0, "profile_count": 0, "architecture_counts": {}}


def test_cache_status_is_compact_and_secret_free() -> None:
    cache = MultimodalRuntimeCache()
    register_multimodal_embedding_runtime_factory("clip", FakeRuntime)
    profile = make_profile(
        provider_model_id="image_embedding/secret-model",
        metadata={"secret": "provider-secret", "vector": [0.1, 0.2], "payload": "AAAA"},
    )

    get_multimodal_embedding_runtime(profile, cache=cache)

    status = cache.status()
    rendered = str(status)
    assert status == {"runtime_count": 1, "profile_count": 1, "architecture_counts": {"clip": 1}}
    assert "secret-model" not in rendered
    assert "provider-secret" not in rendered
    assert "AAAA" not in rendered
    assert "0.1" not in rendered


def test_default_production_runtime_is_not_available_without_registered_factory() -> None:
    profile = make_profile()

    try:
        get_multimodal_embedding_runtime(profile, cache=MultimodalRuntimeCache())
    except MultimodalRuntimeUnavailable:
        pass
    else:
        raise AssertionError("expected no production multimodal runtime in A4.1")


@pytest.mark.parametrize("runtime_cls", [NonNumericRuntime, WrongCountRuntime, RaggedRuntime])
def test_runtime_output_validation_wraps_invalid_vectors_as_runtime_errors(runtime_cls) -> None:
    cache = MultimodalRuntimeCache()
    profile = make_profile()
    register_multimodal_embedding_runtime_factory("clip", runtime_cls)

    try:
        embed_multimodal_inputs(
            profile,
            [MultimodalEmbeddingInput(input_type="image", image_base64="AAAA"), MultimodalEmbeddingInput(input_type="text", text="red")],
            normalize=True,
            cache=cache,
        )
    except MultimodalRuntimeError as exc:
        rendered = str(exc)
        assert "not-a-number" not in rendered
        assert "AAAA" not in rendered
        assert "red" not in rendered
        assert "1.0" not in rendered
    else:
        raise AssertionError("expected invalid multimodal runtime output to fail")


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_non_finite_runtime_vectors_return_sanitized_provider_error(
    value: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client)

    def factory(profile):
        return NonFiniteRuntime(profile, value)

    register_multimodal_embedding_runtime_factory("clip", factory)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [
                {"type": "image_base64", "data": "BASE64-PAYLOAD-SECRET"},
                {"type": "text", "text": "raw input text secret"},
            ],
        },
        headers=auth_headers(),
    )

    payload = response.json()
    rendered = str(payload).lower()
    assert response.status_code == 502
    assert payload["error"]["code"] == "PROVIDER_ERROR"
    assert "nan" not in rendered
    assert "inf" not in rendered
    assert "infinity" not in rendered
    assert "traceback" not in rendered
    assert "valueerror" not in rendered
    assert "non-finite" not in rendered
    assert "base64-payload-secret" not in rendered
    assert "raw input text secret" not in rendered
    assert "provider-secret" not in rendered
    assert "c:\\models\\fake" not in rendered
    assert "[nan" not in rendered
    assert "[inf" not in rendered
