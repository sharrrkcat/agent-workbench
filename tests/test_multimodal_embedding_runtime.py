from pathlib import Path
import builtins

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
from ai_workbench.core.inference.stateless_guard import assert_snapshot_unchanged, capture_stateless_persistence_snapshot
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


class FakeTensor:
    def __init__(self, rows) -> None:
        self.rows = rows

    def to(self, device):
        return self

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.rows

    def unsqueeze(self, dim):
        return self


class FakeTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False

        @staticmethod
        def empty_cache() -> None:
            return None

    class backends:
        class mps:
            @staticmethod
            def is_available() -> bool:
                return False

    class no_grad:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    @staticmethod
    def stack(items):
        return FakeTensor([[float(index), 0.0] for index, _ in enumerate(items)])


class FakeClipProcessor:
    def __call__(self, *, images=None, text=None, **kwargs):
        return {"count": len(images if images is not None else text)}


class FakeClipModel:
    def to(self, device):
        return self

    def eval(self):
        return None

    def get_image_features(self, **batch):
        return FakeTensor([[10.0 + index, 0.0] for index in range(batch["count"])])

    def get_text_features(self, **batch):
        return FakeTensor([[20.0 + index, 0.0] for index in range(batch["count"])])


class FakeOpenClipModel:
    def to(self, device):
        return self

    def eval(self):
        return None

    def load_state_dict(self, state):
        return None

    def encode_image(self, batch):
        return FakeTensor([[30.0 + index, 0.0] for index, _ in enumerate(batch.rows)])

    def encode_text(self, tokens):
        return FakeTensor([[40.0 + index, 0.0] for index, _ in enumerate(tokens.rows)])


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


def create_local_image_embedding_folder(client: TestClient, name: str = "runtime-api") -> Path:
    root = client.app.state.runtime_state.repo_root
    model_dir = root / "data" / "models" / "image_embeddings" / name
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    return model_dir


def install_fake_clip_backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    from ai_workbench.core.inference.clip_runtime import ClipEmbeddingRuntime

    calls = {"load": 0, "image": 0}

    def fake_load(self):
        calls["load"] += 1
        return FakeClipModel(), FakeClipProcessor(), FakeTorch

    def fake_image(value):
        calls["image"] += 1
        return object()

    monkeypatch.setattr(ClipEmbeddingRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.clip_runtime._load_image_from_base64", fake_image)
    return calls


def install_fake_open_clip_backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    from ai_workbench.core.inference.clip_runtime import OpenClipEmbeddingRuntime

    calls = {"load": 0, "image": 0}

    def fake_load(self):
        calls["load"] += 1
        preprocess = lambda image: FakeTensor([[1.0, 0.0]])
        tokenizer = lambda texts: FakeTensor([[float(index), 0.0] for index, _ in enumerate(texts)])
        return FakeOpenClipModel(), preprocess, tokenizer, FakeTorch

    def fake_image(value):
        calls["image"] += 1
        return object()

    monkeypatch.setattr(OpenClipEmbeddingRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.clip_runtime._load_image_from_base64", fake_image)
    return calls


def install_fake_siglip2_backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    from ai_workbench.core.inference.siglip2_runtime import Siglip2EmbeddingRuntime

    calls = {"load": 0, "image": 0}

    def fake_load(self):
        calls["load"] += 1
        return FakeClipModel(), FakeClipProcessor(), FakeTorch

    def fake_image(value):
        calls["image"] += 1
        return object()

    monkeypatch.setattr(Siglip2EmbeddingRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.siglip2_runtime._load_image_from_base64", fake_image)
    return calls


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
    clear_multimodal_embedding_runtime_factories()
    profile = make_profile()

    try:
        get_multimodal_embedding_runtime(profile, cache=MultimodalRuntimeCache())
    except MultimodalRuntimeUnavailable:
        pass
    else:
        raise AssertionError("expected no multimodal runtime without a registered factory")


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


def test_open_clip_checkpoint_loader_uses_weights_only(tmp_path: Path) -> None:
    from ai_workbench.core.inference.clip_runtime import _load_open_clip_checkpoint

    calls = []

    class Torch:
        @staticmethod
        def load(path, *, map_location=None, weights_only=None):
            calls.append({"path": path, "map_location": map_location, "weights_only": weights_only})
            return {"state_dict": {"weight": [1.0]}}

    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"fake")

    assert _load_open_clip_checkpoint(Torch, checkpoint) == {"state_dict": {"weight": [1.0]}}
    assert calls == [{"path": str(checkpoint), "map_location": "cpu", "weights_only": True}]


def test_open_clip_checkpoint_loader_fails_closed_without_weights_only(tmp_path: Path) -> None:
    from ai_workbench.core.inference.clip_runtime import _load_open_clip_checkpoint

    class Torch:
        @staticmethod
        def load(path, *, map_location=None):
            return {"state_dict": {}}

    checkpoint = tmp_path / "secret-model.pt"
    checkpoint.write_bytes(b"fake")

    with pytest.raises(MultimodalRuntimeError) as exc:
        _load_open_clip_checkpoint(Torch, checkpoint)

    rendered = str(exc.value)
    assert "secret-model.pt" not in rendered
    assert str(tmp_path) not in rendered


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


def test_status_and_models_do_not_import_heavy_clip_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_profile(client, provider_model_id="image_embedding/no-load", architecture="clip")
    create_profile(client, provider_model_id="image_embedding/no-load-siglip2", architecture="siglip2")
    original_import = builtins.__import__
    blocked = {"torch", "transformers", "open_clip", "PIL"}

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in blocked:
            raise AssertionError(f"heavy import during no-load endpoint: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    status = client.get("/api/inference/status", headers=auth_headers())
    models = client.get("/api/inference/models", headers=auth_headers())

    assert status.status_code == 200
    assert status.json()["implementation"]["real_multimodal_inference"] is True
    assert models.status_code == 200
    assert f"multimodal:" in str(models.json())


def test_real_clip_runtime_load_is_lazy_until_embedding_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "lazy-clip")
    profile = create_profile(client, provider_model_id="image_embedding/lazy-clip", architecture="clip")
    calls = install_fake_clip_backend(monkeypatch)

    client.get("/api/inference/status", headers=auth_headers())
    client.get("/api/inference/models", headers=auth_headers())

    assert calls == {"load": 0, "image": 0}

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [{"type": "image_base64", "data": "AAAA"}],
            "normalize": False,
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert calls == {"load": 1, "image": 1}


def test_real_siglip2_runtime_load_is_lazy_until_embedding_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "lazy-siglip2")
    profile = create_profile(client, provider_model_id="image_embedding/lazy-siglip2", architecture="siglip2")
    calls = install_fake_siglip2_backend(monkeypatch)

    client.get("/api/inference/status", headers=auth_headers())
    client.get("/api/inference/models", headers=auth_headers())

    assert calls == {"load": 0, "image": 0}

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "secret text"}],
            "normalize": False,
        },
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 200, response.text
    assert payload["architecture"] == "siglip2"
    assert payload["data"] == [
        {"object": "embedding", "index": 0, "input_type": "image", "embedding": [10.0, 0.0]},
        {"object": "embedding", "index": 1, "input_type": "text", "embedding": [20.0, 0.0]},
    ]
    assert calls == {"load": 1, "image": 1}
    assert "secret text" not in str(payload)


def test_siglip2_feature_extraction_uses_inference_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workbench.core.inference.siglip2_runtime import Siglip2EmbeddingRuntime

    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "siglip2-inference-context")
    profile = create_profile(
        client,
        provider_model_id="image_embedding/siglip2-inference-context",
        architecture="siglip2",
    )

    class RecordingTorch(FakeTorch):
        active = False
        enter_count = 0
        exit_count = 0

        class _InferenceMode:
            def __enter__(self):
                RecordingTorch.active = True
                RecordingTorch.enter_count += 1
                return self

            def __exit__(self, exc_type, exc, traceback):
                RecordingTorch.active = False
                RecordingTorch.exit_count += 1
                return False

        @staticmethod
        def inference_mode():
            return RecordingTorch._InferenceMode()

    class ContextAssertingModel(FakeClipModel):
        def get_image_features(self, **batch):
            assert RecordingTorch.active is True
            return super().get_image_features(**batch)

        def get_text_features(self, **batch):
            assert RecordingTorch.active is True
            return super().get_text_features(**batch)

    def fake_load(self):
        return ContextAssertingModel(), FakeClipProcessor(), RecordingTorch

    monkeypatch.setattr(Siglip2EmbeddingRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.siglip2_runtime._load_image_from_base64", lambda value: object())

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "secret text"}],
            "normalize": False,
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert RecordingTorch.enter_count == 2
    assert RecordingTorch.exit_count == 2
    assert RecordingTorch.active is False
    assert response.json()["data"] == [
        {"object": "embedding", "index": 0, "input_type": "image", "embedding": [10.0, 0.0]},
        {"object": "embedding", "index": 1, "input_type": "text", "embedding": [20.0, 0.0]},
    ]


def test_missing_clip_optional_dependency_returns_sanitized_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "missing-deps")
    profile = create_profile(client, provider_model_id="image_embedding/missing-deps", architecture="clip")
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] == "transformers":
            raise ImportError("transformers secret path C:\\models\\fake provider-secret")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        "ai_workbench.core.inference.clip_runtime._load_image_from_base64",
        lambda value: object(),
    )

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]},
        headers=auth_headers(),
    )

    rendered = str(response.json())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "provider-secret" not in rendered
    assert "AAAA" not in rendered
    assert "C:\\models\\fake" not in rendered
    assert "traceback" not in rendered.lower()


def test_missing_siglip2_optional_dependency_returns_sanitized_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "siglip2-missing-deps")
    profile = create_profile(client, provider_model_id="image_embedding/siglip2-missing-deps", architecture="siglip2")
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] == "transformers":
            raise ImportError("transformers secret path C:\\models\\fake provider-secret")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        "ai_workbench.core.inference.siglip2_runtime._load_image_from_base64",
        lambda value: object(),
    )

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]},
        headers=auth_headers(),
    )

    rendered = str(response.json())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "provider-secret" not in rendered
    assert "AAAA" not in rendered
    assert "C:\\models\\fake" not in rendered
    assert "traceback" not in rendered.lower()


@pytest.mark.parametrize(
    "architecture, model_name, checkpoint_name",
    [
        ("clip", None, None),
        ("open_clip", "ViT-B-32", "model.pt"),
        ("siglip2", None, None),
    ],
)
def test_invalid_image_payloads_do_not_load_runtime(
    architecture: str,
    model_name: str | None,
    checkpoint_name: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    model_dir = create_local_image_embedding_folder(client, f"invalid-image-{architecture}")
    profile_kwargs = {
        "provider_model_id": f"image_embedding/invalid-image-{architecture}",
        "architecture": architecture,
    }
    if architecture == "open_clip":
        assert model_name is not None and checkpoint_name is not None
        (model_dir / checkpoint_name).write_bytes(b"fake")
        profile_kwargs["metadata"] = {"open_clip_model_name": model_name, "open_clip_checkpoint": checkpoint_name}
    profile = create_profile(client, **profile_kwargs)

    if architecture == "clip":
        from ai_workbench.core.inference.clip_runtime import ClipEmbeddingRuntime

        calls = {"load": 0}

        def fake_load(self):
            calls["load"] += 1
            return FakeClipModel(), FakeClipProcessor(), FakeTorch

        monkeypatch.setattr(ClipEmbeddingRuntime, "_load", fake_load)
    elif architecture == "open_clip":
        from ai_workbench.core.inference.clip_runtime import OpenClipEmbeddingRuntime

        calls = {"load": 0}

        def fake_load(self):
            calls["load"] += 1
            return FakeOpenClipModel(), (lambda image: FakeTensor([[1.0, 0.0]])), (lambda texts: FakeTensor([[0.0, 0.0] for _ in texts])), FakeTorch

        monkeypatch.setattr(OpenClipEmbeddingRuntime, "_load", fake_load)
    else:
        from ai_workbench.core.inference.siglip2_runtime import Siglip2EmbeddingRuntime

        calls = {"load": 0}

        def fake_load(self):
            calls["load"] += 1
            return FakeClipModel(), FakeClipProcessor(), FakeTorch

        monkeypatch.setattr(Siglip2EmbeddingRuntime, "_load", fake_load)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [{"type": "image_base64", "data": "not-base64-or-image-secret"}],
        },
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert calls["load"] == 0
    assert "not-base64-or-image-secret" not in rendered
    assert "traceback" not in rendered
    assert "secret" not in rendered


@pytest.mark.parametrize(
    "architecture, payload",
    [
        ("clip", "not-base64-or-image-secret"),
        ("clip", "AAECAwQFBgcICQ=="),
        ("open_clip", "not-base64-or-image-secret"),
        ("open_clip", "AAECAwQFBgcICQ=="),
        ("siglip2", "not-base64-or-image-secret"),
        ("siglip2", "AAECAwQFBgcICQ=="),
    ],
)
def test_invalid_image_payloads_do_not_persist_and_do_not_load(
    architecture: str,
    payload: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    model_dir = create_local_image_embedding_folder(client, f"invalid-image-{architecture}")
    profile_kwargs = {
        "provider_model_id": f"image_embedding/invalid-image-{architecture}",
        "architecture": architecture,
    }
    if architecture == "open_clip":
        (model_dir / "model.pt").write_bytes(b"fake")
        profile_kwargs["metadata"] = {"open_clip_model_name": "ViT-B-32", "open_clip_checkpoint": "model.pt"}
    profile = create_profile(client, **profile_kwargs)
    before = capture_stateless_persistence_snapshot(state)

    calls = {"load": 0}

    def fake_load(self):
        calls["load"] += 1
        if architecture == "clip":
            return FakeClipModel(), FakeClipProcessor(), FakeTorch
        if architecture == "siglip2":
            return FakeClipModel(), FakeClipProcessor(), FakeTorch
        return FakeOpenClipModel(), (lambda image: FakeTensor([[1.0, 0.0]])), (lambda texts: FakeTensor([[0.0, 0.0] for _ in texts])), FakeTorch

    if architecture == "clip":
        from ai_workbench.core.inference.clip_runtime import ClipEmbeddingRuntime

        monkeypatch.setattr(ClipEmbeddingRuntime, "_load", fake_load)
    elif architecture == "open_clip":
        from ai_workbench.core.inference.clip_runtime import OpenClipEmbeddingRuntime

        monkeypatch.setattr(OpenClipEmbeddingRuntime, "_load", fake_load)
    else:
        from ai_workbench.core.inference.siglip2_runtime import Siglip2EmbeddingRuntime

        monkeypatch.setattr(Siglip2EmbeddingRuntime, "_load", fake_load)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": payload}]},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert calls["load"] == 0
    assert "traceback" not in rendered
    assert "secret" not in rendered
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))


def test_missing_local_clip_model_folder_returns_sanitized_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, provider_model_id="image_embedding/missing-folder", architecture="clip")

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "BASE64-SECRET"}]},
        headers=auth_headers(),
    )

    rendered = str(response.json())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "missing-folder" not in rendered
    assert str(tmp_path) not in rendered
    assert "BASE64-SECRET" not in rendered


def test_missing_local_siglip2_model_folder_returns_sanitized_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, provider_model_id="image_embedding/missing-siglip2-folder", architecture="siglip2")

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "BASE64-SECRET"}]},
        headers=auth_headers(),
    )

    rendered = str(response.json())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "missing-siglip2-folder" not in rendered
    assert str(tmp_path) not in rendered
    assert "BASE64-SECRET" not in rendered


def test_fake_clip_backend_returns_image_and_text_vectors_through_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "fake-clip")
    profile = create_profile(client, provider_model_id="image_embedding/fake-clip", architecture="clip")
    install_fake_clip_backend(monkeypatch)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "secret text"}],
            "normalize": False,
        },
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 200, response.text
    assert payload["data"] == [
        {"object": "embedding", "index": 0, "input_type": "image", "embedding": [10.0, 0.0]},
        {"object": "embedding", "index": 1, "input_type": "text", "embedding": [20.0, 0.0]},
    ]
    assert payload["dimensions"] == 2
    assert payload["normalized"] is False
    assert "secret text" not in str(payload)


def test_fake_open_clip_backend_returns_image_and_text_vectors_through_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    model_dir = create_local_image_embedding_folder(client, "fake-open-clip")
    (model_dir / "model.pt").write_bytes(b"fake")
    profile = create_profile(
        client,
        provider_model_id="image_embedding/fake-open-clip",
        architecture="open_clip",
        metadata={"open_clip_model_name": "ViT-B-32", "open_clip_checkpoint": "model.pt"},
    )
    install_fake_open_clip_backend(monkeypatch)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['id']}",
            "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "secret text"}],
            "normalize": False,
        },
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 200, response.text
    assert payload["architecture"] == "open_clip"
    assert payload["data"] == [
        {"object": "embedding", "index": 0, "input_type": "image", "embedding": [30.0, 0.0]},
        {"object": "embedding", "index": 1, "input_type": "text", "embedding": [40.0, 0.0]},
    ]
    assert "secret text" not in str(payload)


def test_open_clip_missing_checkpoint_returns_sanitized_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "open-clip-no-checkpoint")
    profile = create_profile(
        client,
        provider_model_id="image_embedding/open-clip-no-checkpoint",
        architecture="open_clip",
        metadata={"open_clip_model_name": "ViT-B-32", "open_clip_checkpoint": "secret-model.pt"},
    )

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]},
        headers=auth_headers(),
    )

    rendered = str(response.json())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "secret-model.pt" not in rendered
    assert str(tmp_path) not in rendered
    assert "AAAA" not in rendered


def test_real_runtime_invalid_base64_is_sanitized_and_does_not_persist_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "invalid-image")
    profile = create_profile(client, provider_model_id="image_embedding/invalid-image", architecture="clip")
    before = capture_stateless_persistence_snapshot(state)

    from ai_workbench.core.inference.clip_runtime import ClipEmbeddingRuntime

    monkeypatch.setattr(ClipEmbeddingRuntime, "_load", lambda self: (FakeClipModel(), FakeClipProcessor(), FakeTorch))

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "not base64 secret"}]},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "not base64 secret" not in rendered
    assert "traceback" not in rendered
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))


def test_real_clip_fake_backend_success_is_stateless_and_unload_clears_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "stateless-clip")
    profile = create_profile(client, provider_model_id="image_embedding/stateless-clip", architecture="clip")
    install_fake_clip_backend(monkeypatch)
    before = capture_stateless_persistence_snapshot(state)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}], "normalize": False},
        headers=auth_headers(),
    )
    status_loaded = client.get("/api/inference/status", headers=auth_headers())
    unload = client.post("/api/inference/unload", json={"target": "multimodal_embedding"}, headers=auth_headers())
    status_unloaded = client.get("/api/inference/status", headers=auth_headers())

    assert response.status_code == 200, response.text
    assert status_loaded.json()["runtime"]["multimodal_embedding_cache"]["runtime_count"] == 1
    assert unload.status_code == 200
    assert unload.json()["results"][0]["removed"] == 1
    assert status_unloaded.json()["runtime"]["multimodal_embedding_cache"]["runtime_count"] == 0
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))
    assert "AAAA" not in str(response.json())


def test_real_siglip2_fake_backend_success_is_stateless_and_unload_clears_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "stateless-siglip2")
    profile = create_profile(client, provider_model_id="image_embedding/stateless-siglip2", architecture="siglip2")
    calls = install_fake_siglip2_backend(monkeypatch)
    before = capture_stateless_persistence_snapshot(state)

    first = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}], "normalize": False},
        headers=auth_headers(),
    )
    status_loaded = client.get("/api/inference/status", headers=auth_headers())
    unload = client.post("/api/inference/unload", json={"target": "multimodal_embedding"}, headers=auth_headers())
    status_unloaded = client.get("/api/inference/status", headers=auth_headers())
    second = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}], "normalize": False},
        headers=auth_headers(),
    )

    assert first.status_code == 200, first.text
    assert status_loaded.json()["runtime"]["multimodal_embedding_cache"]["runtime_count"] == 1
    assert unload.status_code == 200
    assert unload.json()["results"][0]["removed"] == 1
    assert status_unloaded.json()["runtime"]["multimodal_embedding_cache"]["runtime_count"] == 0
    assert second.status_code == 200, second.text
    assert calls["load"] == 2
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))
    assert "AAAA" not in str(first.json())
    assert "AAAA" not in str(second.json())


@pytest.mark.parametrize("architecture", ["clip", "siglip2"])
def test_text_input_rejected_before_real_runtime_when_profile_image_only(
    architecture: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_image_embedding_folder(client, "image-only")
    profile = create_profile(
        client,
        provider_model_id="image_embedding/image-only",
        architecture=architecture,
        supported_input_types=["image"],
    )
    calls = install_fake_siglip2_backend(monkeypatch) if architecture == "siglip2" else install_fake_clip_backend(monkeypatch)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "text", "text": "secret text"}]},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"
    assert calls == {"load": 0, "image": 0}
    assert "secret text" not in str(response.json())
