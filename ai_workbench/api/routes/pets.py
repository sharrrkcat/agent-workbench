from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.datastructures import UploadFile

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.pet_service import PetError, PetSettingsPatch


router = APIRouter(prefix="/api/pets", tags=["pets"])


class PetSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]


@router.get("/settings")
def get_pet_settings(state: RuntimeState = Depends(get_state)) -> dict:
    return state.pet_service.get_settings()


@router.patch("/settings")
def patch_pet_settings(payload: PetSettingsRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        PetSettingsPatch.model_validate(payload.values)
        return state.pet_service.update_settings(payload.values)
    except (ValidationError, PetError) as exc:
        _raise_pet_error(exc)


@router.get("")
def list_pets(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.pet_service.list_pets()
    except PetError as exc:
        _raise_pet_error(exc)


@router.post("/scan")
def scan_pets(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.pet_service.scan_pets()
    except PetError as exc:
        _raise_pet_error(exc)


@router.post("/import")
async def import_pet(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    form = await request.form()
    allowed = {"pet_json", "spritesheet"}
    unexpected = [key for key, _ in form.multi_items() if key not in allowed]
    if unexpected:
        raise_error(422, "PET_IMPORT_UNEXPECTED_FILE", "Only pet.json and spritesheet.webp uploads are accepted.", {"fields": unexpected})
    json_items = form.getlist("pet_json")
    sprite_items = form.getlist("spritesheet")
    if len(json_items) != 1 or len(sprite_items) != 1:
        raise_error(422, "PET_IMPORT_MISSING_FILE", "pet.json and spritesheet.webp are each required exactly once.")
    pet_json, spritesheet = json_items[0], sprite_items[0]
    if not isinstance(pet_json, UploadFile) or not isinstance(spritesheet, UploadFile):
        raise_error(422, "PET_IMPORT_INVALID_FILE", "Both fields must be file uploads.")
    if pet_json.filename != "pet.json" or spritesheet.filename != "spritesheet.webp":
        raise_error(422, "PET_IMPORT_INVALID_FILE", "Upload filenames must be pet.json and spritesheet.webp.")
    try:
        return state.pet_service.import_pet(await pet_json.read(), await spritesheet.read())
    except PetError as exc:
        _raise_pet_error(exc)


@router.delete("/{pet_id}")
def delete_pet(pet_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.pet_service.delete_pet(pet_id)
    except PetError as exc:
        _raise_pet_error(exc)


@router.get("/{pet_id}/spritesheet.webp")
def get_pet_spritesheet(pet_id: str, state: RuntimeState = Depends(get_state)):
    try:
        return FileResponse(state.pet_service.spritesheet_path(pet_id), media_type="image/webp", filename="spritesheet.webp")
    except PetError as exc:
        _raise_pet_error(exc)


def _raise_pet_error(exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0] if exc.errors() else {}
        code = "UNKNOWN_PET_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_PET_SETTINGS"
        message = str(error.get("msg") or "Invalid pet settings.")
        raise_error(422, code, message)
    pet_error = exc if isinstance(exc, PetError) else PetError("PET_ERROR", str(exc))
    if pet_error.code in {"PET_NOT_FOUND", "PET_SPRITESHEET_NOT_FOUND"}:
        status = 404
    elif pet_error.code == "INVALID_PET_SETTINGS":
        status = 422
    else:
        status = 400
    raise_error(status, pet_error.code, pet_error.message, pet_error.detail)
