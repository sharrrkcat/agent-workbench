from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from capabilities.pet import PetError, safe_pet_dir


router = APIRouter(prefix="/api/pets", tags=["pets"])


class PetSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]

    @field_validator("values")
    @classmethod
    def values_must_be_object(cls, value):
        if not isinstance(value, dict):
            raise ValueError("values must be a JSON object")
        return value


@router.get("/settings")
def get_pet_settings(state: RuntimeState = Depends(get_state)) -> dict:
    return _runtime(state).get_settings(context=_context(state))


@router.patch("/settings")
def patch_pet_settings(payload: dict[str, Any], state: RuntimeState = Depends(get_state)) -> dict:
    values = payload.get("values", payload)
    try:
        parsed = PetSettingsPatch.model_validate({"values": values})
        return _runtime(state).update_settings(parsed.values, context=_context(state))
    except ValidationError as exc:
        message = str(exc.errors()[0].get("msg", "Invalid pet settings")) if exc.errors() else "Invalid pet settings"
        raise_error(422, "INVALID_PET_SETTINGS", message)
    except PetError as exc:
        _raise_pet_error(exc)


@router.get("")
def list_pets(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return _runtime(state).list_pets(context=_context(state))
    except PetError as exc:
        _raise_pet_error(exc)


@router.post("/scan")
def scan_pets(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return _runtime(state).scan_pets(context=_context(state))
    except PetError as exc:
        _raise_pet_error(exc)


@router.delete("/{pet_id}")
def delete_pet(pet_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return _runtime(state).delete_pet(pet_id, context=_context(state))
    except PetError as exc:
        _raise_pet_error(exc)


@router.get("/{pet_id}/spritesheet.webp")
def get_pet_spritesheet(pet_id: str, state: RuntimeState = Depends(get_state)):
    try:
        pet_dir = safe_pet_dir(_repo_root(state), pet_id)
        spritesheet = pet_dir / "spritesheet.webp"
        if not spritesheet.is_file():
            raise PetError("PET_SPRITESHEET_NOT_FOUND", "Missing spritesheet.webp", {"pet_id": pet_id})
        return FileResponse(spritesheet, media_type="image/webp", filename="spritesheet.webp")
    except PetError as exc:
        _raise_pet_error(exc)


def _runtime(state: RuntimeState):
    return state.runtimes.get_runtime("pet")


def _repo_root(state: RuntimeState) -> Path:
    return Path(state.repo_root).resolve()


def _context(state: RuntimeState) -> dict:
    capability = state.capabilities.get("pet")
    stored = state.capability_configs.get_config("pet")
    return {
        "repo_root": _repo_root(state),
        "capability_config": stored.get("user_config", {}),
        "capability_config_store": state.capability_configs,
        "config_schema": capability.config_schema,
    }


def _raise_pet_error(exc: PetError) -> None:
    code = exc.code or "PET_ERROR"
    status = 404 if code in {"PET_NOT_FOUND", "PET_SPRITESHEET_NOT_FOUND"} else 400
    raise_error(status, code, exc.message, exc.detail)
