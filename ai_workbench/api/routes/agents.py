from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error


router = APIRouter(prefix="/api/agents", tags=["agents"])


def serialize_agent(agent, enabled: bool = True) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type,
        "description": agent.description,
        "avatar": agent.avatar,
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
    return [serialize_agent(agent, enabled=state.agent_configs.is_enabled(agent.id)) for agent in state.agents.list()]


@router.get("/{agent_id}")
def get_agent(agent_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        agent = state.agents.get(agent_id)
        return serialize_agent(agent, enabled=state.agent_configs.is_enabled(agent.id))
    except KeyError:
        raise_error(404, "AGENT_NOT_FOUND", f"Agent not found: {agent_id}")
