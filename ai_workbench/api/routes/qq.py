"""Read-only QQ transcript and explicit execution controls."""
from typing import Literal
from fastapi import APIRouter, Depends, Query
from ai_workbench.api.deps import get_state, RuntimeState
from ai_workbench.api.schemas.common import ApiModel, public_model, error_responses
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.schema.qq import QQTriggerKind
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery

router = APIRouter(prefix="/api/qq", tags=["qq"])
BindingResponse = public_model("QQBindingResponse", QQBinding, omit={"window_kind"}, fields={"target_kind": (Literal["group", "friend"], ...)})


class QQReference(ApiModel):
    type: Literal["at", "reply"]
    id: str
    name: str | None = None
    is_self: bool = False


MessageResponse = public_model("QQMessageResponse", QQMessage, omit={"references_json"}, fields={
    "id": (int, ...), "references": (list[QQReference], ...),
    "disposition": (Literal["pending", "batched", "skipped"], ...),
})
BatchResponse = public_model("QQBatchResponse", QQBatch, omit={"participants_json"}, fields={"id": (int, ...),
    "trigger_kind": (QQTriggerKind, ...),
    "status": (Literal["queued", "running", "done", "failed", "cancelled", "interrupted"], ...),
})
DeliveryResponse = public_model("QQDeliveryResponse", QQDelivery, fields={"id": (int, ...),
    "status": (Literal["pending", "sending", "sent", "failed", "unknown"], ...),
})


class MessagePage(ApiModel):
    items: list[MessageResponse]
    next_cursor: int | None


class BatchPage(ApiModel):
    items: list[BatchResponse]
    next_cursor: int | None


class DeliveryPage(ApiModel):
    items: list[DeliveryResponse]
    next_cursor: int | None


class ConnectionStatus(ApiModel):
    status: Literal["disabled", "connecting", "connected", "QQ_ACCOUNT_MISMATCH", "QQ_ACTION_FAILED", "QQ_AUTH_FAILED", "QQ_CONNECTION_FAILED"]
    connected: bool


class Control(ApiModel):
    action: Literal["pause", "resume", "stop"]


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
def get_binding(session_id: str, state: RuntimeState = Depends(get_state)):
    return binding(state, session_id)


@router.post("/sessions/{session_id}/control", response_model=BindingResponse, responses=error_responses(404, 409))
async def control(session_id: str, payload: Control, state: RuntimeState = Depends(get_state)):
    if payload.action == "resume":
        state.chat_service.assert_idle(session_id)
    return state.qq.control(session_id, payload.action)


@router.get("/sessions/{session_id}/messages", response_model=MessagePage, responses=error_responses(404))
async def messages(session_id: str, before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100),
             state: RuntimeState = Depends(get_state)):
    bound = binding(state, session_id)
    page = state.qq.store.page(QQMessage, session_id, before, limit)
    await state.qq.names.project(bound, state.projects.get(bound.project_id).bot_account, page["items"])
    for row in page["items"]:
        row.pop("references_json")
    return page


@router.get("/sessions/{session_id}/batches", response_model=BatchPage, responses=error_responses(404))
def batches(session_id: str, before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100),
            state: RuntimeState = Depends(get_state)):
    binding(state, session_id)
    page = state.qq.store.page(QQBatch, session_id, before, limit)
    for row in page["items"]:
        row.pop("participants_json")
    return page


@router.get("/sessions/{session_id}/deliveries", response_model=DeliveryPage, responses=error_responses(404))
def deliveries(session_id: str, before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100),
               state: RuntimeState = Depends(get_state)):
    binding(state, session_id)
    return state.qq.store.page(QQDelivery, session_id, before, limit)
