from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workbench.api.avatar import resolve_avatar_for_response
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.config_schema import (
    ConfigValidationError,
    clear_empty_enum_overrides,
    dump_config_schema,
    mask_config,
    merge_secret_patch,
    resolve_config,
    validate_user_config,
)
from ai_workbench.core.agent_settings import (
    normalize_display_override,
    normalize_runtime_override,
    resolved_agent_settings,
    write_overrides_to_manifest,
)
from ai_workbench.core.llm_config import LLMConfigError, public_llm_config_status, resolve_llm_config


router = APIRouter(tags=["configs"])


class UpdateConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    display: Optional[Dict[str, Any]] = None
    runtime: Optional[Dict[str, Any]] = None
    user_config: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("user_config", mode="before")
    @classmethod
    def user_config_must_be_object(cls, value):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("user_config must be a JSON object")
        return value


@router.get("/api/agent-configs")
def list_agent_configs(state: RuntimeState = Depends(get_state)) -> list:
    return [_serialize_agent_config(state, agent.id) for agent in state.agents.list()]


@router.get("/api/agent-configs/{agent_id}")
def get_agent_config(agent_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_agent_or_404(state, agent_id)
    return _serialize_agent_config(state, agent_id)


@router.patch("/api/agent-configs/{agent_id}")
def update_agent_config(agent_id: str, payload: UpdateConfigRequest, state: RuntimeState = Depends(get_state)) -> dict:
    agent = _get_agent_or_404(state, agent_id)
    user_config = None
    if payload.user_config is not None:
        existing = state.agent_configs.get_config(agent_id)["user_config"]
        user_config = _validate_config_patch(agent.config_schema, existing, payload.user_config)
    try:
        display = normalize_display_override(payload.display) if payload.display is not None else None
        runtime = normalize_runtime_override(payload.runtime) if payload.runtime is not None else None
        _validate_runtime_profile(state, runtime or {})
    except LLMConfigError as exc:
        raise_error(400, exc.code, exc.message)
    except ValueError as exc:
        raise_error(400, "INVALID_AGENT_OVERRIDE", str(exc))
    state.agent_configs.set_config(agent_id, enabled=payload.enabled, user_config=user_config, display=display, runtime=runtime)
    return _serialize_agent_config(state, agent_id)


class WriteManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False


@router.post("/api/agent-configs/{agent_id}/reset-overrides")
def reset_agent_overrides(agent_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_agent_or_404(state, agent_id)
    state.agent_configs.set_config(agent_id, display={}, runtime={})
    return _serialize_agent_config(state, agent_id)


@router.post("/api/agent-configs/{agent_id}/write-manifest")
def write_agent_manifest(agent_id: str, payload: WriteManifestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    agent = _get_agent_or_404(state, agent_id)
    if not payload.confirm:
        raise_error(400, "AGENT_MANIFEST_WRITE_CONFIRM_REQUIRED", "confirm=true is required to write agent overrides to manifest.")
    config = state.agent_configs.get_config(agent_id)
    try:
        agent_dir = state.agents.get_agent_dir(agent_id)
        write_overrides_to_manifest(agent, agent_dir, config)
        agent = state.agents.reload_agent(agent_id)
        state.agent_configs.set_config(agent_id, display={}, runtime={})
    except PermissionError as exc:
        raise_error(400, "AGENT_MANIFEST_NOT_WRITABLE", str(exc) or f"Agent manifest is not writable: {agent_id}")
    except FileNotFoundError as exc:
        raise_error(404, "AGENT_MANIFEST_NOT_WRITABLE", str(exc))
    except Exception as exc:
        raise_error(400, "AGENT_MANIFEST_WRITE_FAILED", str(exc) or "Failed to write agent manifest.")
    return _serialize_agent_config(state, agent_id)


@router.get("/api/capability-configs")
def list_capability_configs(state: RuntimeState = Depends(get_state)) -> list:
    return [_serialize_capability_config(state, capability.id) for capability in state.capabilities.list()]


@router.get("/api/capability-configs/llm/resolved")
def get_resolved_llm_config(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return public_llm_config_status(_resolve_llm_capability_config(state))
    except LLMConfigError as exc:
        raise_error(400, exc.code, exc.message)


@router.get("/api/capability-configs/llm/models")
def list_llm_models(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        config = _resolve_llm_capability_config(state)
        runtime = state.runtimes.get_runtime("llm")
        models = _runtime_list_models(runtime, config.values)
        return {"success": True, "models": [{"id": model_id} for model_id in models]}
    except LLMConfigError as exc:
        raise_error(400, exc.code, exc.message)
    except Exception as exc:
        raise_error(502, "LLM_MODEL_LIST_FAILED", _safe_llm_error(exc, "LLM model list failed."))


@router.get("/api/capability-configs/{capability_id}")
def get_capability_config(capability_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_capability_or_404(state, capability_id)
    return _serialize_capability_config(state, capability_id)


@router.patch("/api/capability-configs/{capability_id}")
def update_capability_config(
    capability_id: str,
    payload: UpdateConfigRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    capability = _get_capability_or_404(state, capability_id)
    user_config = None
    if payload.user_config is not None:
        existing = _clean_capability_user_config(capability_id, state.capability_configs.get_config(capability_id)["user_config"])
        user_config = _validate_config_patch(capability.config_schema, existing, payload.user_config)
    state.capability_configs.set_config(capability_id, enabled=payload.enabled, user_config=user_config)
    return _serialize_capability_config(state, capability_id)


@router.post("/api/capability-configs/llm/test")
def test_llm_connection(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        resolved = _resolve_llm_capability_config(state)
        runtime = state.runtimes.get_runtime("llm")
        models = _runtime_list_models(runtime, resolved.values)
        return {
            "success": True,
            "message": "LLM service is reachable.",
            "base_url": resolved.values.get("base_url", ""),
            "models": models,
        }
    except LLMConfigError as exc:
        return {
            "success": False,
            "message": exc.message,
            "base_url": "",
            "error_code": exc.code,
        }
    except Exception as exc:
        base_url = ""
        try:
            base_url = _resolve_llm_capability_config(state).values.get("base_url", "")
        except Exception:
            base_url = ""
        return {
            "success": False,
            "message": _safe_llm_error(exc, "LLM connection failed."),
            "base_url": base_url,
            "error_code": "LLM_CONNECTION_FAILED",
        }


def _get_agent_or_404(state: RuntimeState, agent_id: str):
    try:
        return state.agents.get(agent_id)
    except KeyError:
        raise_error(404, "AGENT_CONFIG_NOT_FOUND", f"Agent config not found: {agent_id}")


def _get_capability_or_404(state: RuntimeState, capability_id: str):
    try:
        return state.capabilities.get(capability_id)
    except KeyError:
        raise_error(404, "CAPABILITY_CONFIG_NOT_FOUND", f"Capability config not found: {capability_id}")


def _serialize_agent_config(state: RuntimeState, agent_id: str) -> dict:
    agent = state.agents.get(agent_id)
    config = state.agent_configs.get_config(agent_id)
    stored_user_config = clear_empty_enum_overrides(agent.config_schema, config["user_config"])
    masked_user_config = mask_config(agent.config_schema, stored_user_config)
    agent_dir = None
    try:
        agent_dir = state.agents.get_agent_dir(agent.id)
    except KeyError:
        pass
    resolved = resolved_agent_settings(agent, config, agent_dir=agent_dir, settings=state.app_settings.get())
    _enrich_resolved_runtime(state, resolved)
    avatar = resolve_avatar_for_response(state, agent).public_dict()
    return {
        **config,
        "user_config": masked_user_config,
        "resolved_config": mask_config(agent.config_schema, _resolve_for_response(agent.config_schema, stored_user_config)),
        "config_schema": dump_config_schema(agent.config_schema),
        "manifest_summary": {
            "id": agent.id,
            "name": agent.name,
            "type": agent.type,
            "description": agent.description,
            "avatar": agent.avatar,
            "capabilities": agent.capabilities,
            **avatar,
        },
        "manifest": {
            "name": agent.name,
            "description": agent.description,
            "avatar": agent.avatar,
            "capabilities": agent.capabilities,
            "llm": agent.llm,
            "prompt": agent.prompt,
            "context_policy": agent.context_policy.model_dump(exclude_none=True),
            "model_lifecycle": agent.model_lifecycle.model_dump(),
            "timeout_seconds": agent.timeout_seconds,
        },
        "overrides": {
            "display": config.get("display", {}),
            "runtime": config.get("runtime", {}),
            "user_config": masked_user_config,
        },
        "resolved": {
            **resolved,
            "config": mask_config(agent.config_schema, _resolve_for_response(agent.config_schema, stored_user_config)),
        },
        "field_sources": resolved["field_sources"],
    }


def _serialize_capability_config(state: RuntimeState, capability_id: str) -> dict:
    capability = state.capabilities.get(capability_id)
    config = state.capability_configs.get_config(capability_id)
    stored_user_config = clear_empty_enum_overrides(capability.config_schema, _clean_capability_user_config(capability_id, config["user_config"]))
    masked_user_config = mask_config(capability.config_schema, stored_user_config)
    return {
        **config,
        "user_config": masked_user_config,
        "resolved_config": mask_config(
            capability.config_schema,
            _resolve_for_response(capability.config_schema, stored_user_config),
        ),
        "config_schema": dump_config_schema(capability.config_schema),
        "manifest_summary": {
            "id": capability.id,
            "name": capability.name,
            "description": capability.description,
            "commands": [command.model_dump() for command in capability.commands],
            "permissions": capability.permissions,
        },
    }


def _clean_capability_user_config(capability_id: str, user_config: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(user_config or {})
    if capability_id == "http":
        cleaned.pop("enable_http_get", None)
        cleaned.pop("enable_fetch_image", None)
    return cleaned


def _validate_config_patch(schema, existing_config: Dict[str, Any], incoming_config: Dict[str, Any]) -> Dict[str, Any]:
    merged = merge_secret_patch(schema, existing_config, incoming_config)
    merged = clear_empty_enum_overrides(schema, merged)
    try:
        validate_user_config(schema, merged)
        resolve_config(schema, merged)
    except ConfigValidationError as exc:
        raise_error(400, exc.code, exc.message, {"field": exc.field})
    return merged


def _resolve_for_response(schema, user_config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return resolve_config(schema, user_config)
    except ConfigValidationError:
        return {}


def _resolve_llm_capability_config(state: RuntimeState):
    capability = _get_capability_or_404(state, "llm")
    stored = state.capability_configs.get_config("llm")
    return resolve_llm_config(
        capability_schema=capability,
        capability_config=stored,
        llm_profile_store=state.llm_profiles,
        provider_profile_store=state.provider_profiles,
        llm_defaults_store=state.llm_defaults,
    )


def _validate_runtime_profile(state: RuntimeState, runtime: Dict[str, Any]) -> None:
    profile_id = runtime.get("llm_profile_id")
    if not profile_id:
        return
    if state.llm_profiles is None:
        raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"Model profile not found: {profile_id}")
    try:
        profile = state.llm_profiles.get_by_id_or_alias(profile_id)
    except KeyError as exc:
        raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"Model profile not found: {profile_id}") from exc
    if not profile.enabled:
        raise LLMConfigError("LLM_PROFILE_DISABLED", f"Model profile is disabled: {profile.alias}")


def _enrich_resolved_runtime(state: RuntimeState, resolved: Dict[str, Any]) -> None:
    runtime = resolved.get("runtime")
    if not isinstance(runtime, dict):
        return
    profile_ref = runtime.get("llm_profile_id")
    source = resolved.get("field_sources", {}).get("runtime.llm_profile_id", "default")
    runtime["llm_profile_source"] = source
    runtime["llm_profile_name"] = None
    runtime["llm_profile_label"] = None
    runtime["llm_profile_model_id"] = None
    runtime["llm_profile_status"] = "default" if not profile_ref else "missing"
    if not profile_ref:
        return
    if state.llm_profiles is None:
        runtime["llm_profile_label"] = f"Missing: {profile_ref}"
        return
    try:
        profile = state.llm_profiles.get_by_id_or_alias(str(profile_ref))
    except KeyError:
        runtime["llm_profile_label"] = f"Missing: {profile_ref}"
        return
    runtime["llm_profile_name"] = profile.name
    runtime["llm_profile_label"] = profile.name or profile.alias
    runtime["llm_profile_model_id"] = profile.model_id
    runtime["llm_profile_status"] = "enabled" if profile.enabled else "disabled"
    if not profile.enabled:
        runtime["llm_profile_label"] = f"Disabled: {profile.name or profile.alias}"


def _runtime_list_models(runtime, model_config: Dict[str, Any]) -> list[str]:
    return [item["id"] for item in _runtime_model_items(runtime, model_config) if item.get("id")]


def _runtime_model_items(runtime, model_config: Dict[str, Any]) -> list[dict]:
    if hasattr(runtime, "list_model_items") and callable(runtime.list_model_items):
        models = runtime.list_model_items(model_config=model_config)
    elif hasattr(runtime, "list_models") and callable(runtime.list_models):
        models = runtime.list_models(model_config=model_config)
    elif hasattr(runtime, "test_connection") and callable(runtime.test_connection):
        result = runtime.test_connection(model_config=model_config)
        models = result.get("models", [])
    else:
        raise RuntimeError("LLM runtime does not support model listing.")
    items = []
    for model in models or []:
        if isinstance(model, dict):
            model_id = model.get("id") or model.get("name")
            if not model_id:
                continue
            item = {
                "id": str(model_id),
                "name": model.get("name") or model.get("display_name") or str(model_id),
                "type": model.get("type") or "unknown",
                "loaded": model.get("loaded"),
                "loaded_instance_ids": model.get("loaded_instance_ids") if isinstance(model.get("loaded_instance_ids"), list) else [],
                "capabilities": model.get("capabilities") if isinstance(model.get("capabilities"), dict) else None,
                "raw": _safe_model_raw(model),
            }
            items.append(item)
        else:
            value = str(model)
            if value:
                items.append({"id": value, "name": value, "capabilities": None, "raw": {}})
    return items


def _safe_model_raw(model: dict) -> dict:
    blocked = {"api_key", "authorization", "token", "secret", "password"}
    return {str(key): value for key, value in model.items() if str(key).lower() not in blocked}


def _safe_llm_error(exc: Exception, fallback: str) -> str:
    message = str(exc) or fallback
    return message.splitlines()[0]
