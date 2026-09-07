from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.models.schema import GenerationParameters
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import CHAT_PERSONA_ID, SessionPersona
from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.time import ensure_utc, utc_now


router = APIRouter(prefix="/api/sessions", tags=["sessions"])
MAX_SESSION_TITLE_LENGTH = 120


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    context_mode: Literal["single_assistant", "group_transcript"] = "single_assistant"
    model_profile_id: str | None = None
    current_persona_id: str = CHAT_PERSONA_ID
    personas: list[SessionPersona] = Field(default_factory=lambda: [SessionPersona(persona_id=CHAT_PERSONA_ID)], min_length=1, max_length=64)
    context_policy: ContextPolicy = Field(default_factory=lambda: ContextPolicy(mode="session"))
    generation: GenerationParameters = Field(default_factory=GenerationParameters)
    harness_enabled: StrictBool = False
    tools_allowed: list[str] = Field(default_factory=list, max_length=128)


class UpdateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    model_profile_id: str | None = None
    context_mode: Literal["single_assistant", "group_transcript"] | None = None
    current_persona_id: str | None = None
    personas: list[SessionPersona] | None = Field(default=None, min_length=1, max_length=64)
    context_policy: ContextPolicy = Field(default_factory=lambda: ContextPolicy(mode="session"))
    generation: GenerationParameters = Field(default_factory=GenerationParameters)
    harness_enabled: StrictBool = False
    tools_allowed: list[str] = Field(default_factory=list, max_length=128)


class SessionPersonasPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    personas: list[SessionPersona] = Field(min_length=1, max_length=64)
    current_persona_id: str


class SessionKnowledgePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_ids: list[str] = Field(max_length=128)


@router.post("")
async def create_session(payload: CreateSessionRequest, state: RuntimeState = Depends(get_state)) -> dict:
    session = state.chat_service.create_session(payload.model_dump(exclude_unset=True))
    return state.chat_service.session_response(session)


@router.get("")
def list_sessions(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [state.chat_service.session_response(session) for session in state.sessions.list_sessions()]


@router.get("/{session_id}")
def get_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return state.chat_service.session_response(_get_session_or_404(state, session_id))


@router.patch("/{session_id}")
async def update_session(
    session_id: str,
    payload: UpdateSessionRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    session = _get_session_or_404(state, session_id)
    values = payload.model_dump(exclude_unset=True)
    if payload.title is not None:
        title = payload.title.strip()
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
    if payload.context_mode is not None and payload.context_mode != session.context_mode:
        previous = session.context_mode
        state.messages.add_message(
            session_id=session_id,
            role="system",
            content=f"Conversation mode changed to {_context_mode_label(payload.context_mode)}",
            metadata={
                "event_type": "context_mode_changed",
                "context_mode": payload.context_mode,
                "previous_context_mode": previous,
            },
        )
    response = state.chat_service.session_response(updated)
    state.events.emit("session_updated", session_id=session_id, payload={"session": response})
    return response


@router.get("/{session_id}/personas")
def get_session_personas(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    session = get_session(session_id, state)
    return {"personas": session["personas"], "current_persona_id": session["current_persona_id"]}


@router.patch("/{session_id}/personas")
async def update_session_personas(session_id: str, payload: SessionPersonasPatch, state: RuntimeState = Depends(get_state)) -> dict:
    return await update_session(session_id, UpdateSessionRequest(**payload.model_dump()), state)


@router.delete("/{session_id}")
async def delete_session(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    session = _get_session_or_404(state, session_id)
    state.chat_service.assert_idle(session_id)
    state.sessions.set_waiting_run(session_id, None)
    messages = state.messages.list_messages(session_id)
    state.run_events.delete_session(session_id)
    state.runs.delete_session(session_id)
    state.messages.delete_session(session_id)
    if state.knowledge is not None:
        state.knowledge.delete_session_bindings(session_id)
    if state.worldbooks is not None:
        state.worldbooks.delete_session_bindings(session_id)
    for message in messages:
        _cleanup_message_attachments(state, message)
    state.sessions.delete_session(session_id)
    return {"deleted": True, "session_id": session.session_id}


@router.get("/{session_id}/timeline")
def get_session_timeline(session_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    _get_session_or_404(state, session_id)
    messages = state.messages.list_messages(session_id)
    by_id = {item.message_id: item for item in messages}
    sortable: list[tuple[datetime, int, dict]] = []
    for index, message in enumerate(messages):
        sortable.append(
            (
                message.created_at,
                index * 2,
                {"kind": "message", "message": _message_payload(state, message)},
            )
        )
    for index, run in enumerate(state.runs.list_runs(session_id)):
        if run.status != RunStatus.FAILED or not run.error or run.metadata.get("notification_dismissed"):
            continue
        parent_id = _first_string(run.metadata, ("input_message_id", "parent_message_id"))
        parent = by_id.get(parent_id or "")
        created = getattr(parent, "created_at", None) or run.created_at
        notification = {
            "id": f"run-error:{run.run_id}",
            "session_id": session_id,
            "run_id": run.run_id,
            "severity": "error",
            "code": run.error_code or "RUN_FAILED",
            "message": run.error,
            "created_at": created,
            "metadata": {
                "run_kind": run.kind,
                "persona_id": run.persona_id,
                "parent_message_id": parent_id,
            },
            "run": run.model_dump(mode="json"),
            "run_steps": [
                step.model_dump(mode="json") for step in state.runs.list_steps(run.run_id)
            ],
        }
        sortable.append(
            (
                created,
                (len(messages) + index) * 2 + 1,
                {"kind": "notification", "notification": notification},
            )
        )
    sortable.sort(key=lambda item: (ensure_utc(item[0]) or datetime.min, item[1]))
    return [item[2] for item in sortable]


@router.get("/{session_id}/knowledge-bases")
def get_session_knowledge_bases(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_session_or_404(state, session_id)
    return state.chat_service.binding_response(session_id, "knowledge")


@router.patch("/{session_id}/knowledge-bases")
async def update_session_knowledge_bases(
    session_id: str,
    payload: SessionKnowledgePatch,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _get_session_or_404(state, session_id)
    state.chat_service.update_bindings(session_id, "knowledge", payload.knowledge_base_ids)
    state.events.emit("session_updated", session_id=session_id,
        payload={"session": state.chat_service.session_response(state.sessions.get_session(session_id))})
    return state.chat_service.binding_response(session_id, "knowledge")


@router.post("/{session_id}/notifications/{notification_id}/dismiss")
def dismiss_session_notification(
    session_id: str,
    notification_id: str,
    state: RuntimeState = Depends(get_state),
) -> dict:
    _get_session_or_404(state, session_id)
    if not notification_id.startswith("run-error:"):
        raise_error(404, "NOTIFICATION_NOT_FOUND", "Notification not found.")
    run_id = notification_id.removeprefix("run-error:")
    try:
        run = state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "NOTIFICATION_NOT_FOUND", "Notification not found.")
    if run.session_id != session_id or run.status != RunStatus.FAILED:
        raise_error(404, "NOTIFICATION_NOT_FOUND", "Notification not found.")
    metadata = dict(run.metadata or {})
    metadata["notification_dismissed"] = True
    metadata["notification_dismissed_at"] = utc_now().isoformat()
    state.runs.update_metadata(run_id, metadata)
    return {"ok": True, "notification_id": notification_id, "dismissed": True}


def _get_session_or_404(state: RuntimeState, session_id: str):
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _message_payload(state: RuntimeState, message) -> dict:
    payload = message.model_dump(mode="json")
    if message.run_id:
        try:
            run = state.runs.get_run(message.run_id)
            payload["run"] = run.model_dump(mode="json")
            payload["run_steps"] = [
                step.model_dump(mode="json") for step in state.runs.list_steps(run.run_id)
            ]
        except KeyError:
            pass
    return payload


def _cleanup_message_attachments(state: RuntimeState, message) -> None:
    attachments = (message.metadata or {}).get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                delete_attachment_if_unreferenced(item, state.messages, message.session_id, persona_store=state.personas, run_store=state.runs)
    avatar_id = (message.metadata or {}).get("speaker_avatar_attachment_id")
    if avatar_id:
        delete_attachment_if_unreferenced({"id": avatar_id, "uri": "local://attachments/" + avatar_id}, state.messages, persona_store=state.personas, run_store=state.runs)


def _first_string(source: dict | None, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = (source or {}).get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _context_mode_label(mode: str) -> str:
    return "Group transcript" if mode == "group_transcript" else "Single assistant"
