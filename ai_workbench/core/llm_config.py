"""Resolve the one chat model using explicit Phase 1 precedence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LLMConfigError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LLMRuntimeConfig:
    values: dict[str, Any]
    sources: dict[str, str]
    metadata: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return dict(self.values)


def resolve_llm_config(
    *,
    session_llm_profile_id: str | None = None,
    llm_profile_store: Any = None,
    provider_profile_store: Any = None,
    llm_defaults_store: Any = None,
) -> LLMRuntimeConfig:
    """Resolve a profile with ``session override > global default``.

    Environment variables and extension configuration are intentionally not
    consulted.  An empty result is valid at startup; ``require_llm_model``
    turns it into a user-facing error only when a chat run is submitted.
    """

    default_id = None
    if llm_defaults_store is not None:
        defaults = llm_defaults_store.get()
        if isinstance(defaults, dict):
            default_id = defaults.get("default_model_profile_id")
    session_override = str(session_llm_profile_id or "").strip() or None
    selected = session_override or str(default_id or "").strip() or None
    source = "session_override" if session_override else "global_default"
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    metadata: dict[str, Any] = {
        "source": source if selected else "none",
        "profile_id": None,
        "profile_alias": None,
        "profile_name": None,
        "provider_profile_id": None,
        "provider_profile_name": None,
        "provider": None,
        "session_override_requested": session_llm_profile_id,
        "session_override_applied": False,
    }
    if selected:
        profile = _enabled_profile(llm_profile_store, selected)
        provider = _provider(profile, provider_profile_store)
        if provider is not None:
            values.update(
                {
                    "provider": provider.provider,
                    "base_url": provider.base_url,
                    "api_key": provider.api_key,
                    "timeout": provider.timeout_seconds,
                    "provider_profile_id": provider.id,
                    "provider_profile_name": provider.name,
                }
            )
            metadata.update(
                {
                    "provider_profile_id": provider.id,
                    "provider_profile_name": provider.name,
                    "provider": provider.provider,
                }
            )
        else:
            values.update(
                {
                    "provider": profile.provider,
                    "base_url": profile.base_url,
                    "api_key": profile.api_key,
                    "timeout": profile.timeout,
                }
            )
            metadata["provider"] = profile.provider
        for key in (
            "temperature",
            "top_p",
            "top_k",
            "max_tokens",
            "supports_vision",
            "supports_tools",
            "supports_reasoning",
            "supports_streaming",
            "supports_json_mode",
        ):
            value = getattr(profile, key, None)
            if value is not None:
                values[key] = value
        values["model"] = profile.model_id
        values["model_id"] = profile.model_id
        sources = {key: source for key in values}
        metadata.update(
            {
                "source": source,
                "profile_id": profile.id,
                "profile_alias": profile.alias,
                "profile_name": profile.name,
                "session_override_applied": bool(session_override),
            }
        )
    return LLMRuntimeConfig(values=values, sources=sources, metadata=metadata)


def _enabled_profile(store: Any, value: str) -> Any:
    if store is None:
        raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {value}")
    try:
        profile = store.get_by_id_or_alias(value)
    except KeyError as exc:
        raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {value}") from exc
    if not profile.enabled:
        raise LLMConfigError("LLM_PROFILE_DISABLED", f"LLM profile is disabled: {profile.alias}")
    if not profile.model_id:
        raise LLMConfigError(
            "LLM_PROFILE_INVALID",
            f"Model profile '{profile.alias}' must define model_id.",
        )
    return profile


def _provider(profile: Any, store: Any) -> Any | None:
    value = getattr(profile, "provider_profile_id", None)
    if not value:
        return None
    if store is None:
        raise LLMConfigError(
            "LLM_PROVIDER_PROFILE_NOT_FOUND",
            f"Provider profile not found: {value}",
        )
    try:
        provider = store.get(value)
    except KeyError as exc:
        raise LLMConfigError(
            "LLM_PROVIDER_PROFILE_NOT_FOUND",
            f"Provider profile not found: {value}",
        ) from exc
    if not provider.enabled:
        raise LLMConfigError(
            "LLM_PROVIDER_PROFILE_DISABLED",
            f"Provider profile is disabled: {provider.name}",
        )
    return provider


def require_llm_model(config: LLMRuntimeConfig) -> None:
    if not config.values.get("model"):
        raise LLMConfigError(
            "LLM_MODEL_NOT_SELECTED",
            "Select a chat model in Settings before sending a message.",
        )


def public_llm_config_status(config: LLMRuntimeConfig) -> dict[str, Any]:
    values = config.values
    metadata = config.metadata
    return {
        "source": metadata.get("source"),
        "profile_id": metadata.get("profile_id"),
        "profile_alias": metadata.get("profile_alias"),
        "profile_name": metadata.get("profile_name"),
        "provider_profile_id": metadata.get("provider_profile_id"),
        "provider_profile_name": metadata.get("provider_profile_name"),
        "provider": metadata.get("provider") or values.get("provider"),
        "base_url": values.get("base_url", ""),
        "model": values.get("model", ""),
        "model_id": values.get("model_id") or values.get("model", ""),
        "timeout": values.get("timeout"),
        "api_key_set": bool(values.get("api_key")),
        "temperature": values.get("temperature"),
        "top_p": values.get("top_p"),
        "top_k": values.get("top_k"),
        "max_tokens": values.get("max_tokens"),
        "supports_vision": bool(values.get("supports_vision", False)),
        "supports_tools": bool(values.get("supports_tools", False)),
        "supports_reasoning": bool(values.get("supports_reasoning", False)),
        "supports_streaming": bool(values.get("supports_streaming", False)),
        "supports_json_mode": bool(values.get("supports_json_mode", False)),
        "sources": dict(config.sources),
    }


__all__ = [
    "LLMConfigError",
    "LLMRuntimeConfig",
    "public_llm_config_status",
    "require_llm_model",
    "resolve_llm_config",
]
