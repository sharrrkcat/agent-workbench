from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import request_body
from ai_workbench.api.schemas.common import error_responses, public_model
from ai_workbench.api.schemas.attachments import AttachmentInput
from ai_workbench.api.schemas.chat import ChatResult, HistoryResult, MessageResponse
from ai_workbench.core.conversation_history import HistoryPruned
from ai_workbench.api.errors import raise_error
from ai_workbench.api.routes.sessions import _get_session_or_404
from ai_workbench.core.attachments import validate_attachments
from ai_workbench.core.schema.message import MessageSchema


router = APIRouter(prefix="/api/sessions/{session_id}", tags=["messages"])
message_router = APIRouter(prefix="/api/messages", tags=["messages"])


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    client_message_id: str = ""
    source_message_id: str | None = None


class EditMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    rerun: bool = True


CreateMessageBody = public_model("CreateMessageBody", CreateMessageRequest, fields={
    "attachments": (list[AttachmentInput], Field(default_factory=list,
        description="Each item contains exactly one of data_url or a saved local URI.")),
})


@router.get("/messages", response_model=list[MessageResponse], response_model_exclude_unset=True,
    responses=error_responses(404))
def list_messages(session_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    _get_session_or_404(state, session_id)
    return [_message_payload(state, item) for item in state.messages.list_messages(session_id)]


@router.post("/messages", response_model=ChatResult, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422),
    openapi_extra=request_body(CreateMessageBody, description="Attachment metadata is validated by the attachment service; malformed attachments return INVALID_ATTACHMENTS."))
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
        source_message_id=payload.source_message_id,
    )
    if not result.success and not result.run_id:
        raise_error(400, result.error_code or "CHAT_FAILED", result.error or "Chat failed.")
    return _result_payload(state, session_id, result, before)


@message_router.delete("/{message_id}", response_model=HistoryPruned, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409))
async def delete_message(message_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _get_message_or_404(state, message_id)
    return state.history.delete_user(message_id).model_dump()


@message_router.post("/{message_id}/edit", response_model=HistoryResult, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422))
async def edit_message(
    message_id: str,
    payload: EditMessageRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    message = _get_message_or_404(state, message_id)
    if message.role != "user":
        raise_error(400, "CANNOT_EDIT_MESSAGE", "Only user messages can be edited.")
    session = _get_session_or_404(state, message.session_id)
    state.chat_service.assert_idle(session.session_id)
    if payload.rerun:
        state.chat_service.resolve(session)
    updated, change = state.history.edit_user(message_id, payload.content)
    if not payload.rerun:
        return {"success": True, "data": updated.model_dump(mode="json"), "error": None, "run": None,
                "session": state.chat_service.session_response(state.sessions.get_session(session.session_id)),
                "messages": [updated.model_dump(mode="json")], **change.model_dump()}
    before = {item.message_id for item in state.messages.list_messages(session.session_id)}
    result = await state.runtime.rerun_user_message(session, updated)
    if not result.success and not result.run_id:
        raise_error(400, result.error_code or "MESSAGE_EDIT_FAILED", result.error or "Message edit failed.")
    response = _result_payload(state, session.session_id, result, before)
    response["messages"].insert(0, updated.model_dump(mode="json"))
    return {**response, **change.model_dump()}


def _get_message_or_404(state: RuntimeState, message_id: str) -> MessageSchema:
    try:
        return state.messages.get_message(message_id)
    except KeyError:
        raise_error(404, "MESSAGE_NOT_FOUND", f"Message not found: {message_id}")


def _result_payload(state: RuntimeState, session_id: str, result: Any, before: set[str]) -> dict:
    new_messages = [item for item in state.messages.list_messages(session_id) if item.message_id not in before]
    run = state.runs.get_run(result.run_id) if result.run_id else None
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "error_code": result.error_code,
        "run": _run_payload(state, run) if run else None,
        "session": state.chat_service.session_response(state.sessions.get_session(session_id)),
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
