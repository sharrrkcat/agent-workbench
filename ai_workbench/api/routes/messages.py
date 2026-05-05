from fastapi import APIRouter, Depends
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.schema.run import RunStatus


router = APIRouter(prefix="/api/sessions/{session_id}", tags=["messages"])


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class InvokeActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    action_id: str
    source_message_id: Optional[str] = None
    input_text: str = ""
    prefill: dict = Field(default_factory=dict)


@router.get("/messages")
def list_messages(session_id: str, state: RuntimeState = Depends(get_state)) -> list:
    _get_session_or_404(state, session_id)
    return [message.model_dump() for message in state.messages.list_messages(session_id)]


@router.post("/messages")
async def create_message(session_id: str, payload: CreateMessageRequest, state: RuntimeState = Depends(get_state)) -> dict:
    session = _get_session_or_404(state, session_id)
    before_ids = {message.message_id for message in state.messages.list_messages(session_id)}

    if payload.content.startswith("/"):
        state.messages.add_message(session_id=session_id, role="user", content=payload.content)

    result = await state.runtime.handle_input(session, payload.content)
    if not result.success and result.run_id:
        run = state.runs.get_run(result.run_id)
        if run.status == RunStatus.FAILED:
            return _result_payload(state, session_id, result)
    if not result.success:
        status_code = 404 if result.error_code in {"AGENT_NOT_FOUND", "COMMAND_NOT_FOUND", "ACTION_NOT_FOUND"} else 400
        raise_error(status_code, result.error_code or "ROUTE_ERROR", result.error or "Input could not be routed")

    return _result_payload(state, session_id, result, before_ids)


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


def _get_session_or_404(state: RuntimeState, session_id: str):
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _result_payload(state: RuntimeState, session_id: str, result, before_ids=None) -> dict:
    before_ids = before_ids or set()
    messages = [message for message in state.messages.list_messages(session_id) if message.message_id not in before_ids]
    run = state.runs.get_run(result.run_id) if result.run_id else None
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "run": run.model_dump() if run else None,
        "messages": [message.model_dump() for message in messages],
    }
