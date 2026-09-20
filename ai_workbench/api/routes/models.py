from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import request_body
from ai_workbench.api.schemas.common import DeletedResponse, TextResponse, error_responses
from ai_workbench.api.schemas.models import (
    ModelCreate, ModelInventoryItem, ModelPatch, ModelProfileResponse, ModelSettingsPatch,
    ModelSettingsResponse, BackendModelsResponse, BackendPatch, BackendResponse,
)
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.schema import ModelInput, ModelKind, ModelProfile, ModelSettings, ModelStatus, BackendInput, BackendProfile
from ai_workbench.api.schemas.inference import VoiceAvailability

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/profiles/{profile_id}/voices", response_model=list[VoiceAvailability],
            responses=error_responses(400, 404), summary="Inspect preset voice availability without loading a model")
async def model_voices(profile_id: str, state: RuntimeState = Depends(get_state)):
    import asyncio
    return await asyncio.to_thread(state.model_manager.voice_list, profile_id)


def public_backend(profile: BackendProfile) -> dict:
    result = profile.model_dump(mode="json", exclude={"connection": {"api_key"}})
    if profile.connection is not None:
        result["connection"]["has_api_key"] = bool(profile.connection.api_key)
    return result


def public_settings(settings: ModelSettings) -> dict:
    return {**settings.model_dump(exclude={"external_api_key"}), "has_external_api_key": bool(settings.external_api_key)}


@router.get("/backends", response_model=list[BackendResponse], response_model_exclude_unset=True)
async def backends(state: RuntimeState = Depends(get_state)):
    return [public_backend(p) for p in state.backend_profiles.list()]


@router.post("/backends", response_model=BackendResponse, response_model_exclude_unset=True, responses=error_responses(409))
async def create_backend(payload: BackendInput, state: RuntimeState = Depends(get_state)):
    if payload.type == "local":
        raise ModelError("BACKEND_CONFLICT", "The local backend already exists.", 409)
    return public_backend(state.backend_profiles.create(BackendProfile(**payload.model_dump())))


@router.get("/backends/{backend_id}", response_model=BackendResponse, response_model_exclude_unset=True, responses=error_responses(404))
async def backend(backend_id: str, state: RuntimeState = Depends(get_state)):
    return public_backend(state.backend_profiles.get(backend_id))


@router.patch("/backends/{backend_id}", response_model=BackendResponse, response_model_exclude_unset=True,
              openapi_extra=request_body(BackendPatch), responses=error_responses(404, 409, 422))
async def update_backend(backend_id: str, payload: dict, state: RuntimeState = Depends(get_state)):
    current = state.backend_profiles.get(backend_id)
    if payload.get("type", current.type) != current.type:
        raise ModelError("BACKEND_TYPE_IMMUTABLE", "Backend type cannot be changed.", 409)
    merged = current.model_dump(include=set(BackendInput.model_fields))
    for key, value in payload.items():
        merged[key] = {**(merged[key] or {}), **value} if key in {"connection", "download"} and isinstance(value, dict) else value
    values = BackendInput.model_validate(merged)
    if backend_id == "local":
        if state.runtime_supervisor.active_job:
            raise ModelError("RUNTIME_INSTALLING", "Wait for the runtime task before editing the local backend.", 409)
        if values.enabled != current.enabled:
            await state.model_manager.invalidate_local()
    else:
        await state.model_manager.invalidate(backend_id)
    result = state.backend_profiles.update(backend_id, values.model_dump())
    if current.connection and result.connection.base_url != current.connection.base_url:
        for profile in state.model_profiles.list("embedding"):
            if profile.backend_profile_id == backend_id:
                _invalidate_profile_indexes(state, profile.id)
    if backend_id == "local":
        state.model_manager.runtime_changed()
    return public_backend(result)


@router.delete("/backends/{backend_id}", response_model=DeletedResponse, responses=error_responses(404, 409))
async def delete_backend(backend_id: str, state: RuntimeState = Depends(get_state)):
    if backend_id == "local" or any(p.backend_profile_id == backend_id for p in state.model_profiles.list()):
        raise ModelError("BACKEND_IN_USE", "The local backend or a referenced backend cannot be deleted.", 409)
    await state.model_manager.invalidate(backend_id)
    state.backend_profiles.delete(backend_id)
    return {"deleted": True}


@router.get("/backends/{backend_id}/models", response_model=BackendModelsResponse,
            responses=error_responses(404, 409, 422, 429, 502, 503, 504))
async def backend_models(backend_id: str, state: RuntimeState = Depends(get_state)):
    return {"models": await state.model_manager.backend_models(backend_id)}


@router.get("/profiles", response_model=list[ModelProfileResponse], response_model_exclude_unset=True)
async def profiles(kind: ModelKind | None = None, state: RuntimeState = Depends(get_state)):
    return [p.model_dump(mode="json") for p in state.model_profiles.list(kind)]


@router.post("/profiles", response_model=ModelProfileResponse, response_model_exclude_unset=True,
             openapi_extra=request_body(ModelCreate), responses=error_responses(404, 409, 422))
async def create_profile(payload: ModelInput, state: RuntimeState = Depends(get_state)):
    if payload.backend_profile_id:
        state.backend_profiles.get(payload.backend_profile_id)
    profile = ModelProfile(**payload.model_dump())
    state.model_manager.validate_binding(profile)
    return state.model_profiles.create(profile).model_dump(mode="json")


@router.get("/profiles/{profile_id}", response_model=ModelProfileResponse, response_model_exclude_unset=True, responses=error_responses(404))
async def profile(profile_id: str, state: RuntimeState = Depends(get_state)):
    return state.model_profiles.get(profile_id).model_dump(mode="json")


@router.patch("/profiles/{profile_id}", response_model=ModelProfileResponse, response_model_exclude_unset=True,
              openapi_extra=request_body(ModelPatch, description="Only submitted fields change. kind is immutable; cross-field validation uses the resulting saved object."),
              responses=error_responses(404, 409, 422))
async def update_profile(profile_id: str, payload: dict, state: RuntimeState = Depends(get_state)):
    if any(state.runs.get_config_snapshot(r.run_id).get("model_profile_id") == profile_id
           for r in state.runs.list_all_runs() if r.status not in {"DONE", "FAILED", "CANCELLED", "INTERRUPTED"}):
        raise ModelError("MODEL_BUSY", "An unfinished chat run uses this model configuration.", 409)
    current = state.model_profiles.get(profile_id)
    updated = ModelInput.model_validate({**current.model_dump(include=set(ModelInput.model_fields)), **payload})
    if updated.kind != current.kind:
        raise ModelError("MODEL_KIND_IMMUTABLE", "Create a new profile to use a different model kind.", 409)
    if updated.backend_profile_id:
        state.backend_profiles.get(updated.backend_profile_id)
    state.model_manager.validate_binding(ModelProfile(**updated.model_dump(), id=profile_id))
    state.model_manager.require_idle(state.model_manager.backend_key(updated))
    await state.model_manager.invalidate(state.model_manager.backend_key(current))
    result = state.model_profiles.update(profile_id, payload)
    if current.kind == "tts" and (not result.enabled or not result.external_enabled or
            (current.model_ref, current.backend_profile_id, current.execution_options, current.parameters.get("architecture")) !=
            (result.model_ref, result.backend_profile_id, result.execution_options, result.parameters.get("architecture"))):
        state.model_manager.invalidate_voice_references(profile_id)
    if current.kind == "embedding" and (current.backend_profile_id, current.model_ref, current.parameters, current.execution_options) != (result.backend_profile_id, result.model_ref, result.parameters, result.execution_options):
        _invalidate_profile_indexes(state, profile_id)
    return result.model_dump(mode="json")


def _invalidate_profile_indexes(state, profile_id):
    for base in state.knowledge.list_knowledge_bases():
        if base.embedding_model_profile_id == profile_id:
            state.knowledge.invalidate_base_index(base.id)


@router.delete("/profiles/{profile_id}", response_model=DeletedResponse, responses=error_responses(404, 409))
async def delete_profile(profile_id: str, state: RuntimeState = Depends(get_state)):
    profile = state.model_profiles.get(profile_id)
    settings = state.model_settings.get()
    references = [settings.default_model_profile_id, settings.utility_model_profile_id,
                  state.knowledge.get_settings().reranker_model_profile_id]
    references.extend(s.model_profile_id for s in state.sessions.list_sessions())
    references.extend(state.runs.get_config_snapshot(r.run_id).get("model_profile_id")
        for r in state.runs.list_all_runs() if r.status not in {"DONE", "FAILED", "CANCELLED", "INTERRUPTED"})
    references.extend(b.embedding_model_profile_id for b in state.knowledge.list_knowledge_bases())
    if profile_id in references:
        raise ModelError("MODEL_IN_USE", "Remove session, unfinished run, default or Knowledge references before deleting this model.", 409)
    await state.model_manager.invalidate(state.model_manager.backend_key(profile))
    state.model_profiles.delete(profile_id)
    state.model_manager.invalidate_voice_references(profile_id)
    return {"deleted": True}


@router.get("/profiles/{profile_id}/status", response_model=ModelStatus, response_model_exclude_unset=True, responses=error_responses(404))
async def profile_status(profile_id: str, state: RuntimeState = Depends(get_state)):
    return state.model_manager.status(profile_id).model_dump()


@router.get("/profiles/{profile_id}/log", response_model=TextResponse, responses=error_responses(404))
def profile_log(profile_id: str, state: RuntimeState = Depends(get_state)):
    profile = state.model_profiles.get(profile_id)
    return {"text": state.model_manager.process_log(profile)}


@router.post("/profiles/{profile_id}/health", response_model=ModelStatus, response_model_exclude_unset=True,
             responses=error_responses(400, 404, 409, 422, 429, 502, 503, 504))
async def profile_health(profile_id: str, state: RuntimeState = Depends(get_state)):
    return (await state.model_manager.health(profile_id)).model_dump()


@router.post("/profiles/{profile_id}/load", response_model=ModelStatus, response_model_exclude_unset=True,
             responses=error_responses(400, 404, 409, 422, 429, 502, 503, 504))
async def load_profile(profile_id: str, state: RuntimeState = Depends(get_state)):
    return (await state.model_manager.load(profile_id)).model_dump()


@router.post("/profiles/{profile_id}/unload", response_model=ModelStatus, response_model_exclude_unset=True,
             responses=error_responses(400, 404, 409, 422, 502, 503))
async def unload_profile(profile_id: str, state: RuntimeState = Depends(get_state)):
    return (await state.model_manager.unload(profile_id)).model_dump()


@router.get("/inventory", response_model=list[ModelInventoryItem])
async def model_inventory(kind: ModelKind | None = None, state: RuntimeState = Depends(get_state)):
    return inventory(state.repo_root, kind)


@router.get("/settings", response_model=ModelSettingsResponse, response_model_exclude_unset=True)
async def model_settings(state: RuntimeState = Depends(get_state)):
    return public_settings(state.model_settings.get())


@router.patch("/settings", response_model=ModelSettingsResponse, response_model_exclude_unset=True,
              openapi_extra=request_body(ModelSettingsPatch), responses=error_responses(404, 422, 503))
async def update_model_settings(payload: dict, state: RuntimeState = Depends(get_state)):
    current = state.model_settings.get()
    values = ModelSettings.model_validate({**current.model_dump(), **payload})
    for profile_id in (values.default_model_profile_id, values.utility_model_profile_id):
        if profile_id:
            state.model_manager.profile(profile_id, "llm")
    if values.external_enabled and not values.external_api_key.strip():
        raise ModelError("SERVICE_MISCONFIGURED", "Set an API key before enabling the external service.", 422)
    result = state.model_settings.patch(payload)
    if result.external_api_key != current.external_api_key or not result.external_enabled:
        state.model_manager.invalidate_voice_references()
    return public_settings(result)
