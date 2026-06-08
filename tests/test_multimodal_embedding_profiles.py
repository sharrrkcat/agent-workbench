from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from ai_workbench.api.main import create_app
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


def test_multimodal_profile_table_and_defaults_exist_on_old_db(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE appmetadatarecord (key VARCHAR PRIMARY KEY NOT NULL, value VARCHAR NOT NULL, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO appmetadatarecord (key, value) VALUES ('schema_version', '1')"))

    init_db(engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(multimodal_embedding_model_profiles)").fetchall()}
    assert {"id", "provider_model_id", "architecture", "external_inference_enabled", "supported_input_types_json"} <= columns


def test_crud_validates_architecture_refs_unknown_fields_and_delete_keeps_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    model_dir = tmp_path / "data" / "models" / "image_embeddings" / "clip-a"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    clip = create_profile(client, name="OpenCLIP", architecture="open_clip", provider_model_id="image_embedding/clip-a", external_inference_enabled=True)
    siglip = create_profile(client, name="SigLIP2", architecture="siglip2", provider_model_id="image_embedding/siglip")
    dinov2 = create_profile(client, name="DINOv2", architecture="dinov2", provider_model_id="image_embedding/dino", supported_input_types=["image"])

    assert clip["enabled"] is True
    assert siglip["external_inference_enabled"] is False
    assert dinov2["supported_input_types"] == ["image"]
    assert client.post("/api/inference/multimodal-embedding-models", json={**dinov2, "id": "x", "supported_input_types": ["image", "text"]}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "bad", "provider_model_id": "image_embedding/x"}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "clip", "provider_model_id": "../x"}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "clip", "provider_model_id": "C:\\x"}).status_code == 422
    assert client.post("/api/inference/multimodal-embedding-models", json={"name": "Bad", "architecture": "clip", "provider_model_id": "image_embedding/x", "unknown": True}).json()["error"]["code"] == "UNKNOWN_MULTIMODAL_EMBEDDING_FIELD"

    patched = client.patch(f"/api/inference/multimodal-embedding-models/{siglip['id']}", json={"external_inference_enabled": True}).json()
    assert patched["external_inference_enabled"] is True
    deleted = client.delete(f"/api/inference/multimodal-embedding-models/{clip['id']}").json()
    assert deleted == {"deleted": True, "profile_id": clip["id"]}
    assert model_dir.exists()


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


def test_model_lists_include_multimodal_only_in_workbench_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    allowed = create_profile(client, name="Allowed", architecture="clip", provider_model_id="image_embedding/allowed", external_inference_enabled=True)
    blocked = create_profile(client, name="Blocked", architecture="clip", provider_model_id="image_embedding/blocked")
    disabled = create_profile(client, name="Disabled", architecture="clip", provider_model_id="image_embedding/disabled", external_inference_enabled=True, enabled=False)

    workbench = client.get("/api/inference/models").json()
    openai = client.get("/v1/models").json()

    ids = {item["id"] for item in workbench["data"]}
    assert f"multimodal:{allowed['id']}" in ids
    assert f"multimodal:{blocked['id']}" not in ids
    assert f"multimodal:{disabled['id']}" not in ids
    assert workbench["summary"]["multimodal_profiles_available"] == 1
    assert all(not item["id"].startswith("multimodal:") for item in openai["data"])


def test_multimodal_route_validates_then_returns_not_implemented_and_is_stateless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    clip = create_profile(client, architecture="clip", provider_model_id="image_embedding/clip", external_inference_enabled=True)
    dino = create_profile(client, architecture="dinov2", provider_model_id="image_embedding/dino", supported_input_types=["image"], external_inference_enabled=True)
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
        json={"model": f"multimodal:{clip['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}, {"type": "text", "text": "red"}], "normalize": True},
    )
    dino_text = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{dino['id']}", "inputs": [{"type": "text", "text": "red"}]})
    unknown = client.post("/api/inference/embeddings/multimodal", json={"model": "multimodal:missing", "inputs": [{"type": "image_base64", "data": "AAAA"}]})
    not_allowed = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{blocked['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]})
    wrong_type = client.post("/api/inference/embeddings/multimodal", json={"model": "embedding:x", "inputs": [{"type": "image_base64", "data": "AAAA"}]})

    assert ok.status_code == 501
    assert ok.json()["error"]["code"] == "INFERENCE_NOT_IMPLEMENTED"
    assert "embedding" not in ok.json()
    assert dino_text.status_code == 400
    assert dino_text.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert not_allowed.status_code == 403
    assert not_allowed.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert wrong_type.status_code == 404
    assert wrong_type.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert state.messages.list_all_messages() == []
    assert state.runs.list_all_runs() == []


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
