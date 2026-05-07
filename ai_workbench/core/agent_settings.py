from pathlib import Path
from typing import Any

import yaml

from ai_workbench.core.agent_defaults import (
    DEFAULT_ALLOW_SESSION_OVERRIDE,
    DEFAULT_CONTEXT_POLICY,
    DEFAULT_MODEL_LIFECYCLE,
    DEFAULT_TIMEOUT_SECONDS,
)
from ai_workbench.core.avatar import resolve_agent_avatar
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.model_lifecycle import ModelLifecyclePolicy


DISPLAY_KEYS = {"name", "description", "avatar"}
RUNTIME_KEYS = {"llm_profile_id", "allow_session_override", "context_policy", "model_lifecycle", "timeout_seconds", "prompt"}


def normalize_display_override(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("display must be a JSON object")
    result = {}
    for key, raw in value.items():
        if key not in DISPLAY_KEYS:
            raise ValueError(f"unknown display override field: {key}")
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise ValueError(f"display.{key} must be a string")
        text = raw.strip()
        if text:
            result[key] = text
    return result


def normalize_runtime_override(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("runtime must be a JSON object")
    result: dict[str, Any] = {}
    for key, raw in value.items():
        if key not in RUNTIME_KEYS:
            raise ValueError(f"unknown runtime override field: {key}")
        if key == "llm_profile_id":
            if raw in (None, ""):
                continue
            if not isinstance(raw, str):
                raise ValueError("runtime.llm_profile_id must be a string")
            result[key] = raw.strip()
        elif key == "allow_session_override":
            if raw is None:
                continue
            if not isinstance(raw, bool):
                raise ValueError("runtime.allow_session_override must be a boolean")
            result[key] = raw
        elif key == "context_policy":
            if raw in (None, {}):
                continue
            result[key] = ContextPolicy.model_validate(raw).model_dump(exclude_none=True)
        elif key == "model_lifecycle":
            if raw in (None, {}):
                continue
            result[key] = ModelLifecyclePolicy.model_validate(raw).model_dump()
        elif key == "timeout_seconds":
            if raw in (None, ""):
                continue
            timeout = int(raw)
            if timeout < 1 or timeout > 3600:
                raise ValueError("runtime.timeout_seconds must be between 1 and 3600")
            result[key] = timeout
        elif key == "prompt":
            if raw in (None, ""):
                continue
            if not isinstance(raw, str):
                raise ValueError("runtime.prompt must be a string")
            result[key] = raw
    return result


def resolved_agent_settings(agent: AgentSchema, config: dict[str, Any] | None = None, agent_dir: Path | None = None) -> dict[str, Any]:
    config = config or {}
    display_override = normalize_display_override(config.get("display", {}))
    runtime_override = normalize_runtime_override(config.get("runtime", {}))
    display, display_sources = _resolve_display(agent, display_override, agent_dir)
    runtime, runtime_sources = _resolve_runtime(agent, runtime_override)
    sections = [{"id": "basic", "label": "Basic information"}]
    if agent.type == "prompt":
        sections.append({"id": "prompt", "label": "Prompt"})
    if "llm" in (agent.capabilities or []):
        sections.append({"id": "llm_runtime", "label": "LLM Runtime Settings", "capability_id": "llm"})
    return {
        "display": display,
        "runtime": runtime,
        "sections": sections,
        "field_sources": {**display_sources, **runtime_sources},
    }


def resolved_context_policy(agent: AgentSchema, action: Any = None, config: dict[str, Any] | None = None) -> ContextPolicy:
    if action is not None and getattr(action, "context_policy", None) is not None:
        return action.context_policy
    runtime = normalize_runtime_override((config or {}).get("runtime", {}))
    if "context_policy" in runtime:
        return ContextPolicy.model_validate(runtime["context_policy"])
    return agent.context_policy or DEFAULT_CONTEXT_POLICY


def resolved_model_lifecycle(agent: AgentSchema, config: dict[str, Any] | None = None) -> ModelLifecyclePolicy:
    runtime = normalize_runtime_override((config or {}).get("runtime", {}))
    if "model_lifecycle" in runtime:
        return ModelLifecyclePolicy.model_validate(runtime["model_lifecycle"])
    return agent.model_lifecycle or DEFAULT_MODEL_LIFECYCLE


def resolved_prompt(agent: AgentSchema, config: dict[str, Any] | None = None) -> str:
    runtime = normalize_runtime_override((config or {}).get("runtime", {}))
    if "prompt" in runtime:
        return runtime["prompt"]
    return agent.prompt or ""


def resolved_runtime_override(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return normalize_runtime_override((config or {}).get("runtime", {}))


def write_overrides_to_manifest(agent: AgentSchema, agent_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    manifest_path = agent_dir / "agent.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"agent manifest not found: {manifest_path}")
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("agent manifest must contain a YAML mapping")

    display = normalize_display_override(config.get("display", {}))
    runtime = normalize_runtime_override(config.get("runtime", {}))
    for key, value in display.items():
        if key == "name":
            raw["name"] = value
        elif key == "description":
            raw["description"] = value
        elif key == "avatar":
            raw["avatar"] = value

    if "llm_profile_id" in runtime:
        llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
        llm["profile"] = runtime["llm_profile_id"]
        raw["llm"] = llm
    if "allow_session_override" in runtime:
        llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
        llm["allow_session_override"] = runtime["allow_session_override"]
        raw["llm"] = llm
    if "context_policy" in runtime:
        raw["context_policy"] = runtime["context_policy"]
    if "model_lifecycle" in runtime:
        raw["model_lifecycle"] = runtime["model_lifecycle"]
    if "timeout_seconds" in runtime:
        raw["timeout_seconds"] = runtime["timeout_seconds"]
    if "prompt" in runtime:
        raw["prompt"] = runtime["prompt"]

    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return raw


def _resolve_display(agent: AgentSchema, override: dict[str, str], agent_dir: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    avatar = resolve_agent_avatar(agent, agent_dir)
    display = {
        "name": override.get("name") or agent.name or agent.id,
        "description": override.get("description") or agent.description or "",
        "avatar": override.get("avatar") or agent.avatar or avatar.avatar or "",
    }
    sources = {
        "display.name": "override" if "name" in override else ("manifest" if agent.name else "default"),
        "display.description": "override" if "description" in override else ("manifest" if agent.description else "default"),
        "display.avatar": "override" if "avatar" in override else ("manifest" if agent.avatar else "default"),
    }
    return display, sources


def _resolve_runtime(agent: AgentSchema, override: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    manifest_llm = agent.llm if isinstance(agent.llm, dict) else {}
    runtime: dict[str, Any] = {}
    sources: dict[str, str] = {}

    runtime["llm_profile_id"] = override.get("llm_profile_id", manifest_llm.get("profile"))
    runtime["llm_profile_key"] = runtime["llm_profile_id"]
    sources["runtime.llm_profile_id"] = "override" if "llm_profile_id" in override else ("manifest" if manifest_llm.get("profile") else "default")

    if "allow_session_override" in override:
        runtime["allow_session_override"] = override["allow_session_override"]
        sources["runtime.allow_session_override"] = "override"
    elif "allow_session_override" in manifest_llm:
        runtime["allow_session_override"] = bool(manifest_llm.get("allow_session_override"))
        sources["runtime.allow_session_override"] = "manifest"
    else:
        runtime["allow_session_override"] = DEFAULT_ALLOW_SESSION_OVERRIDE
        sources["runtime.allow_session_override"] = "default"

    if "context_policy" in override:
        context_policy = ContextPolicy.model_validate(override["context_policy"])
        sources["runtime.context_policy"] = "override"
    else:
        context_policy = agent.context_policy or DEFAULT_CONTEXT_POLICY
        sources["runtime.context_policy"] = "manifest" if agent.context_policy is not None else "default"
    runtime["context_policy"] = context_policy.model_dump(exclude_none=True)

    if "model_lifecycle" in override:
        lifecycle = ModelLifecyclePolicy.model_validate(override["model_lifecycle"])
        sources["runtime.model_lifecycle"] = "override"
    else:
        lifecycle = agent.model_lifecycle or DEFAULT_MODEL_LIFECYCLE
        sources["runtime.model_lifecycle"] = "manifest" if agent.model_lifecycle is not None else "default"
    runtime["model_lifecycle"] = lifecycle.model_dump()

    if "timeout_seconds" in override:
        runtime["timeout_seconds"] = override["timeout_seconds"]
        sources["runtime.timeout_seconds"] = "override"
    elif getattr(agent, "timeout_seconds", None) is not None:
        runtime["timeout_seconds"] = agent.timeout_seconds
        sources["runtime.timeout_seconds"] = "manifest"
    else:
        runtime["timeout_seconds"] = DEFAULT_TIMEOUT_SECONDS
        sources["runtime.timeout_seconds"] = "default"
    if "prompt" in override:
        runtime["prompt"] = override["prompt"]
        sources["runtime.prompt"] = "override"
    else:
        runtime["prompt"] = agent.prompt or ""
        sources["runtime.prompt"] = "manifest" if agent.prompt else "default"
    return runtime, sources
