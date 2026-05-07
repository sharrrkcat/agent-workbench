from fastapi import APIRouter, Depends
from pydantic import ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.settings import settings_validation_message


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/general")
def get_general_settings(state: RuntimeState = Depends(get_state)) -> dict:
    return state.app_settings.get().model_dump()


@router.patch("/general")
def patch_general_settings(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.app_settings.patch(payload).model_dump()
    except ValidationError as exc:
        error_type = exc.errors()[0].get("type") if exc.errors() else ""
        code = "UNKNOWN_SETTING_FIELD" if error_type == "extra_forbidden" else "INVALID_SETTING_VALUE"
        raise_error(422, code, settings_validation_message(exc))
