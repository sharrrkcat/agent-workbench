from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.settings import AppSettingsPatch, app_settings_patch_updates, app_settings_response, settings_validation_message


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/general")
def get_general_settings(state: RuntimeState = Depends(get_state)) -> dict:
    return app_settings_response(state.app_settings.get())


@router.patch("/general")
def patch_general_settings(payload: AppSettingsPatch, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return app_settings_response(state.app_settings.patch(app_settings_patch_updates(payload)))
    except ValidationError as exc:
        _raise_settings_validation(exc)


class LLMDefaultsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_model_profile_id: str | None = None


@router.get("/llm-defaults")
def get_llm_defaults(state: RuntimeState = Depends(get_state)) -> dict:
    return state.llm_defaults.get()


@router.patch("/llm-defaults")
def patch_llm_defaults(payload: LLMDefaultsPatch, state: RuntimeState = Depends(get_state)) -> dict:
    if payload.default_model_profile_id:
        try:
            profile = state.llm_profiles.get_by_id_or_alias(payload.default_model_profile_id)
        except KeyError:
            raise_error(404, "LLM_PROFILE_NOT_FOUND", f"Model profile not found: {payload.default_model_profile_id}")
        if not profile.enabled:
            raise_error(400, "LLM_PROFILE_DISABLED", f"Model profile is disabled: {profile.alias}")
    return state.llm_defaults.patch(payload.model_dump())


def _raise_settings_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_SETTING_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_SETTING_VALUE"
    raise_error(422, code, settings_validation_message(exc))
