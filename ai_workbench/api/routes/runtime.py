from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.runtime_memory import expand_targets


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


class FreeMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[str]
    session_id: str | None = None


@router.get("/memory")
def get_runtime_memory(
    session_id: str | None = Query(default=None),
    state: RuntimeState = Depends(get_state),
) -> dict:
    return state.runtime_memory.memory_summary(session_id=session_id)


@router.get("/resources")
def get_runtime_resources(state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.runtime_resources.resources()
    except Exception:
        return {
            "cpu": {"available": False, "percent": None, "reason": "Runtime resources unavailable."},
            "memory": {"available": False, "used_bytes": None, "total_bytes": None, "percent": None, "reason": "Runtime resources unavailable."},
            "gpus": [],
            "process": {"backend_memory_bytes": None, "reason": "Runtime resources unavailable."},
            "updated_at": None,
            "error": "Runtime resources unavailable.",
        }


@router.post("/free-memory")
def free_runtime_memory(payload: FreeMemoryRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        targets = expand_targets(payload.targets)
    except ValueError as exc:
        raise_error(422, "INVALID_RUNTIME_MEMORY_TARGET", str(exc))
    return state.runtime_memory.free_memory(targets, context={"session_id": payload.session_id or ""})
