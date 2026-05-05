from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error


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
    _get_agent_or_404(state, agent_id)
    state.agent_configs.set_config(agent_id, enabled=payload.enabled, user_config=payload.user_config)
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
    _get_capability_or_404(state, capability_id)
    state.capability_configs.set_config(capability_id, enabled=payload.enabled, user_config=payload.user_config)
    return _serialize_capability_config(state, capability_id)


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
    return {
        **config,
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
    return {
        **config,
        "manifest_summary": {
            "id": capability.id,
            "name": capability.name,
            "description": capability.description,
            "commands": [command.model_dump() for command in capability.commands],
        },
    }
