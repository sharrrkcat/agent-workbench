from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.chat import (
    SessionResponse, SessionDeleted,
    SessionKnowledgeResponse,
)
from ai_workbench.api.openapi import request_body
from ai_workbench.api.schemas.common import error_responses, patch_model
from ai_workbench.api.schemas.projects import WorkspaceSessionCreate
from ai_workbench.api.errors import raise_error
from ai_workbench.core.session import SessionGenerationParameters
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID
from ai_workbench.core.attachments import delete_attachment_if_unreferenced


router = APIRouter(prefix="/api/sessions", tags=["sessions"])
MAX_SESSION_TITLE_LENGTH = 120


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    model_profile_id: str | None = None
    persona_id: str = COGITA_PERSONA_ID
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    generation: SessionGenerationParameters = Field(default_factory=SessionGenerationParameters)
    reasoning: StrictBool = True
    harness_enabled: StrictBool = False
    tools_allowed: list[str] = Field(default_factory=list, max_length=128,
        description="Omission selects all currently registered tools; an explicit empty array selects none.")


class SessionKnowledgePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_ids: list[str] = Field(max_length=128)


OrdinarySessionPatch = patch_model("OrdinarySessionPatch", CreateSessionRequest, fields={
    "title": (str, Field(default_factory=lambda: None, min_length=1, max_length=MAX_SESSION_TITLE_LENGTH,
        description="A nonempty title after trimming; updates mark the title as manually set.")),
    "tools_allowed": (list[str], Field(default_factory=lambda: None, max_length=128,
        description="Omission keeps the saved allowlist; an empty array disables all tools.")),
})
QQSessionPatch = patch_model("QQSessionPatch", CreateSessionRequest, omit=set(CreateSessionRequest.model_fields) - {"title"})
WorkspaceSessionPatch = patch_model("WorkspaceSessionPatch", WorkspaceSessionCreate, fields={
    "title": (str, Field(default_factory=lambda: None, min_length=1, max_length=MAX_SESSION_TITLE_LENGTH)),
})


class SessionPatchRequest(RootModel[OrdinarySessionPatch | WorkspaceSessionPatch | QQSessionPatch]):
    pass


@router.post("", response_model=SessionResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422, 503))
async def create_session(payload: CreateSessionRequest, state: RuntimeState = Depends(get_state)) -> dict:
    session = state.chat_service.create_session(payload.model_dump(exclude_unset=True))
    return state.chat_service.session_response(session)


@router.get("", response_model=list[SessionResponse], response_model_exclude_unset=True)
def list_sessions(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [state.chat_service.session_response(session) for session in state.sessions.list_sessions() if session.kind == "ordinary"]


@router.get("/{session_id}", response_model=SessionResponse, response_model_exclude_unset=True,
    responses=error_responses(404, 409))
def get_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return state.chat_service.session_response(_get_session_or_404(state, session_id))


@router.patch("/{session_id}", response_model=SessionResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422, 503), openapi_extra=request_body(SessionPatchRequest,
        description="Ordinary sessions accept concrete settings. Workspace sessions accept title and sparse overrides; null inside overrides restores inheritance. Identity and Project membership are immutable."))
async def update_session(
    session_id: str,
    payload: dict,
    state: RuntimeState = Depends(get_state),
) -> dict:
    session = _get_session_or_404(state, session_id)
    schema = {"ordinary": OrdinarySessionPatch, "workspace": WorkspaceSessionPatch, "qqbot": QQSessionPatch}[session.kind]
    values = schema.model_validate(payload).model_dump(exclude_unset=True)
    if "title" in values:
        title = values["title"].strip()
        if not title:
            raise_error(400, "SESSION_TITLE_EMPTY", "Session title cannot be empty.")
        if len(title) > MAX_SESSION_TITLE_LENGTH:
            raise_error(
                400,
                "SESSION_TITLE_TOO_LONG",
                f"Session title must be {MAX_SESSION_TITLE_LENGTH} characters or fewer.",
            )
        values.update(title=title, title_generation_state="manual")
    updated = state.chat_service.update_session(session_id, values)
    response = state.chat_service.session_response(updated)
    state.events.emit("session_updated", session_id=session_id, payload={"session": response})
    return response


@router.delete("/{session_id}", response_model=SessionDeleted, response_model_exclude_unset=True,
    responses=error_responses(404, 409))
async def delete_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    session = _get_session_or_404(state, session_id)
    state.chat_service.assert_idle(session_id)
    state.qq.assert_idle(session_id)
    delete_session_data(state, session_id)
    return {"deleted": True, "session_id": session.session_id}


def delete_session_data(state: RuntimeState, session_id: str) -> None:
    state.qq.icebreaker.reset_session(session_id)
    attachments = state.qq.store.media_attachment_ids(session_id=session_id)
    state.qq.store.delete_session(session_id)
    attachments.update(state.qq.store.release_unused_assets(attachments))
    state.sessions.set_waiting_run(session_id, None)
    attachments.update(state.messages.attachment_filenames(session_id=session_id))
    attachments.update(state.runs.context_attachment_ids(session_id=session_id))
    state.run_events.delete_session(session_id)
    state.runs.delete_session(session_id)
    state.messages.delete_session(session_id)
    if state.knowledge is not None:
        state.knowledge.delete_session_bindings(session_id)
    for attachment_id in attachments:
        delete_attachment_if_unreferenced({"uri": "local://attachments/" + attachment_id}, state.messages,
            persona_store=state.personas, knowledge_store=state.knowledge, run_store=state.runs, qq_store=state.qq.store)
    state.sessions.delete_session(session_id)


@router.get("/{session_id}/knowledge-bases", response_model=SessionKnowledgeResponse, response_model_exclude_unset=True,
    responses=error_responses(404))
def get_session_knowledge_bases(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_session_or_404(state, session_id)
    return state.chat_service.knowledge_response(session_id)


@router.patch("/{session_id}/knowledge-bases", response_model=SessionKnowledgeResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422))
async def update_session_knowledge_bases(
    session_id: str,
    payload: SessionKnowledgePatch,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _get_session_or_404(state, session_id)
    state.chat_service.update_knowledge(session_id, payload.knowledge_base_ids)
    state.events.emit("session_updated", session_id=session_id,
        payload={"session": state.chat_service.session_response(state.sessions.get_session(session_id))})
    return state.chat_service.knowledge_response(session_id)


def _get_session_or_404(state: RuntimeState, session_id: str):
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")
