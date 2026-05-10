from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.stores import CapabilityConfigStore
from capabilities.pet import CapabilityRuntime, PetError
from tests.test_prompt_agent_execution import FakeLLMRuntime


WEBP_BYTES = b"RIFF\x10\x00\x00\x00WEBPVP8 fake"


def write_pet(root: Path, pet_id: str, manifest: str = '{"displayName":"Test Pet","description":"A test pet."}', spritesheet: bool = True) -> None:
    pet_dir = root / "data" / "pet" / pet_id
    pet_dir.mkdir(parents=True)
    (pet_dir / "pet.json").write_text(manifest, encoding="utf-8")
    if spritesheet:
        (pet_dir / "spritesheet.webp").write_bytes(WEBP_BYTES)


def test_scan_returns_empty_when_data_pet_missing(tmp_path: Path) -> None:
    result = CapabilityRuntime(root=tmp_path).scan_pets()

    assert result == {"pets": []}


def test_scan_returns_valid_codex_pet(tmp_path: Path) -> None:
    write_pet(tmp_path, "test_pet")

    result = CapabilityRuntime(root=tmp_path).scan_pets()

    assert result["pets"][0]["id"] == "test_pet"
    assert result["pets"][0]["display_name"] == "Test Pet"
    assert result["pets"][0]["description"] == "A test pet."
    assert result["pets"][0]["valid"] is True
    assert result["pets"][0]["spritesheet_url"] == "/api/pets/test_pet/spritesheet.webp"


def test_missing_spritesheet_returns_invalid_pet(tmp_path: Path) -> None:
    write_pet(tmp_path, "broken_pet", spritesheet=False)

    pet = CapabilityRuntime(root=tmp_path).validate_pet("broken_pet")

    assert pet["valid"] is False
    assert pet["status"] == "missing_spritesheet"
    assert pet["errors"] == ["Missing spritesheet.webp"]
    assert pet["spritesheet_url"] is None


@pytest.mark.parametrize("pet_id", ["../x", "bad/pet", "BadPet", ""])
def test_invalid_pet_id_is_rejected(tmp_path: Path, pet_id: str) -> None:
    with pytest.raises(PetError) as exc:
        CapabilityRuntime(root=tmp_path).validate_pet(pet_id)

    assert exc.value.code == "INVALID_PET_ID"


def test_delete_removes_only_data_pet_directory(tmp_path: Path) -> None:
    write_pet(tmp_path, "delete_me")
    outside = tmp_path / "data" / "keep.txt"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("keep", encoding="utf-8")

    result = CapabilityRuntime(root=tmp_path).delete_pet("delete_me")

    assert result == {"deleted": True, "pet_id": "delete_me"}
    assert not (tmp_path / "data" / "pet" / "delete_me").exists()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_api_lists_pets_from_data_directory(tmp_path: Path) -> None:
    write_pet(tmp_path, "api_pet")
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    client.app.state.runtime_state.repo_root = tmp_path

    response = client.get("/api/pets")

    assert response.status_code == 200
    assert response.json()["pets"][0]["id"] == "api_pet"


def test_api_spritesheet_rejects_path_traversal(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    client.app.state.runtime_state.repo_root = tmp_path

    response = client.get("/api/pets/../x/spritesheet.webp")

    assert response.status_code in {400, 404}


def test_api_import_valid_pet_saves_and_selects_default(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    client.app.state.runtime_state.repo_root = tmp_path

    response = client.post(
        "/api/pets/import",
        files={
            "pet_json": ("pet.json", b'{"id":"import_pet","displayName":"Import Pet"}', "application/json"),
            "spritesheet": ("spritesheet.webp", WEBP_BYTES, "image/webp"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pet"]["id"] == "import_pet"
    assert payload["pet"]["valid"] is True
    assert payload["selected"] is True
    assert (tmp_path / "data" / "pet" / "import_pet" / "pet.json").is_file()
    assert (tmp_path / "data" / "pet" / "import_pet" / "spritesheet.webp").is_file()
    assert client.get("/api/pets").json()["pets"][0]["id"] == "import_pet"
    assert client.get("/api/pets/settings").json()["settings"]["default_pet_id"] == "import_pet"


def test_api_import_missing_file_returns_structured_error(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    client.app.state.runtime_state.repo_root = tmp_path

    response = client.post(
        "/api/pets/import",
        files={"pet_json": ("pet.json", b'{"id":"missing_sprite"}', "application/json")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PET_IMPORT_MISSING_FILE"


def test_api_import_rejects_unexpected_file_field(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    client.app.state.runtime_state.repo_root = tmp_path

    response = client.post(
        "/api/pets/import",
        files={
            "pet_json": ("pet.json", b'{"id":"bad_extra"}', "application/json"),
            "spritesheet": ("spritesheet.webp", WEBP_BYTES, "image/webp"),
            "extra": ("other.png", b"nope", "image/png"),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PET_IMPORT_UNEXPECTED_FILE"
    assert not (tmp_path / "data" / "pet").exists()


def test_api_import_invalid_pet_json_does_not_pollute_data_pet(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    client.app.state.runtime_state.repo_root = tmp_path

    response = client.post(
        "/api/pets/import",
        files={
            "pet_json": ("pet.json", b"not json", "application/json"),
            "spritesheet": ("spritesheet.webp", WEBP_BYTES, "image/webp"),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PET_JSON_INVALID"
    assert not (tmp_path / "data" / "pet").exists()


def test_import_duplicate_pet_id_uses_suffix_without_overwrite(tmp_path: Path) -> None:
    runtime = CapabilityRuntime(root=tmp_path)
    first = runtime.import_pet(b'{"id":"dup_pet","displayName":"First"}', WEBP_BYTES)
    second = runtime.import_pet(b'{"id":"dup_pet","displayName":"Second"}', WEBP_BYTES)

    assert first["pet"]["id"] == "dup_pet"
    assert second["pet"]["id"] == "dup_pet_2"
    assert (tmp_path / "data" / "pet" / "dup_pet" / "pet.json").read_text(encoding="utf-8") == '{"id":"dup_pet","displayName":"First"}'


def test_pet_command_controls_settings_and_reports_status(tmp_path: Path) -> None:
    write_pet(tmp_path, "command_pet")
    context = _pet_command_context(tmp_path)
    runtime = CapabilityRuntime(root=tmp_path)

    status = runtime.command("status", context=context)
    wake = runtime.command("wake", context=context)
    selected = runtime.command("select command_pet", context=context)
    tuck = runtime.command("tuck", context=context)
    reload = runtime.command("reload", context=context)

    assert status["valid_count"] == 1
    assert wake["settings"]["pet_enabled"] is True
    assert selected["settings"] == {"pet_enabled": True, "default_pet_id": "command_pet"}
    assert tuck["settings"]["pet_enabled"] is False
    assert reload["valid_count"] == 1
    assert context["capability_config_store"].get_config("pet")["user_config"]["default_pet_id"] == "command_pet"


def test_pet_command_select_missing_pet_returns_error(tmp_path: Path) -> None:
    runtime = CapabilityRuntime(root=tmp_path)

    with pytest.raises(PetError) as exc:
        runtime.command("select missing", context=_pet_command_context(tmp_path))

    assert exc.value.code == "PET_NOT_FOUND"


def _pet_command_context(tmp_path: Path) -> dict:
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(Path(__file__).resolve().parents[1] / "capabilities")
    return {
        "repo_root": tmp_path,
        "capability_config": {},
        "capability_config_store": CapabilityConfigStore(),
        "config_schema": capabilities.get("pet").config_schema,
    }
