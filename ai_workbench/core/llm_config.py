import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ai_workbench.core.config_schema import MASKED_SECRET, ConfigFieldSchema, validate_user_config


class LLMConfigError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LLMRuntimeConfig:
    values: Dict[str, Any]
    sources: Dict[str, str]
    metadata: Dict[str, Any]

    def model_dump(self) -> Dict[str, Any]:
        return dict(self.values)


ENV_FIELDS = {
    "base_url": "AGENT_WORKBENCH_LLM_BASE_URL",
    "api_key": "AGENT_WORKBENCH_LLM_API_KEY",
    "model": "AGENT_WORKBENCH_LLM_MODEL",
    "timeout": "AGENT_WORKBENCH_LLM_TIMEOUT",
}


def resolve_llm_config(
    agent_schema: Any = None,
    action_schema: Any = None,
    capability_schema: Any = None,
    capability_config: Optional[Dict[str, Any]] = None,
    llm_profile_store: Any = None,
    session_llm_profile_id: Optional[str] = None,
    explicit_override: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, str]] = None,
) -> LLMRuntimeConfig:
    schema_fields = _llm_config_schema(capability_schema)
    persisted = (capability_config or {}).get("user_config", capability_config or {})
    if not isinstance(persisted, dict):
        raise LLMConfigError("LLM_CONFIG_INVALID", "LLM capability config must be a JSON object.")
    persisted = {key: value for key, value in persisted.items() if value != MASKED_SECRET}
    capability_default_profile = persisted.get("default_profile")

    try:
        validate_user_config(schema_fields, persisted)
    except Exception as exc:
        raise LLMConfigError("LLM_CONFIG_INVALID", str(exc) or "LLM config is invalid.") from exc

    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    metadata: Dict[str, Any] = {
        "source": "manifest_default",
        "profile_id": None,
        "profile_alias": None,
        "profile_key": None,
        "profile_name": None,
        "provider": None,
        "session_override_requested": session_llm_profile_id,
        "session_override_applied": False,
        "allow_session_override": True,
    }

    for field in schema_fields:
        if field.default not in (None, ""):
            _set_value(values, sources, field.name, field.default, "manifest_default")

    env_source = env if env is not None else os.environ
    for key, env_name in ENV_FIELDS.items():
        value = env_source.get(env_name)
        if value not in (None, ""):
            _set_value(values, sources, key, _coerce_env_value(key, value), "env")
            metadata["source"] = "env"

    for key, value in persisted.items():
        if key == "default_profile":
            continue
        if value not in (None, ""):
            _set_value(values, sources, key, value, "llm_capability_config")
            metadata["source"] = "llm_capability_config"

    if capability_default_profile:
        profile = _get_enabled_profile(llm_profile_store, str(capability_default_profile))
        _apply_profile(values, sources, metadata, profile, "llm_capability_config")

    agent_model = getattr(agent_schema, "model", None) if agent_schema is not None else None
    if isinstance(agent_model, dict):
        for key in ("provider", "base_url", "api_key", "model", "model_id", "timeout"):
            value = agent_model.get(key)
            if value not in (None, ""):
                _set_value(values, sources, key, value, "agent_legacy_model")
                metadata["source"] = "agent_legacy_model"

    llm_config = _merged_agent_action_llm(agent_schema, action_schema)
    if llm_config:
        metadata["allow_session_override"] = bool(llm_config.get("allow_session_override", True))

    profile_ref = llm_config.get("profile") if llm_config else None
    if profile_ref:
        profile = _get_enabled_profile(llm_profile_store, str(profile_ref))
        _apply_profile(values, sources, metadata, profile, "agent_llm_profile")

    if session_llm_profile_id and metadata["allow_session_override"]:
        profile = _get_enabled_profile(llm_profile_store, str(session_llm_profile_id))
        _apply_profile(values, sources, metadata, profile, "session_override")
        metadata["session_override_applied"] = True

    if llm_config:
        for key in ("temperature", "top_p", "top_k", "max_tokens"):
            value = llm_config.get(key)
            if value is not None:
                _set_value(values, sources, key, value, metadata["source"] or "agent_llm_profile")

    if explicit_override:
        for key, value in explicit_override.items():
            if value not in (None, ""):
                _set_value(values, sources, key, value, "explicit_override")
                metadata["source"] = "explicit_override"

    _sync_model_alias(values, sources)
    if values.get("provider"):
        metadata["provider"] = values.get("provider")
    return LLMRuntimeConfig(values=values, sources=sources, metadata=metadata)


def _get_enabled_profile(llm_profile_store: Any, profile_ref: str):
    if llm_profile_store is None:
        raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {profile_ref}")
    try:
        profile = llm_profile_store.get_by_id_or_alias(profile_ref)
    except KeyError as exc:
        raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {profile_ref}") from exc
    if not profile.enabled:
        raise LLMConfigError("LLM_PROFILE_DISABLED", f"LLM profile is disabled: {profile.alias}")
    if not profile.base_url or not profile.model_id:
        raise LLMConfigError(
            "LLM_PROFILE_INVALID",
            f"LLM profile '{profile.alias}' must define base_url and model_id.",
        )
    return profile


def _apply_profile(values: Dict[str, Any], sources: Dict[str, str], metadata: Dict[str, Any], profile, source: str) -> None:
    profile_values = profile.model_dump()
    for key in (
        "provider",
        "base_url",
        "api_key",
        "model_id",
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "timeout",
        "supports_vision",
        "supports_tools",
        "supports_reasoning",
        "supports_streaming",
        "supports_json_mode",
    ):
        value = profile_values.get(key)
        if value is not None:
            _set_value(values, sources, key, value, source)
    _set_value(values, sources, "model", profile.model_id, source)
    metadata.update(
        {
            "source": source,
            "profile_id": profile.id,
            "profile_alias": profile.alias,
            "profile_key": profile.alias,
            "profile_name": profile.name,
            "provider": profile.provider,
        }
    )


def _set_value(values: Dict[str, Any], sources: Dict[str, str], key: str, value: Any, source: str) -> None:
    normalized_key = "model" if key == "model_id" else key
    if key == "model_id":
        values["model_id"] = value
        sources["model_id"] = source
    values[normalized_key] = value
    sources[normalized_key] = source


def _sync_model_alias(values: Dict[str, Any], sources: Dict[str, str]) -> None:
    if values.get("model") and not values.get("model_id"):
        values["model_id"] = values["model"]
        sources["model_id"] = sources.get("model", "")
    if values.get("model_id") and not values.get("model"):
        values["model"] = values["model_id"]
        sources["model"] = sources.get("model_id", "")


def _merged_agent_action_llm(agent_schema: Any = None, action_schema: Any = None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    agent_llm = getattr(agent_schema, "llm", None) if agent_schema is not None else None
    action_llm = getattr(action_schema, "llm", None) if action_schema is not None else None
    if isinstance(agent_llm, dict):
        merged.update(agent_llm)
    if isinstance(action_llm, dict):
        merged.update(action_llm)
    if merged and "allow_session_override" not in merged:
        merged["allow_session_override"] = True
    return merged


def require_llm_model(config: LLMRuntimeConfig) -> None:
    if not config.values.get("model"):
        raise LLMConfigError(
            "LLM_MODEL_NOT_SELECTED",
            "LLM model is not selected. Configure a model in Settings or AGENT_WORKBENCH_LLM_MODEL.",
        )


def public_llm_config_status(config: LLMRuntimeConfig) -> Dict[str, Any]:
    return {
        "source": config.metadata.get("source"),
        "profile_id": config.metadata.get("profile_id"),
        "profile_alias": config.metadata.get("profile_alias"),
        "profile_key": config.metadata.get("profile_key") or config.metadata.get("profile_alias"),
        "profile_name": config.metadata.get("profile_name"),
        "provider": config.metadata.get("provider") or config.values.get("provider"),
        "base_url": config.values.get("base_url", ""),
        "model": config.values.get("model", ""),
        "model_id": config.values.get("model_id") or config.values.get("model", ""),
        "timeout": config.values.get("timeout", None),
        "api_key_set": bool(config.values.get("api_key")),
        "temperature": config.values.get("temperature", None),
        "top_p": config.values.get("top_p", None),
        "top_k": config.values.get("top_k", None),
        "max_tokens": config.values.get("max_tokens", None),
        "supports_vision": bool(config.values.get("supports_vision", False)),
        "supports_tools": bool(config.values.get("supports_tools", False)),
        "supports_reasoning": bool(config.values.get("supports_reasoning", False)),
        "supports_streaming": bool(config.values.get("supports_streaming", False)),
        "supports_json_mode": bool(config.values.get("supports_json_mode", False)),
        "allow_session_override": bool(config.metadata.get("allow_session_override", True)),
        "sources": dict(config.sources),
    }


def _llm_config_schema(capability_schema: Any = None) -> list[ConfigFieldSchema]:
    fields = getattr(capability_schema, "config_schema", None)
    if fields is not None:
        return fields
    return [
        ConfigFieldSchema(name="base_url", type="string", label="Base URL", default="http://localhost:1234/v1"),
        ConfigFieldSchema(name="api_key", type="string", label="API key", secret=True),
        ConfigFieldSchema(name="model", type="string", label="Model"),
        ConfigFieldSchema(name="default_profile", type="string", label="Default profile"),
        ConfigFieldSchema(name="timeout", type="float", label="Timeout", default=60),
    ]


def _coerce_env_value(key: str, value: str) -> Any:
    if key == "timeout":
        try:
            return float(value)
        except ValueError as exc:
            raise LLMConfigError("LLM_CONFIG_INVALID", "AGENT_WORKBENCH_LLM_TIMEOUT must be a number.") from exc
    return value
