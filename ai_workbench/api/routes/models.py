from fastapi import APIRouter, Depends
from typing import Literal

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import request_body
from ai_workbench.api.schemas.common import DeletedResponse, TextResponse, error_responses
from ai_workbench.api.schemas.models import (
    ModelCreate, ModelInventoryItem, ModelPatch, ModelProfileResponse, ModelSettingsPatch,
    ModelSettingsResponse, ProviderModelsResponse, ProviderPatch, ProviderResponse,
)
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.inspection import ModelInspection, inspect_asr, inspect_reranker, inspect_siglip, inspect_text_embedding
from ai_workbench.core.models.schema import ModelInput, ModelKind, ModelLoadRequest, ModelProfile, ModelSettings, ModelStatus, ProviderInput, ProviderProfile, Tower
from ai_workbench.api.schemas.inference import VoiceAvailability

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/profiles/{profile_id}/voices", response_model=list[VoiceAvailability],
            responses=error_responses(400, 404), summary="Inspect preset voice availability without loading a model")
async def model_voices(profile_id: str, state: RuntimeState = Depends(get_state)):
    import asyncio
    return await asyncio.to_thread(state.model_manager.voice_list, profile_id)


def public_provider(profile: ProviderProfile) -> dict:
    result = profile.model_dump(mode="json", exclude={"connection": {"api_key"}})
    result["connection"]["has_api_key"] = bool(profile.connection.api_key)
    return result


def public_settings(settings: ModelSettings) -> dict:
    return {**settings.model_dump(exclude={"external_api_key"}), "has_external_api_key": bool(settings.external_api_key)}


def _binding(profile):
    return profile.source.model_dump(exclude={"lifecycle"}) if profile.source else None


@router.get("/providers", response_model=list[ProviderResponse], response_model_exclude_unset=True)
async def providers(state: RuntimeState = Depends(get_state)):
    return [public_provider(p) for p in state.provider_profiles.list()]


@router.post("/providers", response_model=ProviderResponse, response_model_exclude_unset=True, responses=error_responses(409))
async def create_provider(payload: ProviderInput, state: RuntimeState = Depends(get_state)):
    return public_provider(state.provider_profiles.create(ProviderProfile(**payload.model_dump())))


@router.get("/providers/{provider_id}", response_model=ProviderResponse, response_model_exclude_unset=True, responses=error_responses(404))
async def provider(provider_id: str, state: RuntimeState = Depends(get_state)):
    return public_provider(state.provider_profiles.get(provider_id))


@router.patch("/providers/{provider_id}", response_model=ProviderResponse, response_model_exclude_unset=True,
              openapi_extra=request_body(ProviderPatch), responses=error_responses(404, 409, 422))
async def update_provider(provider_id: str, payload: dict, state: RuntimeState = Depends(get_state)):
    current = state.provider_profiles.get(provider_id)
    merged = current.model_dump(include=set(ProviderInput.model_fields))
    for key, value in payload.items():
        merged[key] = {**merged[key], **value} if key == "connection" and isinstance(value, dict) else value
    values = ProviderInput.model_validate(merged)
    await state.model_manager.invalidate(("provider", provider_id))
    result = state.provider_profiles.update(provider_id, values.model_dump())
    if result.connection.base_url != current.connection.base_url:
        for profile in state.model_profiles.list("embedding"):
            if profile.source and profile.source.type == "provider" and profile.source.provider_profile_id == provider_id:
                _invalidate_profile_indexes(state, profile.id)
    return public_provider(result)


@router.delete("/providers/{provider_id}", response_model=DeletedResponse, responses=error_responses(404, 409))
async def delete_provider(provider_id: str, state: RuntimeState = Depends(get_state)):
    state.provider_profiles.get(provider_id)
    if any(p.source and p.source.type == "provider" and p.source.provider_profile_id == provider_id for p in state.model_profiles.list()):
        raise ModelError("PROVIDER_IN_USE", "A referenced provider cannot be deleted.", 409)
    await state.model_manager.invalidate(("provider", provider_id))
    state.provider_profiles.delete(provider_id)
    return {"deleted": True}


@router.get("/providers/{provider_id}/models", response_model=ProviderModelsResponse,
            responses=error_responses(404, 409, 422, 429, 502, 503, 504))
async def provider_models(provider_id: str, state: RuntimeState = Depends(get_state)):
    return {"models": await state.model_manager.provider_models(provider_id)}


@router.get("/profiles", response_model=list[ModelProfileResponse], response_model_exclude_unset=True)
async def profiles(kind: ModelKind | None = None, state: RuntimeState = Depends(get_state)):
    return [p.model_dump(mode="json") for p in state.model_profiles.list(kind)]


@router.post("/profiles", response_model=ModelProfileResponse, response_model_exclude_unset=True,
             openapi_extra=request_body(ModelCreate), responses=error_responses(404, 409, 422))
async def create_profile(payload: ModelInput, state: RuntimeState = Depends(get_state)):
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
    if payload.get("kind", current.kind) != current.kind:
        raise ModelError("MODEL_KIND_IMMUTABLE", "Create a new profile to use a different model kind.", 409)
    updated = ModelInput.model_validate({**current.model_dump(include=set(ModelInput.model_fields)), **payload})
    state.model_manager.validate_binding(ModelProfile(**updated.model_dump(), id=profile_id))
    state.model_manager.require_idle(state.model_manager.execution_key(updated))
    await state.model_manager.invalidate(state.model_manager.execution_key(current))
    result = state.model_profiles.update(profile_id, payload)
    if current.kind == "tts" and (not result.enabled or not result.external_enabled or
            (current.model_ref, _binding(current), current.parameters.get("architecture")) !=
            (result.model_ref, _binding(result), result.parameters.get("architecture"))):
        state.model_manager.invalidate_voice_references(profile_id)
    if current.kind == "embedding" and (_binding(current), current.model_ref, current.parameters) != (_binding(result), result.model_ref, result.parameters):
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
    await state.model_manager.invalidate(state.model_manager.execution_key(profile))
    state.model_profiles.delete(profile_id)
    state.model_manager.invalidate_voice_references(profile_id)
    return {"deleted": True}


@router.get("/profiles/{profile_id}/status", response_model=ModelStatus, response_model_exclude_unset=True, responses=error_responses(404))
async def profile_status(profile_id: str, state: RuntimeState = Depends(get_state)):
    return state.model_manager.status(profile_id).model_dump()


@router.get("/profiles/{profile_id}/log", response_model=TextResponse, responses=error_responses(404, 422, 503))
def profile_log(profile_id: str, tower: Tower | None = None, state: RuntimeState = Depends(get_state)):
    profile = state.model_profiles.get(profile_id)
    return {"text": state.model_manager.process_log(profile, tower=tower)}


@router.post("/profiles/{profile_id}/health", response_model=ModelStatus, response_model_exclude_unset=True,
             responses=error_responses(400, 404, 409, 422, 429, 502, 503, 504))
async def profile_health(profile_id: str, state: RuntimeState = Depends(get_state)):
    return (await state.model_manager.health(profile_id)).model_dump()


@router.post("/profiles/{profile_id}/load", response_model=ModelStatus, response_model_exclude_unset=True,
             responses=error_responses(400, 404, 409, 422, 429, 502, 503, 504))
async def load_profile(profile_id: str, payload: ModelLoadRequest | None = None, state: RuntimeState = Depends(get_state)):
    return (await state.model_manager.load(profile_id, tower=payload.tower if payload else None)).model_dump()


@router.post("/profiles/{profile_id}/unload", response_model=ModelStatus, response_model_exclude_unset=True,
             responses=error_responses(400, 404, 409, 422, 502, 503))
async def unload_profile(profile_id: str, state: RuntimeState = Depends(get_state)):
    return (await state.model_manager.unload(profile_id)).model_dump()


@router.get("/inventory", response_model=list[ModelInventoryItem])
async def model_inventory(kind: ModelKind | None = None, state: RuntimeState = Depends(get_state)):
    return inventory(state.repo_root, kind)


@router.get("/inspect", response_model=ModelInspection, responses=error_responses(404, 422),
            summary="Read local model configuration without loading weights")
async def inspect_model(kind: Literal["image_embedding", "embedding", "reranker", "asr"], model_ref: str,
                        query_prompt_name: str | None = None, document_prompt_name: str | None = None,
                        state: RuntimeState = Depends(get_state)):
    import asyncio
    if kind == "embedding":
        return await asyncio.to_thread(inspect_text_embedding, state.repo_root, model_ref,
            {"query_prompt_name": query_prompt_name, "document_prompt_name": document_prompt_name})
    if query_prompt_name is not None or document_prompt_name is not None:
        raise ModelError("INVALID_REQUEST", "Prompt selections apply only to text embeddings.", 422)
    if kind == "reranker":
        return await asyncio.to_thread(inspect_reranker, state.repo_root, model_ref)
    if kind == "asr":
        return await asyncio.to_thread(inspect_asr, state.repo_root, model_ref)
    return await asyncio.to_thread(inspect_siglip, state.repo_root, model_ref)


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
