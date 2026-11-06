"""Owned Session reads, sparse overrides, compaction and deletion."""

from fastapi import APIRouter, Depends
from pydantic import Field, RootModel

from ai_workbench.api.deps import RuntimeState, get_state, get_ui_language
from ai_workbench.core.instructions import UiLanguage
from ai_workbench.api.schemas.chat import RunResponse, SessionResponse, SessionDeleted
from ai_workbench.api.schemas.characters import NormalSessionCreate
from ai_workbench.api.schemas.common import ApiModel, error_responses, patch_model
from ai_workbench.api.openapi import request_body
from ai_workbench.api.errors import raise_error
from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.schema.memory import MemoryDeletionChoice
from ai_workbench.api.memory_deletion import delete_normal_owner


router = APIRouter(prefix="/api/sessions", tags=["sessions"])
MAX_SESSION_TITLE_LENGTH = 120


class CompactSessionRequest(ApiModel):
    pass


NormalSessionPatch = patch_model("NormalSessionPatch", NormalSessionCreate, fields={
    "title": (str, Field(default_factory=lambda: None, min_length=1, max_length=MAX_SESSION_TITLE_LENGTH)),
})
QQSessionPatch = patch_model("QQSessionPatch", NormalSessionCreate, omit={"overrides", "memory_isolation"}, fields={
    "title": (str, Field(default_factory=lambda: None, min_length=1, max_length=MAX_SESSION_TITLE_LENGTH)),
})


class SessionPatchRequest(RootModel[NormalSessionPatch | QQSessionPatch]):
    pass


@router.post("/{session_id}/compact", status_code=202, response_model=RunResponse, response_model_exclude_unset=True,
    responses=error_responses(404, 409, 422, 503))
async def compact_session(session_id: str, payload: CompactSessionRequest = CompactSessionRequest(),
                          state: RuntimeState = Depends(get_state), ui_language: UiLanguage = Depends(get_ui_language)) -> dict:
    session = _get_session_or_404(state, session_id)
    return state.runtime.manual_compaction.start(session, ui_language=ui_language).model_dump(mode="json")


@router.get("/{session_id}", response_model=SessionResponse, response_model_exclude_unset=True, responses=error_responses(404))
def get_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return state.chat_service.session_response(_get_session_or_404(state, session_id))


@router.patch("/{session_id}", response_model=SessionResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422, 503), openapi_extra=request_body(SessionPatchRequest,
        description="Normal Sessions accept title and sparse overrides; null fields restore Character defaults. QQ Sessions accept only title."))
async def update_session(session_id: str, payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    session = _get_session_or_404(state, session_id)
    schema = NormalSessionPatch if session.kind == "normal" else QQSessionPatch
    values = schema.model_validate(payload).model_dump(exclude_unset=True)
    if "title" in values:
        title = values["title"].strip()
        if not title:
            raise_error(400, "SESSION_TITLE_EMPTY", "Session title cannot be empty.")
        values.update(title=title, title_generation_state="manual")
    updated = state.chat_service.update_session(session_id, values)
    response = state.chat_service.session_response(updated)
    state.events.emit("session_updated", session_id=session_id, payload={"session": response})
    return response


@router.delete("/{session_id}", response_model=SessionDeleted, response_model_exclude_unset=True,
    responses=error_responses(404, 409, 422))
async def delete_session(session_id: str, payload: MemoryDeletionChoice | None = None, state: RuntimeState = Depends(get_state)) -> dict:
    session = _get_session_or_404(state, session_id)
    state.chat_service.assert_idle(session_id)
    state.qq.assert_idle(session_id)
    if session.kind == "normal":
        delete_normal_owner(state, payload or MemoryDeletionChoice(), session_id=session_id)
    else:
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
    for attachment_id in attachments:
        delete_attachment_if_unreferenced({"uri": "local://attachments/" + attachment_id}, state.messages,
            persona_store=state.personas, character_store=state.characters,
            knowledge_store=state.knowledge, run_store=state.runs, qq_store=state.qq.store)
    state.sessions.delete_session(session_id)


def _get_session_or_404(state: RuntimeState, session_id: str):
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")
