"""QQ transcript, local deletion and explicit execution controls."""
import asyncio
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query
from pydantic import Field
from ai_workbench.api.deps import get_state, RuntimeState
from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, DeletedResponse, error_responses
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.qq_history import QQHistoryPruned
from ai_workbench.core.schema.qq import QQImageAttachment
from ai_workbench.core.history_page import HistoryQuery
from ai_workbench.core.qq_transcript import BINDING_PRIVATE
from ai_workbench.api.schemas.qq import BindingResponse, QQHistoryPage
from ai_workbench.core.qq_segments import public_segments
from ai_workbench.db.qq_models import QQBinding

router = APIRouter(prefix="/api/qq", tags=["qq"])
class ConnectionStatus(ApiModel):
    status: Literal["disabled", "connecting", "connected", "QQ_ACCOUNT_MISMATCH", "QQ_ACTION_FAILED", "QQ_AUTH_FAILED", "QQ_CONNECTION_FAILED"]
    connected: bool


class Control(ApiModel):
    action: Literal["pause", "resume", "stop"]


class QQResourceResponse(ApiModel):
    id: int
    attachment: QQImageAttachment
    description: str | None
    is_favorite: bool
    created_at: ApiTimestamp
    has_references: bool


class QQResourcePage(ApiModel):
    items: list[QQResourceResponse]
    total: int
    page: int
    page_size: int


class QQResourcePatch(ApiModel):
    description: str | None = None
    is_favorite: bool = Field(default=False, strict=True)


class QQResourceQuery(ApiModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=100)
    sort: Literal["created_at", "size"] = "created_at"
    order: Literal["asc", "desc"] = "desc"
    favorite: Literal["all", "favorites", "unfavorited"] = "all"


@router.get("/resources", response_model=QQResourcePage, responses=error_responses(422))
async def resources(query: Annotated[QQResourceQuery, Query()], state: RuntimeState = Depends(get_state)):
    return state.qq.resources.page(**query.model_dump())


@router.patch("/resources/{asset_id}", response_model=QQResourceResponse, responses=error_responses(404, 409, 422))
async def update_resource(asset_id: int, payload: QQResourcePatch, state: RuntimeState = Depends(get_state)):
    return state.qq.resources.update(asset_id, payload.model_dump(exclude_unset=True))


@router.delete("/resources/{asset_id}", response_model=DeletedResponse, responses=error_responses(404, 409))
async def delete_resource(asset_id: int, state: RuntimeState = Depends(get_state)):
    return state.qq.resources.delete(asset_id)


def binding(state, session_id):
    value = state.qq.store.get(QQBinding, session_id)
    if value is None:
        raise ChatError("SESSION_NOT_FOUND", "QQ Session does not exist.", 404)
    return value


@router.get("/projects/{project_id}/status", response_model=ConnectionStatus, responses=error_responses(404, 422))
def connection_status(project_id: str, state: RuntimeState = Depends(get_state)):
    project = state.project_service.get(project_id)
    if project.kind != "qqbot":
        raise ChatError("PROJECT_TYPE_INVALID", "Choose a QQBot Project.", 422)
    connection = state.qq.connections.get(project_id)
    return {"status": connection.status if connection else "disabled" if not project.connection_enabled else "connecting",
        "connected": bool(connection and connection.ready)}


@router.get("/sessions/{session_id}", response_model=BindingResponse, responses=error_responses(404))
async def get_binding(session_id: str, state: RuntimeState = Depends(get_state)):
    return binding_response(state, binding(state, session_id))


def binding_response(state, bound):
    return {**bound.model_dump(exclude=BINDING_PRIVATE),
        "history_version": state.sessions.get_session(bound.session_id).history_version,
        "busy": state.qq.history.busy(bound.session_id)}


@router.post("/sessions/{session_id}/control", response_model=BindingResponse, responses=error_responses(404, 409))
async def control(session_id: str, payload: Control, state: RuntimeState = Depends(get_state)):
    return binding_response(state, await state.qq.control(session_id, payload.action))


@router.get("/sessions/{session_id}/history", response_model=QQHistoryPage,
    responses=error_responses(404, 422))
async def history(session_id: str, query: Annotated[HistoryQuery, Query()], state: RuntimeState = Depends(get_state)):
    from ai_workbench.api.errors import raise_error
    program_busy = state.qq.programs.busy(session_id)
    def read():
        page, bound, media = state.qq.transcript.page(session_id, query, program_busy=program_busy)
        return page, bound, media, state.projects.get(bound.project_id).bot_account
    try:
        # The in-memory test backend shares one SQLite connection and event-loop-owned run stores.
        page, bound, media, bot_account = await asyncio.to_thread(read) if state.qq.transcript.sql_runs else read()
    except ValueError as exc:
        raise_error(422, "INVALID_HISTORY_CURSOR", str(exc))
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", "QQ Session does not exist.")
    rows = [item["message"] for item in page["items"] if item["kind"] == "incoming"]
    original = {row["id"]: row["text"] for row in rows}
    state.qq.names.display(bound, bot_account, rows)
    for row in rows:
        row["segments"] = public_segments(original[row["id"]], row.pop("references_json"), media[row["id"]])
    return page


@router.delete("/sessions/{session_id}/messages/{message_id}", response_model=QQHistoryPruned,
    responses=error_responses(404, 409))
async def delete_message(session_id: str, message_id: int, state: RuntimeState = Depends(get_state)):
    return state.qq.history.delete(session_id, message_id=message_id)


@router.delete("/sessions/{session_id}/deliveries/{delivery_id}", response_model=QQHistoryPruned,
    responses=error_responses(404, 409))
async def delete_delivery(session_id: str, delivery_id: int, state: RuntimeState = Depends(get_state)):
    return state.qq.history.delete(session_id, delivery_id=delivery_id)
