from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.schema.run import RunSchema, RunStatus


router = APIRouter(prefix="/api/sessions", tags=["sessions"])
MAX_SESSION_TITLE_LENGTH = 120


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


@router.get("/{session_id}/timeline")
def get_session_timeline(session_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    _get_session_or_404(state, session_id)
    messages = state.messages.list_messages(session_id)
    message_by_id = {message.message_id: message for message in messages}
    message_sequence = {message.message_id: index * 2 for index, message in enumerate(messages)}
    sortable_items = [
        (message_sequence[message.message_id], {"kind": "message", "message": message.model_dump()})
        for message in messages
    ]
    for run_index, run in enumerate(state.runs.list_runs(session_id)):
        if not _is_visible_failed_run_notification(run):
            continue
        notification = _notification_from_failed_run(run, message_by_id)
        parent_message_id = notification["metadata"].get("parent_message_id")
        sequence = message_sequence.get(parent_message_id, (len(messages) + run_index) * 2) + 1
        sortable_items.append((sequence, {"kind": "notification", "notification": notification}))
    return [
        item
        for _, item in sorted(
            sortable_items,
            key=lambda sortable: (
                _timeline_created_at(sortable[1]),
                sortable[0],
                0 if sortable[1]["kind"] == "message" and sortable[1]["message"]["role"] == "user" else 1,
            ),
        )
    ]


@router.post("/{session_id}/notifications/{notification_id}/dismiss")
def dismiss_session_notification(session_id: str, notification_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_session_or_404(state, session_id)
    run_id = _run_id_from_notification_id(notification_id)
    if not run_id:
        raise_error(404, "NOTIFICATION_NOT_FOUND", f"Notification not found: {notification_id}")
    try:
        run = state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "NOTIFICATION_NOT_FOUND", f"Notification not found: {notification_id}")
    if run.session_id != session_id or not _is_failed_run_notification(run):
        raise_error(404, "NOTIFICATION_NOT_FOUND", f"Notification not found: {notification_id}")
    if not run.metadata.get("notification_dismissed"):
        metadata = dict(run.metadata or {})
        metadata["notification_dismissed"] = True
        metadata["notification_dismissed_at"] = datetime.utcnow().isoformat()
        state.runs.update_metadata(run.run_id, metadata)
    return {"ok": True, "notification_id": notification_id, "dismissed": True}


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
        title = payload.title.strip()
        if not title:
            raise_error(400, "SESSION_TITLE_EMPTY", "Session title cannot be empty.")
        if len(title) > MAX_SESSION_TITLE_LENGTH:
            raise_error(
                400,
                "SESSION_TITLE_TOO_LONG",
                f"Session title must be {MAX_SESSION_TITLE_LENGTH} characters or fewer.",
            )
        session = state.sessions.set_title(session_id, title)

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
    deleted_messages = state.messages.list_messages(session_id)
    state.run_events.delete_session(session_id)
    state.runs.delete_session(session_id)
    state.messages.delete_session(session_id)
    for message in deleted_messages:
        attachments = (message.metadata or {}).get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if isinstance(attachment, dict):
                    delete_attachment_if_unreferenced(attachment, state.messages, session_id)
    state.sessions.delete_session(session_id)
    return {"deleted": True, "session_id": session_id}


def _get_session_or_404(state: RuntimeState, session_id: str):
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _notification_from_failed_run(run: RunSchema, message_by_id: dict[str, object]) -> dict:
    parent_message_id = _first_string(run.metadata, ["parent_message_id", "input_message_id", "source_message_id"])
    related_message = message_by_id.get(parent_message_id or "")
    related_created_at = getattr(related_message, "created_at", None)
    created_at = run.created_at or run.updated_at or related_created_at or datetime.utcnow()
    return {
        "id": _notification_id_for_run(run.run_id),
        "session_id": run.session_id,
        "run_id": run.run_id,
        "severity": "error",
        "code": "RUN_FAILED",
        "message": run.error or "Run failed.",
        "created_at": created_at,
        "metadata": {
            "run_kind": run.kind,
            "target_id": run.target_id,
            "action_id": run.action_id,
            "parent_message_id": parent_message_id,
        },
    }


def _timeline_created_at(item: dict) -> datetime:
    value = item["message"]["created_at"] if item["kind"] == "message" else item["notification"]["created_at"]
    return value if isinstance(value, datetime) else datetime.min


def _is_visible_failed_run_notification(run: RunSchema) -> bool:
    return _is_failed_run_notification(run) and not run.metadata.get("notification_dismissed")


def _is_failed_run_notification(run: RunSchema) -> bool:
    return run.status == RunStatus.FAILED and bool(run.error) and bool(run.run_id)


def _notification_id_for_run(run_id: str) -> str:
    return f"run-error:{run_id}"


def _run_id_from_notification_id(notification_id: str) -> str | None:
    prefix = "run-error:"
    if not notification_id.startswith(prefix):
        return None
    run_id = notification_id[len(prefix) :]
    return run_id or None


def _first_string(source: dict | None, keys: list[str]) -> str | None:
    if not source:
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None
