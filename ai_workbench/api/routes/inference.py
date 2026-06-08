from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from ai_workbench.api.errors import raise_error
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.inference.auth import check_inference_auth
from ai_workbench.core.inference.errors import (
    InferenceErrorCode,
    raise_workbench_inference_error,
)
from ai_workbench.core.inference.request_limits import check_content_length, read_limited_workbench_json
from ai_workbench.core.inference.schemas import status_response
from ai_workbench.core.inference.settings import StatelessInferenceSettings, resolve_inference_settings
from ai_workbench.core.inference.stateless import (
    StatelessInferenceError,
    inference_status_models_summary,
    validate_multimodal_embedding_request,
    workbench_model_list,
)
from ai_workbench.core.multimodal_profiles import (
    MultimodalEmbeddingModelProfile,
    MultimodalEmbeddingModelProfileCreate,
    MultimodalEmbeddingModelProfilePatch,
    multimodal_profile_updates,
)


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
        models=inference_status_models_summary(state),
    )


@router.get("/models")
def list_models(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    _guard_workbench_request(request, state)
    return workbench_model_list(state)


@router.get("/multimodal-embedding-models")
def list_multimodal_embedding_models(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [profile.model_dump() for profile in state.multimodal_embedding_profiles.list()]


@router.post("/multimodal-embedding-models")
def create_multimodal_embedding_model(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        request = MultimodalEmbeddingModelProfileCreate.model_validate(payload)
        profile = MultimodalEmbeddingModelProfile.model_validate(request.model_dump(exclude_none=True))
        return state.multimodal_embedding_profiles.create(profile).model_dump()
    except ValidationError as exc:
        _raise_multimodal_validation(exc)
    except ValueError as exc:
        raise_error(422, "INVALID_MULTIMODAL_EMBEDDING_MODEL", str(exc))


@router.get("/multimodal-embedding-models/{profile_id}")
def get_multimodal_embedding_model(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.multimodal_embedding_profiles.get(profile_id).model_dump()
    except KeyError:
        raise_error(404, "MULTIMODAL_EMBEDDING_MODEL_NOT_FOUND", f"Multimodal embedding model profile not found: {profile_id}")


@router.patch("/multimodal-embedding-models/{profile_id}")
def patch_multimodal_embedding_model(
    profile_id: str,
    payload: dict,
    state: RuntimeState = Depends(get_state),
) -> dict:
    try:
        request = MultimodalEmbeddingModelProfilePatch.model_validate(payload)
        updates = multimodal_profile_updates(request)
        return state.multimodal_embedding_profiles.update(profile_id, updates).model_dump()
    except ValidationError as exc:
        _raise_multimodal_validation(exc)
    except KeyError:
        raise_error(404, "MULTIMODAL_EMBEDDING_MODEL_NOT_FOUND", f"Multimodal embedding model profile not found: {profile_id}")
    except ValueError as exc:
        raise_error(422, "INVALID_MULTIMODAL_EMBEDDING_MODEL", str(exc))


@router.delete("/multimodal-embedding-models/{profile_id}")
def delete_multimodal_embedding_model(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = state.multimodal_embedding_profiles.delete(profile_id)
        return {"deleted": True, "profile_id": profile.id}
    except KeyError:
        raise_error(404, "MULTIMODAL_EMBEDDING_MODEL_NOT_FOUND", f"Multimodal embedding model profile not found: {profile_id}")


@router.post("/unload")
def unload_models(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


@router.post("/embeddings/multimodal")
async def create_multimodal_embeddings(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    settings = _guard_workbench_request(request, state)
    raw = await read_limited_workbench_json(request, settings)
    if not isinstance(raw, dict):
        raise_workbench_inference_error(400, InferenceErrorCode.INVALID_REQUEST)
    try:
        validate_multimodal_embedding_request(state, raw)
    except StatelessInferenceError as exc:
        raise_workbench_inference_error(exc.status_code, exc.code, exc.message)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


@router.post("/vision")
def run_vision_task(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _guard_workbench_request(request, state)
    raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)


def _raise_multimodal_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_MULTIMODAL_EMBEDDING_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_MULTIMODAL_EMBEDDING_MODEL"
    loc = ".".join(str(item) for item in error.get("loc", []))
    message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
    raise_error(422, code, message)
