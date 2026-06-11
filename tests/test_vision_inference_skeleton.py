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
from ai_workbench.core.inference.vision_runtime import (
    VisionRuntimeResult,
    clear_vision_runtime_cache,
    clear_vision_runtime_factories,
    register_vision_runtime_factory,
)
from ai_workbench.core.provider_inventory import scan_internal_provider_models
from ai_workbench.db.database import get_engine, init_db
from tests.test_prompt_agent_execution import FakeLLMRuntime
from tests.test_stateless_inference_skeleton import auth_headers, enable_inference


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, use_memory: bool = True) -> TestClient:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=use_memory, root=tmp_path))


def create_vision_profile(client: TestClient, **overrides) -> dict:
    folder = overrides.pop("folder", f"vision-{uuid4().hex[:8]}")
    payload = {
        "name": "Florence2 Vision",
        "provider_model_id": f"vision/{folder}",
        "architecture": "florence2",
        "backend": "transformers",
        "supported_tasks": ["caption", "detailed_caption", "ocr", "object_detection"],
    }
    payload.update(overrides)
    response = client.post("/api/inference/vision-models", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def create_multimodal_profile(client: TestClient, **overrides) -> dict:
    folder = overrides.pop("folder", f"image-{uuid4().hex[:8]}")
    payload = {
        "name": "Image Embeddings",
        "provider_model_id": f"image_embedding/{folder}",
        "architecture": "clip",
        "supported_input_types": ["image", "text"],
        "external_inference_enabled": True,
    }
    payload.update(overrides)
    response = client.post("/api/inference/multimodal-embedding-models", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class FakeVisionRuntime:
    instances = []

    def __init__(self, profile) -> None:
        self.profile_id = profile.id
        self.calls = []
        self.unloaded = False
        FakeVisionRuntime.instances.append(self)

    def run(self, *, profile, task: str, input, options: dict):
        self.calls.append({"profile_id": profile.id, "task": task, "options": options})
        if task == "object_detection":
            return VisionRuntimeResult(
                data={
                    "type": "objects",
                    "objects": [
                        {
                            "label": "cat",
                            "score": 0.98,
                            "box": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.5, "y_max": 0.7},
                        }
                    ],
                }
            )
        text = {"caption": "a short caption", "detailed_caption": "a detailed caption", "ocr": "OCR text"}[task]
        return VisionRuntimeResult(data={"type": "text", "text": text})

    def unload(self) -> None:
        self.unloaded = True


class BadVisionRuntime(FakeVisionRuntime):
    def run(self, *, profile, task: str, input, options: dict):
        super().run(profile=profile, task=task, input=input, options=options)
        return VisionRuntimeResult(
            data={
                "type": "objects",
                "objects": [
                    {
                        "label": "secret-object-label",
                        "score": float("nan"),
                        "box": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.5, "y_max": 0.7},
                    }
                ],
            }
        )


class FakeMultimodalRuntime:
    instances = []

    def __init__(self, profile) -> None:
        self.unloaded = False
        FakeMultimodalRuntime.instances.append(self)

    def embed(self, *, profile, inputs, normalize: bool):
        return MultimodalEmbeddingResult(vectors=[[0.0, 1.0] for _ in inputs])

    def unload(self) -> None:
        self.unloaded = True


def teardown_function() -> None:
    clear_vision_runtime_factories()
    clear_vision_runtime_cache()
    clear_multimodal_embedding_runtime_factories()
    clear_multimodal_runtime_cache()
    FakeVisionRuntime.instances.clear()
    FakeMultimodalRuntime.instances.clear()


def test_vision_profile_table_defaults_and_safe_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "old.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE appmetadatarecord (key VARCHAR PRIMARY KEY NOT NULL, value VARCHAR NOT NULL, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO appmetadatarecord (key, value) VALUES ('schema_version', '1')"))

    init_db(engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(vision_model_profiles)").fetchall()}
    assert {"id", "provider_model_id", "architecture", "external_inference_enabled", "supported_tasks_json"} <= columns

    client = make_client(tmp_path, monkeypatch)
    profile = create_vision_profile(client, provider_model_id="vision/florence")
    assert profile["external_inference_enabled"] is False
    assert profile["architecture"] == "florence2"
    assert profile["supported_tasks"] == ["caption", "detailed_caption", "ocr", "object_detection"]
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "../x"}).status_code == 422
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "C:\\x"}).status_code == 422
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "image_embedding/x"}).status_code == 422
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "vision/x", "unknown": True}).json()["error"]["code"] == "UNKNOWN_VISION_MODEL_FIELD"


def test_vision_inventory_returns_safe_refs_without_optional_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_dir = tmp_path / "data" / "models" / "vision" / "florence-local"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    checked_specs: list[str] = []

    def record_find_spec(name: str):
        checked_specs.append(name)
        return None

    monkeypatch.setattr("importlib.util.find_spec", record_find_spec)
    inventory = scan_internal_provider_models("internal_transformers", tmp_path)
    vision_items = [item for item in inventory["models"] if item["type"] == "vision"]

    assert vision_items
    assert vision_items[0]["id"] == "vision/florence-local"
    assert vision_items[0]["relative_path"] == "vision/florence-local"
    assert str(tmp_path) not in str(vision_items)
    assert (tmp_path / "data" / "models" / "vision").is_dir()
    assert "PIL" not in checked_specs


def test_model_lists_include_vision_only_in_workbench_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    allowed = create_vision_profile(client, external_inference_enabled=True)
    blocked = create_vision_profile(client)
    disabled = create_vision_profile(client, external_inference_enabled=True, enabled=False)

    workbench = client.get("/api/inference/models").json()
    openai = client.get("/v1/models").json()

    ids = {item["id"] for item in workbench["data"]}
    assert f"vision:{allowed['id']}" in ids
    assert f"vision:{blocked['id']}" not in ids
    assert f"vision:{disabled['id']}" not in ids
    assert workbench["summary"]["vision_profiles_available"] == 1
    assert all(not item["id"].startswith("vision:") for item in openai["data"])
    assert all(not item["id"].startswith("multimodal:") for item in openai["data"])


def test_vision_route_validates_allowlist_task_and_input_before_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    allowed = create_vision_profile(client, external_inference_enabled=True, supported_tasks=["caption"])
    blocked = create_vision_profile(client)

    production = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    unknown = client.post("/api/inference/vision", json={"model": "vision:missing", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    wrong_type = client.post("/api/inference/vision", json={"model": "multimodal:x", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    not_allowed = client.post("/api/inference/vision", json={"model": f"vision:{blocked['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    bad_task = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "classify", "input": {"type": "image", "image_base64": "AAAA"}})
    unsupported_task = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "ocr", "input": {"type": "image", "image_base64": "AAAA"}})
    text_input = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "caption", "input": {"type": "text", "text": "hello"}})

    assert production.status_code == 501
    assert production.json()["error"]["code"] == "INFERENCE_NOT_IMPLEMENTED"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert wrong_type.status_code == 404
    assert wrong_type.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert not_allowed.status_code == 403
    assert not_allowed.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert bad_task.status_code == 400
    assert bad_task.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert unsupported_task.status_code == 400
    assert unsupported_task.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"
    assert text_input.status_code == 400
    assert text_input.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"


@pytest.mark.parametrize(("task", "expected_type"), [("caption", "text"), ("ocr", "text"), ("object_detection", "objects")])
def test_fake_vision_runtime_returns_task_outputs_and_is_stateless(
    task: str,
    expected_type: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    profile = create_vision_profile(client, external_inference_enabled=True)
    register_vision_runtime_factory("florence2", FakeVisionRuntime)
    before = capture_stateless_persistence_snapshot(state)

    def fail(*args, **kwargs):
        raise AssertionError("vision route called an unsafe helper")

    monkeypatch.setattr(state.runtime, "handle_input", fail)
    monkeypatch.setattr(state.agent_runner, "run", fail, raising=False)
    monkeypatch.setattr(state.command_runner, "run", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_data_url", fail)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_upload", fail)
    monkeypatch.setattr("ai_workbench.core.knowledge_indexing.upsert_indexed_source", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.embedding.embed_texts", fail)
    monkeypatch.setattr(state.runtimes.get_runtime("llm"), "chat", fail)

    response = client.post(
        "/api/inference/vision",
        json={
            "model": f"vision:{profile['id']}",
            "task": task,
            "input": {"type": "image", "image_base64": "AAAA"},
            "options": {"detail": "safe"},
        },
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 200, response.text
    assert payload["object"] == "vision_result"
    assert payload["model"] == f"vision:{profile['id']}"
    assert payload["profile_id"] == profile["id"]
    assert payload["architecture"] == "florence2"
    assert payload["task"] == task
    assert payload["data"]["type"] == expected_type
    assert payload["usage"] == {"input_count": 1}
    assert "AAAA" not in str(payload)
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))


def test_invalid_fake_vision_output_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_vision_profile(client, external_inference_enabled=True)
    register_vision_runtime_factory("florence2", BadVisionRuntime)

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "object_detection", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    payload = response.json()
    rendered = str(payload).lower()
    assert response.status_code == 502
    assert payload["error"]["code"] == "PROVIDER_ERROR"
    assert "secret-object-label" not in rendered
    assert "nan" not in rendered
    assert "aaaa" not in rendered
    assert "traceback" not in rendered
    assert "c:\\models" not in rendered


def test_vision_unload_clears_vision_cache_without_breaking_multimodal_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    vision_profile = create_vision_profile(client, external_inference_enabled=True)
    multimodal_profile = create_multimodal_profile(client)
    register_vision_runtime_factory("florence2", FakeVisionRuntime)
    register_multimodal_embedding_runtime_factory("clip", FakeMultimodalRuntime)

    vision_first = client.post("/api/inference/vision", json={"model": f"vision:{vision_profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}}, headers=auth_headers())
    multimodal_first = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{multimodal_profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())
    unload = client.post("/api/inference/unload", json={"target": "vision"}, headers=auth_headers())
    vision_second = client.post("/api/inference/vision", json={"model": f"vision:{vision_profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}}, headers=auth_headers())
    multimodal_second = client.post("/api/inference/embeddings/multimodal", json={"model": f"multimodal:{multimodal_profile['id']}", "inputs": [{"type": "image_base64", "data": "AAAA"}]}, headers=auth_headers())

    assert vision_first.status_code == 200
    assert multimodal_first.status_code == 200
    assert unload.status_code == 200
    assert unload.json()["results"] == [{"target": "vision", "status": "freed", "removed": 1, "message": "Freed."}]
    assert vision_second.status_code == 200
    assert multimodal_second.status_code == 200
    assert len(FakeVisionRuntime.instances) == 2
    assert len(FakeMultimodalRuntime.instances) == 1


def test_status_and_models_do_not_construct_vision_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_vision_profile(client, external_inference_enabled=True)

    def fail_factory(profile):
        raise AssertionError("status/models must not construct vision runtimes")

    register_vision_runtime_factory("florence2", fail_factory)

    status = client.get("/api/inference/status")
    models = client.get("/api/inference/models")

    assert status.status_code == 200
    assert status.json()["runtime"]["vision_cache"] == {"runtime_count": 0, "profile_count": 0, "architecture_counts": {}}
    assert status.json()["models"]["vision_external_enabled_count"] == 1
    assert models.status_code == 200
    assert models.json()["summary"]["vision_profiles_available"] == 1
