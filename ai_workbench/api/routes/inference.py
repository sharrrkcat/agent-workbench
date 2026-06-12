from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from ai_workbench.api.errors import raise_error
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.inference.auth import check_inference_auth
from ai_workbench.core.inference.errors import (
    InferenceErrorCode,
    raise_workbench_inference_error,
)
from ai_workbench.core.inference.multimodal_runtime import clear_multimodal_runtime_cache
from ai_workbench.core.inference.vision_runtime import clear_vision_runtime_cache
from ai_workbench.core.inference.request_limits import check_content_length, read_limited_workbench_body, read_limited_workbench_json
from ai_workbench.core.inference.schemas import InferenceUnloadRequest, status_response
from ai_workbench.core.inference.settings import StatelessInferenceSettings, resolve_inference_settings
from ai_workbench.core.inference.stateless import (
    StatelessInferenceError,
    create_multimodal_embeddings_response,
    create_vision_response,
    inference_status_models_summary,
    workbench_model_list,
)
from ai_workbench.core.profile_aliases import profile_alias_base, unique_profile_alias
from ai_workbench.core.multimodal_profiles import (
    MultimodalEmbeddingModelProfile,
    MultimodalEmbeddingModelProfileCreate,
    MultimodalEmbeddingModelProfilePatch,
    multimodal_profile_updates,
)
from ai_workbench.core.vision_profiles import (
    VisionModelProfile,
    VisionModelProfileCreate,
    VisionModelProfilePatch,
    vision_profile_updates,
)
from ai_workbench.core.provider_inventory import scan_internal_provider_models


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


@router.get("/model-inventory")
def list_model_inventory(kind: str, state: RuntimeState = Depends(get_state)) -> dict:
    if kind not in {"image_embedding", "vision"}:
        raise_error(422, "INVALID_MODEL_INVENTORY_KIND", "Model inventory kind must be image_embedding or vision.")
    inventory = scan_internal_provider_models("internal_transformers", state.repo_root)
    items = []
    for item in inventory["models"]:
        if item.get("kind") != kind:
            continue
        if item.get("source") != "internal" or item.get("backend") != "internal_transformers":
            continue
        ref = str(item.get("model_ref") or item.get("id") or "")
        if not ref.startswith(f"{kind}/"):
            continue
        items.append(
            {
                "ref": ref,
                "name": str(item.get("name") or item.get("display_name") or ref.removeprefix(f"{kind}/")),
                "kind": kind,
                "relative_path": item.get("relative_path"),
            }
        )
    return {
        "kind": kind,
        "models_root": inventory["models_root"],
        "items": items,
        "warnings": inventory["warnings"],
    }


@router.get("/multimodal-embedding-models")
def list_multimodal_embedding_models(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [profile.model_dump() for profile in state.multimodal_embedding_profiles.list()]


@router.post("/multimodal-embedding-models")
def create_multimodal_embedding_model(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        request = MultimodalEmbeddingModelProfileCreate.model_validate(payload)
        values = request.model_dump(exclude_none=True)
        values["alias"] = values.get("alias") or _next_profile_alias(
            state.multimodal_embedding_profiles,
            values.get("name"),
            values.get("provider_model_id"),
        )
        profile = MultimodalEmbeddingModelProfile.model_validate(values)
        return state.multimodal_embedding_profiles.create(profile).model_dump()
    except ValidationError as exc:
        _raise_multimodal_validation(exc)
    except ValueError as exc:
        _raise_multimodal_value_error(exc)


@router.get("/multimodal-embedding-models/{profile_id_or_alias}")
def get_multimodal_embedding_model(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.multimodal_embedding_profiles.get_by_id_or_alias(profile_id_or_alias).model_dump()
    except KeyError:
        raise_error(404, "MULTIMODAL_EMBEDDING_MODEL_NOT_FOUND", f"Multimodal embedding model profile not found: {profile_id_or_alias}")


@router.patch("/multimodal-embedding-models/{profile_id_or_alias}")
def patch_multimodal_embedding_model(
    profile_id_or_alias: str,
    payload: dict,
    state: RuntimeState = Depends(get_state),
) -> dict:
    try:
        request = MultimodalEmbeddingModelProfilePatch.model_validate(payload)
        updates = multimodal_profile_updates(request)
        return state.multimodal_embedding_profiles.update(profile_id_or_alias, updates).model_dump()
    except ValidationError as exc:
        _raise_multimodal_validation(exc)
    except KeyError:
        raise_error(404, "MULTIMODAL_EMBEDDING_MODEL_NOT_FOUND", f"Multimodal embedding model profile not found: {profile_id_or_alias}")
    except ValueError as exc:
        _raise_multimodal_value_error(exc)


@router.delete("/multimodal-embedding-models/{profile_id_or_alias}")
def delete_multimodal_embedding_model(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = state.multimodal_embedding_profiles.delete(profile_id_or_alias)
        return {"deleted": True, "profile_id": profile.id}
    except KeyError:
        raise_error(404, "MULTIMODAL_EMBEDDING_MODEL_NOT_FOUND", f"Multimodal embedding model profile not found: {profile_id_or_alias}")


@router.get("/vision-models")
def list_vision_models(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [profile.model_dump() for profile in state.vision_profiles.list()]


@router.post("/vision-models")
def create_vision_model(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        request = VisionModelProfileCreate.model_validate(payload)
        values = request.model_dump(exclude_none=True)
        values["alias"] = values.get("alias") or _next_profile_alias(
            state.vision_profiles,
            values.get("name"),
            values.get("provider_model_id"),
        )
        profile = VisionModelProfile.model_validate(values)
        return state.vision_profiles.create(profile).model_dump()
    except ValidationError as exc:
        _raise_vision_validation(exc)
    except ValueError as exc:
        _raise_vision_value_error(exc)


@router.get("/vision-models/{profile_id_or_alias}")
def get_vision_model(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.vision_profiles.get_by_id_or_alias(profile_id_or_alias).model_dump()
    except KeyError:
        raise_error(404, "VISION_MODEL_NOT_FOUND", f"Vision model profile not found: {profile_id_or_alias}")


@router.patch("/vision-models/{profile_id_or_alias}")
def patch_vision_model(
    profile_id_or_alias: str,
    payload: dict,
    state: RuntimeState = Depends(get_state),
) -> dict:
    try:
        request = VisionModelProfilePatch.model_validate(payload)
        updates = vision_profile_updates(request)
        return state.vision_profiles.update(profile_id_or_alias, updates).model_dump()
    except ValidationError as exc:
        _raise_vision_validation(exc)
    except KeyError:
        raise_error(404, "VISION_MODEL_NOT_FOUND", f"Vision model profile not found: {profile_id_or_alias}")
    except ValueError as exc:
        _raise_vision_value_error(exc)


@router.delete("/vision-models/{profile_id_or_alias}")
def delete_vision_model(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = state.vision_profiles.delete(profile_id_or_alias)
        return {"deleted": True, "profile_id": profile.id}
    except KeyError:
        raise_error(404, "VISION_MODEL_NOT_FOUND", f"Vision model profile not found: {profile_id_or_alias}")


@router.post("/unload")
async def unload_models(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    settings = _guard_workbench_request(request, state)
    raw_body = await read_limited_workbench_body(request, settings)
    if raw_body.strip():
        import json

        try:
            raw = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise_workbench_inference_error(400, InferenceErrorCode.INVALID_REQUEST)
        if not isinstance(raw, dict):
            raise_workbench_inference_error(400, InferenceErrorCode.INVALID_REQUEST)
    else:
        raw = {}
    try:
        payload = InferenceUnloadRequest.model_validate(raw)
    except ValidationError:
        raise_workbench_inference_error(400, InferenceErrorCode.INVALID_REQUEST)
    if payload.target not in {"image_embedding", "multimodal_embedding", "vision", "vision_task", "all"}:
        raise_workbench_inference_error(501, InferenceErrorCode.NOT_IMPLEMENTED)
    multimodal_profile_id = None
    vision_profile_id = None
    if payload.model:
        if payload.model.startswith("multimodal:"):
            if payload.target in {"vision", "vision_task"}:
                raise_workbench_inference_error(400, InferenceErrorCode.MODEL_NOT_ALLOWED)
            multimodal_profile_id = _resolve_multimodal_unload_profile_id(state, payload.model)
        elif payload.model.startswith("vision:"):
            if payload.target in {"image_embedding", "multimodal_embedding"}:
                raise_workbench_inference_error(400, InferenceErrorCode.MODEL_NOT_ALLOWED)
            vision_profile_id = _resolve_vision_unload_profile_id(state, payload.model)
        else:
            raise_workbench_inference_error(400, InferenceErrorCode.MODEL_NOT_ALLOWED)
    results = []
    if payload.target in {"image_embedding", "multimodal_embedding", "all"} and vision_profile_id is None:
        removed = clear_multimodal_runtime_cache(multimodal_profile_id)
        results.append(
            {
                "target": "multimodal_embedding",
                "status": "freed" if removed else "skipped",
                "removed": removed,
                "message": "Freed." if removed else "No multimodal embedding runtime loaded.",
            }
        )
    if payload.target in {"vision", "vision_task", "all"} and multimodal_profile_id is None:
        removed = clear_vision_runtime_cache(vision_profile_id)
        results.append(
            {
                "target": "vision",
                "status": "freed" if removed else "skipped",
                "removed": removed,
                "message": "Freed." if removed else "No vision runtime loaded.",
            }
        )
    return {
        "ok": True,
        "results": results,
    }


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
        return create_multimodal_embeddings_response(state, raw)
    except StatelessInferenceError as exc:
        raise_workbench_inference_error(exc.status_code, exc.code, exc.message)


@router.post("/vision")
async def run_vision_task_route(
    request: Request,
    state: RuntimeState = Depends(get_state),
) -> dict:
    settings = _guard_workbench_request(request, state)
    raw = await read_limited_workbench_json(request, settings)
    if not isinstance(raw, dict):
        raise_workbench_inference_error(400, InferenceErrorCode.INVALID_REQUEST)
    try:
        return create_vision_response(state, raw)
    except StatelessInferenceError as exc:
        raise_workbench_inference_error(exc.status_code, exc.code, exc.message)


def _raise_multimodal_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_MULTIMODAL_EMBEDDING_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_MULTIMODAL_EMBEDDING_MODEL"
    loc = ".".join(str(item) for item in error.get("loc", []))
    message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
    raise_error(422, code, message)


def _raise_multimodal_value_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "MULTIMODAL_EMBEDDING_ALIAS_EXISTS":
        raise_error(409, "MULTIMODAL_EMBEDDING_ALIAS_EXISTS", "Multimodal embedding model alias already exists.")
    raise_error(422, "INVALID_MULTIMODAL_EMBEDDING_MODEL", message)


def _raise_vision_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_VISION_MODEL_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_VISION_MODEL"
    loc = ".".join(str(item) for item in error.get("loc", []))
    message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
    raise_error(422, code, message)


def _raise_vision_value_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "VISION_MODEL_ALIAS_EXISTS":
        raise_error(409, "VISION_MODEL_ALIAS_EXISTS", "Vision model alias already exists.")
    raise_error(422, "INVALID_VISION_MODEL", message)


def _next_profile_alias(store, name: object, provider_model_id: object) -> str:
    existing: list[str] = []
    for profile in store.list():
        existing.append(str(getattr(profile, "alias", "") or ""))
        existing.append(str(getattr(profile, "id", "") or ""))
    base = profile_alias_base(name, provider_model_id, fallback="profile")
    return unique_profile_alias(base, existing)


def _resolve_multimodal_unload_profile_id(state: RuntimeState, model: str) -> str:
    store = getattr(state, "multimodal_embedding_profiles", None)
    if store is None:
        raise_workbench_inference_error(404, InferenceErrorCode.MODEL_NOT_FOUND)
    try:
        return store.get_by_id_or_alias(model.removeprefix("multimodal:")).id
    except KeyError:
        raise_workbench_inference_error(404, InferenceErrorCode.MODEL_NOT_FOUND)


def _resolve_vision_unload_profile_id(state: RuntimeState, model: str) -> str:
    store = getattr(state, "vision_profiles", None)
    if store is None:
        raise_workbench_inference_error(404, InferenceErrorCode.MODEL_NOT_FOUND)
    try:
        return store.get_by_id_or_alias(model.removeprefix("vision:")).id
    except KeyError:
        raise_workbench_inference_error(404, InferenceErrorCode.MODEL_NOT_FOUND)
