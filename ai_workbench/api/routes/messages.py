from fastapi import APIRouter, Depends
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.attachments import delete_attachment_if_unreferenced, validate_attachments
from ai_workbench.core.forms import FormValidationError, find_action_form_block, validate_action_form_values
from ai_workbench.core.llm_config import LLMConfigError
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunStatus


router = APIRouter(prefix="/api/sessions/{session_id}", tags=["messages"])
message_router = APIRouter(prefix="/api/messages", tags=["messages"])


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    attachments: list[dict] = Field(default_factory=list)


class InvokeActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    action_id: str
    source_message_id: Optional[str] = None
    input_text: str = ""
    prefill: dict = Field(default_factory=dict)


class SubmitFormRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_message_id: str
    form_id: str
    values: dict[str, Any] = Field(default_factory=dict)


class EditMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    rerun: bool = True


@router.get("/messages")
def list_messages(session_id: str, state: RuntimeState = Depends(get_state)) -> list:
    _get_session_or_404(state, session_id)
    return [_message_payload(state, message) for message in state.messages.list_messages(session_id)]


@router.post("/messages")
async def create_message(session_id: str, payload: CreateMessageRequest, state: RuntimeState = Depends(get_state)) -> dict:
    session = _get_session_or_404(state, session_id)
    before_ids = {message.message_id for message in state.messages.list_messages(session_id)}
    try:
        attachments = validate_attachments(payload.attachments, settings=state.app_settings.get())
    except ValueError as exc:
        raise_error(400, "INVALID_ATTACHMENTS", str(exc) or "Invalid attachments.")

    if not payload.content.strip() and not attachments:
        raise_error(400, "EMPTY_MESSAGE", "Message content or an attachment is required.")

    input_message_id = ""
    try:
        state.runtime.announce_model_change_if_needed(session_id)
    except LLMConfigError as exc:
        raise_error(400, exc.code, exc.message)

    if payload.content.startswith("/"):
        command_name = payload.content.split(maxsplit=1)[0]
        user_message = state.messages.add_message(
            session_id=session_id,
            role="user",
            content=payload.content,
            metadata={
                "attachments": attachments,
                "input_source": "command",
                "invocation": {
                    "route_type": "command",
                    "command_id": command_name,
                    "raw_text": payload.content,
                },
            },
        )
        input_message_id = user_message.message_id

    result = await state.runtime.handle_input(
        session,
        payload.content,
        input_message_id=input_message_id,
        attachments=attachments,
    )
    if not result.success and result.run_id:
        run = state.runs.get_run(result.run_id)
        if run.status == RunStatus.FAILED:
            return _result_payload(state, session_id, result)
    if not result.success:
        status_code = 404 if result.error_code in {"AGENT_NOT_FOUND", "COMMAND_NOT_FOUND", "ACTION_NOT_FOUND"} else 400
        raise_error(status_code, result.error_code or "ROUTE_ERROR", result.error or "Input could not be routed")

    return _result_payload(state, session_id, result, before_ids)


@message_router.delete("/{message_id}")
def delete_message(message_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        deleted = state.messages.delete_message(message_id)
        _cleanup_message_attachments(state, deleted)
    except KeyError:
        raise_error(404, "MESSAGE_NOT_FOUND", f"Message not found: {message_id}")
    except Exception as exc:
        raise_error(400, "MESSAGE_DELETE_FAILED", str(exc) or "Message delete failed")
    return {"deleted": True, "message_id": message_id}


@message_router.post("/{message_id}/retry")
async def retry_message(message_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    message = _get_message_or_404(state, message_id)
    if message.role not in {"assistant", "agent"}:
        raise_error(400, "CANNOT_RETRY_MESSAGE", "Only assistant messages can be retried.")
    if not message.agent_id:
        raise_error(400, "CANNOT_RETRY_MESSAGE", "Message has no agent invocation to retry.")

    source_user_message = _source_user_message_for_retry(state, message)
    session = _get_session_or_404(state, message.session_id)
    try:
        deleted = state.messages.delete_messages_after(message.session_id, message.message_id, include_target=True)
        _cancel_runs_for_deleted_messages(state, deleted)
        _cleanup_deleted_attachments(state, deleted)
        state.runtime.announce_model_change_if_needed(message.session_id)
        before_ids = {item.message_id for item in state.messages.list_messages(message.session_id)}
        result = await state.runtime.retry_assistant_message(session, message, source_user_message)
    except LLMConfigError as exc:
        raise_error(400, exc.code, exc.message)
    except Exception as exc:
        raise_error(400, "MESSAGE_RETRY_FAILED", str(exc) or "Message retry failed")

    if not result.success:
        if result.error_code == "ACTION_NOT_FOUND":
            raise_error(404, result.error_code, result.error or "Action not found")
        raise_error(400, result.error_code or "MESSAGE_RETRY_FAILED", result.error or "Message retry failed")
    return _result_payload(state, message.session_id, result, before_ids)


@message_router.post("/{message_id}/edit")
async def edit_message(message_id: str, payload: EditMessageRequest, state: RuntimeState = Depends(get_state)) -> dict:
    message = _get_message_or_404(state, message_id)
    if message.role != "user":
        raise_error(400, "CANNOT_EDIT_MESSAGE", "Only user messages can be edited.")

    session = _get_session_or_404(state, message.session_id)
    try:
        updated_message = message.model_copy(update={"content": payload.content})
        updated_message = state.messages.update_message(updated_message)
        deleted = state.messages.delete_messages_after(message.session_id, message.message_id, include_target=False)
        _cancel_runs_for_deleted_messages(state, deleted)
        _cleanup_deleted_attachments(state, deleted)
        result = None
        before_ids = {item.message_id for item in state.messages.list_messages(message.session_id)}
        if payload.rerun:
            state.runtime.announce_model_change_if_needed(message.session_id)
            before_ids = {item.message_id for item in state.messages.list_messages(message.session_id)}
            result = await state.runtime.rerun_user_message(session, updated_message)
    except LLMConfigError as exc:
        raise_error(400, exc.code, exc.message)
    except Exception as exc:
        raise_error(400, "MESSAGE_EDIT_FAILED", str(exc) or "Message edit failed")

    if result is None:
        return {
            "success": True,
            "data": updated_message.model_dump(),
            "error": None,
            "run": None,
            "messages": [],
        }
    if not result.success:
        raise_error(400, result.error_code or "MESSAGE_EDIT_FAILED", result.error or "Message edit failed")
    return _result_payload(state, message.session_id, result, before_ids)


@router.post("/actions")
async def invoke_action(session_id: str, payload: InvokeActionRequest, state: RuntimeState = Depends(get_state)) -> dict:
    _get_session_or_404(state, session_id)
    before_ids = {message.message_id for message in state.messages.list_messages(session_id)}
    try:
        state.agents.get(payload.agent_id)
    except KeyError:
        raise_error(404, "AGENT_NOT_FOUND", f"Agent not found: {payload.agent_id}")
    if payload.source_message_id:
        try:
            state.messages.get_message(payload.source_message_id)
        except KeyError:
            raise_error(404, "MESSAGE_NOT_FOUND", f"Message not found: {payload.source_message_id}")

    result = await state.runtime.invoke_action(
        session_id=session_id,
        agent_id=payload.agent_id,
        action_id=payload.action_id,
        source_message_id=payload.source_message_id,
        input_text=payload.input_text,
        prefill=payload.prefill,
    )
    if not result.success:
        if result.run_id:
            return _result_payload(state, session_id, result, before_ids)
        status_code = 404 if result.error_code in {"AGENT_NOT_FOUND", "ACTION_NOT_FOUND"} else 400
        raise_error(status_code, result.error_code or "ACTION_NOT_FOUND", result.error or "Action failed")
    return _result_payload(state, session_id, result, before_ids)


@router.post("/forms/submit")
async def submit_form(session_id: str, payload: SubmitFormRequest, state: RuntimeState = Depends(get_state)) -> dict:
    _get_session_or_404(state, session_id)
    before_ids = {message.message_id for message in state.messages.list_messages(session_id)}
    source = _get_message_or_404(state, payload.source_message_id)
    if source.session_id != session_id:
        raise_error(404, "FORM_NOT_FOUND", f"Form source message not found in session: {payload.source_message_id}")
    try:
        form = find_action_form_block(source.content, payload.form_id)
    except FormValidationError as exc:
        raise_error(400, exc.code, exc.message, exc.details)
    if form is None:
        raise_error(404, "FORM_NOT_FOUND", f"Form not found: {payload.form_id}")

    submit = form["submit"]
    target_agent_id = submit.get("agent_id") or source.agent_id
    target_action_id = submit.get("action_id")
    if not target_agent_id or not target_action_id:
        raise_error(400, "FORM_TARGET_INVALID", "Form submit target is incomplete.")
    try:
        target_agent = state.agents.get(target_agent_id)
    except KeyError:
        raise_error(404, "FORM_TARGET_INVALID", f"Form target agent not found: {target_agent_id}")
    if hasattr(state, "agent_configs") and not state.agent_configs.is_enabled(target_agent_id):
        raise_error(400, "FORM_TARGET_INVALID", f"Form target agent is disabled: {target_agent_id}")
    if target_action_id not in {action.id for action in target_agent.actions}:
        raise_error(400, "FORM_TARGET_INVALID", f"Form target action not found: {target_agent_id}:{target_action_id}")

    try:
        values = validate_action_form_values(form, payload.values)
    except FormValidationError as exc:
        raise_error(400, exc.code, exc.message, exc.details)

    visibility = submit.get("visibility") or "message"
    if visibility == "silent":
        result = await state.agent_runner.run(
            agent_id=target_agent_id,
            action_id=target_action_id,
            args="",
            session_id=session_id,
            source_message_id=source.message_id,
            parent_message_id=source.message_id,
            prefill=values,
            form_id=payload.form_id,
            create_user_message=False,
            suppress_output=True,
            is_silent_submission=True,
        )
        message = submit.get("success_message") or "Saved"
        if not result.success:
            prefix = submit.get("failure_message")
            error = result.error or "Form submission failed."
            if prefix:
                error = f"{prefix}: {error}"
            if result.run_id:
                payload_data = _result_payload(state, session_id, result, before_ids)
                payload_data.update({"ok": False, "message": error, "silent": True, "run_id": result.run_id})
                return payload_data
            raise_error(400, result.error_code or "FORM_SUBMISSION_FAILED", error)
        payload_data = _result_payload(state, session_id, result, before_ids)
        payload_data.update({"ok": True, "message": message, "silent": True, "run_id": result.run_id or None})
        return payload_data

    display_text = submit.get("message") or f"Submitted form: {form.get('title') or payload.form_id}"
    user_message = state.messages.add_message(
        session_id=session_id,
        role="user",
        content=display_text,
        agent_id=target_agent_id,
        action_id=target_action_id,
        parent_message_id=source.message_id,
        metadata={
            "origin": "form_submission",
            "input_source": "form_submission",
            "source_message_id": source.message_id,
            "form_id": payload.form_id,
            "target_agent_id": target_agent_id,
            "target_action_id": target_action_id,
            "prefill": values,
            "invocation": {
                "route_type": "agent",
                "agent_id": target_agent_id,
                "action_id": target_action_id,
                "raw_text": display_text,
                "args": display_text,
            },
        },
        speaker_type="user",
        speaker_id="local_user",
        speaker_name="User",
        origin="form_submission",
    )

    result = await state.agent_runner.run(
        agent_id=target_agent_id,
        action_id=target_action_id,
        args=display_text,
        session_id=session_id,
        source_message_id=source.message_id,
        parent_message_id=source.message_id,
        prefill=values,
        form_id=payload.form_id,
        input_message_id=user_message.message_id,
        create_user_message=False,
    )
    if not result.success:
        if result.run_id:
            return _result_payload(state, session_id, result, before_ids)
        raise_error(400, result.error_code or "FORM_SUBMISSION_FAILED", result.error or "Form submission failed.")
    return _result_payload(state, session_id, result, before_ids)


def _get_session_or_404(state: RuntimeState, session_id: str):
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _get_message_or_404(state: RuntimeState, message_id: str) -> MessageSchema:
    try:
        return state.messages.get_message(message_id)
    except KeyError:
        raise_error(404, "MESSAGE_NOT_FOUND", f"Message not found: {message_id}")


def _source_user_message_for_retry(state: RuntimeState, message: MessageSchema) -> MessageSchema:
    metadata = message.metadata or {}
    candidate_ids = [
        metadata.get("source_user_message_id"),
        metadata.get("input_message_id"),
        message.parent_message_id,
    ]
    if message.run_id:
        try:
            run = state.runs.get_run(message.run_id)
            candidate_ids.append((run.metadata or {}).get("input_message_id"))
        except KeyError:
            pass
    for candidate_id in candidate_ids:
        if not candidate_id:
            continue
        try:
            candidate = state.messages.get_message(str(candidate_id))
        except KeyError:
            continue
        if candidate.role == "user":
            return candidate
    raise_error(400, "CANNOT_RETRY_MESSAGE", "Could not find the user message that produced this response.")


def _cancel_runs_for_deleted_messages(state: RuntimeState, messages: list[MessageSchema]) -> None:
    run_ids = sorted({message.run_id for message in messages if message.run_id})
    cancel_runs = getattr(state.runs, "cancel_runs", None)
    if callable(cancel_runs):
        cancel_runs(run_ids, reason="Messages were removed.")


def _cleanup_deleted_attachments(state: RuntimeState, messages: list[MessageSchema]) -> None:
    for message in messages:
        _cleanup_message_attachments(state, message)


def _cleanup_message_attachments(state: RuntimeState, message: MessageSchema) -> None:
    attachments = (message.metadata or {}).get("attachments")
    if not isinstance(attachments, list):
        return
    for attachment in attachments:
        if isinstance(attachment, dict):
            delete_attachment_if_unreferenced(attachment, state.messages, message.session_id)


def _result_payload(state: RuntimeState, session_id: str, result, before_ids=None) -> dict:
    before_ids = before_ids or set()
    messages = [message for message in state.messages.list_messages(session_id) if message.message_id not in before_ids]
    run = state.runs.get_run(result.run_id) if result.run_id else None
    session = state.sessions.get_session(session_id)
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "run": run.model_dump() if run else None,
        "session": session.model_dump(),
        "messages": [_message_payload(state, message) for message in messages],
    }


def _message_payload(state: RuntimeState, message: MessageSchema) -> dict:
    payload = message.model_dump()
    if not message.run_id:
        return payload
    try:
        run = state.runs.get_run(message.run_id)
    except KeyError:
        return payload
    payload["run"] = run.model_dump()
    payload["run_steps"] = [step.model_dump() for step in state.runs.list_steps(run.run_id)]
    return payload
