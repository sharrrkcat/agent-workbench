from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.system import RuntimeResources


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/resources", response_model=RuntimeResources, response_model_exclude_unset=True)
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
