from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.api.routes.configs import _runtime_list_models, _safe_llm_error
from ai_workbench.core.config_schema import MASKED_SECRET
from ai_workbench.core.schema.llm_profile import LLMProfileSchema
from ai_workbench.core.time import utc_now


router = APIRouter(prefix="/api/llm-profiles", tags=["llm-profiles"])


class LLMProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str
    name: str
    provider_profile_id: Optional[str] = None
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model_id: str = ""
    enabled: bool = True
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    supports_vision: bool = False
    supports_tools: bool = False
    supports_reasoning: bool = False
    supports_streaming: bool = True
    supports_json_mode: bool = False
    notes: Optional[str] = None


class LLMProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: Optional[str] = None
    name: Optional[str] = None
    provider_profile_id: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_id: Optional[str] = None
    enabled: Optional[bool] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    supports_vision: Optional[bool] = None
    supports_tools: Optional[bool] = None
    supports_reasoning: Optional[bool] = None
    supports_streaming: Optional[bool] = None
    supports_json_mode: Optional[bool] = None
    notes: Optional[str] = None


@router.get("")
def list_llm_profiles(state: RuntimeState = Depends(get_state)) -> list:
    return [_serialize_profile(profile) for profile in state.llm_profiles.list()]


@router.post("")
def create_llm_profile(payload: LLMProfileCreateRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        _validate_model_profile_create(payload, state)
        profile = LLMProfileSchema(id=str(uuid4()), created_at=utc_now(), updated_at=utc_now(), **payload.model_dump())
        created = state.llm_profiles.create(profile)
        return _serialize_profile(created)
    except ValidationError as exc:
        raise_error(400, "LLM_PROFILE_INVALID", _validation_message(exc))
    except ValueError as exc:
        code = "LLM_PROFILE_INVALID" if "required" in str(exc).lower() or "provider profile" in str(exc).lower() else "LLM_PROFILE_ALIAS_CONFLICT"
        raise_error(400 if code == "LLM_PROFILE_INVALID" else 409, code, str(exc) or "LLM profile alias already exists.")


@router.get("/{profile_id_or_alias}")
def get_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    return _serialize_profile(_get_profile_or_404(state, profile_id_or_alias))


@router.patch("/{profile_id_or_alias}")
def patch_llm_profile(
    profile_id_or_alias: str,
    payload: LLMProfilePatchRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    existing = _get_profile_or_404(state, profile_id_or_alias)
    values = payload.model_dump(exclude_unset=True)
    if values.get("api_key") == MASKED_SECRET:
        values.pop("api_key", None)
    if "api_key" in values and values.get("api_key") is None:
        values["api_key"] = ""
    try:
        updated = state.llm_profiles.update(existing.id, values)
        return _serialize_profile(updated)
    except ValidationError as exc:
        raise_error(400, "LLM_PROFILE_INVALID", _validation_message(exc))
    except ValueError as exc:
        raise_error(409, "LLM_PROFILE_ALIAS_CONFLICT", str(exc) or "LLM profile alias already exists.")


@router.delete("/{profile_id_or_alias}")
def delete_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_profile_or_404(state, profile_id_or_alias)
    state.llm_profiles.delete(profile.id)
    return {"deleted": True, "profile_id": profile.id}


@router.post("/{profile_id_or_alias}/duplicate")
def duplicate_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_profile_or_404(state, profile_id_or_alias)
    data = profile.model_dump()
    data["id"] = str(uuid4())
    data["alias"] = _copy_alias(profile.alias, state.llm_profiles)
    data["name"] = f"{profile.name} copy"
    data["created_at"] = utc_now()
    data["updated_at"] = utc_now()
    created = state.llm_profiles.create(LLMProfileSchema.model_validate(data))
    return _serialize_profile(created)


@router.post("/{profile_id_or_alias}/test")
def test_llm_profile(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_profile_or_404(state, profile_id_or_alias)
    try:
        _validate_profile_for_runtime(profile)
        runtime = state.runtimes.get_runtime("llm")
        models = _runtime_list_models(runtime, _profile_model_config(profile, state))
        return {
            "success": True,
            "message": "LLM profile is reachable.",
            "base_url": profile.base_url,
            "models": models,
        }
    except ValueError as exc:
        raise_error(400, "LLM_PROFILE_INVALID", str(exc))
    except Exception as exc:
        raise_error(
            502,
            "LLM_CONNECTION_FAILED",
            _safe_llm_error(exc, "LLM profile connection failed."),
            {"profile_id": profile.id, "alias": profile.alias},
        )


@router.get("/{profile_id_or_alias}/models")
def list_llm_profile_models(profile_id_or_alias: str, state: RuntimeState = Depends(get_state)) -> dict:
    profile = _get_profile_or_404(state, profile_id_or_alias)
    try:
        if not profile.provider_profile_id and not profile.base_url:
            raise ValueError(f"LLM profile '{profile.alias}' must define base_url.")
        runtime = state.runtimes.get_runtime("llm")
        models = _runtime_list_models(runtime, _profile_model_config(profile, state))
        return {"success": True, "models": [{"id": model_id} for model_id in models]}
    except ValueError as exc:
        raise_error(400, "LLM_PROFILE_INVALID", str(exc))
    except Exception as exc:
        raise_error(
            502,
            "LLM_MODEL_LIST_FAILED",
            _safe_llm_error(exc, "LLM profile model list failed."),
            {"profile_id": profile.id, "alias": profile.alias},
        )


def _get_profile_or_404(state: RuntimeState, profile_id_or_alias: str) -> LLMProfileSchema:
    try:
        return state.llm_profiles.get_by_id_or_alias(profile_id_or_alias)
    except KeyError:
        raise_error(404, "LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {profile_id_or_alias}")


def _serialize_profile(profile: LLMProfileSchema) -> Dict[str, Any]:
    data = profile.model_dump()
    data["api_key"] = MASKED_SECRET if profile.api_key else ""
    data["api_key_set"] = bool(profile.api_key)
    return data


def _profile_model_config(profile: LLMProfileSchema, state: RuntimeState | None = None) -> Dict[str, Any]:
    provider = None
    if profile.provider_profile_id and state is not None and state.provider_profiles is not None:
        provider = state.provider_profiles.get(profile.provider_profile_id)
    return {
        "provider": provider.provider if provider is not None else profile.provider,
        "base_url": provider.base_url if provider is not None else profile.base_url,
        "api_key": provider.api_key if provider is not None else profile.api_key,
        "model": profile.model_id,
        "model_id": profile.model_id,
        "timeout": (provider.timeout_seconds if provider is not None else profile.timeout) or 60,
    }


def _validate_profile_for_runtime(profile: LLMProfileSchema) -> None:
    if not profile.provider_profile_id and not profile.base_url:
        raise ValueError(f"Model profile '{profile.alias}' must define a provider profile or legacy base_url.")
    if not profile.model_id:
        raise ValueError(f"Model profile '{profile.alias}' must define model_id.")


def _validate_model_profile_create(payload: LLMProfileCreateRequest, state: RuntimeState) -> None:
    if not str(payload.name or "").strip():
        raise ValueError("name is required.")
    if not str(payload.provider_profile_id or "").strip():
        raise ValueError("provider_profile_id is required.")
    if not str(payload.model_id or "").strip():
        raise ValueError("model_id is required.")
    try:
        state.provider_profiles.get(str(payload.provider_profile_id))
    except KeyError as exc:
        raise ValueError(f"Provider profile not found: {payload.provider_profile_id}") from exc


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "LLM profile is invalid."
    return str(errors[0].get("msg") or "LLM profile is invalid.")


def _copy_alias(alias: str, store) -> str:
    base = f"{alias}_copy"
    candidate = base
    index = 2
    while store.find_by_alias(candidate) is not None:
        candidate = f"{base}_{index}"
        index += 1
    return candidate
