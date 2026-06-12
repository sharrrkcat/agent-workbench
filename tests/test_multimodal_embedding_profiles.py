from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from ai_workbench.api.main import create_app
from ai_workbench.core.inference.multimodal_runtime import (
    MultimodalEmbeddingResult,
    clear_multimodal_embedding_runtime_factories,
    clear_multimodal_runtime_cache,
    register_multimodal_embedding_runtime_factory,
)
from ai_workbench.core.inference.stateless_guard import assert_snapshot_unchanged, capture_stateless_persistence_snapshot
from ai_workbench.core.provider_inventory import scan_internal_provider_models
from ai_workbench.db.database import get_engine, init_db
from tests.test_prompt_agent_execution import FakeLLMRuntime
from tests.test_stateless_inference_skeleton import auth_headers, enable_inference


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, use_memory: bool = True) -> TestClient:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=use_memory, root=tmp_path))


def create_profile(client: TestClient, **overrides) -> dict:
    folder = overrides.pop("folder", f"model-{uuid4().hex[:8]}")
    payload = {
        "name": "SigLIP2 Image Embeddings",
        "provider_model_id": f"image_embedding/{folder}",
        "architecture": "siglip2",
        "backend": "transformers",
        "supported_input_types": ["image", "text"],
    }
    payload.update(overrides)
    response = client.post("/api/inference/multimodal-embedding-models", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class FakeMultimodalRuntime:
    instances = []

    def __init__(self, profile) -> None:
        self.profile_id = profile.id
        self.calls = []
        self.unloaded = False
        FakeMultimodalRuntime.instances.append(self)

    def embed(self, *, profile, inputs, normalize: bool):
        self.calls.append({"profile_id": profile.id, "inputs": [item.input_type for item in inputs], "normalize": normalize})
        return type("Result", (), {"vectors": [[float(index), float(index + 1)] for index, _ in enumerate(inputs)]})()

    def unload(self) -> None:
        self.unloaded = True


class FailingMultimodalRuntime:
    def __init__(self, profile) -> None:
        self.profile_id = profile.id

    def embed(self, *, profile, inputs, normalize: bool):
        raise RuntimeError("secret=provider-secret payload=AAAA vector=[9.9] path=C:\\models\\fake")


class NonNumericMultimodalRuntime(FakeMultimodalRuntime):
    def embed(self, *, profile, inputs, normalize: bool):
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[["not-a-number"] for _ in inputs])


class WrongCountMultimodalRuntime(FakeMultimodalRuntime):
    def embed(self, *, profile, inputs, normalize: bool):
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[[1.0, 2.0]])


class RaggedMultimodalRuntime(FakeMultimodalRuntime):
    def embed(self, *, profile, inputs, normalize: bool):
        super().embed(profile=profile, inputs=inputs, normalize=normalize)
        return MultimodalEmbeddingResult(vectors=[[1.0, 2.0], [3.0]])


def teardown_function() -> None:
    clear_multimodal_embedding_runtime_factories()
    clear_multimodal_runtime_cache()
    FakeMultimodalRuntime.instances.clear()


def test_multimodal_profile_table_and_defaults_exist_on_old_db(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE appmetadatarecord (key VARCHAR PRIMARY KEY NOT NULL, value VARCHAR NOT NULL, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO appmetadatarecord (key, value) VALUES ('schema_version', '1')"))
        connection.execute(
            text(
                """
                CREATE TABLE multimodal_embedding_model_profiles (
                  id VARCHAR PRIMARY KEY NOT NULL,
                  name VARCHAR NOT NULL,
                  description VARCHAR DEFAULT '',
                  notes VARCHAR DEFAULT '',
                  enabled BOOLEAN DEFAULT 1,
                  external_inference_enabled BOOLEAN DEFAULT 0,
                  provider_profile_id VARCHAR,
                  provider_model_id VARCHAR NOT NULL DEFAULT '',
                  architecture VARCHAR NOT NULL,
                  backend VARCHAR DEFAULT 'auto',
                  embedding_space VARCHAR,
                  dimensions INTEGER,
                  normalize_default BOOLEAN DEFAULT 1,
                  supported_input_types_json VARCHAR DEFAULT '["image", "text"]',
                  preprocessing_signature VARCHAR,
                  pooling_strategy VARCHAR DEFAULT 'model_default',
                  max_batch_size INTEGER,
                  metadata_json VARCHAR DEFAULT '{}',
                  created_at DATETIME,
                  updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO multimodal_embedding_model_profiles "
                "(id, name, provider_model_id, architecture, created_at, updated_at) VALUES "
                "('m1', 'CLIP Model', 'image_embedding/clip-a', 'clip', '2024-01-01', '2024-01-01'), "
                "('m2', 'CLIP Model', 'image_embedding/clip-b', 'clip', '2024-01-02', '2024-01-02')"
            )
        )

    init_db(engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(multimodal_embedding_model_profiles)").fetchall()}
        rows = [tuple(row) for row in connection.exec_driver_sql("SELECT id, alias FROM multimodal_embedding_model_profiles ORDER BY id").fetchall()]
    assert {"id", "alias", "provider_model_id", "architecture", "external_inference_enabled", "supported_input_types_json"} <= columns
    assert rows == [("m1", "clip-model"), ("m2", "clip-model-2")]


def test_crud_validates_architecture_refs_unknown_fields_and_delete_keeps_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    model_dir = tmp_path / "data" / "models" / "image_embeddings" / "clip-a"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    clip = create_profile(client, name="OpenCLIP", architecture="open_clip", provider_model_id="image_embedding/clip-a", external_inference_enabled=True)
    siglip = create_profile(client, name="SigLIP2", alias="siglip-profile", architecture="siglip2", provider_model_id="image_embedding/siglip")
    dinov2 = create_profile(client, name="DINOv2", architecture="dinov2", provider_model_id="image_embedding/dino", supported_input_types=["image"])

    assert clip["alias"] == "openclip"
    assert siglip["alias"] == "siglip-profile"
    assert clip["enabled"] is True
    assert siglip["external_inference_enabled"] is False
    assert dinov2["supported_input_types"] == ["image"]
    assert client.get(f"/api/inference/multimodal-embedding-models/{siglip['alias']}").json()["id"] == siglip["id"]
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "alias": "Bad Alias", "architecture": "clip", "provider_model_id": "image_embedding/x"}).status_code == 422
    duplicate_alias = client.post("/api/inference/multimodal-embedding-models", json={"name": "Duplicate", "alias": siglip["alias"], "architecture": "clip", "provider_model_id": "image_embedding/duplicate"})
    assert duplicate_alias.status_code == 409
    assert duplicate_alias.json()["error"]["code"] == "MULTIMODAL_EMBEDDING_ALIAS_EXISTS"
    assert client.post("/api/inference/multimodal-embedding-models", json={**dinov2, "id": "x", "supported_input_types": ["image", "text"]}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "bad", "provider_model_id": "image_embedding/x"}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "clip", "provider_model_id": "../x"}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "clip", "provider_model_id": "C:\\x"}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "clip", "provider_model_id": "image_embedding/x", "unknown": True}).json()["error"]["code"] == "UNKNOWN_MULTIMODAL_EMBEDDING_FIELD"

    renamed = client.patch(f"/api/inference/multimodal-embedding-models/{siglip['alias']}", json={"alias": "siglip-renamed"}).json()
    assert renamed["alias"] == "siglip-renamed"
    duplicate_patch = client.patch(f"/api/inference/multimodal-embedding-models/{renamed['id']}", json={"alias": dinov2["alias"]})
    assert duplicate_patch.status_code == 409
    assert duplicate_patch.json()["error"]["code"] == "MULTIMODAL_EMBEDDING_ALIAS_EXISTS"
    patched = client.patch(f"/api/inference/multimodal-embedding-models/{renamed['id']}", json={"external_inference_enabled": True}).json()
    assert patched["external_inference_enabled"] is True
    deleted = client.delete(f"/api/inference/multimodal-embedding-models/{clip['id']}").json()
    assert deleted == {"deleted": True, "profile_id": clip["id"]}
    deleted_by_alias = client.delete(f"/api/inference/multimodal-embedding-models/{dinov2['alias']}").json()
    assert deleted_by_alias == {"deleted": True, "profile_id": dinov2["id"]}
    assert model_dir.exists()


def test_multimodal_profile_aliases_work_with_sql_store(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'multimodal.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, database_url=db_url))
    profile = create_profile(client, alias="sql-multimodal", provider_model_id="image_embedding/sql-model")

    duplicate = client.post(
        "/api/inference/multimodal-embedding-models",
        json={"name": "Duplicate", "alias": "sql-multimodal", "architecture": "clip", "provider_model_id": "image_embedding/other"},
    )
    restarted = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, database_url=db_url))

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "MULTIMODAL_EMBEDDING_ALIAS_EXISTS"
    assert restarted.get("/api/inference/multimodal-embedding-models/sql-multimodal").json()["id"] == profile["id"]


def test_image_embedding_inventory_returns_safe_refs_and_no_optional_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    model_dir = root / "data" / "models" / "image_embeddings" / "siglip-local"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    checked_specs: list[str] = []

    def record_find_spec(name: str):
        checked_specs.append(name)
        return None

    monkeypatch.setattr("importlib.util.find_spec", record_find_spec)
    inventory = scan_internal_provider_models("internal_transformers", root)
    image_items = [item for item in inventory["models"] if item["type"] == "image_embedding"]

    assert image_items
    assert image_items[0]["id"] == "image_embedding/siglip-local"
    assert image_items[0]["relative_path"] == "image_embeddings/siglip-local"
    assert str(root) not in str(image_items)
    assert (root / "data" / "models" / "image_embeddings").is_dir()
    assert "open_clip" not in checked_specs


def test_image_embedding_model_inventory_endpoint_returns_internal_transformers_safe_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    models_root = tmp_path / "data" / "models"
    image_dir = models_root / "image_embeddings" / "clip-local"
    image_dir.mkdir(parents=True)
    (image_dir / "config.json").write_text("{}", encoding="utf-8")
    (models_root / "image_embeddings" / "gguf-file.gguf").write_text("", encoding="utf-8")
    llm_dir = models_root / "llms" / "qwen"
    llm_dir.mkdir(parents=True)
    (llm_dir / "config.json").write_text("{}", encoding="utf-8")
    reranker_dir = models_root / "rerankers" / "ranker"
    reranker_dir.mkdir(parents=True)
    (reranker_dir / "config.json").write_text("{}", encoding="utf-8")
    vision_dir = models_root / "vision" / "florence"
    vision_dir.mkdir(parents=True)
    (vision_dir / "config.json").write_text("{}", encoding="utf-8")

    response = client.get("/api/inference/model-inventory?kind=image_embedding")
    invalid = client.get("/api/inference/model-inventory?kind=llm")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "image_embedding"
    assert payload["models_root"] == "data/models"
    assert payload["items"] == [
        {
            "ref": "image_embedding/clip-local",
            "name": "clip-local",
            "kind": "image_embedding",
            "relative_path": "image_embeddings/clip-local",
        }
    ]
    assert str(tmp_path) not in str(payload)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_MODEL_INVENTORY_KIND"


def test_model_lists_include_multimodal_only_in_workbench_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    allowed = create_profile(client, name="Allowed", architecture="clip", provider_model_id="image_embedding/allowed", external_inference_enabled=True)
    blocked = create_profile(client, name="Blocked", architecture="clip", provider_model_id="image_embedding/blocked")
    disabled = create_profile(client, name="Disabled", architecture="clip", provider_model_id="image_embedding/disabled", external_inference_enabled=True, enabled=False)

    workbench = client.get("/api/inference/models").json()
    openai = client.get("/v1/models").json()

    ids = {item["id"] for item in workbench["data"]}
    assert f"multimodal:{allowed['alias']}" in ids
    assert f"multimodal:{allowed['id']}" not in ids
    assert f"multimodal:{blocked['alias']}" not in ids
    assert f"multimodal:{disabled['alias']}" not in ids
    listed = next(item for item in workbench["data"] if item["id"] == f"multimodal:{allowed['alias']}")
    assert listed["profile_id"] == allowed["id"]
    assert listed["profile_alias"] == allowed["alias"]
    assert listed["legacy_model_id"] == f"multimodal:{allowed['id']}"
    assert workbench["summary"]["multimodal_profiles_available"] == 1
    assert all(not item["id"].startswith("multimodal:") for item in openai["data"])


def test_multimodal_route_validates_then_returns_sanitized_runtime_error_and_is_stateless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    clip = create_profile(client, architecture="clip", provider_model_id="image_embedding/clip", external_inference_enabled=True)
    dino = create_profile(client, architecture="dinov2", provider_model_id="image_embedding/dino", supported_input_types=["image"], external_inference_enabled=True)
    limited = create_profile(client, architecture="clip", provider_model_id="image_embedding/limited", external_inference_enabled=True, max_batch_size=1)
    blocked = create_profile(client, architecture="siglip2", provider_model_id="image_embedding/blocked", external_inference_enabled=False)

    def fail(*args, **kwargs):
        raise AssertionError("multimodal route must not call runtime/storage helpers")

    monkeypatch.setattr(state.runtime, "handle_input", fail)
    monkeypatch.setattr(state.agent_runner, "run", fail, raising=False)
    monkeypatch.setattr(state.command_runner, "run", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_data_url", fail)
    monkeypatch.setattr("ai_workbench.core.embedding.embed_texts", fail)
    monkeypatch.setattr(state.runtimes.get_runtime("llm"), "chat", fail)

    ok = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{clip['alias']}", "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "red"}], "normalize": True},
    )
    dino_text = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{dino['id']}", "inputs": [{"type": "text", "text": "red"}]})
    invalid_type = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{clip['id']}", "inputs": [{"type": "image_url", "url": "https://example.invalid/x.png"}]})
    batch_too_large = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{limited['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "image_base64", "data": "BBBB"}]})
    unknown = client.post("/api/inference/embeddings/multimodal", json={"model": "multimodal:missing", "inputs": [{"type": "image_base64", "data": "AAAA"}]})
    not_allowed = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{blocked['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]})
    wrong_type = client.post("/api/inference/embeddings/multimodal", json={"model": "embedding:x", "inputs": [{"type": "image_base64", "data": "AAAA"}]})

    assert ok.status_code == 502
    assert ok.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "embedding" not in ok.json()
    assert dino_text.status_code == 400
    assert dino_text.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"
    assert invalid_type.status_code == 400
    assert invalid_type.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert batch_too_large.status_code == 400
    assert batch_too_large.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert not_allowed.status_code == 403
    assert not_allowed.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert wrong_type.status_code == 404
    assert wrong_type.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert state.messages.list_all_messages() == []
    assert state.runs.list_all_runs() == []


def test_multimodal_route_with_fake_runtime_returns_schema_and_does_not_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, architecture="siglip2", provider_model_id="image_embedding/fake", external_inference_enabled=True)
    before = capture_stateless_persistence_snapshot(state)
    register_multimodal_embedding_runtime_factory("siglip2", FakeMultimodalRuntime)

    def fail(*args, **kwargs):
        raise AssertionError("multimodal route called an unsafe helper")

    monkeypatch.setattr(state.runtime, "handle_input", fail)
    monkeypatch.setattr(state.agent_runner, "run", fail, raising=False)
    monkeypatch.setattr(state.command_runner, "run", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_data_url", fail)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_upload", fail)
    monkeypatch.setattr("ai_workbench.core.knowledge_indexing.upsert_indexed_source", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.embedding.embed_texts", fail)
    monkeypatch.setattr(state.runtimes.get_runtime("llm"), "chat", fail)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={
            "model": f"multimodal:{profile['alias']}",
            "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "red robot"}],
        },
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 200, response.text
    assert payload == {
        "object": "list",
        "model": f"multimodal:{profile['alias']}",
        "profile_id": profile["id"],
        "profile_alias": profile["alias"],
        "architecture": "siglip2",
        "embedding_space": f"siglip2/{profile['id']}/default",
        "dimensions": 2,
        "normalized": True,
        "data": [
            {"object": "embedding", "index": 0, "input_type": "image", "embedding": [0.0, 1.0]},
            {"object": "embedding", "index": 1, "input_type": "text", "embedding": [1.0, 2.0]},
        ],
        "usage": {"input_count": 2},
    }
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))
    assert "AAAA" not in str(payload)
    assert "red robot" not in str(payload)
    assert "multimodal" in payload["model"]


@pytest.mark.parametrize("architecture", ["clip", "open_clip", "siglip2"])
def test_clip_family_multimodal_profiles_accept_image_and_text_with_fake_runtime(
    architecture: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, architecture=architecture, provider_model_id=f"image_embedding/{architecture}", external_inference_enabled=True)
    register_multimodal_embedding_runtime_factory(architecture, FakeMultimodalRuntime)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "red"}]},
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert [item["input_type"] for item in response.json()["data"]] == ["image", "text"]


def test_multimodal_unload_clears_runtime_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, architecture="clip", provider_model_id="image_embedding/cache", external_inference_enabled=True)
    register_multimodal_embedding_runtime_factory("clip", FakeMultimodalRuntime)

    first = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())
    missing = client.post("/api/inference/unload", json={"target": "multimodal_embedding", "model": "multimodal:missing"}, headers=auth_headers())
    unload = client.post("/api/inference/unload", json={"target": "multimodal_embedding", "model": f"multimodal:{profile['alias']}"}, headers=auth_headers())
    second = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())

    assert first.status_code == 200
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert unload.status_code == 200
    assert unload.json()["results"][0]["target"] == "multimodal_embedding"
    assert second.status_code == 200


def test_multimodal_unload_rejects_non_object_json_without_clearing_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, architecture="clip", provider_model_id="image_embedding/cache", external_inference_enabled=True)
    register_multimodal_embedding_runtime_factory("clip", FakeMultimodalRuntime)

    first = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())
    invalid = client.post("/api/inference/unload", content=b"[]", headers={"content-type": "application/json", **auth_headers()})
    second = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())

    assert first.status_code == 200
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert second.status_code == 200
    assert len(FakeMultimodalRuntime.instances) == 1


def test_multimodal_unload_rejects_oversized_streamed_body_without_clearing_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False, max_request_mb=1)
    profile = create_profile(client, architecture="clip", provider_model_id="image_embedding/cache", external_inference_enabled=True)
    register_multimodal_embedding_runtime_factory("clip", FakeMultimodalRuntime)

    first = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())

    def chunks():
        yield b'{"target":"all","model":"multimodal:'
        yield b"missing"
        yield b'"}'
        yield b"A" * (2 * 1024 * 1024)

    invalid = client.post(
        "/api/inference/unload",
        content=chunks(),
        headers={"content-type": "application/json", **auth_headers()},
    )
    second = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())

    assert first.status_code == 200
    assert invalid.status_code == 413
    assert invalid.json()["error"]["code"] == "INFERENCE_REQUEST_TOO_LARGE"
    assert second.status_code == 200
    assert len(FakeMultimodalRuntime.instances) == 1


def test_multimodal_runtime_exception_is_normalized_without_payload_leaks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, architecture="clip", provider_model_id="image_embedding/failing", external_inference_enabled=True)
    register_multimodal_embedding_runtime_factory("clip", FailingMultimodalRuntime)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]},
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 502
    assert payload["error"]["code"] == "PROVIDER_ERROR"
    assert "provider-secret" not in str(payload)
    assert "AAAA" not in str(payload)
    assert "9.9" not in str(payload)
    assert "C:\\models\\fake" not in str(payload)


@pytest.mark.parametrize(
    ("runtime_cls", "expected_code"),
    [
        (NonNumericMultimodalRuntime, "PROVIDER_ERROR"),
        (WrongCountMultimodalRuntime, "PROVIDER_ERROR"),
        (RaggedMultimodalRuntime, "PROVIDER_ERROR"),
    ],
)
def test_multimodal_invalid_fake_runtime_outputs_are_sanitized(
    runtime_cls,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_profile(client, architecture="clip", provider_model_id="image_embedding/fake", external_inference_enabled=True)
    register_multimodal_embedding_runtime_factory("clip", runtime_cls)

    response = client.post(
        "/api/inference/embeddings/multimodal",
        json={"model": f"multimodal:{profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "red"}]},
        headers=auth_headers(),
    )

    payload = response.json()
    rendered = str(payload)
    assert response.status_code == 502
    assert payload["error"]["code"] == expected_code
    assert "not-a-number" not in rendered
    assert "AAAA" not in rendered
    assert "red" not in rendered
    assert "1.0" not in rendered
    assert "C:\\models\\fake" not in rendered


def test_multimodal_route_guards_before_body_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    assert client.post("/api/inference/embeddings/multimodal", content=b'{"malformed"').status_code == 503

    enable_inference(client)
    missing_auth = client.post("/api/inference/embeddings/multimodal", content=b'{"malformed"')
    assert missing_auth.status_code == 401
    assert missing_auth.json()["error"]["code"] == "INFERENCE_AUTH_REQUIRED"

    malformed = client.post("/api/inference/embeddings/multimodal", content=b'{"malformed"', headers=auth_headers())
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
