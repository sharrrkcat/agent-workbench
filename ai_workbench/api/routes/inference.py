from fastapi import APIRouter, Depends, Request

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.inference.auth import check_inference_auth_shape
from ai_workbench.core.inference.errors import (
    InferenceErrorCode,
    raise_workbench_inference_error,
)
from ai_workbench.core.inference.settings import resolve_inference_settings


router = APIRouter(prefix="/api/inference", tags=["inference"])


def _guard_workbench_request(request: Request, state: RuntimeState) -> None:
    settings = resolve_inference_settings(state.app_settings)
    if not settings.enabled:
        raise_workbench_inference_error(503, InferenceErrorCode.SERVICE_DISABLED)
    auth_error = check_inference_auth_shape(request, require_api_key=settings.require_api_key)
    if auth_error is not None:
        status_code = 401 if auth_error == InferenceErrorCode.AUTH_REQUIRED else 403
        raise_workbench_inference_error(status_code, auth_error)


@router.get("/status")
def get_status(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


@router.get("/models")
def list_models(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


@router.post("/unload")
def unload_models(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


@router.post("/embeddings/multimodal")
def create_multimodal_embeddings(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


@router.post("/vision")
def run_vision_task(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)
