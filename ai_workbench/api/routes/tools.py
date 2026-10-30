from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.common import JsonObject, error_responses
from ai_workbench.api.schemas.chat import ToolCatalogItem, ToolResult
from ai_workbench.api.errors import raise_error
from ai_workbench.core.harness.schema import ApprovalDecision, ToolExecutionError
from ai_workbench.core.message_parts import text_from_parts
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.web_schemas import WebToolsSettingsPatch, WebToolsSettingsResponse
from ai_workbench.core.web_filter_rules import FilterRuleError
from ai_workbench.core.web_filter_schemas import (
    WebFilterPatch, WebFilterSettingsResponse, WebSubscriptionCreate, WebSubscriptionInfo, WebSubscriptionPatch,
)


async def validate_tool_json(request: Request) -> None:
    body = await request.body()
    if body:
        try:
            strict_json_loads(body.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise_error(422, "INVALID_TOOL_JSON", "Tool requests must contain finite JSON without duplicate object keys.")


router = APIRouter(prefix="/api/tools", tags=["tools"], dependencies=[Depends(validate_tool_json)])


class DirectToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(min_length=1)
    arguments: JsonObject = Field(default_factory=dict, description="Finite JSON arguments validated against the named built-in tool's schema.")


@router.get("", response_model=list[ToolCatalogItem], response_model_exclude_unset=True,
    responses=error_responses(422))
def list_tools(state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    return state.tool_registry.catalog()


@router.get("/web/settings", response_model=WebToolsSettingsResponse, responses=error_responses(422))
def get_web_settings(state: RuntimeState = Depends(get_state)) -> WebToolsSettingsResponse:
    return state.web_tools.settings.public()


@router.patch("/web/settings", response_model=WebToolsSettingsResponse, responses=error_responses(422))
def patch_web_settings(payload: WebToolsSettingsPatch, state: RuntimeState = Depends(get_state)) -> WebToolsSettingsResponse:
    return state.web_tools.settings.patch(payload)


async def _filter_result(operation):
    try:
        return await operation
    except FilterRuleError as exc:
        raise_error(422, "WEB_FILTER_RULE_INVALID", str(exc), {"line": exc.line})
    except KeyError:
        raise_error(404, "WEB_SUBSCRIPTION_NOT_FOUND", "Subscription does not exist.")
    except ToolExecutionError as exc:
        raise_error(409, exc.code, exc.message, exc.details)


@router.get("/web/filters", response_model=WebFilterSettingsResponse)
def get_web_filters(state: RuntimeState = Depends(get_state)):
    return state.web_tools.filters.public()


@router.patch("/web/filters", response_model=WebFilterSettingsResponse, responses=error_responses(422))
async def patch_web_filters(payload: WebFilterPatch, state: RuntimeState = Depends(get_state)):
    return await _filter_result(state.web_tools.filters.set_custom(payload.custom_rules))


@router.post("/web/subscriptions", response_model=WebSubscriptionInfo, status_code=201, responses=error_responses(404, 409, 422))
async def add_web_subscription(payload: WebSubscriptionCreate, state: RuntimeState = Depends(get_state)):
    return await _filter_result(state.web_tools.filters.add(payload.name, payload.url))


@router.patch("/web/subscriptions/{subscription_id}", response_model=WebSubscriptionInfo, responses=error_responses(404, 422))
async def patch_web_subscription(subscription_id: str, payload: WebSubscriptionPatch, state: RuntimeState = Depends(get_state)):
    return await _filter_result(state.web_tools.filters.set_enabled(subscription_id, payload.enabled))


@router.delete("/web/subscriptions/{subscription_id}", status_code=204, responses=error_responses(404, 422))
async def delete_web_subscription(subscription_id: str, state: RuntimeState = Depends(get_state)):
    await _filter_result(state.web_tools.filters.delete(subscription_id))
    return Response(status_code=204)


@router.post("/web/subscriptions/{subscription_id}/refresh", response_model=WebSubscriptionInfo, responses=error_responses(404, 422))
async def refresh_web_subscription(subscription_id: str, state: RuntimeState = Depends(get_state)):
    result = await state.web_tools.filters.refresh(subscription_id)
    if result is None:
        raise_error(404, "WEB_SUBSCRIPTION_NOT_FOUND", "Subscription does not exist.")
    return result


@router.post("/{tool_name}/call", response_model=ToolResult, response_model_exclude_unset=True,
    responses=error_responses(400, 403, 404, 409, 422))
async def call_tool(tool_name: str, payload: DirectToolRequest, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        session = state.sessions.get_session(payload.session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", "Session not found.")
    result = await state.runtime.call_tool(session, tool_name, payload.arguments)
    return _tool_result_payload(state, session.session_id, result.run_id)


@router.post("/approvals/{run_id}", response_model=ToolResult, response_model_exclude_unset=True,
    responses=error_responses(404, 409, 422))
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
            await state.chat_runner.maybe_title(session.session_id, text_from_parts(user.parts), user.message_id)
        return _tool_result_payload(state, session.session_id, result.run_id)
    except ToolExecutionError as exc:
        raise_error(409, exc.code, exc.message, exc.details)


@router.get("/runs/{run_id}", response_model=ToolResult, response_model_exclude_unset=True,
    responses=error_responses(404, 422))
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
    messages = [item.model_dump(mode="json") for item in state.messages.messages_for_run(run_id)]
    payload = run.model_dump(mode="json")
    payload["steps"] = [step.model_dump(mode="json") for step in state.runs.list_steps(run_id)]
    return {"run": payload, "messages": messages,
            "session": state.chat_service.session_response(state.sessions.get_session(session_id))}
