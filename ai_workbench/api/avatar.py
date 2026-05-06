from ai_workbench.api.deps import RuntimeState
from ai_workbench.core.avatar import ResolvedAvatar, resolve_agent_avatar
from ai_workbench.core.schema.agent import AgentSchema


def resolve_avatar_for_response(state: RuntimeState, agent: AgentSchema) -> ResolvedAvatar:
    try:
        agent_dir = state.agents.get_agent_dir(agent.id)
    except KeyError:
        agent_dir = None
    return resolve_agent_avatar(agent, agent_dir)
