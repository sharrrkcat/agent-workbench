from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    default_agent_id: str = "chat"


class UpdateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    default_agent_id: Optional[str] = None
    llm_profile_id: Optional[str] = None


@router.post("")
def create_session(payload: CreateSessionRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        state.agents.get(payload.default_agent_id)
    except KeyError:
        raise_error(400, "AGENT_NOT_FOUND", f"Agent not found: {payload.default_agent_id}")
    if not state.agent_configs.is_enabled(payload.default_agent_id):
        raise_error(400, "AGENT_DISABLED", f"Agent is disabled: {payload.default_agent_id}")
    return state.sessions.create_session(
        title=payload.title,
        default_agent_id=payload.default_agent_id,
    ).model_dump()


@router.get("")
def list_sessions(state: RuntimeState = Depends(get_state)) -> list:
    return [session.model_dump() for session in state.sessions.list_sessions()]


@router.get("/{session_id}")
def get_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.sessions.get_session(session_id).model_dump()
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


@router.patch("/{session_id}")
def update_session(session_id: str, payload: UpdateSessionRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        session = state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")

    if payload.default_agent_id is not None:
        try:
            state.agents.get(payload.default_agent_id)
        except KeyError:
            raise_error(400, "AGENT_NOT_FOUND", f"Agent not found: {payload.default_agent_id}")
        if not state.agent_configs.is_enabled(payload.default_agent_id):
            raise_error(400, "AGENT_DISABLED", f"Agent is disabled: {payload.default_agent_id}")
        session = state.sessions.set_default_agent(session_id, payload.default_agent_id)

    if payload.title is not None:
        session = state.sessions.set_title(session_id, payload.title)

    if "llm_profile_id" in payload.model_fields_set:
        if payload.llm_profile_id is not None:
            try:
                profile = state.llm_profiles.get(payload.llm_profile_id)
            except KeyError:
                raise_error(400, "LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {payload.llm_profile_id}")
            if not profile.enabled:
                raise_error(400, "LLM_PROFILE_DISABLED", f"LLM profile is disabled: {profile.alias}")
        session = state.sessions.set_llm_profile(session_id, payload.llm_profile_id)

    return session.model_dump()


@router.delete("/{session_id}")
def delete_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        session = state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")

    if session.waiting_run_id:
        state.sessions.set_waiting_run(session_id, None)
    state.run_events.delete_session(session_id)
    state.runs.delete_session(session_id)
    state.messages.delete_session(session_id)
    state.sessions.delete_session(session_id)
    return {"deleted": True, "session_id": session_id}
