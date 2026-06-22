import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from ai_workbench.api.main import create_app
from ai_workbench.db.database import get_engine, init_db
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client(tmp_path: Path, *, use_memory: bool = True, database_url: str | None = None) -> TestClient:
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=use_memory, root=tmp_path, database_url=database_url))


def create_profile(client: TestClient, **overrides) -> dict:
    filename = overrides.pop("filename", f"model-{uuid4().hex[:8]}.safetensors")
    payload = {
        "name": "SDXL Image Model",
        "checkpoint_ref": f"image_generation/checkpoints/{filename}",
        "architecture": "sdxl",
    }
    payload.update(overrides)
    response = client.post("/api/image-generation/model-profiles", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_image_generation_profile_table_defaults_and_safe_refs(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE appmetadatarecord (key VARCHAR PRIMARY KEY NOT NULL, value VARCHAR NOT NULL, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO appmetadatarecord (key, value) VALUES ('schema_version', '1')"))
        connection.execute(
            text(
                """
                CREATE TABLE image_generation_model_profiles (
                  id VARCHAR PRIMARY KEY NOT NULL,
                  name VARCHAR NOT NULL,
                  description VARCHAR DEFAULT '',
                  notes VARCHAR DEFAULT '',
                  enabled BOOLEAN DEFAULT 1,
                  architecture VARCHAR NOT NULL DEFAULT 'sdxl',
                  variant VARCHAR DEFAULT 'base',
                  checkpoint_ref VARCHAR NOT NULL DEFAULT '',
                  vae_ref VARCHAR,
                  dtype VARCHAR DEFAULT 'auto',
                  device VARCHAR DEFAULT 'auto',
                  clip_skip INTEGER,
                  supported_tasks_json VARCHAR DEFAULT '["txt2img"]',
                  metadata_json VARCHAR DEFAULT '{}',
                  created_at DATETIME,
                  updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO image_generation_model_profiles "
                "(id, name, checkpoint_ref, architecture, variant, created_at, updated_at) VALUES "
                "('i1', 'SDXL Image Model', 'image_generation/checkpoints/a.safetensors', 'sdxl', 'base', '2024-01-01', '2024-01-01'), "
                "('i2', 'SDXL Image Model', 'image_generation/checkpoints/b.safetensors', 'sdxl', 'base', '2024-01-02', '2024-01-02')"
            )
        )

    init_db(engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(image_generation_model_profiles)").fetchall()}
        rows = [tuple(row) for row in connection.exec_driver_sql("SELECT id, alias FROM image_generation_model_profiles ORDER BY id").fetchall()]
    assert {"id", "alias", "checkpoint_ref", "architecture", "variant", "supported_tasks_json"} <= columns
    assert rows == [("i1", "sdxl-image-model"), ("i2", "sdxl-image-model-2")]

    client = make_client(tmp_path)
    profile = create_profile(client, checkpoint_ref="image_generation/checkpoints/sdxl.safetensors")
    assert profile["alias"] == "sdxl-image-model"
    assert profile["architecture"] == "sdxl"
    assert profile["variant"] == "base"
    assert profile["dtype"] == "auto"
    assert profile["device"] == "auto"
    assert profile["supported_tasks"] == ["txt2img"]
    assert profile["vae_ref"] is None

    with_vae = create_profile(
        client,
        name="Pony Image Model",
        alias="pony-image",
        variant="pony",
        checkpoint_ref="image_generation/checkpoints/pony.safetensors",
        vae_ref="image_generation/vae/sdxl-vae.safetensors",
        clip_skip=2,
        dtype="fp16",
        device="cuda",
        metadata={"family": "pony"},
    )
    assert with_vae["alias"] == "pony-image"
    assert with_vae["supported_tasks"] == ["txt2img"]
    assert with_vae["clip_skip"] == 2
    assert with_vae["metadata"] == {"family": "pony"}

    invalid_variant = client.post(
        "/api/image-generation/model-profiles",
        json={
            "name": "Bad Pony",
            "architecture": "sd15",
            "variant": "pony",
            "checkpoint_ref": "image_generation/checkpoints/bad.safetensors",
        },
    )
    assert invalid_variant.status_code == 422
    assert invalid_variant.json()["error"]["code"] == "INVALID_IMAGE_GENERATION_MODEL"

    invalid_task = client.post(
        "/api/image-generation/model-profiles",
        json={
            "name": "Bad Task",
            "checkpoint_ref": "image_generation/checkpoints/bad-task.safetensors",
            "supported_tasks": ["img2img"],
        },
    )
    assert invalid_task.status_code == 422
    assert invalid_task.json()["error"]["code"] == "INVALID_IMAGE_GENERATION_MODEL"

    for bad_ref in ["", "../x", "C:\\x", "vision/x", "image_generation/checkpoints"]:
        response = client.post(
            "/api/image-generation/model-profiles",
            json={"name": "Bad Ref", "checkpoint_ref": bad_ref},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_IMAGE_GENERATION_MODEL"

    bad_vae = client.post(
        "/api/image-generation/model-profiles",
        json={
            "name": "Bad VAE",
            "checkpoint_ref": "image_generation/checkpoints/ok.safetensors",
            "vae_ref": "image_generation/checkpoints/not-vae.safetensors",
        },
    )
    assert bad_vae.status_code == 422
    assert bad_vae.json()["error"]["code"] == "INVALID_IMAGE_GENERATION_MODEL"


def test_image_generation_profile_crud_alias_and_delete_keeps_files(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    checkpoint = tmp_path / "data" / "models" / "image_generation" / "checkpoints" / "keep.safetensors"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")

    profile = create_profile(client, alias="image-main", checkpoint_ref="image_generation/checkpoints/keep.safetensors")
    second = create_profile(client, name="Second Image", alias="image-second", checkpoint_ref="image_generation/checkpoints/second.safetensors")

    status = client.get("/api/image-generation/status")
    assert status.status_code == 200
    assert status.json()["profiles_total"] == 2
    assert status.json()["profiles_enabled"] == 2
    assert status.json()["supported_tasks"] == ["txt2img"]
    assert status.json()["runtime"] == {
        "available": True,
        "status": "ready",
        "backend": "fake",
        "real_generation": False,
        "supports_queue": True,
        "supports_cancel": True,
        "supports_unload": True,
    }
    assert status.json()["queue"] == {"max_concurrent": 1, "active_count": 0, "queued_count": 0}

    assert client.get(f"/api/image-generation/model-profiles/{profile['alias']}").json()["id"] == profile["id"]
    duplicate_alias = client.post(
        "/api/image-generation/model-profiles",
        json={
            "name": "Duplicate",
            "alias": profile["alias"],
            "checkpoint_ref": "image_generation/checkpoints/duplicate.safetensors",
        },
    )
    assert duplicate_alias.status_code == 409
    assert duplicate_alias.json()["error"]["code"] == "IMAGE_GENERATION_MODEL_ALIAS_EXISTS"

    renamed = client.patch(f"/api/image-generation/model-profiles/{profile['alias']}", json={"alias": "image-renamed", "enabled": False}).json()
    assert renamed["alias"] == "image-renamed"
    assert renamed["enabled"] is False

    duplicate_patch = client.patch(f"/api/image-generation/model-profiles/{renamed['id']}", json={"alias": second["alias"]})
    assert duplicate_patch.status_code == 409
    assert duplicate_patch.json()["error"]["code"] == "IMAGE_GENERATION_MODEL_ALIAS_EXISTS"

    unknown_field = client.post(
        "/api/image-generation/model-profiles",
        json={"name": "Bad", "checkpoint_ref": "image_generation/checkpoints/x.safetensors", "unknown": True},
    )
    assert unknown_field.status_code == 422
    assert unknown_field.json()["error"]["code"] == "UNKNOWN_IMAGE_GENERATION_MODEL_FIELD"

    deleted_by_alias = client.delete(f"/api/image-generation/model-profiles/{second['alias']}").json()
    deleted = client.delete(f"/api/image-generation/model-profiles/{renamed['id']}").json()
    assert deleted_by_alias == {"deleted": True, "profile_id": second["id"]}
    assert deleted == {"deleted": True, "profile_id": renamed["id"]}
    assert checkpoint.exists()


def test_image_generation_unload_api_is_internal_and_compact(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    profile = create_profile(client, alias="image-main", checkpoint_ref="image_generation/checkpoints/keep.safetensors")
    service = client.app.state.runtime_state.image_generation_service

    skipped = client.post("/api/image-generation/unload", json={})
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"
    assert skipped.json()["removed"] == 0

    result = asyncio.run(
        service.txt2img(
            profile_id_or_alias=profile["alias"],
            positive_prompt="secret prompt for cache",
            width=64,
            height=64,
            context={"run_id": "run-image"},
        )
    )
    assert result["metadata"]["queue"]["status"] == "completed"
    status = client.get("/api/image-generation/status")
    assert status.status_code == 200
    assert status.json()["cache"]["cached_profiles"] == 1

    freed = client.post("/api/image-generation/unload", json={"profile_id_or_alias": profile["alias"]})
    assert freed.status_code == 200
    assert freed.json()["status"] == "freed"
    assert freed.json()["removed"] == 1

    missing = client.post("/api/image-generation/unload", json={"profile_id_or_alias": "missing-profile"})
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_found"

    compact_text = str({"status": status.json(), "freed": freed.json(), "missing": missing.json()})
    assert "secret prompt for cache" not in compact_text
    assert "data_base64" not in compact_text
    assert str(tmp_path) not in compact_text
    assert "image_generation/loras" not in compact_text


def test_image_generation_profile_aliases_work_with_sql_store(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'image-generation.db'}"
    client = make_client(tmp_path, database_url=db_url, use_memory=False)
    profile = create_profile(client, alias="sql-image", checkpoint_ref="image_generation/checkpoints/sql.safetensors")

    duplicate = client.post(
        "/api/image-generation/model-profiles",
        json={
            "name": "Duplicate",
            "alias": "sql-image",
            "checkpoint_ref": "image_generation/checkpoints/other.safetensors",
        },
    )
    restarted = make_client(tmp_path, database_url=db_url, use_memory=False)

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "IMAGE_GENERATION_MODEL_ALIAS_EXISTS"
    assert restarted.get("/api/image-generation/model-profiles/sql-image").json()["id"] == profile["id"]


def test_image_generation_inventory_returns_safe_refs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    models_root = tmp_path / "data" / "models" / "image_generation"
    checkpoint = models_root / "checkpoints" / "sdxl.safetensors"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")
    ignored_checkpoint = models_root / "checkpoints" / "notes.txt"
    ignored_checkpoint.write_text("ignore", encoding="utf-8")
    vae = models_root / "vae" / "sdxl-vae.safetensors"
    vae.parent.mkdir(parents=True)
    vae.write_bytes(b"vae")
    lora = models_root / "loras" / "style" / "style-a.safetensors"
    lora.parent.mkdir(parents=True)
    lora.write_bytes(b"lora")

    checkpoints = client.get("/api/image-generation/model-inventory?kind=checkpoint")
    vaes = client.get("/api/image-generation/model-inventory?kind=vae")
    loras = client.get("/api/image-generation/model-inventory?kind=lora")
    invalid = client.get("/api/image-generation/model-inventory?kind=vision")

    assert checkpoints.status_code == 200, checkpoints.text
    assert checkpoints.json()["kind"] == "checkpoint"
    assert checkpoints.json()["models_root"] == "data/models"
    assert checkpoints.json()["items"] == [
        {
            "ref": "image_generation/checkpoints/sdxl.safetensors",
            "name": "sdxl",
            "kind": "checkpoint",
            "relative_path": "image_generation/checkpoints/sdxl.safetensors",
        }
    ]
    assert vaes.json()["items"] == [
        {
            "ref": "image_generation/vae/sdxl-vae.safetensors",
            "name": "sdxl-vae",
            "kind": "vae",
            "relative_path": "image_generation/vae/sdxl-vae.safetensors",
        }
    ]
    assert loras.json()["items"] == [
        {
            "ref": "image_generation/loras/style",
            "name": "style",
            "kind": "lora",
            "relative_path": "image_generation/loras/style",
        },
        {
            "ref": "image_generation/loras/style/style-a.safetensors",
            "name": "style-a",
            "kind": "lora",
            "relative_path": "image_generation/loras/style/style-a.safetensors",
        },
    ]
    assert str(tmp_path) not in str(checkpoints.json())
    assert str(tmp_path) not in str(vaes.json())
    assert str(tmp_path) not in str(loras.json())
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_IMAGE_GENERATION_INVENTORY_KIND"
