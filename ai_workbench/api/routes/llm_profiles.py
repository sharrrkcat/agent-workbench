from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.secrets import MASKED_SECRET
from ai_workbench.core.schema.llm_profile import LLMProfileSchema
from ai_workbench.core.time import utc_now


router = APIRouter(prefix="/api/llm-profiles", tags=["models"])


class LLMProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str
    name: str
    provider_profile_id: str | None = None
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model_id: str = ""
    enabled: bool = True
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    supports_vision: bool = False
    supports_tools: bool = False
    supports_reasoning: bool = False
    supports_streaming: bool = True
    supports_json_mode: bool = False
    external_inference_enabled: bool = False
    notes: str | None = None


class LLMProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None = None
    name: str | None = None
    provider_profile_id: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    enabled: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    supports_vision: bool | None = None
    supports_tools: bool | None = None
    supports_reasoning: bool | None = None
    supports_streaming: bool | None = None
    supports_json_mode: bool | None = None
    external_inference_enabled: bool | None = None
    notes: str | None = None


@router.get("")
def list_llm_profiles(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [_serialize(profile) for profile in state.llm_profiles.list()]


@router.post("")
def create_llm_profile(payload: LLMProfileCreateRequest, state: RuntimeState = Depends(get_state)) -> dict:
    values = payload.model_dump()
    if values.get("provider_profile_id"):
        _provider(state, values["provider_profile_id"])
    try:
        profile = LLMProfileSchema(id=str(uuid4()), created_at=utc_now(), updated_at=utc_now(), **values)
        return _serialize(state.llm_profiles.create(profile))
    except (ValidationError, ValueError) as exc:
        code = "LLM_PROFILE_ALIAS_CONFLICT" if "alias" in str(exc).lower() else "LLM_PROFILE_INVALID"
        raise_error(409 if code.endswith("CONFLICT") else 422, code, str(exc) or "Invalid model profile.")


@router.get("/{profile_id_or_alias}")
def get_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    return _serialize(_profile(state, profile_id_or_alias))


@router.patch("/{profile_id_or_alias}")
def patch_llm_profile(profile_id_or_alias: str, payload: LLMProfilePatchRequest, state: RuntimeState = Depends(get_state)) -> dict:
    current = _profile(state, profile_id_or_alias)
    values = payload.model_dump(exclude_unset=True)
    if values.get("api_key") == MASKED_SECRET:
        values.pop("api_key", None)
    if "provider_profile_id" in values and values["provider_profile_id"]:
        _provider(state, values["provider_profile_id"])
    try:
        return _serialize(state.llm_profiles.update(current.id, values))
    except (ValidationError, ValueError) as exc:
        raise_error(422, "LLM_PROFILE_INVALID", str(exc) or "Invalid model profile.")


@router.delete("/{profile_id_or_alias}")
def delete_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _profile(state, profile_id_or_alias)
    state.llm_profiles.delete(profile.id)
    return {"deleted": True, "profile_id": profile.id}


@router.post("/{profile_id_or_alias}/duplicate")
def duplicate_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _profile(state, profile_id_or_alias)
    data = profile.model_dump()
    data.update(id=str(uuid4()), alias=_copy_alias(profile.alias, state.llm_profiles), name=f"{profile.name} copy", created_at=utc_now(), updated_at=utc_now())
    return _serialize(state.llm_profiles.create(LLMProfileSchema.model_validate(data)))


@router.post("/{profile_id_or_alias}/test")
def test_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _profile(state, profile_id_or_alias)
    config = _profile_config(profile, state)
    try:
        models = state.llm.list_models(config)
        return {"success": True, "message": "Model provider is reachable.", "models": models}
    except Exception as exc:
        raise_error(502, "LLM_CONNECTION_FAILED", str(exc) or "Model provider connection failed.")


@router.get("/{profile_id_or_alias}/models")
def list_llm_profile_models(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _profile(state, profile_id_or_alias)
    try:
        models = state.llm.list_models(_profile_config(profile, state))
        return {"success": True, "models": [{"id": value} for value in models]}
    except Exception as exc:
        raise_error(502, "LLM_MODEL_LIST_FAILED", str(exc) or "Model list failed.")


def _profile(state: RuntimeState, value: str) -> LLMProfileSchema:
    try:
        return state.llm_profiles.get_by_id_or_alias(value)
    except KeyError:
        raise_error(404, "LLM_PROFILE_NOT_FOUND", f"Model profile not found: {value}")


def _provider(state: RuntimeState, value: str):
    try:
        return state.provider_profiles.get(value)
    except KeyError:
        raise_error(404, "LLM_PROVIDER_PROFILE_NOT_FOUND", f"Provider profile not found: {value}")


def _profile_config(profile: LLMProfileSchema, state: RuntimeState) -> dict[str, Any]:
    provider = _provider(state, profile.provider_profile_id) if profile.provider_profile_id else None
    return {
        "provider": provider.provider if provider else profile.provider,
        "base_url": provider.base_url if provider else profile.base_url,
        "api_key": provider.api_key if provider else profile.api_key,
        "model": profile.model_id,
        "model_id": profile.model_id,
        "timeout": (provider.timeout_seconds if provider else profile.timeout) or 60,
    }


def _serialize(profile: LLMProfileSchema) -> dict[str, Any]:
    data = profile.model_dump(mode="json")
    data["api_key"] = MASKED_SECRET if profile.api_key else ""
    data["api_key_set"] = bool(profile.api_key)
    return data


def _copy_alias(alias: str, store: Any) -> str:
    base = f"{alias}_copy"
    candidate = base
    index = 2
    while store.find_by_alias(candidate) is not None:
        candidate = f"{base}_{index}"
        index += 1
    return candidate
