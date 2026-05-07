from fastapi import APIRouter, Depends

from ai_workbench import __version__
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.llm_config import public_llm_config_status, resolve_llm_config
from ai_workbench.db.database import SCHEMA_VERSION


router = APIRouter(tags=["health"])


@router.get("/api/health")
def health(state: RuntimeState = Depends(get_state)) -> dict:
    status = _database_status(state)
    return {
        "status": "ok" if status["status"] == "ok" else "degraded",
        "version": __version__,
        "database": status["status"],
        "schema_version": SCHEMA_VERSION,
    }


@router.get("/api/health/details")
def health_details(state: RuntimeState = Depends(get_state)) -> dict:
    details = {
        "version": __version__,
        "database": _database_status(state),
        "schema_version": SCHEMA_VERSION,
        "registries": _registry_counts(state),
        "llm": _llm_status(state),
    }
    degraded = _has_degraded(details)
    return {"status": "degraded" if degraded else "ok", **details}


def _database_status(state: RuntimeState) -> dict:
    try:
        state.sessions.list_sessions()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc) or "database unavailable"}


def _registry_counts(state: RuntimeState) -> dict:
    return {
        "agents": len(state.agents.list()),
        "capabilities": len(state.capabilities.list()),
        "commands": len(state.commands.list()),
    }


def _llm_status(state: RuntimeState) -> dict:
    try:
        capability = state.capabilities.get("llm")
        capability_config = state.capability_configs.get_config("llm")
        resolved = resolve_llm_config(
            capability_schema=capability,
            capability_config=capability_config,
            llm_profile_store=state.llm_profiles,
            provider_profile_store=state.provider_profiles,
            llm_defaults_store=state.llm_defaults,
        )
        return {"status": "ok", **public_llm_config_status(resolved)}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc) or "LLM config unavailable"}


def _has_degraded(details: dict) -> bool:
    return any(
        value.get("status") == "degraded"
        for value in details.values()
        if isinstance(value, dict)
    )
