from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.harness.schema import ApprovalDecision, ToolExecutionError
from ai_workbench.core.message_parts import text_from_parts
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.schema.run import RunStatus


async def validate_tool_json(request: Request) -> None:
    body = await request.body()
    if body:
        try:
            strict_json_loads(body.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise_error(422, "INVALID_TOOL_JSON", "Tool requests must contain finite JSON without duplicate object keys.")


router = APIRouter(prefix="/api/tools", tags=["tools"], dependencies=[Depends(validate_tool_json)])


class HarnessSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    searxng_base_url: str | None = None


class DirectToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_tools(state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    return state.tool_registry.catalog()


@router.get("/settings")
def get_tool_settings(state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    return state.harness_settings.get().model_dump(mode="json")


@router.patch("/settings")
def patch_tool_settings(payload: HarnessSettingsPatch, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        values = payload.model_dump(exclude_unset=True)
        if (values.get("searxng_base_url") or "").strip():
            state.network_policy.validate_url(values["searxng_base_url"], resolve_dns=False)
        value = state.harness_settings.patch(values)
        return value.model_dump(mode="json")
    except (ValidationError, ValueError):
        raise_error(422, "INVALID_TOOL_SETTING", "Use a public HTTP(S) SearXNG URL without credentials, query or fragment.")


@router.post("/{tool_name}/call")
async def call_tool(tool_name: str, payload: DirectToolRequest, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        session = state.sessions.get_session(payload.session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", "Session not found.")
    result = await state.runtime.call_tool(session, tool_name, payload.arguments)
    return _tool_result_payload(state, session.session_id, result.run_id)


@router.post("/approvals/{run_id}")
async def resolve_approval(run_id: str, payload: ApprovalDecision, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        run = state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", "Run not found.")
    if run.status != RunStatus.WAITING_FOR_USER:
        raise_error(409, "APPROVAL_NOT_WAITING", "Run is not waiting for approval.")
    try:
        session = state.sessions.get_session(run.session_id)
        result = await state.chat_runner.harness_loop.resume_approval(session=session, run=run, decision=payload.decision)
        if result.success and state.runs.get_run(run_id).status == RunStatus.DONE and run.kind == "chat":
            user = state.messages.get_message(run.metadata["input_message_id"])
            await state.chat_runner.maybe_title(session.session_id, text_from_parts(user.parts))
        return _tool_result_payload(state, session.session_id, result.run_id)
    except ToolExecutionError as exc:
        raise_error(409, exc.code, exc.message, exc.details)


@router.get("/runs/{run_id}")
def get_tool_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        run = state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", "Run not found.")
    if run.kind != "tool" and not (run.metadata or {}).get("harness"):
        raise_error(404, "TOOL_RUN_NOT_FOUND", "Tool run not found.")
    return _tool_result_payload(state, run.session_id, run_id)


def _tool_result_payload(state: RuntimeState, session_id: str, run_id: str) -> dict[str, Any]:
    run = state.runs.get_run(run_id)
    messages = [item.model_dump(mode="json") for item in state.messages.list_messages(session_id) if item.run_id == run_id]
    payload = run.model_dump(mode="json")
    payload["steps"] = [step.model_dump(mode="json") for step in state.runs.list_steps(run_id)]
    return {"run": payload, "messages": messages,
            "session": state.chat_service.session_response(state.sessions.get_session(session_id))}
