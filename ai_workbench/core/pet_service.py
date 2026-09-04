"""Pet package management backed by ordinary application settings."""

from __future__ import annotations

import json
import re
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_workbench.core.settings import PetSettings, PetSettingsPatch


PET_ID_RE = re.compile(r"^[a-z0-9_-]+$")
PET_SLUG_CHAR_RE = re.compile(r"[^a-z0-9_-]+")
MAX_PET_JSON_BYTES = 256 * 1024
MAX_SPRITESHEET_BYTES = 10 * 1024 * 1024


class PetError(ValueError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


class PetService:
    def __init__(self, *, repo_root: str | Path, app_settings_store: Any) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.app_settings_store = app_settings_store

    def get_settings(self) -> dict[str, Any]:
        settings = self.app_settings_store.get().pet
        return {"settings": settings.model_dump(mode="json")}

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise PetError("INVALID_PET_SETTINGS", "Pet settings update must be a JSON object.")
        try:
            PetSettingsPatch.model_validate(values)
            settings = self.app_settings_store.patch({"pet": values}).pet
        except ValidationError as exc:
            error = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(item) for item in error.get("loc", []))
            message = str(error.get("msg") or "Invalid pet settings.")
            if location:
                message = f"{location}: {message}"
            raise PetError("INVALID_PET_SETTINGS", message) from exc
        return {"settings": settings.model_dump(mode="json")}

    def list_pets(self) -> dict[str, Any]:
        return self.scan_pets()

    def scan_pets(self) -> dict[str, Any]:
        data_dir = pet_data_dir(self.repo_root)
        if not data_dir.exists():
            return {"pets": []}
        if not data_dir.is_dir():
            raise PetError("PET_DATA_DIR_INVALID", "Pet data path is not a directory.")
        pets = [self._validate_pet_dir(path.name) for path in sorted(data_dir.iterdir()) if path.is_dir()]
        return {"pets": pets}

    def validate_pet(self, pet_id: str) -> dict[str, Any]:
        return self._validate_pet_dir(validate_pet_id(pet_id))

    def import_pet(self, pet_json: bytes, spritesheet: bytes) -> dict[str, Any]:
        manifest = _parse_pet_json_upload(pet_json)
        _validate_spritesheet_upload(spritesheet)
        data_dir = pet_data_dir(self.repo_root)
        data_dir.mkdir(parents=True, exist_ok=True)
        pet_id = _unique_pet_id(data_dir, _pet_id_from_manifest(manifest, pet_json))
        pet_dir = safe_pet_dir(self.repo_root, pet_id)
        pet_dir.mkdir(parents=False, exist_ok=False)
        try:
            (pet_dir / "pet.json").write_bytes(pet_json)
            (pet_dir / "spritesheet.webp").write_bytes(spritesheet)
            pet = self._validate_pet_dir(pet_id)
            if not pet["valid"]:
                raise PetError(
                    "PET_IMPORT_INVALID",
                    "Imported pet is not valid.",
                    {"pet_id": pet_id, "errors": pet["errors"]},
                )
        except Exception:
            if pet_dir.is_dir():
                shutil.rmtree(pet_dir)
            raise
        settings = self.update_settings({"default_pet_id": pet_id, "pet_enabled": True})["settings"]
        return {
            "pet": pet,
            "pets": self.scan_pets()["pets"],
            "selected": True,
            "settings": settings,
            "warnings": [],
        }

    def delete_pet(self, pet_id: str) -> dict[str, Any]:
        pet_id = validate_pet_id(pet_id)
        pet_dir = safe_pet_dir(self.repo_root, pet_id)
        if not pet_dir.exists():
            raise PetError("PET_NOT_FOUND", f"Pet not found: {pet_id}", {"pet_id": pet_id})
        if not pet_dir.is_dir():
            raise PetError("PET_PATH_INVALID", f"Pet path is not a directory: {pet_id}", {"pet_id": pet_id})
        shutil.rmtree(pet_dir)
        settings = self.app_settings_store.get().pet
        if settings.default_pet_id == pet_id:
            self.update_settings({"default_pet_id": ""})
        return {"deleted": True, "pet_id": pet_id, "pets": self.scan_pets()["pets"]}

    def spritesheet_path(self, pet_id: str) -> Path:
        path = safe_pet_dir(self.repo_root, pet_id) / "spritesheet.webp"
        if not path.is_file():
            raise PetError("PET_SPRITESHEET_NOT_FOUND", "Missing spritesheet.webp", {"pet_id": pet_id})
        return path

    def _validate_pet_dir(self, pet_id: str) -> dict[str, Any]:
        try:
            pet_id = validate_pet_id(pet_id)
        except PetError as exc:
            return _pet_result(str(pet_id), valid=False, status="invalid_pet_id", errors=[exc.message])

        pet_dir = safe_pet_dir(self.repo_root, pet_id)
        errors: list[str] = []
        status = "valid"
        display_name = pet_id
        description = ""
        manifest = pet_dir / "pet.json"
        spritesheet = pet_dir / "spritesheet.webp"
        if not manifest.is_file():
            errors.append("Missing pet.json")
            status = "missing_manifest"
        else:
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("pet.json must be a JSON object")
                display_name = str(data.get("displayName") or data.get("name") or pet_id)
                description = str(data.get("description") or "")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(str(exc) or "pet.json is not valid JSON")
                status = "invalid_manifest"
        if not spritesheet.is_file():
            errors.append("Missing spritesheet.webp")
            if status == "valid":
                status = "missing_spritesheet"
        return _pet_result(
            pet_id,
            display_name=display_name,
            description=description,
            valid=not errors,
            status=status if errors else "valid",
            errors=errors,
        )


def validate_pet_id(pet_id: str) -> str:
    if not isinstance(pet_id, str) or not pet_id:
        raise PetError("INVALID_PET_ID", "Pet id is required.")
    if pet_id in {".", ".."} or ".." in pet_id or "/" in pet_id or "\\" in pet_id:
        raise PetError("INVALID_PET_ID", "Pet id must be a safe slug.")
    if Path(pet_id).is_absolute() or not PET_ID_RE.fullmatch(pet_id):
        raise PetError(
            "INVALID_PET_ID",
            "Pet id must contain only lowercase letters, numbers, underscores, and hyphens.",
        )
    return pet_id


def pet_data_dir(root: str | Path) -> Path:
    return Path(root).resolve() / "data" / "pet"


def safe_pet_dir(root: str | Path, pet_id: str) -> Path:
    data_dir = pet_data_dir(root).resolve()
    target = (data_dir / validate_pet_id(pet_id)).resolve()
    try:
        target.relative_to(data_dir)
    except ValueError as exc:
        raise PetError("INVALID_PET_ID", "Pet id resolves outside data/pet.") from exc
    return target


def _parse_pet_json_upload(data: bytes) -> dict[str, Any]:
    if not data:
        raise PetError("PET_JSON_EMPTY", "pet.json is required.")
    if len(data) > MAX_PET_JSON_BYTES:
        raise PetError("PET_JSON_TOO_LARGE", "pet.json is too large.", {"max_bytes": MAX_PET_JSON_BYTES})
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PetError("PET_JSON_INVALID", "pet.json must be valid UTF-8 JSON.") from exc
    if not isinstance(parsed, dict):
        raise PetError("PET_JSON_INVALID", "pet.json must be a JSON object.")
    return parsed


def _validate_spritesheet_upload(data: bytes) -> None:
    if not data:
        raise PetError("PET_SPRITESHEET_EMPTY", "spritesheet.webp is required.")
    if len(data) > MAX_SPRITESHEET_BYTES:
        raise PetError(
            "PET_SPRITESHEET_TOO_LARGE",
            "spritesheet.webp is too large.",
            {"max_bytes": MAX_SPRITESHEET_BYTES},
        )
    if len(data) < 12 or not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        raise PetError("PET_SPRITESHEET_INVALID", "spritesheet.webp must be a WebP file.")


def _pet_id_from_manifest(manifest: dict[str, Any], raw: bytes) -> str:
    value = manifest.get("id")
    if isinstance(value, str):
        candidate = value.strip().lower()
        if PET_ID_RE.fullmatch(candidate):
            return candidate
    for key in ("displayName", "name"):
        if isinstance(manifest.get(key), str):
            slug = _slugify(str(manifest[key]))
            if slug:
                return slug
    return f"pet_{sha256(raw).hexdigest()[:10]}"


def _unique_pet_id(data_dir: Path, base_id: str) -> str:
    base_id = validate_pet_id(base_id)
    for suffix in range(1, 101):
        candidate = base_id if suffix == 1 else f"{base_id}_{suffix}"
        if not (data_dir / candidate).exists():
            return candidate
    raise PetError("PET_IMPORT_NAME_EXHAUSTED", "Could not allocate a unique pet id.", {"base_id": base_id})


def _slugify(value: str) -> str:
    slug = PET_SLUG_CHAR_RE.sub("_", value.strip().lower()).strip("_-")
    slug = re.sub(r"[_-]{2,}", "_", slug)
    if slug and not slug[0].isalnum():
        slug = f"pet_{slug}"
    return slug[:64].strip("_-")


def _pet_result(
    pet_id: str,
    *,
    display_name: str | None = None,
    description: str = "",
    valid: bool = True,
    status: str = "valid",
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": pet_id,
        "display_name": display_name or pet_id,
        "description": description,
        "source": "data",
        "valid": valid,
        "status": status,
        "errors": errors or [],
        "can_delete": True,
        "is_builtin": False,
        "spritesheet_url": f"/api/pets/{pet_id}/spritesheet.webp" if valid else None,
    }


__all__ = [
    "PetError",
    "PetService",
    "PetSettings",
    "safe_pet_dir",
    "validate_pet_id",
]

