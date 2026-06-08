from fastapi import APIRouter, Depends, Request

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.inference.auth import check_inference_auth
from ai_workbench.core.inference.errors import (
    InferenceErrorCode,
    raise_workbench_inference_error,
)
from ai_workbench.core.inference.request_limits import check_content_length
from ai_workbench.core.inference.schemas import status_response, workbench_models_response
from ai_workbench.core.inference.settings import StatelessInferenceSettings, resolve_inference_settings


router = APIRouter(prefix="/api/inference", tags=["inference"])


def _guard_workbench_request(request: Request, state: RuntimeState) -> StatelessInferenceSettings:
    settings = resolve_inference_settings(state.app_settings)
    if not settings.enabled:
        raise_workbench_inference_error(503, InferenceErrorCode.SERVICE_DISABLED)
    size_error = check_content_length(request, settings)
    if size_error is not None:
        status_code = 413 if size_error == InferenceErrorCode.REQUEST_TOO_LARGE else 400
        raise_workbench_inference_error(status_code, size_error)
    auth_error = check_inference_auth(
        request,
        require_api_key=settings.require_api_key,
        configured_api_key=settings.api_key,
    )
    if auth_error is not None:
        if auth_error == InferenceErrorCode.SERVICE_MISCONFIGURED:
            status_code = 500
        else:
            status_code = 401 if auth_error == InferenceErrorCode.AUTH_REQUIRED else 403
        raise_workbench_inference_error(status_code, auth_error)
    return settings


@router.get("/status")
def get_status(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    settings = _guard_workbench_request(request, state)
    return status_response(
        enabled=settings.enabled,
        auth_required=settings.require_api_key,
        api_key_configured=bool(settings.api_key),
        max_request_mb=settings.max_request_mb,
    )


@router.get("/models")
def list_models(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    _guard_workbench_request(request, state)
    return workbench_models_response()


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
