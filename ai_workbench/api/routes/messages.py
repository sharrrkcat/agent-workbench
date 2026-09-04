from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.api.routes.sessions import _get_session_or_404
from ai_workbench.core.attachments import delete_attachment_if_unreferenced, validate_attachments
from ai_workbench.core.message_parts import make_text_part, text_from_parts
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunStatus


router = APIRouter(prefix="/api/sessions/{session_id}", tags=["messages"])
message_router = APIRouter(prefix="/api/messages", tags=["messages"])


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    client_message_id: str = ""


class EditMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    rerun: bool = True


@router.get("/messages")
def list_messages(session_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    _get_session_or_404(state, session_id)
    return [_message_payload(state, item) for item in state.messages.list_messages(session_id)]


@router.post("/messages")
async def create_message(
    session_id: str,
    payload: CreateMessageRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    session = _get_session_or_404(state, session_id)
    try:
        attachments = validate_attachments(payload.attachments, settings=state.app_settings.get())
    except ValueError as exc:
        raise_error(400, "INVALID_ATTACHMENTS", str(exc) or "Invalid attachments.")
    if not payload.content.strip() and not attachments:
        raise_error(400, "EMPTY_MESSAGE", "Message content or an attachment is required.")

    before = {item.message_id for item in state.messages.list_messages(session_id)}
    result = await state.runtime.handle_input(
        session,
        payload.content,
        attachments=attachments,
        client_message_id=payload.client_message_id,
    )
    if not result.success and not result.run_id:
        raise_error(400, result.error_code or "CHAT_FAILED", result.error or "Chat failed.")
    return _result_payload(state, session_id, result, before)


@message_router.delete("/{message_id}")
def delete_message(message_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    message = _get_message_or_404(state, message_id)
    try:
        state.messages.delete_message(message_id)
        _cleanup_message_attachments(state, message)
    except KeyError:
        raise_error(404, "MESSAGE_NOT_FOUND", f"Message not found: {message_id}")
    return {"deleted": True, "message_id": message_id}


@message_router.post("/{message_id}/retry")
async def retry_message(message_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    message = _get_message_or_404(state, message_id)
    if message.role != "assistant":
        raise_error(400, "CANNOT_RETRY_MESSAGE", "Only assistant messages can be retried.")
    source = _source_user_message_for_retry(state, message)
    session = _get_session_or_404(state, message.session_id)
    deleted = state.messages.delete_messages_after(session.session_id, message.message_id, include_target=True)
    _cancel_runs_for_deleted_messages(state, deleted)
    for item in deleted:
        _cleanup_message_attachments(state, item)
    before = {item.message_id for item in state.messages.list_messages(session.session_id)}
    result = await state.runtime.retry_assistant_message(session, message, source)
    if not result.success and not result.run_id:
        raise_error(400, result.error_code or "MESSAGE_RETRY_FAILED", result.error or "Message retry failed.")
    return _result_payload(state, session.session_id, result, before)


@message_router.post("/{message_id}/edit")
async def edit_message(
    message_id: str,
    payload: EditMessageRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    message = _get_message_or_404(state, message_id)
    if message.role != "user":
        raise_error(400, "CANNOT_EDIT_MESSAGE", "Only user messages can be edited.")
    session = _get_session_or_404(state, message.session_id)
    updated = message.model_copy(update={"parts": [make_text_part(payload.content, format="plain")]})
    state.messages.update_message(updated)
    deleted = state.messages.delete_messages_after(session.session_id, message.message_id, include_target=False)
    _cancel_runs_for_deleted_messages(state, deleted)
    for item in deleted:
        _cleanup_message_attachments(state, item)
    if not payload.rerun:
        return {"success": True, "data": updated.model_dump(mode="json"), "error": None, "run": None, "session": session.model_dump(mode="json"), "messages": []}
    before = {item.message_id for item in state.messages.list_messages(session.session_id)}
    result = await state.runtime.rerun_user_message(session, updated)
    if not result.success and not result.run_id:
        raise_error(400, result.error_code or "MESSAGE_EDIT_FAILED", result.error or "Message edit failed.")
    return _result_payload(state, session.session_id, result, before)


def _get_message_or_404(state: RuntimeState, message_id: str) -> MessageSchema:
    try:
        return state.messages.get_message(message_id)
    except KeyError:
        raise_error(404, "MESSAGE_NOT_FOUND", f"Message not found: {message_id}")


def _source_user_message_for_retry(state: RuntimeState, message: MessageSchema) -> MessageSchema:
    candidates = [message.parent_message_id, (message.metadata or {}).get("input_message_id")]
    if message.run_id:
        try:
            candidates.append((state.runs.get_run(message.run_id).metadata or {}).get("input_message_id"))
        except KeyError:
            pass
    for value in candidates:
        if not value:
            continue
        try:
            candidate = state.messages.get_message(str(value))
        except KeyError:
            continue
        if candidate.role == "user":
            return candidate
    # A linear history is a useful fallback for manually inserted messages.
    messages = state.messages.list_messages(message.session_id)
    index = next((i for i, item in enumerate(messages) if item.message_id == message.message_id), -1)
    for candidate in reversed(messages[:max(index, 0)]):
        if candidate.role == "user":
            return candidate
    raise_error(400, "CANNOT_RETRY_MESSAGE", "Could not find the user message that produced this response.")


def _cancel_runs_for_deleted_messages(state: RuntimeState, messages: list[MessageSchema]) -> None:
    run_ids = [item.run_id for item in messages if item.run_id]
    if run_ids:
        state.runs.cancel_runs(list(dict.fromkeys(run_ids)), reason="Messages were removed.")


def _cleanup_message_attachments(state: RuntimeState, message: MessageSchema) -> None:
    attachments = (message.metadata or {}).get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                delete_attachment_if_unreferenced(item, state.messages, message.session_id)


def _result_payload(state: RuntimeState, session_id: str, result: Any, before: set[str]) -> dict:
    new_messages = [item for item in state.messages.list_messages(session_id) if item.message_id not in before]
    run = state.runs.get_run(result.run_id) if result.run_id else None
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "error_code": result.error_code,
        "run": _run_payload(state, run) if run else None,
        "session": state.sessions.get_session(session_id).model_dump(mode="json"),
        "messages": [_message_payload(state, item) for item in new_messages],
    }


def _run_payload(state: RuntimeState, run: Any) -> dict:
    payload = run.model_dump(mode="json")
    payload["steps"] = [step.model_dump(mode="json") for step in state.runs.list_steps(run.run_id)]
    return payload


def _message_payload(state: RuntimeState, message: MessageSchema) -> dict:
    payload = message.model_dump(mode="json")
    if message.run_id:
        try:
            run = state.runs.get_run(message.run_id)
            payload["run"] = _run_payload(state, run)
        except KeyError:
            pass
    return payload
