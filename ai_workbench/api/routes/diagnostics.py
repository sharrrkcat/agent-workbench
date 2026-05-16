from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends

from ai_workbench import __version__
from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.attachments import attachments_root
from ai_workbench.core.config_schema import resolve_config
from ai_workbench.core.llm_config import public_llm_config_status, resolve_llm_config
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.storage_maintenance import storage_stats
from ai_workbench.core.time import ensure_utc, utc_now
from ai_workbench.db.database import SCHEMA_VERSION


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("")
def get_diagnostics(state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    warnings: list[str] = []

    def section(name: str, fallback: dict[str, Any], fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except Exception as exc:
            warnings.append(f"{name} diagnostics unavailable: {_safe_message(exc)}")
            return {**fallback, "status": "degraded"}

    payload = {
        "backend": section("backend", {"status": "degraded"}, lambda: _backend(state)),
        "database": section("database", {"status": "degraded", "schema_version": SCHEMA_VERSION}, lambda: _database(state)),
        "attachments": section("attachments", {"status": "degraded", "writable": False}, lambda: _attachments(state)),
        "event_bus": section("event_bus", {"status": "degraded", "subscriber_count": 0}, lambda: _event_bus(state)),
        "runs": section("runs", {"active_count": 0, "active_task_count": 0, "recent_failed_count": 0, "recent_failures": []}, lambda: _runs(state)),
        "llm": section("llm", {"status": "degraded", "profiles_total": 0, "profiles_enabled": 0, "default_resolved": None}, lambda: _llm(state)),
        "capabilities": section("capabilities", {"file": {"enabled": False, "status": "degraded"}, "http": {"enabled": False, "status": "degraded"}}, lambda: _capabilities(state)),
    }

    for warning in _collect_section_warnings(payload):
        warnings.append(warning)
    payload["warnings"] = warnings
    if warnings and payload["backend"].get("status") == "ok":
        payload["backend"]["status"] = "degraded"
    return payload


def _backend(state: RuntimeState) -> dict[str, Any]:
    started_at = ensure_utc(getattr(state, "started_at", utc_now())) or utc_now()
    return {
        "status": "ok",
        "version": __version__,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "uptime_seconds": max(0, int((utc_now() - started_at).total_seconds())),
    }


def _database(state: RuntimeState) -> dict[str, Any]:
    stats = storage_stats(state.messages, database_url=state.database_url)
    database = dict(stats["database"])
    try:
        state.sessions.list_sessions()
    except Exception as exc:
        database["status"] = "degraded"
        database["warning"] = _safe_message(exc)
    if database.get("status") == "warning":
        database["status"] = "degraded"
    return database


def _attachments(state: RuntimeState) -> dict[str, Any]:
    stats = storage_stats(state.messages, database_url=state.database_url)
    attachments = dict(stats["attachments"])
    root = attachments_root()
    exists = root.exists()
    writable = exists and os.access(root, os.W_OK)
    status = "ok" if exists and writable else "degraded"
    return {
        "status": status,
        "directory": str(root),
        "count": attachments.get("count", 0),
        "total_size_bytes": attachments.get("total_size_bytes", 0),
        "writable": writable,
        **({"warning": "Attachment directory is unavailable or not writable."} if status != "ok" else {}),
    }


def _event_bus(state: RuntimeState) -> dict[str, Any]:
    return {
        "status": "ok",
        "subscriber_count": state.events.subscriber_count(),
        "active_websocket_connections": getattr(state, "active_websockets", 0),
    }


def _runs(state: RuntimeState) -> dict[str, Any]:
    runs = list(state.runs.list_all_runs())
    active_statuses = {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_USER}
    failed = [run for run in runs if run.status == RunStatus.FAILED]
    recent = sorted(failed, key=lambda run: run.created_at, reverse=True)[:5]
    return {
        "active_count": sum(1 for run in runs if run.status in active_statuses),
        "active_task_count": state.active_runs.active_count(),
        "recent_failed_count": len(failed),
        "recent_failures": [
            {
                "run_id": run.run_id,
                "session_id": run.session_id,
                "agent_id": run.target_id if run.kind == "agent" else None,
                "command_name": run.target_id if run.kind == "command" else None,
                "error_code": _error_code(run),
                "message": _truncate(_safe_message(run.error or ""), 300),
                "created_at": run.created_at.isoformat(),
            }
            for run in recent
        ],
    }


def _llm(state: RuntimeState) -> dict[str, Any]:
    profiles = list(state.llm_profiles.list()) if state.llm_profiles is not None else []
    capability = state.capabilities.get("llm")
    capability_config = state.capability_configs.get_config("llm")
    resolved_status = "ok"
    last_error = None
    try:
        resolved = public_llm_config_status(
            resolve_llm_config(
                capability_schema=capability,
                capability_config=capability_config,
                llm_profile_store=state.llm_profiles,
                provider_profile_store=state.provider_profiles,
                llm_defaults_store=state.llm_defaults,
            )
        )
        default_resolved = {
            "profile": resolved.get("profile_alias") or resolved.get("profile_id"),
            "model_id": resolved.get("model_id") or resolved.get("model"),
            "base_url": resolved.get("base_url", ""),
            "api_key_set": bool(resolved.get("api_key_set")),
        }
    except Exception as exc:
        resolved_status = "degraded"
        last_error = _safe_message(exc)
        default_resolved = None
    return {
        "status": resolved_status,
        "profiles_total": len(profiles),
        "profiles_enabled": sum(1 for profile in profiles if profile.enabled),
        "provider_profiles_total": len(state.provider_profiles.list()) if state.provider_profiles is not None else 0,
        "global_fallback_enabled": bool(capability_config.get("enabled", True)),
        "default_resolved": default_resolved,
        "last_error": last_error,
    }


def _capabilities(state: RuntimeState) -> dict[str, Any]:
    return {
        "file": _file_capability(state),
        "http": _http_capability(state),
    }


def _file_capability(state: RuntimeState) -> dict[str, Any]:
    import capabilities.file as file_runtime

    stored = state.capability_configs.get_config("file")
    capability = state.capabilities.get("file")
    resolved = resolve_config(capability.config_schema, stored.get("user_config") or {})
    allowed_dirs = file_runtime._allowed_dirs(resolved)
    status = "ok" if allowed_dirs else "degraded"
    return {
        "enabled": bool(stored.get("enabled", True)),
        "status": status,
        "allowed_directories_count": len(allowed_dirs),
        "max_local_text_read_size_mb": resolved.get("max_local_text_read_size_mb"),
        "max_local_image_read_size_mb": resolved.get("max_local_image_read_size_mb"),
        "max_local_audio_read_size_mb": resolved.get("max_local_audio_read_size_mb"),
        "read_file_enabled": bool(resolved.get("enable_read_file", True)),
        "read_image_enabled": bool(resolved.get("enable_read_image", True)),
        "read_audio_enabled": bool(resolved.get("enable_read_audio_command", True)),
        **({"warning": "No allowed directories are configured."} if not allowed_dirs else {}),
    }


def _http_capability(state: RuntimeState) -> dict[str, Any]:
    stored = state.capability_configs.get_config("http")
    capability = state.capabilities.get("http")
    resolved = resolve_config(capability.config_schema, stored.get("user_config") or {})
    return {
        "enabled": bool(stored.get("enabled", True)),
        "status": "ok",
        "http_get_enabled": bool(resolved.get("enable_http_get", True)),
        "fetch_image_enabled": bool(resolved.get("enable_fetch_image", True)),
        "timeout_seconds": resolved.get("timeout_seconds"),
        "max_text_response_size_mb": resolved.get("max_text_response_size_mb"),
        "max_image_response_size_mb": resolved.get("max_image_response_size_mb"),
        "allow_redirects": bool(resolved.get("allow_redirects", True)),
    }


def _collect_section_warnings(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for value in payload.values():
        if isinstance(value, dict):
            warning = value.get("warning")
            if isinstance(warning, str):
                warnings.append(warning)
    return warnings


def _error_code(run) -> str:
    metadata = run.metadata or {}
    code = metadata.get("error_code")
    return str(code) if code else "RUN_FAILED"


def _safe_message(value: Any) -> str:
    message = str(value or "unavailable").splitlines()[0]
    return _truncate(message, 300)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return f"{value[: limit - 3]}..."
