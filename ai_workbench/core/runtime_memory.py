from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ai_workbench.core.llm_config import LLMConfigError, resolve_llm_config
from ai_workbench.core.provider_status import (
    MODEL_NOT_LOADED,
    PROVIDER_UNREACHABLE,
    READY,
    MODEL_STATUS_UNKNOWN,
    refresh_provider_status_for_profile,
    unload_model_for_profile,
)


RuntimeMemoryTarget = Literal["llm", "comfyui", "embedding", "reranker", "all"]
TARGETS: tuple[str, ...] = ("llm", "comfyui", "embedding", "reranker")
VALID_TARGETS = (*TARGETS, "all")


@dataclass
class RuntimeMemoryService:
    agents: Any
    runtimes: Any
    sessions: Any
    runs: Any
    agent_configs: Any
    capability_configs: Any
    capabilities: Any
    llm_profiles: Any
    provider_profiles: Any
    llm_defaults: Any
    knowledge_model_backend: Any
    agent_runner: Any = None

    def memory_summary(self, session_id: str | None = None) -> dict[str, Any]:
        return {"targets": [self._target_summary(target, session_id=session_id) for target in TARGETS]}

    def free_memory(self, targets: list[str], context: dict[str, Any] | None = None) -> dict[str, Any]:
        expanded = expand_targets(targets)
        session_id = str((context or {}).get("session_id") or "")
        return {"results": [self._free_target(target, session_id=session_id) for target in expanded]}

    def _target_summary(self, target: str, session_id: str | None = None) -> dict[str, Any]:
        if target == "llm":
            return self._llm_summary(session_id=session_id)
        if target == "comfyui":
            return self._comfyui_summary()
        if target == "embedding":
            return self._knowledge_summary("embedding")
        if target == "reranker":
            return self._knowledge_summary("reranker")
        return _summary(target, False, False, "unsupported target", "unavailable")

    def _free_target(self, target: str, session_id: str = "") -> dict[str, str]:
        try:
            if target == "llm":
                return self._free_llm(session_id=session_id)
            if target == "comfyui":
                return self._free_comfyui()
            if target == "embedding":
                return self._free_embedding()
            if target == "reranker":
                return self._free_reranker()
            return _result(target, "unavailable", "Unsupported target.")
        except Exception as exc:
            return _result(target, "failed", str(exc) or "Memory release failed.")

    def _llm_summary(self, session_id: str | None = None) -> dict[str, Any]:
        target = self._resolve_llm_target(session_id=session_id)
        if target.get("error"):
            return _summary("llm", False, False, str(target["error"]), "unavailable")
        if target.get("provider") not in {"lm_studio", "internal_transformers", "internal_llama_cpp"}:
            return _summary("llm", False, False, "Current provider is not LM Studio.", "unavailable")
        provider_profile_id = str(target.get("provider_profile_id") or "")
        model_id = str(target.get("model_id") or "")
        if self._llm_busy(provider_profile_id, model_id):
            return _summary("llm", True, False, "LLM is busy.", "busy")
        try:
            status = refresh_provider_status_for_profile(self.provider_profiles, self.llm_profiles, provider_profile_id)
        except Exception:
            return _summary("llm", True, False, "Not connected.", "unavailable")
        if not status.get("reachable"):
            return _summary("llm", True, False, "Not connected.", "unavailable")
        model_status = _matching_model_status(status, model_id)
        if model_status == MODEL_NOT_LOADED:
            return _summary("llm", True, True, "No model loaded.", "not_loaded")
        if model_status == READY:
            return _summary("llm", True, True, "", "loaded")
        if target.get("provider") in {"internal_transformers", "internal_llama_cpp"} and model_status == MODEL_STATUS_UNKNOWN:
            return _summary("llm", True, True, "", "unknown")
        return _summary("llm", True, True, "", "unknown")

    def _free_llm(self, session_id: str = "") -> dict[str, str]:
        summary = self._llm_summary(session_id=session_id)
        if summary["status"] == "busy":
            return _result("llm", "busy", "LLM is busy.")
        if not summary["available"]:
            return _result("llm", "unavailable", summary.get("reason") or "LLM unload is unavailable.")
        target = self._resolve_llm_target(session_id=session_id)
        result = unload_model_for_profile(
            provider_profile_store=self.provider_profiles,
            llm_profile_store=self.llm_profiles,
            provider_profile_id=str(target.get("provider_profile_id") or ""),
            model_profile_id=str(target.get("model_profile_id") or ""),
            model_id=str(target.get("model_id") or ""),
            reason="manual_free_memory",
        )
        self._refresh_llm_after_free(result, session_id=session_id)
        if result.get("ok") and result.get("unloaded"):
            return _result("llm", "freed", "Freed.")
        if result.get("ok"):
            return _result("llm", "skipped", "No model loaded.")
        return _result("llm", "failed", _first_error(result) or "LLM unload failed.")

    def _comfyui_summary(self) -> dict[str, Any]:
        if not self._capability_enabled("comfyui"):
            return _summary("comfyui", False, False, "ComfyUI is disabled.", "unavailable")
        try:
            runtime = self.runtimes.get_runtime("comfyui")
        except KeyError:
            return _summary("comfyui", False, False, "ComfyUI is unavailable.", "unavailable")
        context = self._capability_context("comfyui")
        try:
            queue = runtime.get_queue(context=context)
        except Exception:
            return _summary("comfyui", True, False, "Not connected.", "unavailable")
        running_count = int((queue.get("summary") or {}).get("running_count") or 0)
        if running_count > 0:
            return _summary("comfyui", True, False, "ComfyUI is busy.", "busy")
        return _summary("comfyui", True, True, "", "unknown")

    def _free_comfyui(self) -> dict[str, str]:
        summary = self._comfyui_summary()
        if summary["status"] == "busy":
            return _result("comfyui", "busy", "ComfyUI is busy.")
        if not summary["available"]:
            return _result("comfyui", "unavailable", summary.get("reason") or "ComfyUI is unavailable.")
        runtime = self.runtimes.get_runtime("comfyui")
        result = runtime.free_memory(unload_models=True, free_memory=True, context=self._capability_context("comfyui"))
        if result.get("ok"):
            return _result("comfyui", "freed", "Freed.")
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        return _result("comfyui", "failed", str(error.get("message") or "ComfyUI memory release failed."))

    def _knowledge_summary(self, target: str) -> dict[str, Any]:
        backend = self.knowledge_model_backend
        if backend is None:
            return _summary(target, False, False, "Knowledge local model backend is unavailable.", "unavailable")
        busy_method = getattr(backend, f"{target}_busy", None)
        if callable(busy_method) and busy_method():
            return _summary(target, True, False, f"{target.title()} is busy.", "busy")
        count = self._cache_count(target)
        if count <= 0:
            return _summary(target, True, True, "No model loaded.", "not_loaded")
        return _summary(target, True, True, "", "loaded")

    def _free_embedding(self) -> dict[str, str]:
        summary = self._knowledge_summary("embedding")
        if summary["status"] == "busy":
            return _result("embedding", "busy", "Embedding is busy.")
        unload = getattr(self.knowledge_model_backend, "unload_all_embedding_models", None)
        if not callable(unload):
            return _result("embedding", "unavailable", "Embedding unload is unavailable.")
        removed = int(unload())
        if removed:
            return _result("embedding", "freed", "Freed.")
        return _result("embedding", "skipped", "No model loaded.")

    def _free_reranker(self) -> dict[str, str]:
        summary = self._knowledge_summary("reranker")
        if summary["status"] == "busy":
            return _result("reranker", "busy", "Reranker is busy.")
        unload = getattr(self.knowledge_model_backend, "unload_all_reranker_models", None)
        if not callable(unload):
            return _result("reranker", "unavailable", "Reranker unload is unavailable.")
        removed = int(unload())
        if removed:
            return _result("reranker", "freed", "Freed.")
        return _result("reranker", "skipped", "No model loaded.")

    def _resolve_llm_target(self, session_id: str | None = None) -> dict[str, Any]:
        session = None
        agent = None
        action = None
        agent_runtime = None
        if session_id and self.sessions is not None:
            try:
                session = self.sessions.get_session(session_id)
                agent = self.agents.get(session.default_agent_id)
                action = next((item for item in agent.actions if item.id == "default"), None)
                if self.agent_configs is not None:
                    agent_runtime = self.agent_configs.get_config(agent.id).get("runtime") or {}
            except Exception:
                session = None
                agent = None
                action = None
        try:
            llm_capability = self.capabilities.get("llm") if self.capabilities is not None else None
            llm_config = self.capability_configs.get_config("llm") if self.capability_configs is not None else {}
            config = resolve_llm_config(
                agent_schema=agent,
                action_schema=action,
                capability_schema=llm_capability,
                capability_config=llm_config,
                llm_profile_store=self.llm_profiles,
                provider_profile_store=self.provider_profiles,
                llm_defaults_store=self.llm_defaults,
                session_llm_profile_id=getattr(session, "llm_profile_id", None),
                agent_runtime=agent_runtime,
            )
        except LLMConfigError as exc:
            return {"error": exc.message}
        except Exception as exc:
            return {"error": str(exc) or "LLM configuration could not be resolved."}
        return {
            "provider": config.metadata.get("provider") or config.values.get("provider"),
            "provider_profile_id": config.metadata.get("provider_profile_id") or "",
            "provider_profile_name": config.metadata.get("provider_profile_name") or "",
            "model_profile_id": config.metadata.get("profile_id") or "",
            "model_profile_name": config.metadata.get("profile_name") or "",
            "model_id": config.values.get("model_id") or config.values.get("model") or "",
        }

    def _llm_busy(self, provider_profile_id: str, model_id: str) -> bool:
        active = getattr(self.agent_runner, "active_llm_uses", None)
        if active is None:
            return False
        return bool(active.active_count(provider_profile_id, model_id))

    def _refresh_llm_after_free(self, result: dict[str, Any], session_id: str = "") -> None:
        provider_profile_id = str(result.get("provider_profile_id") or "")
        if not provider_profile_id:
            return
        try:
            status = refresh_provider_status_for_profile(self.provider_profiles, self.llm_profiles, provider_profile_id)
            events = getattr(self.agent_runner, "event_bus", None)
            if events is not None:
                events.emit("llm_provider_status_updated", session_id=session_id or "", run_id=None, payload={"provider": status})
        except Exception:
            return

    def _cache_count(self, target: str) -> int:
        cache_name = "_embedding_cache" if target == "embedding" else "_reranker_cache"
        cache = getattr(self.knowledge_model_backend, cache_name, None)
        return len(cache) if isinstance(cache, dict) else 0

    def _capability_enabled(self, capability_id: str) -> bool:
        try:
            return bool(self.capability_configs.is_enabled(capability_id))
        except Exception:
            return True

    def _capability_context(self, capability_id: str) -> dict[str, Any]:
        capability_config = {}
        config_schema = []
        if self.capability_configs is not None and self.capabilities is not None:
            try:
                capability = self.capabilities.get(capability_id)
                stored = self.capability_configs.get_config(capability_id)
                config_schema = capability.config_schema
                capability_config = stored.get("user_config") or {}
            except Exception:
                capability_config = {}
                config_schema = []
        return {
            "capability_id": capability_id,
            "capability_config": capability_config,
            "capability_config_store": self.capability_configs,
            "config_schema": config_schema,
        }


def expand_targets(targets: list[str]) -> list[str]:
    normalized = [str(target or "").strip().lower() for target in targets]
    invalid = [target for target in normalized if target not in VALID_TARGETS]
    if invalid:
        raise ValueError(f"Invalid memory target: {invalid[0]}")
    if not normalized:
        raise ValueError("Memory target is required.")
    if "all" in normalized:
        return list(TARGETS)
    result: list[str] = []
    for target in normalized:
        if target not in result:
            result.append(target)
    return result


def format_memory_result(payload: dict[str, Any]) -> str:
    rows = payload.get("results") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    lines = ["Memory release result", ""]
    for item in rows:
        if not isinstance(item, dict):
            continue
        label = _target_label(str(item.get("target") or ""))
        status = str(item.get("status") or "")
        message = str(item.get("message") or "")
        lines.append(f"{label}: {status}{' · ' + message if message else ''}")
    return "\n".join(lines).rstrip()


def _summary(target: str, available: bool, enabled: bool, reason: str, status: str) -> dict[str, Any]:
    return {"target": target, "available": available, "enabled": enabled, "reason": reason, "status": status}


def _result(target: str, status: str, message: str = "") -> dict[str, str]:
    return {"target": target, "status": status, "message": message}


def _matching_model_status(status: dict[str, Any], model_id: str) -> str:
    for model in status.get("models") or []:
        if isinstance(model, dict) and str(model.get("id") or "") == model_id:
            return str(model.get("status") or "")
    if status.get("status") == PROVIDER_UNREACHABLE:
        return PROVIDER_UNREACHABLE
    return str(status.get("status") or "")


def _first_error(result: dict[str, Any]) -> str:
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("code") or "")
    return ""


def _target_label(target: str) -> str:
    return {"llm": "LLM", "comfyui": "ComfyUI", "embedding": "Embedding", "reranker": "Reranker"}.get(target, target)
