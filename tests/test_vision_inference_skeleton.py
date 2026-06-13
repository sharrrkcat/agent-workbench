from pathlib import Path
import sys
from types import ModuleType
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
    VisionRuntimeError,
    VisionRuntimeInvalidRequest,
    VisionRuntimeResult,
    clear_vision_runtime_cache,
    clear_vision_runtime_factories,
    register_vision_runtime_factory,
    vision_runtime_cache_status,
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
    }
    payload.update(overrides)
    response = client.post("/api/inference/vision-models", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def create_local_vision_folder(client: TestClient, folder: str) -> Path:
    model_dir = client.app.state.runtime_state.repo_root / "data" / "models" / "vision" / folder
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    return model_dir


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
        text = {
            "caption": "a short caption",
            "detailed_caption": "a detailed caption",
            "more_detailed_caption": "a more detailed caption",
            "ocr": "OCR text",
        }[task]
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


class FakeVisionImage:
    size = (200, 100)


class FakeTinyVisionImage:
    size = (1, 1)


class FakeVisionTensor:
    def to(self, device):
        return self


class FakeFlorence2Model:
    def to(self, device):
        return self

    def eval(self):
        return None

    def generate(self, **kwargs):
        return ["generated_ids"]


class FakeFlorence2Processor:
    def __init__(self, *, task_outputs: dict[str, object]) -> None:
        self.task_outputs = task_outputs

    def __call__(self, *, text, images, return_tensors):
        return {"input_ids": FakeVisionTensor()}

    def batch_decode(self, generated_ids, skip_special_tokens=False):
        return ["generated text that must not leak in errors"]

    def post_process_generation(self, generated_text, *, task, image_size):
        return {task: self.task_outputs[task]}


class FakeFlorence2Torch:
    inference_entries = 0
    inference_exits = 0
    active = False

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

    @staticmethod
    def inference_mode():
        class Context:
            def __enter__(self):
                FakeFlorence2Torch.inference_entries += 1
                FakeFlorence2Torch.active = True
                return self

            def __exit__(self, exc_type, exc, traceback):
                FakeFlorence2Torch.inference_exits += 1
                FakeFlorence2Torch.active = False
                return False

        return Context()

    class no_grad:
        def __enter__(self):
            FakeFlorence2Torch.inference_entries += 1
            FakeFlorence2Torch.active = True
            return self

        def __exit__(self, exc_type, exc, traceback):
            FakeFlorence2Torch.inference_exits += 1
            FakeFlorence2Torch.active = False
            return False


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
        connection.execute(
            text(
                """
                CREATE TABLE vision_model_profiles (
                  id VARCHAR PRIMARY KEY NOT NULL,
                  name VARCHAR NOT NULL,
                  description VARCHAR DEFAULT '',
                  notes VARCHAR DEFAULT '',
                  enabled BOOLEAN DEFAULT 1,
                  external_inference_enabled BOOLEAN DEFAULT 0,
                  provider_profile_id VARCHAR,
                  provider_model_id VARCHAR NOT NULL DEFAULT '',
                  architecture VARCHAR NOT NULL DEFAULT 'florence2',
                  backend VARCHAR DEFAULT 'transformers',
                  supported_tasks_json VARCHAR DEFAULT '["caption", "detailed_caption", "more_detailed_caption", "ocr", "object_detection"]',
                  max_batch_size INTEGER DEFAULT 1,
                  metadata_json VARCHAR DEFAULT '{}',
                  created_at DATETIME,
                  updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO vision_model_profiles "
                "(id, name, provider_model_id, architecture, created_at, updated_at) VALUES "
                "('v1', 'Florence2 Vision', 'vision/florence-a', 'florence2', '2024-01-01', '2024-01-01'), "
                "('v2', 'Florence2 Vision', 'vision/florence-b', 'florence2', '2024-01-02', '2024-01-02')"
            )
        )

    init_db(engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(vision_model_profiles)").fetchall()}
        rows = [tuple(row) for row in connection.exec_driver_sql("SELECT id, alias FROM vision_model_profiles ORDER BY id").fetchall()]
    assert {"id", "alias", "provider_model_id", "architecture", "external_inference_enabled", "supported_tasks_json"} <= columns
    assert rows == [("v1", "florence2-vision"), ("v2", "florence2-vision-2")]

    client = make_client(tmp_path, monkeypatch)
    profile = create_vision_profile(client, provider_model_id="vision/florence")
    assert profile["external_inference_enabled"] is False
    assert profile["alias"] == "florence2-vision"
    assert profile["architecture"] == "florence2"
    assert profile["supported_tasks"] == ["caption", "detailed_caption", "more_detailed_caption", "ocr", "object_detection"]
    legacy = create_vision_profile(
        client,
        name="Legacy Vision",
        alias="legacy-vision",
        provider_model_id="vision/legacy",
        supported_tasks=["caption", "detailed_caption", "ocr", "object_detection"],
    )
    assert legacy["supported_tasks"] == ["caption", "detailed_caption", "ocr", "object_detection"]
    assert client.get(f"/api/inference/vision-models/{profile['alias']}").json()["id"] == profile["id"]
    invalid_alias = client.post("/api/inference/vision-models", json={"name": "Bad", "alias": "Bad Alias", "provider_model_id": "vision/x"})
    assert invalid_alias.status_code == 422
    duplicate_alias = client.post("/api/inference/vision-models", json={"name": "Duplicate", "alias": profile["alias"], "provider_model_id": "vision/duplicate"})
    assert duplicate_alias.status_code == 409
    assert duplicate_alias.json()["error"]["code"] == "VISION_MODEL_ALIAS_EXISTS"
    renamed = client.patch(f"/api/inference/vision-models/{profile['alias']}", json={"alias": "florence-renamed"}).json()
    assert renamed["alias"] == "florence-renamed"
    second = create_vision_profile(client, name="Second Vision", alias="second-vision", provider_model_id="vision/second")
    duplicate_patch = client.patch(f"/api/inference/vision-models/{renamed['id']}", json={"alias": second["alias"]})
    assert duplicate_patch.status_code == 409
    assert duplicate_patch.json()["error"]["code"] == "VISION_MODEL_ALIAS_EXISTS"
    deleted_by_alias = client.delete(f"/api/inference/vision-models/{second['alias']}").json()
    assert deleted_by_alias == {"deleted": True, "profile_id": second["id"]}
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "../x"}).status_code == 422
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "C:\\x"}).status_code == 422
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "image_embedding/x"}).status_code == 422
    assert client.post("/api/inference/vision-models", json={"name": "Bad", "provider_model_id": "vision/x", "unknown": True}).json()["error"]["code"] == "UNKNOWN_VISION_MODEL_FIELD"


def test_vision_profile_aliases_work_with_sql_store(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'vision.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, database_url=db_url))
    profile = create_vision_profile(client, alias="sql-vision", provider_model_id="vision/sql-model")

    duplicate = client.post(
        "/api/inference/vision-models",
        json={"name": "Duplicate", "alias": "sql-vision", "provider_model_id": "vision/other"},
    )
    restarted = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, database_url=db_url))

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "VISION_MODEL_ALIAS_EXISTS"
    assert restarted.get("/api/inference/vision-models/sql-vision").json()["id"] == profile["id"]


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


def test_vision_model_inventory_endpoint_returns_internal_transformers_safe_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    models_root = tmp_path / "data" / "models"
    vision_dir = models_root / "vision" / "florence-local"
    vision_dir.mkdir(parents=True)
    (vision_dir / "config.json").write_text("{}", encoding="utf-8")
    (models_root / "vision" / "not-a-directory.gguf").write_text("", encoding="utf-8")
    image_dir = models_root / "image_embeddings" / "clip-local"
    image_dir.mkdir(parents=True)
    (image_dir / "config.json").write_text("{}", encoding="utf-8")
    embedding_dir = models_root / "embeddings" / "bge"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "config.json").write_text("{}", encoding="utf-8")
    reranker_dir = models_root / "rerankers" / "ranker"
    reranker_dir.mkdir(parents=True)
    (reranker_dir / "config.json").write_text("{}", encoding="utf-8")

    response = client.get("/api/inference/model-inventory?kind=vision")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "vision"
    assert payload["models_root"] == "data/models"
    assert payload["items"] == [
        {
            "ref": "vision/florence-local",
            "name": "florence-local",
            "kind": "vision",
            "relative_path": "vision/florence-local",
        }
    ]
    assert str(tmp_path) not in str(payload)


def test_model_lists_include_vision_only_in_workbench_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    allowed = create_vision_profile(client, external_inference_enabled=True)
    blocked = create_vision_profile(client)
    disabled = create_vision_profile(client, external_inference_enabled=True, enabled=False)

    workbench = client.get("/api/inference/models").json()
    openai = client.get("/v1/models").json()

    ids = {item["id"] for item in workbench["data"]}
    assert f"vision:{allowed['alias']}" in ids
    assert f"vision:{allowed['id']}" not in ids
    assert f"vision:{blocked['alias']}" not in ids
    assert f"vision:{disabled['alias']}" not in ids
    listed = next(item for item in workbench["data"] if item["id"] == f"vision:{allowed['alias']}")
    assert listed["profile_id"] == allowed["id"]
    assert listed["profile_alias"] == allowed["alias"]
    assert listed["legacy_model_id"] == f"vision:{allowed['id']}"
    assert workbench["summary"]["vision_profiles_available"] == 1
    assert all(not item["id"].startswith("vision:") for item in openai["data"])
    assert all(not item["id"].startswith("multimodal:") for item in openai["data"])


def test_vision_route_validates_allowlist_task_and_input_before_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    allowed = create_vision_profile(client, external_inference_enabled=True, supported_tasks=["caption"])
    blocked = create_vision_profile(client)

    production = client.post("/api/inference/vision", json={"model": f"vision:{allowed['alias']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    unknown = client.post("/api/inference/vision", json={"model": "vision:missing", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    wrong_type = client.post("/api/inference/vision", json={"model": "multimodal:x", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    not_allowed = client.post("/api/inference/vision", json={"model": f"vision:{blocked['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}})
    bad_task = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "classify", "input": {"type": "image", "image_base64": "AAAA"}})
    unsupported_task = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "ocr", "input": {"type": "image", "image_base64": "AAAA"}})
    unsupported_more_detailed = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "more_detailed_caption", "input": {"type": "image", "image_base64": "AAAA"}})
    text_input = client.post("/api/inference/vision", json={"model": f"vision:{allowed['id']}", "task": "caption", "input": {"type": "text", "text": "hello"}})

    assert production.status_code == 502
    assert production.json()["error"]["code"] == "PROVIDER_ERROR"
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
    assert unsupported_more_detailed.status_code == 400
    assert unsupported_more_detailed.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"
    assert text_input.status_code == 400
    assert text_input.json()["error"]["code"] == "MODEL_INPUT_TYPE_UNSUPPORTED"


@pytest.mark.parametrize(
    ("task", "expected_type"),
    [("caption", "text"), ("more_detailed_caption", "text"), ("ocr", "text"), ("object_detection", "objects")],
)
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
            "model": f"vision:{profile['alias']}",
            "task": task,
            "input": {"type": "image", "image_base64": "AAAA"},
            "options": {"detail": "safe"},
        },
        headers=auth_headers(),
    )

    payload = response.json()
    assert response.status_code == 200, response.text
    assert payload["object"] == "vision_result"
    assert payload["model"] == f"vision:{profile['alias']}"
    assert payload["profile_id"] == profile["id"]
    assert payload["profile_alias"] == profile["alias"]
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


def install_fake_florence2_backend(monkeypatch: pytest.MonkeyPatch, *, task_outputs: dict[str, object] | None = None) -> dict[str, int]:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    calls = {"load": 0, "decode": 0}
    outputs = task_outputs or {
        "<CAPTION>": "a local caption",
        "<DETAILED_CAPTION>": "a local detailed caption",
        "<MORE_DETAILED_CAPTION>": "a local more detailed caption",
        "<OCR>": "local OCR text",
        "<OD>": {"labels": ["cat"], "bboxes": [[20.0, 10.0, 100.0, 80.0]], "scores": [0.98]},
    }

    def fake_load(self):
        calls["load"] += 1
        return FakeFlorence2Model(), FakeFlorence2Processor(task_outputs=outputs), FakeFlorence2Torch

    def fake_image(value):
        calls["decode"] += 1
        return FakeVisionImage()

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", fake_image)
    FakeFlorence2Torch.inference_entries = 0
    FakeFlorence2Torch.inference_exits = 0
    FakeFlorence2Torch.active = False
    return calls


def install_fake_florence2_transformers_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config_error: Exception | None = None,
    processor_error: Exception | None = None,
    model_error: Exception | None = None,
) -> dict[str, object]:
    calls: dict[str, object] = {"config": 0, "model": 0, "processor": 0, "unloaded": 0}

    torch_module = ModuleType("torch")

    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False

        @staticmethod
        def empty_cache() -> None:
            calls["unloaded"] = int(calls["unloaded"]) + 1

    class backends:
        class mps:
            @staticmethod
            def is_available() -> bool:
                return False

    torch_module.cuda = cuda
    torch_module.backends = backends

    transformers_module = ModuleType("transformers")
    transformers_module.__version__ = "5.0.0-test"

    class PretrainedConfig:
        pass

    class PreTrainedModel:
        pass

    class PreTrainedTokenizerBase:
        pass

    class AutoConfig:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["config"] = int(calls["config"]) + 1
            calls["config_kwargs"] = kwargs
            if config_error is not None:
                raise config_error
            return PretrainedConfig()

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["model"] = int(calls["model"]) + 1
            calls["model_kwargs"] = kwargs
            if model_error is not None:
                raise model_error

            class Model(PreTrainedModel):
                def to(self, device):
                    return self

                def eval(self):
                    return None

            return Model()

    class AutoProcessor:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["processor"] = int(calls["processor"]) + 1
            calls["processor_kwargs"] = kwargs
            if processor_error is not None:
                raise processor_error

            class Tokenizer(PreTrainedTokenizerBase):
                def __init__(self) -> None:
                    self.extra_special_tokens = {"image_token": "<image>"}
                    calls["observed_additional_special_tokens"] = self.additional_special_tokens

            class Processor:
                def __init__(self) -> None:
                    self.tokenizer = Tokenizer()

            return Processor()

    transformers_module.PretrainedConfig = PretrainedConfig
    transformers_module.PreTrainedModel = PreTrainedModel
    transformers_module.PreTrainedTokenizerBase = PreTrainedTokenizerBase
    transformers_module.AutoConfig = AutoConfig
    transformers_module.AutoModelForCausalLM = AutoModelForCausalLM
    transformers_module.AutoProcessor = AutoProcessor

    monkeypatch.setitem(sys.modules, "torch", torch_module)
    monkeypatch.setitem(sys.modules, "PIL", ModuleType("PIL"))
    monkeypatch.setitem(sys.modules, "transformers", transformers_module)
    calls["tokenizer_base_cls"] = PreTrainedTokenizerBase
    return calls


def test_real_florence2_runtime_load_is_lazy_until_valid_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "lazy-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/lazy-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    calls = install_fake_florence2_backend(monkeypatch)

    status = client.get("/api/inference/status")
    models = client.get("/api/inference/models")

    assert status.status_code == 200
    assert models.status_code == 200
    assert calls == {"load": 0, "decode": 0}

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"type": "text", "text": "a local caption"}
    assert calls == {"load": 1, "decode": 1}


def test_invalid_florence2_image_fails_before_model_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "bad-image-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/bad-image-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    calls = {"load": 0}

    def fail_load(self):
        calls["load"] += 1
        raise AssertionError("Florence2 _load should not run for invalid image input")

    def invalid_image(value):
        raise VisionRuntimeError("Invalid image input with fake-secret and AAAA.")

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fail_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", invalid_image)

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert calls["load"] == 0
    assert "aaaa" not in rendered
    assert "fake-secret" not in rendered
    assert "traceback" not in rendered


def test_tiny_florence2_image_returns_invalid_request_before_model_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "tiny-image-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/tiny-image-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    calls = {"load": 0}

    def fail_load(self):
        calls["load"] += 1
        raise AssertionError("Florence2 _load should not run for tiny image input")

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fail_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeTinyVisionImage())

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert "16x16" in response.json()["error"]["message"]
    assert calls["load"] == 0
    assert "aaaa" not in rendered
    assert "traceback" not in rendered
    assert str(tmp_path).lower() not in rendered


def test_missing_local_florence2_model_folder_returns_sanitized_provider_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_vision_profile(client, provider_model_id="vision/missing-florence2-folder", external_inference_enabled=True, metadata={"trust_remote_code": True})
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "missing-florence2-folder" not in rendered
    assert str(tmp_path).lower() not in rendered


def test_missing_florence2_optional_dependency_returns_sanitized_provider_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "missing-deps-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/missing-deps-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})

    def fail_load(self):
        raise VisionRuntimeError("Florence2 runtime dependencies are not installed: fake-secret-transformers.")

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fail_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "fake-secret-transformers" not in rendered
    assert "traceback" not in rendered


def test_florence2_trust_remote_code_is_explicit_metadata_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "trust-default")
    create_local_vision_folder(client, "trust-opt-in")
    default_profile = create_vision_profile(client, provider_model_id="vision/trust-default")
    trusted_profile = create_vision_profile(client, provider_model_id="vision/trust-opt-in", metadata={"trust_remote_code": True})

    default_runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(default_profile["id"]), repo_root=tmp_path)
    trusted_runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(trusted_profile["id"]), repo_root=tmp_path)

    assert default_runtime.trust_remote_code is False
    assert trusted_runtime.trust_remote_code is True


def test_florence2_runtime_fails_fast_without_trust_remote_code_before_model_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "trust-required")
    profile = create_vision_profile(client, provider_model_id="vision/trust-required", external_inference_enabled=True)
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    calls = install_fake_florence2_transformers_modules(monkeypatch)

    with pytest.raises(VisionRuntimeInvalidRequest) as exc_info:
        runtime._load()

    assert "metadata.trust_remote_code=true" in str(exc_info.value)
    assert calls["model"] == 0
    assert calls["processor"] == 0


def test_florence2_http_returns_invalid_request_when_trust_remote_code_is_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "trust-http")
    profile = create_vision_profile(client, provider_model_id="vision/trust-http", external_inference_enabled=True)
    calls = {"load": 0}

    def fail_load(self):
        calls["load"] += 1
        raise AssertionError("AutoModelForCausalLM.from_pretrained must not run")

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fail_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert "metadata.trust_remote_code=true" in response.json()["error"]["message"]
    assert calls["load"] == 0
    assert "aaaa" not in rendered
    assert "traceback" not in rendered


def test_florence2_load_passes_trust_remote_code_only_during_lazy_local_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "trust-load")
    profile = create_vision_profile(client, provider_model_id="vision/trust-load", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)

    records: dict[str, list[dict[str, object]]] = {"model": [], "processor": []}

    class FakeTorchModule(ModuleType):
        def __init__(self) -> None:
            super().__init__("torch")

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

            self.cuda = cuda
            self.backends = backends

    class FakeTransformersModule(ModuleType):
        class PretrainedConfig:
            pass

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(path, **kwargs):
                records["model"].append({"path": path, "kwargs": kwargs})

                class Model:
                    def to(self, device):
                        return self

                    def eval(self):
                        return None

                return Model()

        class AutoProcessor:
            @staticmethod
            def from_pretrained(path, **kwargs):
                records["processor"].append({"path": path, "kwargs": kwargs})

                class Processor:
                    pass

                return Processor()

    monkeypatch.setitem(sys.modules, "torch", FakeTorchModule())
    monkeypatch.setitem(sys.modules, "transformers", FakeTransformersModule("transformers"))

    model, processor, torch = runtime._load()

    assert model is not None
    assert processor is not None
    assert torch is not None
    assert records["model"][0]["kwargs"]["local_files_only"] is True
    assert records["model"][0]["kwargs"]["trust_remote_code"] is True
    assert records["model"][0]["kwargs"]["attn_implementation"] == "eager"
    assert records["processor"][0]["kwargs"]["local_files_only"] is True
    assert records["processor"][0]["kwargs"]["trust_remote_code"] is True
    assert records["processor"][0]["kwargs"]["attn_implementation"] == "eager"


def test_florence2_generation_casts_float_inputs_to_model_dtype(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "dtype-cast")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/dtype-cast",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    records: dict[str, object] = {}

    class Tensor:
        def __init__(self, *, dtype: str, floating: bool) -> None:
            self.dtype = dtype
            self.floating = floating
            self.to_calls: list[dict[str, object]] = []

        def is_floating_point(self) -> bool:
            return self.floating

        def to(self, *args, **kwargs):
            self.to_calls.append({"args": args, "kwargs": kwargs})
            if args:
                self.device = args[0]
            if "device" in kwargs:
                self.device = kwargs["device"]
            if "dtype" in kwargs:
                self.dtype = kwargs["dtype"]
            elif len(args) > 1:
                self.dtype = args[1]
            return self

    class BatchEncoding:
        def __init__(self) -> None:
            self.pixel_values = Tensor(dtype="float32", floating=True)
            self.input_ids = Tensor(dtype="int64", floating=False)

        def items(self):
            return {"pixel_values": self.pixel_values, "input_ids": self.input_ids}.items()

    class Model:
        dtype = "float16"

        def generate(self, **kwargs):
            records["pixel_values"] = kwargs["pixel_values"]
            records["input_ids"] = kwargs["input_ids"]
            return ["generated_ids"]

    class Processor:
        def __init__(self) -> None:
            self.batch = BatchEncoding()

        def __call__(self, *, text, images, return_tensors):
            return self.batch

        def batch_decode(self, generated_ids, skip_special_tokens=False):
            return ["generated text"]

        def post_process_generation(self, generated_text, *, task, image_size):
            return {task: "typed caption"}

    class Torch:
        float16 = "float16"
        float32 = "float32"

        @staticmethod
        def inference_mode():
            class Context:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return False

            return Context()

    processor = Processor()

    def fake_load(self):
        self.device = "cuda"
        return Model(), processor, Torch

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    result = runtime.run(
        profile=client.app.state.runtime_state.vision_profiles.get(profile["id"]),
        task="caption",
        input=type("Input", (), {"image_base64": "AAAA"})(),
        options={},
    )

    assert result.data == {"type": "text", "text": "typed caption"}
    assert records["pixel_values"].dtype == "float16"
    assert records["input_ids"].dtype == "int64"
    assert processor.batch.pixel_values.to_calls[-1]["kwargs"] == {"device": "cuda", "dtype": "float16"}
    assert processor.batch.input_ids.to_calls[-1]["kwargs"] == {"device": "cuda"}


def test_florence2_load_converts_low_precision_cpu_model_to_float32(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "cpu-float32")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/cpu-float32",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)

    class FakeTorchModule(ModuleType):
        float16 = "float16"
        float32 = "float32"
        half = "float16"

        def __init__(self) -> None:
            super().__init__("torch")

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

            self.cuda = cuda
            self.backends = backends

    class FakeTransformersModule(ModuleType):
        class PretrainedConfig:
            pass

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Model:
                    def __init__(self) -> None:
                        self.dtype = "float16"
                        self.to_device = None
                        self.float_called = False

                    def to(self, device):
                        self.to_device = device
                        return self

                    def float(self):
                        self.float_called = True
                        self.dtype = "float32"
                        return self

                    def eval(self):
                        return None

                return Model()

        class AutoProcessor:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Processor:
                    pass

                return Processor()

    monkeypatch.setitem(sys.modules, "torch", FakeTorchModule())
    monkeypatch.setitem(sys.modules, "transformers", FakeTransformersModule("transformers"))

    model, processor, torch = runtime._load()

    assert model.to_device == "cpu"
    assert model.float_called is True
    assert model.dtype == "float32"
    assert processor is not None
    assert torch is not None


def test_florence2_load_shims_missing_tokenizer_additional_special_tokens_and_restores_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "transformers5-tokenizer")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/transformers5-tokenizer",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    calls = install_fake_florence2_transformers_modules(monkeypatch)
    tokenizer_base_cls = calls["tokenizer_base_cls"]

    assert not hasattr(tokenizer_base_cls, "additional_special_tokens")

    model, processor, torch = runtime._load()

    assert model is not None
    assert processor is not None
    assert torch is not None
    assert calls["observed_additional_special_tokens"] == ["<image>"]
    assert not hasattr(tokenizer_base_cls, "additional_special_tokens")


def test_florence2_load_shims_missing_legacy_transformers_config_attrs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime, LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "transformers5-load")
    profile = create_vision_profile(client, provider_model_id="vision/transformers5-load", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)

    class FakeTorchModule(ModuleType):
        def __init__(self) -> None:
            super().__init__("torch")

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

            self.cuda = cuda
            self.backends = backends

    class FakeTransformersModule(ModuleType):
        class PretrainedConfig:
            pass

        class Florence2LanguageConfig(PretrainedConfig):
            def __init__(self) -> None:
                self.observed_forced_bos_token_id = self.forced_bos_token_id

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(path, **kwargs):
                config = FakeTransformersModule.PretrainedConfig()
                config.language_config = FakeTransformersModule.Florence2LanguageConfig()

                class Model:
                    def __init__(self) -> None:
                        self.config = config

                    def to(self, device):
                        return self

                    def eval(self):
                        return None

                return Model()

        class AutoProcessor:
            @staticmethod
            def from_pretrained(path, **kwargs):
                config = FakeTransformersModule.PretrainedConfig()
                config.text_config = FakeTransformersModule.Florence2LanguageConfig()

                class Processor:
                    def __init__(self) -> None:
                        self.config = config

                return Processor()

    for attr in LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS:
        assert not hasattr(FakeTransformersModule.PretrainedConfig, attr)
    monkeypatch.setitem(sys.modules, "torch", FakeTorchModule())
    monkeypatch.setitem(sys.modules, "transformers", FakeTransformersModule("transformers"))

    model, processor, torch = runtime._load()

    assert model is not None
    assert processor is not None
    assert torch is not None
    for attr, default in LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS.items():
        assert not hasattr(FakeTransformersModule.PretrainedConfig, attr)
        assert getattr(model.config, attr) is default
        assert getattr(model.config.language_config, attr) is default
        assert getattr(processor.config, attr) is default
        assert getattr(processor.config.text_config, attr) is default
    assert model.config.language_config.observed_forced_bos_token_id is None
    assert processor.config.text_config.observed_forced_bos_token_id is None


def test_florence2_generation_shims_legacy_config_attrs_constructed_during_generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime, LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "transformers5-generate")
    profile = create_vision_profile(client, provider_model_id="vision/transformers5-generate", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    calls: dict[str, object] = {}

    class FakeTorchModule(ModuleType):
        def __init__(self) -> None:
            super().__init__("torch")

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

            self.cuda = cuda
            self.backends = backends

        @staticmethod
        def inference_mode():
            class Context:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return False

            return Context()

    class FakeTransformersModule(ModuleType):
        class PretrainedConfig:
            pass

        class Florence2LanguageConfig(PretrainedConfig):
            def __init__(self) -> None:
                calls["constructed_forced_bos_token_id"] = self.forced_bos_token_id

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(path, **kwargs):
                config = FakeTransformersModule.PretrainedConfig()
                config.language_config = FakeTransformersModule.Florence2LanguageConfig()

                class Model:
                    def __init__(self) -> None:
                        self.config = config

                    def to(self, device):
                        return self

                    def eval(self):
                        return None

                    def generate(self, **kwargs):
                        calls["class_attr_available_during_generate"] = hasattr(
                            FakeTransformersModule.Florence2LanguageConfig,
                            "forced_bos_token_id",
                        )
                        FakeTransformersModule.Florence2LanguageConfig()
                        return ["generated_ids"]

                return Model()

        class AutoProcessor:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Processor:
                    def __call__(self, *, text, images, return_tensors):
                        return {"input_ids": FakeVisionTensor()}

                    def batch_decode(self, generated_ids, skip_special_tokens=False):
                        return ["generated text"]

                    def post_process_generation(self, generated_text, *, task, image_size):
                        return {task: "generated caption"}

                return Processor()

    for attr in LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS:
        assert not hasattr(FakeTransformersModule.PretrainedConfig, attr)
        assert not hasattr(FakeTransformersModule.Florence2LanguageConfig, attr)
    monkeypatch.setitem(sys.modules, "torch", FakeTorchModule())
    monkeypatch.setitem(sys.modules, "transformers", FakeTransformersModule("transformers"))
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    result = runtime.run(
        profile=client.app.state.runtime_state.vision_profiles.get(profile["id"]),
        task="caption",
        input=type("Input", (), {"image_base64": "AAAA"})(),
        options={},
    )

    assert result.data == {"type": "text", "text": "generated caption"}
    assert calls["class_attr_available_during_generate"] is True
    assert calls["constructed_forced_bos_token_id"] is None
    for attr in LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS:
        assert not hasattr(FakeTransformersModule.PretrainedConfig, attr)
        assert not hasattr(FakeTransformersModule.Florence2LanguageConfig, attr)


def test_florence2_generation_disables_transformers5_cache_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "transformers5-cache")
    profile = create_vision_profile(client, provider_model_id="vision/transformers5-cache", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    records: dict[str, object] = {}

    class Model:
        def generate(self, **kwargs):
            records["use_cache"] = kwargs.get("use_cache")
            if kwargs.get("use_cache") is not False:
                raise TypeError("'EncoderDecoderCache' object is not subscriptable")
            return ["generated_ids"]

    class Processor:
        def __call__(self, *, text, images, return_tensors):
            return {"input_ids": FakeVisionTensor()}

        def batch_decode(self, generated_ids, skip_special_tokens=False):
            return ["generated text"]

        def post_process_generation(self, generated_text, *, task, image_size):
            return {task: "cache-safe caption"}

    class Torch:
        @staticmethod
        def inference_mode():
            class Context:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return False

            return Context()

    def fake_load(self):
        self.device = "cpu"
        return Model(), Processor(), Torch

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    result = runtime.run(
        profile=client.app.state.runtime_state.vision_profiles.get(profile["id"]),
        task="caption",
        input=type("Input", (), {"image_base64": "AAAA"})(),
        options={},
    )

    assert result.data == {"type": "text", "text": "cache-safe caption"}
    assert records["use_cache"] is False


def test_florence2_text_output_cleanup_is_conservative() -> None:
    from ai_workbench.core.inference.florence2_runtime import _normalize_task_output

    noisy_caption = _normalize_task_output(
        "more_detailed_caption",
        "<MORE_DETAILED_CAPTION>",
        {"<MORE_DETAILED_CAPTION>": "<MORE_DETAILED_CAPTION> InIn this image <loc_68> we can see a person.\n\n"},
        (200, 100),
    )
    normal_caption = _normalize_task_output(
        "detailed_caption",
        "<DETAILED_CAPTION>",
        {"<DETAILED_CAPTION>": "A person stands near a plain wall."},
        (200, 100),
    )
    ocr = _normalize_task_output("ocr", "<OCR>", {"<OCR>": "Shelf <loc_68> label"}, (200, 100))

    assert noisy_caption == {"type": "text", "text": "In this image we can see a person."}
    assert normal_caption == {"type": "text", "text": "A person stands near a plain wall."}
    assert ocr == {"type": "text", "text": "Shelf <loc_68> label"}


def test_florence2_square_pads_non_square_images_and_unpads_object_boxes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "square-pad-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/square-pad-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    records: dict[str, object] = {}

    class FakePillowImage:
        def __init__(self, *, size: tuple[int, int], color: tuple[int, int, int], mode: str = "RGB") -> None:
            self.size = size
            self.color = color
            self.mode = mode
            self.pasted: tuple[object, tuple[int, int]] | None = None

        def getpixel(self, xy):
            return self.color

        def paste(self, image, box):
            self.pasted = (image, box)

        def resize(self, size, resample=None):
            records["resize_source_size"] = self.size
            records["resize_target_size"] = size
            records["resize_resample"] = resample
            return FakePillowImage(size=size, color=self.color, mode=self.mode)

    fake_image_module = ModuleType("PIL.Image")
    fake_image_module.Image = FakePillowImage

    def new_image(mode, size, color):
        return FakePillowImage(size=size, color=color, mode=mode)

    fake_image_module.new = new_image
    fake_pil_module = ModuleType("PIL")
    fake_pil_module.Image = fake_image_module
    monkeypatch.setitem(sys.modules, "PIL", fake_pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image_module)

    class Model:
        def generate(self, **kwargs):
            return ["generated_ids"]

    class Processor:
        def __call__(self, *, text, images, return_tensors):
            records["processor_image_size"] = images.size
            records["processor_corner"] = images.getpixel((0, 0))
            return {"input_ids": FakeVisionTensor()}

        def batch_decode(self, generated_ids, skip_special_tokens=False):
            return ["generated text"]

        def post_process_generation(self, generated_text, *, task, image_size):
            records["post_process_image_size"] = image_size
            return {task: {"labels": ["person"], "bboxes": [[50.0, 75.0, 150.0, 125.0]], "scores": [0.9]}}

    def fake_load(self):
        self.device = "cpu"
        return Model(), Processor(), FakeFlorence2Torch

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fake_load)
    monkeypatch.setattr(
        "ai_workbench.core.inference.florence2_runtime._load_image_from_base64",
        lambda value: FakePillowImage(size=(200, 100), color=(10, 20, 30)),
    )

    result = runtime.run(
        profile=client.app.state.runtime_state.vision_profiles.get(profile["id"]),
        task="object_detection",
        input=type("Input", (), {"image_base64": "AAAA"})(),
        options={},
    )

    assert records["resize_source_size"] == (200, 200)
    assert records["resize_target_size"] == (768, 768)
    assert records["processor_image_size"] == (768, 768)
    assert records["post_process_image_size"] == (200, 200)
    assert records["processor_corner"] == (10, 20, 30)
    assert result.data == {
        "type": "objects",
        "objects": [
            {
                "label": "person",
                "score": 0.9,
                "box": {"x_min": 0.25, "y_min": 0.25, "x_max": 0.75, "y_max": 0.75},
            }
        ],
    }


@pytest.mark.parametrize("error_message", ["CUDA error: out of memory", "CUDA error: device-side assert triggered"])
def test_florence2_fatal_accelerator_error_unloads_cached_model_and_allows_reload(
    error_message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "oom-reload-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/oom-reload-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    calls = {"load": 0, "generate": 0}

    class Model:
        def generate(self, **kwargs):
            calls["generate"] += 1
            if calls["generate"] == 1:
                raise RuntimeError(error_message)
            return ["generated_ids"]

    class Processor:
        def __call__(self, *, text, images, return_tensors):
            return {"input_ids": FakeVisionTensor()}

        def batch_decode(self, generated_ids, skip_special_tokens=False):
            return ["generated text"]

        def post_process_generation(self, generated_text, *, task, image_size):
            return {task: "recovered caption"}

    def fake_load(self):
        if self._model is not None and self._processor is not None and self._torch is not None:
            return self._model, self._processor, self._torch
        calls["load"] += 1
        self.device = "cuda"
        self._model = Model()
        self._processor = Processor()
        self._torch = FakeFlorence2Torch
        return self._model, self._processor, self._torch

    monkeypatch.setattr(Florence2VisionRuntime, "_load", fake_load)
    monkeypatch.setattr("ai_workbench.core.inference.florence2_runtime._load_image_from_base64", lambda value: FakeVisionImage())

    with pytest.raises(VisionRuntimeError):
        runtime.run(
            profile=client.app.state.runtime_state.vision_profiles.get(profile["id"]),
            task="caption",
            input=type("Input", (), {"image_base64": "AAAA"})(),
            options={},
        )

    assert calls["load"] == 1
    assert runtime._model is None
    assert runtime._processor is None
    assert runtime._torch is None

    result = runtime.run(
        profile=client.app.state.runtime_state.vision_profiles.get(profile["id"]),
        task="caption",
        input=type("Input", (), {"image_base64": "AAAA"})(),
        options={},
    )

    assert calls["load"] == 2
    assert result.data == {"type": "text", "text": "recovered caption"}


def test_florence2_load_shims_missing_legacy_transformers_model_attrs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime, LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "transformers5-model-attrs")
    profile = create_vision_profile(client, provider_model_id="vision/transformers5-model-attrs", external_inference_enabled=True, metadata={"trust_remote_code": True})
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)

    class FakeTorchModule(ModuleType):
        def __init__(self) -> None:
            super().__init__("torch")

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

            self.cuda = cuda
            self.backends = backends

    class FakeTransformersModule(ModuleType):
        class PretrainedConfig:
            pass

        class PreTrainedModel:
            pass

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Florence2ForConditionalGeneration(FakeTransformersModule.PreTrainedModel):
                    def __init__(self) -> None:
                        self.observed_model_attrs = {attr: getattr(self, attr) for attr in LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS}

                    def to(self, device):
                        return self

                    def eval(self):
                        return None

                return Florence2ForConditionalGeneration()

        class AutoProcessor:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Processor:
                    pass

                return Processor()

    for attr in LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS:
        assert not hasattr(FakeTransformersModule.PreTrainedModel, attr)
    monkeypatch.setitem(sys.modules, "torch", FakeTorchModule())
    monkeypatch.setitem(sys.modules, "transformers", FakeTransformersModule("transformers"))

    model, processor, torch = runtime._load()

    assert model is not None
    assert processor is not None
    assert torch is not None
    for attr, default in LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS.items():
        assert not hasattr(FakeTransformersModule.PreTrainedModel, attr)
        assert model.observed_model_attrs[attr] is default
        assert getattr(model, attr) is default


def test_florence2_load_repairs_transformers5_tied_language_weights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "transformers5-tied-weights")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/transformers5-tied-weights",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    runtime = Florence2VisionRuntime(client.app.state.runtime_state.vision_profiles.get(profile["id"]), repo_root=tmp_path)
    records: dict[str, object] = {}

    class FakeTorchModule(ModuleType):
        def __init__(self) -> None:
            super().__init__("torch")

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

            self.cuda = cuda
            self.backends = backends

    class Weight:
        def __init__(self, name: str) -> None:
            self.name = name

        def data_ptr(self) -> int:
            return id(self)

    class WeightHolder:
        def __init__(self, weight: Weight) -> None:
            self.weight = weight

    class FakeTransformersModule(ModuleType):
        class PretrainedConfig:
            pass

        class PreTrainedModel:
            pass

        class PreTrainedTokenizerBase:
            pass

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Model(FakeTransformersModule.PreTrainedModel):
                    def __init__(self) -> None:
                        shared = Weight("shared")
                        self.language_model = type("LanguageModel", (), {})()
                        self.language_model.model = type("LanguageInnerModel", (), {})()
                        self.language_model.model.shared = WeightHolder(shared)
                        self.language_model.model.encoder = type("Encoder", (), {})()
                        self.language_model.model.encoder.embed_tokens = WeightHolder(Weight("encoder"))
                        self.language_model.model.decoder = type("Decoder", (), {})()
                        self.language_model.model.decoder.embed_tokens = WeightHolder(Weight("decoder"))
                        self.language_model.lm_head = WeightHolder(Weight("lm_head"))
                        records["shared_weight"] = shared
                        records["encoder_was_shared_before_repair"] = (
                            self.language_model.model.encoder.embed_tokens.weight is shared
                        )

                    def to(self, device):
                        records["encoder_shared_during_to"] = (
                            self.language_model.model.encoder.embed_tokens.weight
                            is self.language_model.model.shared.weight
                        )
                        return self

                    def eval(self):
                        return None

                return Model()

        class AutoProcessor:
            @staticmethod
            def from_pretrained(path, **kwargs):
                class Processor:
                    pass

                return Processor()

    monkeypatch.setitem(sys.modules, "torch", FakeTorchModule())
    monkeypatch.setitem(sys.modules, "transformers", FakeTransformersModule("transformers"))

    model, processor, torch = runtime._load()

    shared = records["shared_weight"]
    assert model is not None
    assert processor is not None
    assert torch is not None
    assert records["encoder_was_shared_before_repair"] is False
    assert records["encoder_shared_during_to"] is True
    assert model.language_model.model.encoder.embed_tokens.weight is shared
    assert model.language_model.model.decoder.embed_tokens.weight is shared
    assert model.language_model.lm_head.weight is shared


def test_florence2_preflight_missing_profile_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/api/inference/vision-models/missing/preflight", json={"load_model": False})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VISION_MODEL_NOT_FOUND"


def test_florence2_preflight_reports_trust_remote_code_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "preflight-trust")
    profile = create_vision_profile(client, provider_model_id="vision/preflight-trust", external_inference_enabled=True)

    response = client.post(f"/api/inference/vision-models/{profile['alias']}/preflight", json={"load_model": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    checks = {item["id"]: item for item in payload["checks"]}
    assert payload["ok"] is False
    assert payload["load_model"] is False
    assert checks["trust_remote_code"]["status"] == "fail"
    assert "metadata.trust_remote_code=true" in checks["trust_remote_code"]["message"]
    assert str(tmp_path).lower() not in str(payload).lower()


def test_florence2_preflight_constructs_processor_with_tokenizer_compat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "preflight-tokenizer")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/preflight-tokenizer",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    calls = install_fake_florence2_transformers_modules(monkeypatch)
    tokenizer_base_cls = calls["tokenizer_base_cls"]

    response = client.post(f"/api/inference/vision-models/{profile['id']}/preflight")

    assert response.status_code == 200, response.text
    payload = response.json()
    checks = {item["id"]: item for item in payload["checks"]}
    assert payload["ok"] is True
    assert payload["runtime"]["transformers_version"] == "5.0.0-test"
    assert payload["runtime"]["torch_available"] is True
    assert checks["config"]["status"] == "pass"
    assert checks["processor_tokenizer"]["status"] == "pass"
    assert calls["observed_additional_special_tokens"] == ["<image>"]
    assert not hasattr(tokenizer_base_cls, "additional_special_tokens")


def test_florence2_preflight_load_model_loads_and_unloads_without_global_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workbench.core.inference.florence2_runtime import Florence2VisionRuntime

    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "preflight-load")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/preflight-load",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    calls = install_fake_florence2_transformers_modules(monkeypatch)
    original_unload = Florence2VisionRuntime.unload

    def record_unload(self):
        calls["runtime_unload"] = int(calls.get("runtime_unload", 0)) + 1
        return original_unload(self)

    monkeypatch.setattr(Florence2VisionRuntime, "unload", record_unload)
    before = vision_runtime_cache_status()

    response = client.post(f"/api/inference/vision-models/{profile['id']}/preflight", json={"load_model": True})

    after = vision_runtime_cache_status()
    payload = response.json()
    checks = {item["id"]: item for item in payload["checks"]}
    assert response.status_code == 200, response.text
    assert payload["ok"] is True
    assert payload["load_model"] is True
    assert checks["model_load"]["status"] == "pass"
    assert calls["model"] == 1
    assert calls["processor"] == 2
    assert calls["runtime_unload"] == 1
    assert before == {"runtime_count": 0, "profile_count": 0, "architecture_counts": {}}
    assert after == before


def test_florence2_preflight_reports_unavailable_configured_cuda_before_model_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "preflight-cuda-unavailable")
    provider = client.post(
        "/api/llm-provider-profiles",
        json={
            "name": "Internal CUDA",
            "provider": "internal_transformers",
            "metadata": {"local_runtime_device": "cuda"},
        },
    ).json()
    profile = create_vision_profile(
        client,
        provider_model_id="vision/preflight-cuda-unavailable",
        provider_profile_id=provider["id"],
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    calls = install_fake_florence2_transformers_modules(monkeypatch)

    response = client.post(f"/api/inference/vision-models/{profile['id']}/preflight", json={"load_model": True})

    payload = response.json()
    checks = {item["id"]: item for item in payload["checks"]}
    assert response.status_code == 200, response.text
    assert payload["ok"] is False
    assert payload["runtime"]["cuda_available"] is False
    assert checks["device"]["status"] == "fail"
    assert checks["model_load"]["status"] == "fail"
    assert calls["model"] == 0


def test_florence2_preflight_failure_response_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    create_local_vision_folder(client, "preflight-sanitized")
    profile = create_vision_profile(
        client,
        provider_model_id="vision/preflight-sanitized",
        external_inference_enabled=True,
        metadata={"trust_remote_code": True},
    )
    install_fake_florence2_transformers_modules(
        monkeypatch,
        processor_error=RuntimeError(f"secret-token at {tmp_path} with traceback and AAAA"),
    )

    response = client.post(f"/api/inference/vision-models/{profile['id']}/preflight", json={"load_model": False})

    rendered = str(response.json()).lower()
    checks = {item["id"]: item for item in response.json()["checks"]}
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is False
    assert checks["processor_tokenizer"]["status"] == "fail"
    assert "secret-token" not in rendered
    assert str(tmp_path).lower() not in rendered
    assert "traceback" not in rendered
    assert "aaaa" not in rendered


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("caption", {"type": "text", "text": "a local caption"}),
        ("detailed_caption", {"type": "text", "text": "a local detailed caption"}),
        ("more_detailed_caption", {"type": "text", "text": "a local more detailed caption"}),
        ("ocr", {"type": "text", "text": "local OCR text"}),
        (
            "object_detection",
            {
                "type": "objects",
                "objects": [
                    {
                        "label": "cat",
                        "score": 0.98,
                        "box": {"x_min": 0.1, "y_min": 0.1, "x_max": 0.5, "y_max": 0.8},
                    }
                ],
            },
        ),
    ],
)
def test_fake_florence2_backend_returns_task_outputs_through_http(
    task: str,
    expected: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "fake-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/fake-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    calls = install_fake_florence2_backend(monkeypatch)

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": task, "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == expected
    assert calls["load"] == 1


def test_invalid_florence2_generation_options_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "bad-options-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/bad-options-florence2", external_inference_enabled=True)
    calls = install_fake_florence2_backend(monkeypatch)

    response = client.post(
        "/api/inference/vision",
        json={
            "model": f"vision:{profile['id']}",
            "task": "caption",
            "input": {"type": "image", "image_base64": "AAAA"},
            "options": {"temperature": 1.0},
        },
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INFERENCE_INVALID_REQUEST"
    assert calls["load"] == 0
    assert calls["decode"] == 0
    rendered = str(response.json()).lower()
    assert "aaaa" not in rendered
    assert "traceback" not in rendered
    assert str(tmp_path).lower() not in rendered
    assert "generated text" not in rendered
    assert "ocr text" not in rendered
    assert "secret" not in rendered


def test_invalid_florence2_model_output_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "bad-output-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/bad-output-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    install_fake_florence2_backend(monkeypatch, task_outputs={"<OD>": {"labels": ["secret-label"], "bboxes": [[1, 2, 3, 4]], "scores": [float("nan")]}})

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "object_detection", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "secret-label" not in rendered
    assert "nan" not in rendered
    assert "generated text" not in rendered


def test_malformed_florence2_object_list_item_is_rejected_and_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "bad-object-item-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/bad-object-item-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    install_fake_florence2_backend(monkeypatch, task_outputs={"<OD>": {"objects": ["secret-object"]}})
    before = capture_stateless_persistence_snapshot(state)

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "object_detection", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    rendered = str(response.json()).lower()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "secret-object" not in rendered
    assert "generated text" not in rendered
    assert "aaaa" not in rendered
    assert "traceback" not in rendered
    assert str(tmp_path).lower() not in rendered
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))


def test_florence2_generation_uses_inference_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "inference-context-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/inference-context-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    install_fake_florence2_backend(monkeypatch)

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert FakeFlorence2Torch.inference_entries == 1
    assert FakeFlorence2Torch.inference_exits == 1
    assert FakeFlorence2Torch.active is False


def test_real_florence2_fake_backend_success_is_stateless_and_unload_clears_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    enable_inference(client, require_api_key=False)
    create_local_vision_folder(client, "stateless-florence2")
    profile = create_vision_profile(client, provider_model_id="vision/stateless-florence2", external_inference_enabled=True, metadata={"trust_remote_code": True})
    install_fake_florence2_backend(monkeypatch)
    before = capture_stateless_persistence_snapshot(state)

    response = client.post(
        "/api/inference/vision",
        json={"model": f"vision:{profile['id']}", "task": "ocr", "input": {"type": "image", "image_base64": "AAAA"}},
        headers=auth_headers(),
    )
    missing = client.post("/api/inference/unload", json={"target": "vision", "model": "vision:missing"}, headers=auth_headers())
    unload = client.post("/api/inference/unload", json={"target": "vision", "model": f"vision:{profile['alias']}"}, headers=auth_headers())

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"type": "text", "text": "local OCR text"}
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert unload.status_code == 200
    assert unload.json()["results"] == [{"target": "vision", "status": "freed", "removed": 1, "message": "Freed."}]
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))
