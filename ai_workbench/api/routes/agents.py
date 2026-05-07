from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ai_workbench.api.avatar import resolve_avatar_for_response
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.agent_settings import resolved_agent_settings
from ai_workbench.api.routes.configs import _enrich_resolved_runtime


router = APIRouter(prefix="/api/agents", tags=["agents"])


def serialize_agent(state: RuntimeState, agent, enabled: bool = True) -> dict:
    avatar = resolve_avatar_for_response(state, agent).public_dict()
    config = state.agent_configs.get_config(agent.id)
    agent_dir = None
    try:
        agent_dir = state.agents.get_agent_dir(agent.id)
    except KeyError:
        pass
    resolved = resolved_agent_settings(agent, config, agent_dir=agent_dir)
    _enrich_resolved_runtime(state, resolved)
    display = resolved["display"]
    avatar_type = display.get("avatar_type", avatar.get("avatar_type"))
    avatar_url = display.get("avatar_url", avatar.get("avatar_url"))
    avatar_value = display.get("avatar") if avatar_type in {"emoji", "text"} else None
    return {
        "id": agent.id,
        "name": display["name"],
        "type": agent.type,
        "description": display["description"],
        "avatar": avatar_value,
        "avatar_type": avatar_type,
        "avatar_url": avatar_url,
        "entry": agent.entry,
        "actions": [action.model_dump() for action in agent.actions],
        "model": agent.model,
        "llm": agent.llm,
        "context_policy": agent.context_policy.model_dump(),
        "model_lifecycle": agent.model_lifecycle.model_dump(),
        "resolved_runtime": resolved["runtime"],
        "resolved_display": display,
        "capabilities": agent.capabilities,
        "enabled": enabled,
    }


@router.get("")
def list_agents(state: RuntimeState = Depends(get_state)) -> list:
    return [serialize_agent(state, agent, enabled=state.agent_configs.is_enabled(agent.id)) for agent in state.agents.list()]


@router.get("/{agent_id}")
def get_agent(agent_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        agent = state.agents.get(agent_id)
        return serialize_agent(state, agent, enabled=state.agent_configs.is_enabled(agent.id))
    except KeyError:
        raise_error(404, "AGENT_NOT_FOUND", f"Agent not found: {agent_id}")


@router.get("/{agent_id}/avatar")
def get_agent_avatar(agent_id: str, state: RuntimeState = Depends(get_state)):
    try:
        agent = state.agents.get(agent_id)
    except KeyError:
        raise_error(404, "AGENT_NOT_FOUND", f"Agent not found: {agent_id}")

    avatar = resolve_avatar_for_response(state, agent)
    if avatar.avatar_type != "image" or avatar.file_path is None or avatar.content_type is None:
        raise_error(404, "AGENT_AVATAR_NOT_FOUND", f"Local avatar not found for agent: {agent_id}")
    return FileResponse(avatar.file_path, media_type=avatar.content_type)
