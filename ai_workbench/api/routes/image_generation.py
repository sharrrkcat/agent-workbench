from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.image_generation.profiles import (
    DEFAULT_IMAGE_GENERATION_TASKS,
    ImageModelProfile,
    ImageModelProfileCreate,
    ImageModelProfilePatch,
    image_generation_profile_updates,
)
from ai_workbench.core.profile_aliases import profile_alias_base, unique_profile_alias


router = APIRouter(prefix="/api/image-generation", tags=["image-generation"])

INVENTORY_KINDS = {
    "checkpoint": ("checkpoints", "image_generation/checkpoints"),
    "vae": ("vae", "image_generation/vae"),
    "lora": ("loras", "image_generation/loras"),
}
MODEL_FILE_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
MODEL_DIRECTORY_MARKERS = {"model_index.json", "config.json"}


@router.get("/status")
def get_image_generation_status(state: RuntimeState = Depends(get_state)) -> dict:
    if state.image_generation_service is not None:
        return state.image_generation_service.status()
    profiles = state.image_generation_profiles.list()
    return {
        "ok": True,
        "service": "internal",
        "profiles_total": len(profiles),
        "profiles_enabled": sum(1 for profile in profiles if profile.enabled),
        "supported_tasks": list(DEFAULT_IMAGE_GENERATION_TASKS),
        "supported_architectures": ["sd15", "sdxl", "z_image"],
        "runtime": {"available": False, "status": "not_configured"},
    }


@router.post("/unload")
def unload_image_generation_runtime(payload: dict | None = None, state: RuntimeState = Depends(get_state)) -> dict:
    if state.image_generation_service is None:
        return {
            "ok": False,
            "target": "image_generation",
            "status": "unavailable",
            "removed": 0,
            "message": "Image generation service is not configured.",
        }
    values = payload or {}
    return state.image_generation_service.unload(profile_id_or_alias=values.get("profile_id_or_alias"))


@router.get("/model-inventory")
def list_image_generation_model_inventory(kind: str, state: RuntimeState = Depends(get_state)) -> dict:
    if kind not in INVENTORY_KINDS:
        raise_error(422, "INVALID_IMAGE_GENERATION_INVENTORY_KIND", "Model inventory kind must be checkpoint, vae, or lora.")
    directory, ref_prefix = INVENTORY_KINDS[kind]
    root = _image_generation_model_root(state.repo_root, directory)
    return {
        "kind": kind,
        "models_root": "data/models",
        "items": _scan_inventory_items(root, ref_prefix, directory, kind),
        "warnings": [],
    }


@router.get("/model-profiles")
def list_image_generation_model_profiles(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [profile.model_dump() for profile in state.image_generation_profiles.list()]


@router.post("/model-profiles")
def create_image_generation_model_profile(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        request = ImageModelProfileCreate.model_validate(payload)
        values = request.model_dump(exclude_none=True)
        values["alias"] = values.get("alias") or _next_profile_alias(
            state.image_generation_profiles,
            values.get("name"),
            values.get("checkpoint_ref"),
        )
        profile = ImageModelProfile.model_validate(values)
        return state.image_generation_profiles.create(profile).model_dump()
    except ValidationError as exc:
        _raise_image_generation_validation(exc)
    except ValueError as exc:
        _raise_image_generation_value_error(exc)


@router.get("/model-profiles/{profile_id_or_alias}")
def get_image_generation_model_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.image_generation_profiles.get_by_id_or_alias(profile_id_or_alias).model_dump()
    except KeyError:
        raise_error(
            404,
            "IMAGE_GENERATION_MODEL_NOT_FOUND",
            f"Image generation model profile not found: {profile_id_or_alias}",
        )


@router.patch("/model-profiles/{profile_id_or_alias}")
def patch_image_generation_model_profile(
    profile_id_or_alias: str,
    payload: dict,
    state: RuntimeState = Depends(get_state),
) -> dict:
    try:
        request = ImageModelProfilePatch.model_validate(payload)
        updates = image_generation_profile_updates(request)
        return state.image_generation_profiles.update(profile_id_or_alias, updates).model_dump()
    except ValidationError as exc:
        _raise_image_generation_validation(exc)
    except KeyError:
        raise_error(
            404,
            "IMAGE_GENERATION_MODEL_NOT_FOUND",
            f"Image generation model profile not found: {profile_id_or_alias}",
        )
    except ValueError as exc:
        _raise_image_generation_value_error(exc)


@router.delete("/model-profiles/{profile_id_or_alias}")
def delete_image_generation_model_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = state.image_generation_profiles.delete(profile_id_or_alias)
        return {"deleted": True, "profile_id": profile.id}
    except KeyError:
        raise_error(
            404,
            "IMAGE_GENERATION_MODEL_NOT_FOUND",
            f"Image generation model profile not found: {profile_id_or_alias}",
        )


def _raise_image_generation_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_IMAGE_GENERATION_MODEL_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_IMAGE_GENERATION_MODEL"
    loc = ".".join(str(item) for item in error.get("loc", []))
    message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
    raise_error(422, code, message)


def _raise_image_generation_value_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "IMAGE_GENERATION_MODEL_ALIAS_EXISTS":
        raise_error(409, "IMAGE_GENERATION_MODEL_ALIAS_EXISTS", "Image generation model alias already exists.")
    raise_error(422, "INVALID_IMAGE_GENERATION_MODEL", message)


def _next_profile_alias(store: Any, name: object, checkpoint_ref: object) -> str:
    existing: list[str] = []
    for profile in store.list():
        existing.append(str(getattr(profile, "alias", "") or ""))
        existing.append(str(getattr(profile, "id", "") or ""))
    base = profile_alias_base(name, checkpoint_ref, fallback="image-model")
    return unique_profile_alias(base, existing)


def _image_generation_model_root(repo_root: Path | None, directory: str) -> Path:
    root = Path(repo_root or ".").resolve() / "data" / "models" / "image_generation" / directory
    root.mkdir(parents=True, exist_ok=True)
    return root


def _scan_inventory_items(root: Path, ref_prefix: str, directory: str, kind: str) -> list[dict]:
    items: list[dict] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().lower()):
        if path.is_symlink() or not _is_safe_descendant(path, root):
            continue
        if path.is_dir():
            if not _looks_like_model_directory(path):
                continue
            name = path.name
        elif path.is_file() and path.suffix.casefold() in MODEL_FILE_EXTENSIONS:
            name = path.stem
        else:
            continue
        relative = path.relative_to(root).as_posix()
        items.append(
            {
                "ref": f"{ref_prefix}/{relative}",
                "name": name,
                "kind": kind,
                "relative_path": f"image_generation/{directory}/{relative}",
            }
        )
    return items


def _looks_like_model_directory(path: Path) -> bool:
    try:
        children = [child for child in path.iterdir() if not child.is_symlink()]
    except OSError:
        return False
    if any(child.is_file() and child.name in MODEL_DIRECTORY_MARKERS for child in children):
        return True
    return any(child.is_file() and child.suffix.casefold() in MODEL_FILE_EXTENSIONS for child in children)


def _is_safe_descendant(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
