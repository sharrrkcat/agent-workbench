from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.secrets import MASKED_SECRET
from ai_workbench.core.schema.llm_profile import ProviderProfileSchema
from ai_workbench.core.time import utc_now


router = APIRouter(prefix="/api/llm-provider-profiles", tags=["models"])


class ProviderProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: int | None = 60
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


@router.get("")
def list_provider_profiles(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [_serialize(item) for item in state.provider_profiles.list()]


@router.post("")
def create_provider_profile(payload: ProviderProfileCreateRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = ProviderProfileSchema(id=str(uuid4()), created_at=utc_now(), updated_at=utc_now(), **payload.model_dump())
        return _serialize(state.provider_profiles.create(profile))
    except (ValidationError, ValueError) as exc:
        raise_error(422, "LLM_PROVIDER_PROFILE_INVALID", str(exc) or "Invalid provider profile.")


@router.get("/{profile_id}")
def get_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return _serialize(_profile(state, profile_id))


@router.patch("/{profile_id}")
def patch_provider_profile(profile_id: str, payload: ProviderProfilePatchRequest, state: RuntimeState = Depends(get_state)) -> dict:
    current = _profile(state, profile_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("api_key") == MASKED_SECRET:
        values.pop("api_key", None)
    try:
        return _serialize(state.provider_profiles.update(current.id, values))
    except (ValidationError, ValueError) as exc:
        raise_error(422, "LLM_PROVIDER_PROFILE_INVALID", str(exc) or "Invalid provider profile.")


@router.delete("/{profile_id}")
def delete_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _profile(state, profile_id)
    used = [item.id for item in state.llm_profiles.list() if item.provider_profile_id == profile_id]
    if used:
        raise_error(409, "LLM_PROVIDER_PROFILE_IN_USE", "Provider profile is used by model profiles.", {"model_profile_ids": used})
    state.provider_profiles.delete(profile_id)
    return {"deleted": True, "profile_id": profile_id}


@router.post("/{profile_id}/duplicate")
def duplicate_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    current = _profile(state, profile_id)
    data = current.model_dump()
    data.update(id=str(uuid4()), name=f"{current.name} copy", created_at=utc_now(), updated_at=utc_now())
    return _serialize(state.provider_profiles.create(ProviderProfileSchema.model_validate(data)))


@router.post("/{profile_id}/test")
def test_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _profile(state, profile_id)
    try:
        models = state.llm.list_models(_provider_config(profile))
        return {"success": True, "message": "Provider is reachable.", "models": models}
    except Exception as exc:
        raise_error(502, "LLM_CONNECTION_FAILED", str(exc) or "Provider connection failed.")


@router.get("/{profile_id}/models")
def list_provider_models(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _profile(state, profile_id)
    try:
        models = state.llm.list_models(_provider_config(profile))
        return {"success": True, "provider_profile_id": profile.id, "models": [{"id": value} for value in models]}
    except Exception as exc:
        raise_error(502, "LLM_MODEL_LIST_FAILED", str(exc) or "Model list failed.")


def _profile(state: RuntimeState, profile_id: str) -> ProviderProfileSchema:
    try:
        return state.provider_profiles.get(profile_id)
    except KeyError:
        raise_error(404, "LLM_PROVIDER_PROFILE_NOT_FOUND", f"Provider profile not found: {profile_id}")


def _provider_config(profile: ProviderProfileSchema) -> dict[str, Any]:
    return {"provider": profile.provider, "base_url": profile.base_url, "api_key": profile.api_key, "timeout": profile.timeout_seconds or 60}


def _serialize(profile: ProviderProfileSchema) -> dict[str, Any]:
    data = profile.model_dump(mode="json")
    data["api_key"] = MASKED_SECRET if profile.api_key else ""
    data["api_key_set"] = bool(profile.api_key)
    return data
