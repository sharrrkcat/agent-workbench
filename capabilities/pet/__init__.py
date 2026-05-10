import json
import re
import shutil
from pathlib import Path
from typing import Any

from ai_workbench.core.config_schema import ConfigValidationError, resolve_config, validate_user_config


PET_ID_RE = re.compile(r"^[a-z0-9_-]+$")
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SETTINGS = {
    "pet_enabled": True,
    "default_pet_id": "",
    "pet_scale": 1.0,
    "show_status_bubble": True,
    "jump_on_hover": True,
    "running_prefix": "正在",
    "position": {"mode": "default", "x": None, "y": None},
    "bubble_texts": {
        "idle": "",
        "waiting": "等你一下",
        "done": "完成啦",
        "failed": "出错了",
        "cancelled": "已取消",
        "interrupted": "已中断",
        "wake": "我来啦",
        "tuck": "先睡一会儿",
        "status": "我在这里",
        "select": "换好啦",
        "reload": "重新扫描完成",
        "no_pet": "还没有可用的宠物",
        "import_success": "导入成功",
        "import_failed": "导入失败",
        "delete_success": "已删除",
        "delete_failed": "删除失败",
    },
}


class PetError(ValueError):
    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class CapabilityRuntime:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).resolve() if root is not None else REPO_ROOT

    def get_settings(self, context: dict | None = None) -> dict:
        config = _context_config(context)
        schema = _context_schema(context)
        if schema:
            return {"settings": resolve_config(schema, config)}
        return {"settings": _merge_defaults(config)}

    def update_settings(self, values: dict, context: dict | None = None) -> dict:
        if not isinstance(values, dict):
            raise PetError("INVALID_PET_SETTINGS", "Pet settings update must be a JSON object.")

        store = _context_store(context)
        schema = _context_schema(context)
        existing = _context_config(context)
        merged = {**existing, **values}
        if schema:
            try:
                validate_user_config(schema, merged)
                resolved = resolve_config(schema, merged)
            except ConfigValidationError as exc:
                raise PetError(exc.code, exc.message, {"field": exc.field}) from exc
        else:
            resolved = _merge_defaults(merged)

        if store is not None:
            store.set_config("pet", user_config=merged)
        return {"settings": resolved}

    def list_pets(self, context: dict | None = None) -> dict:
        return self.scan_pets(context=context)

    def scan_pets(self, context: dict | None = None) -> dict:
        root = self._root_from_context(context)
        data_dir = pet_data_dir(root)
        if not data_dir.exists():
            return {"pets": []}
        if not data_dir.is_dir():
            raise PetError("PET_DATA_DIR_INVALID", "Pet data path is not a directory.")
        pets = [self._validate_pet_dir(path.name, root) for path in sorted(data_dir.iterdir()) if path.is_dir()]
        return {"pets": pets}

    def validate_pet(self, pet_id: str, context: dict | None = None) -> dict:
        root = self._root_from_context(context)
        return self._validate_pet_dir(validate_pet_id(pet_id), root)

    def delete_pet(self, pet_id: str, context: dict | None = None) -> dict:
        root = self._root_from_context(context)
        pet_id = validate_pet_id(pet_id)
        pet_dir = safe_pet_dir(root, pet_id)
        if not pet_dir.exists():
            raise PetError("PET_NOT_FOUND", f"Pet not found: {pet_id}", {"pet_id": pet_id})
        if not pet_dir.is_dir():
            raise PetError("PET_PATH_INVALID", f"Pet path is not a directory: {pet_id}", {"pet_id": pet_id})

        pet = self._validate_pet_dir(pet_id, root)
        if pet.get("is_builtin"):
            raise PetError("PET_DELETE_FORBIDDEN", f"Builtin pet cannot be deleted: {pet_id}", {"pet_id": pet_id})

        shutil.rmtree(pet_dir)
        return {"deleted": True, "pet_id": pet_id}

    def _validate_pet_dir(self, pet_id: str, root: Path) -> dict:
        try:
            pet_id = validate_pet_id(pet_id)
        except PetError as exc:
            return _pet_result(pet_id, valid=False, status="invalid_pet_id", errors=[exc.message])

        pet_dir = safe_pet_dir(root, pet_id)
        errors: list[str] = []
        status = "valid"
        manifest = pet_dir / "pet.json"
        spritesheet = pet_dir / "spritesheet.webp"
        display_name = pet_id
        description = ""

        if not manifest.is_file():
            errors.append("Missing pet.json")
            status = "missing_manifest"
        else:
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    display_name = str(data.get("displayName") or data.get("name") or pet_id)
                    description = str(data.get("description") or "")
                else:
                    errors.append("pet.json must be a JSON object")
                    status = "invalid_manifest"
            except json.JSONDecodeError:
                errors.append("pet.json is not valid JSON")
                status = "invalid_manifest"

        if not spritesheet.is_file():
            errors.append("Missing spritesheet.webp")
            if status == "valid":
                status = "missing_spritesheet"

        valid = not errors
        return _pet_result(
            pet_id,
            display_name=display_name,
            description=description,
            valid=valid,
            status=status if not valid else "valid",
            errors=errors,
        )

    def _root_from_context(self, context: dict | None) -> Path:
        root = (context or {}).get("repo_root")
        return Path(root).resolve() if root is not None else self.root


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()


def validate_pet_id(pet_id: str) -> str:
    if not isinstance(pet_id, str) or not pet_id:
        raise PetError("INVALID_PET_ID", "Pet id is required.")
    if pet_id in {".", ".."} or ".." in pet_id or "/" in pet_id or "\\" in pet_id:
        raise PetError("INVALID_PET_ID", "Pet id must be a safe slug.")
    if Path(pet_id).is_absolute() or not PET_ID_RE.fullmatch(pet_id):
        raise PetError("INVALID_PET_ID", "Pet id must contain only lowercase letters, numbers, underscores, and hyphens.")
    return pet_id


def pet_data_dir(root: str | Path) -> Path:
    return Path(root).resolve() / "data" / "pet"


def safe_pet_dir(root: str | Path, pet_id: str) -> Path:
    data_dir = pet_data_dir(root)
    pet_dir = (data_dir / validate_pet_id(pet_id)).resolve()
    try:
        pet_dir.relative_to(data_dir.resolve())
    except ValueError as exc:
        raise PetError("INVALID_PET_ID", "Pet id resolves outside data/pet.") from exc
    return pet_dir


def _pet_result(
    pet_id: str,
    display_name: str | None = None,
    description: str = "",
    valid: bool = True,
    status: str = "valid",
    errors: list[str] | None = None,
) -> dict:
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


def _merge_defaults(config: dict | None) -> dict:
    return {**DEFAULT_SETTINGS, **(config or {})}


def _context_config(context: dict | None) -> dict:
    config = (context or {}).get("capability_config")
    if isinstance(config, dict):
        return dict(config)
    return {}


def _context_schema(context: dict | None):
    return (context or {}).get("config_schema") or []


def _context_store(context: dict | None):
    return (context or {}).get("capability_config_store")
