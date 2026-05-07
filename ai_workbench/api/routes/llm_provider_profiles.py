from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.api.routes.configs import _runtime_list_models, _runtime_model_items, _safe_llm_error
from ai_workbench.core.config_schema import MASKED_SECRET
from ai_workbench.core.schema.llm_profile import ProviderProfileSchema


router = APIRouter(prefix="/api/llm-provider-profiles", tags=["llm-provider-profiles"])


class ProviderProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: Optional[int] = 60
    enabled: bool = True
    metadata: Dict[str, Any] = {}


class ProviderProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout_seconds: Optional[int] = None
    enabled: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


@router.get("")
def list_provider_profiles(state: RuntimeState = Depends(get_state)) -> list:
    return [_serialize_provider(profile) for profile in state.provider_profiles.list()]


@router.post("")
def create_provider_profile(payload: ProviderProfileCreateRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = ProviderProfileSchema(id=str(uuid4()), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **payload.model_dump())
        return _serialize_provider(state.provider_profiles.create(profile))
    except ValidationError as exc:
        raise_error(400, "LLM_PROVIDER_PROFILE_INVALID", _validation_message(exc))
    except ValueError as exc:
        raise_error(409, "LLM_PROVIDER_PROFILE_CONFLICT", str(exc))


@router.get("/{profile_id}")
def get_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return _serialize_provider(_get_provider_or_404(state, profile_id))


@router.patch("/{profile_id}")
def patch_provider_profile(profile_id: str, payload: ProviderProfilePatchRequest, state: RuntimeState = Depends(get_state)) -> dict:
    _get_provider_or_404(state, profile_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("api_key") == MASKED_SECRET:
        values.pop("api_key", None)
    if "api_key" in values and values.get("api_key") is None:
        values["api_key"] = ""
    try:
        return _serialize_provider(state.provider_profiles.update(profile_id, values))
    except ValidationError as exc:
        raise_error(400, "LLM_PROVIDER_PROFILE_INVALID", _validation_message(exc))


@router.delete("/{profile_id}")
def delete_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_provider_or_404(state, profile_id)
    used_by = [profile.id for profile in state.llm_profiles.list() if profile.provider_profile_id == profile_id]
    if used_by:
        raise_error(409, "LLM_PROVIDER_PROFILE_IN_USE", "Provider profile is used by model profiles.", {"model_profile_ids": used_by})
    state.provider_profiles.delete(profile_id)
    return {"deleted": True, "profile_id": profile_id}


@router.post("/{profile_id}/duplicate")
def duplicate_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_provider_or_404(state, profile_id)
    data = profile.model_dump()
    data["id"] = str(uuid4())
    data["name"] = f"{profile.name} copy"
    data["created_at"] = datetime.utcnow()
    data["updated_at"] = datetime.utcnow()
    created = state.provider_profiles.create(ProviderProfileSchema.model_validate(data))
    return _serialize_provider(created)


@router.get("/{profile_id}/models")
def list_provider_models(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return refresh_provider_models(profile_id, state)


@router.post("/{profile_id}/refresh-models")
def refresh_provider_models(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_provider_or_404(state, profile_id)
    if not profile.enabled:
        raise_error(400, "LLM_PROVIDER_PROFILE_DISABLED", f"Provider profile is disabled: {profile.name}", {"provider_profile_id": profile.id})
    try:
        runtime = state.runtimes.get_runtime("llm")
        models = _runtime_model_items(runtime, _provider_model_config(profile))
        return {
            "success": True,
            "provider_profile_id": profile.id,
            "provider": profile.provider,
            "models": models,
            "warnings": _provider_model_warnings(profile),
        }
    except Exception as exc:
        raise_error(
            502,
            "LLM_MODEL_LIST_FAILED",
            _safe_llm_error(exc, "Provider model list failed."),
            {"provider_profile_id": profile.id, "provider": profile.provider},
        )


@router.post("/{profile_id}/test")
def test_provider_profile(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_provider_or_404(state, profile_id)
    try:
        runtime = state.runtimes.get_runtime("llm")
        models = _runtime_list_models(runtime, _provider_model_config(profile))
        return {"success": True, "message": "Provider profile is reachable.", "base_url": profile.base_url, "models": models}
    except Exception as exc:
        raise_error(502, "LLM_CONNECTION_FAILED", _safe_llm_error(exc, "Provider profile connection failed."))


def _get_provider_or_404(state: RuntimeState, profile_id: str) -> ProviderProfileSchema:
    try:
        return state.provider_profiles.get(profile_id)
    except KeyError:
        raise_error(404, "LLM_PROVIDER_PROFILE_NOT_FOUND", f"Provider profile not found: {profile_id}")


def _serialize_provider(profile: ProviderProfileSchema) -> Dict[str, Any]:
    data = profile.model_dump()
    data["api_key"] = MASKED_SECRET if profile.api_key else ""
    data["api_key_set"] = bool(profile.api_key)
    return data


def _provider_model_config(profile: ProviderProfileSchema) -> Dict[str, Any]:
    return {
        "provider": profile.provider,
        "base_url": profile.base_url,
        "api_key": profile.api_key,
        "timeout": profile.timeout_seconds or 60,
    }


def _provider_model_warnings(profile: ProviderProfileSchema) -> list[str]:
    if profile.provider == "llama_cpp":
        return ["llama.cpp usually reports the currently served model. Use --alias for a stable model ID if needed."]
    return []


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Provider profile is invalid."
    return str(errors[0].get("msg") or "Provider profile is invalid.")
