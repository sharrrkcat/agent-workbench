from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_workbench import __version__
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.system import HealthResponse, HealthDetails
from ai_workbench.db.migrations import HEAD_REVISION


router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse, response_model_exclude_unset=True)
def health(state: RuntimeState = Depends(get_state)) -> dict:
    database = _database_status(state)
    return {
        "status": "ok" if database["status"] == "ok" else "degraded",
        "version": __version__,
        "database": database["status"],
        "schema_revision": HEAD_REVISION,
    }


@router.get("/api/health/details", response_model=HealthDetails, response_model_exclude_unset=True)
def health_details(state: RuntimeState = Depends(get_state)) -> dict:
    database = _database_status(state)
    llm = _llm_status(state)
    return {
        "status": "ok" if database["status"] == "ok" and llm["status"] == "ok" else "degraded",
        "version": __version__,
        "database": database,
        "schema_revision": HEAD_REVISION,
        "llm": llm,
        "runs": {"active_count": state.active_runs.active_count()},
    }


def _database_status(state: RuntimeState) -> dict:
    try:
        state.sessions.list_sessions()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc) or "database unavailable"}


def _llm_status(state: RuntimeState) -> dict:
    try:
        profile = state.model_manager.default_chat_profile()
        if profile is None:
            return {"status": "degraded", "error": "No enabled chat model is configured."}
        return {"status": "ok", "model_profile_id": profile.id, "alias": profile.alias,
                **state.model_manager.status(profile.id).model_dump()}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc) or "LLM config unavailable"}
