from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.config_schema import (
    ConfigValidationError,
    dump_config_schema,
    mask_config,
    merge_secret_patch,
    resolve_config,
    validate_user_config,
)


router = APIRouter(tags=["configs"])


class UpdateConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
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
    state.agent_configs.set_config(agent_id, enabled=payload.enabled, user_config=user_config)
    return _serialize_agent_config(state, agent_id)


@router.get("/api/capability-configs")
def list_capability_configs(state: RuntimeState = Depends(get_state)) -> list:
    return [_serialize_capability_config(state, capability.id) for capability in state.capabilities.list()]


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
        existing = state.capability_configs.get_config(capability_id)["user_config"]
        user_config = _validate_config_patch(capability.config_schema, existing, payload.user_config)
    state.capability_configs.set_config(capability_id, enabled=payload.enabled, user_config=user_config)
    return _serialize_capability_config(state, capability_id)


@router.post("/api/capability-configs/llm/test")
def test_llm_connection(state: RuntimeState = Depends(get_state)) -> dict:
    capability = _get_capability_or_404(state, "llm")
    stored = state.capability_configs.get_config("llm")
    try:
        resolved = resolve_config(capability.config_schema, stored["user_config"])
        runtime = state.runtimes.get_runtime("llm")
        if hasattr(runtime, "list_models") and callable(runtime.list_models):
            models = runtime.list_models(model_config=resolved)
        elif hasattr(runtime, "test_connection") and callable(runtime.test_connection):
            result = runtime.test_connection(model_config=resolved)
            models = result.get("models", [])
        else:
            raise RuntimeError("LLM runtime does not support connection testing.")
        return {
            "success": True,
            "message": "LLM service is reachable.",
            "base_url": resolved.get("base_url", ""),
            "models": models,
        }
    except Exception as exc:
        base_url = ""
        try:
            base_url = resolve_config(capability.config_schema, stored["user_config"]).get("base_url", "")
        except Exception:
            base_url = stored.get("user_config", {}).get("base_url", "")
        return {
            "success": False,
            "message": str(exc) or "LLM connection failed.",
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
    masked_user_config = mask_config(agent.config_schema, config["user_config"])
    return {
        **config,
        "user_config": masked_user_config,
        "resolved_config": mask_config(agent.config_schema, _resolve_for_response(agent.config_schema, config["user_config"])),
        "config_schema": dump_config_schema(agent.config_schema),
        "manifest_summary": {
            "id": agent.id,
            "name": agent.name,
            "type": agent.type,
            "description": agent.description,
            "avatar": agent.avatar,
        },
    }


def _serialize_capability_config(state: RuntimeState, capability_id: str) -> dict:
    capability = state.capabilities.get(capability_id)
    config = state.capability_configs.get_config(capability_id)
    masked_user_config = mask_config(capability.config_schema, config["user_config"])
    return {
        **config,
        "user_config": masked_user_config,
        "resolved_config": mask_config(
            capability.config_schema,
            _resolve_for_response(capability.config_schema, config["user_config"]),
        ),
        "config_schema": dump_config_schema(capability.config_schema),
        "manifest_summary": {
            "id": capability.id,
            "name": capability.name,
            "description": capability.description,
            "commands": [command.model_dump() for command in capability.commands],
        },
    }


def _validate_config_patch(schema, existing_config: Dict[str, Any], incoming_config: Dict[str, Any]) -> Dict[str, Any]:
    merged = merge_secret_patch(schema, existing_config, incoming_config)
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
