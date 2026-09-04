from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_workbench import __version__
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.llm_config import public_llm_config_status, resolve_llm_config
from ai_workbench.db.database import SCHEMA_VERSION


router = APIRouter(tags=["health"])


@router.get("/api/health")
def health(state: RuntimeState = Depends(get_state)) -> dict:
    database = _database_status(state)
    return {
        "status": "ok" if database["status"] == "ok" else "degraded",
        "version": __version__,
        "database": database["status"],
        "schema_version": SCHEMA_VERSION,
    }


@router.get("/api/health/details")
def health_details(state: RuntimeState = Depends(get_state)) -> dict:
    database = _database_status(state)
    llm = _llm_status(state)
    return {
        "status": "ok" if database["status"] == "ok" and llm["status"] == "ok" else "degraded",
        "version": __version__,
        "database": database,
        "schema_version": SCHEMA_VERSION,
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
        config = resolve_llm_config(
            llm_profile_store=state.llm_profiles,
            provider_profile_store=state.provider_profiles,
            llm_defaults_store=state.llm_defaults,
        )
        return {"status": "ok", **public_llm_config_status(config)}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc) or "LLM config unavailable"}
