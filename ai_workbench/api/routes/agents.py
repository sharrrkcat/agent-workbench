from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ai_workbench.api.avatar import resolve_avatar_for_response
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error


router = APIRouter(prefix="/api/agents", tags=["agents"])


def serialize_agent(state: RuntimeState, agent, enabled: bool = True) -> dict:
    avatar = resolve_avatar_for_response(state, agent).public_dict()
    return {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type,
        "description": agent.description,
        "avatar": agent.avatar,
        **avatar,
        "entry": agent.entry,
        "actions": [action.model_dump() for action in agent.actions],
        "model": agent.model,
        "context_policy": agent.context_policy.model_dump(),
        "model_lifecycle": agent.model_lifecycle.model_dump(),
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
