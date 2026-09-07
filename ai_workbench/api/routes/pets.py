"""Presentation-independent position settings reserved for a future Pet UI."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.settings import PetSettings, PetSettingsPatch


router = APIRouter(prefix="/api/pets", tags=["pets"])


class PetSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: PetSettingsPatch


class PetSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: PetSettings


@router.get("/settings")
def get_pet_settings(state: RuntimeState = Depends(get_state)) -> PetSettingsResponse:
    return PetSettingsResponse(settings=state.app_settings.get().pet)


@router.patch("/settings")
def patch_pet_settings(payload: PetSettingsRequest, state: RuntimeState = Depends(get_state)) -> PetSettingsResponse:
    settings = state.app_settings.patch({"pet": payload.values.model_dump(exclude_unset=True)})
    return PetSettingsResponse(settings=settings.pet)
