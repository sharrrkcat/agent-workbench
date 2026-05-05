import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ai_workbench.core.config_schema import MASKED_SECRET, ConfigFieldSchema, resolve_config


class LLMConfigError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LLMRuntimeConfig:
    values: Dict[str, Any]
    sources: Dict[str, str]

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
    env: Optional[Dict[str, str]] = None,
) -> LLMRuntimeConfig:
    schema_fields = _llm_config_schema(capability_schema)
    persisted = (capability_config or {}).get("user_config", capability_config or {})
    if not isinstance(persisted, dict):
        raise LLMConfigError("LLM_CONFIG_INVALID", "LLM capability config must be a JSON object.")
    persisted = {key: value for key, value in persisted.items() if value != MASKED_SECRET}

    try:
        resolved = resolve_config(schema_fields, persisted)
    except Exception as exc:
        raise LLMConfigError("LLM_CONFIG_INVALID", str(exc) or "LLM config is invalid.") from exc

    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    for key, value in resolved.items():
        if value not in (None, ""):
            values[key] = value
            sources[key] = "capability_config" if key in persisted else "capability_default"

    agent_model = getattr(agent_schema, "model", None) if agent_schema is not None else None
    if isinstance(agent_model, dict):
        for key in ("provider", "base_url", "api_key", "model", "timeout"):
            value = agent_model.get(key)
            if value not in (None, ""):
                values[key] = value
                sources[key] = "agent_manifest"

    env_source = env if env is not None else os.environ
    for key, env_name in ENV_FIELDS.items():
        value = env_source.get(env_name)
        if value not in (None, ""):
            values[key] = _coerce_env_value(key, value)
            sources[key] = "env"

    return LLMRuntimeConfig(values=values, sources=sources)


def require_llm_model(config: LLMRuntimeConfig) -> None:
    if not config.values.get("model"):
        raise LLMConfigError(
            "LLM_MODEL_NOT_SELECTED",
            "LLM model is not selected. Configure a model in Settings or AGENT_WORKBENCH_LLM_MODEL.",
        )


def public_llm_config_status(config: LLMRuntimeConfig) -> Dict[str, Any]:
    return {
        "base_url": config.values.get("base_url", ""),
        "model": config.values.get("model", ""),
        "timeout": config.values.get("timeout", None),
        "api_key_set": bool(config.values.get("api_key")),
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
        ConfigFieldSchema(name="timeout", type="float", label="Timeout", default=60),
    ]


def _coerce_env_value(key: str, value: str) -> Any:
    if key == "timeout":
        try:
            return float(value)
        except ValueError as exc:
            raise LLMConfigError("LLM_CONFIG_INVALID", "AGENT_WORKBENCH_LLM_TIMEOUT must be a number.") from exc
    return value
