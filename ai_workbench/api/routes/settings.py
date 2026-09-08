from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.openapi import request_body
from ai_workbench.api.schemas.system import GeneralSettingsRequest, GeneralSettingsResponse
from ai_workbench.api.errors import raise_error
from ai_workbench.core.settings import AppSettingsPatch, app_settings_patch_updates, app_settings_response, settings_validation_message


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/general", response_model=GeneralSettingsResponse, response_model_exclude_unset=True)
def get_general_settings(state: RuntimeState = Depends(get_state)) -> dict:
    return app_settings_response(state.app_settings.get())


@router.patch("/general", response_model=GeneralSettingsResponse, response_model_exclude_unset=True,
    responses=error_responses(422), openapi_extra=request_body(GeneralSettingsRequest,
        description="Omission preserves values. null clears the optional group instruction; other scalar settings are non-nullable."))
def patch_general_settings(payload: AppSettingsPatch, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return app_settings_response(state.app_settings.patch(app_settings_patch_updates(payload)))
    except ValidationError as exc:
        _raise_settings_validation(exc)


def _raise_settings_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_SETTING_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_SETTING_VALUE"
    raise_error(422, code, settings_validation_message(exc))
