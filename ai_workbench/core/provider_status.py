from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.time import isoformat_utc, utc_now


READY = "READY"
PROVIDER_UNREACHABLE = "PROVIDER_UNREACHABLE"
MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
MODEL_NOT_LOADED = "MODEL_NOT_LOADED"
MODEL_MISMATCH = "MODEL_MISMATCH"
MODEL_STATUS_UNKNOWN = "MODEL_STATUS_UNKNOWN"
UNSUPPORTED = "UNSUPPORTED"
UNLOADING = "UNLOADING"
UNLOAD_FAILED = "MODEL_UNLOAD_FAILED"
MODEL_UNLOAD_UNSUPPORTED = "MODEL_UNLOAD_UNSUPPORTED"


class ProviderStatusError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def refresh_provider_statuses(
    provider_profiles: Iterable[ProviderProfileSchema],
    model_profiles: Iterable[LLMProfileSchema],
    provider_profile_ids: Optional[Iterable[str]] = None,
    force: bool = True,
) -> Dict[str, Any]:
    del force
    requested_ids = set(provider_profile_ids or [])
    providers = list(provider_profiles)
    if requested_ids:
        known_ids = {provider.id for provider in providers}
        missing = sorted(requested_ids - known_ids)
        if missing:
            raise ProviderStatusError(
                "LLM_PROVIDER_PROFILE_NOT_FOUND",
                f"Provider profile not found: {missing[0]}",
                {"provider_profile_id": missing[0]},
            )
        providers = [provider for provider in providers if provider.id in requested_ids]
    else:
        providers = [provider for provider in providers if provider.enabled]

    model_profiles_by_provider: Dict[str, List[LLMProfileSchema]] = {}
    for profile in model_profiles:
        if profile.provider_profile_id:
            model_profiles_by_provider.setdefault(profile.provider_profile_id, []).append(profile)

    return {
        "providers": [
            refresh_provider_status(provider, model_profiles_by_provider.get(provider.id, []))
            for provider in dedupe_providers(providers)
        ]
    }


def refresh_provider_status_for_profile(provider_profile_store: Any, llm_profile_store: Any, provider_profile_id: str) -> Dict[str, Any]:
    provider = provider_profile_store.get(provider_profile_id)
    profiles = [item for item in llm_profile_store.list() if item.provider_profile_id == provider.id]
    return refresh_provider_status(provider, profiles)


def refresh_provider_status(provider: ProviderProfileSchema, model_profiles: Iterable[LLMProfileSchema]) -> Dict[str, Any]:
    checked_at = isoformat_utc(utc_now())
    if not provider.enabled:
        return _provider_payload(
            provider=provider,
            reachable=False,
            status=PROVIDER_UNREACHABLE,
            mode="disabled",
            checked_at=checked_at,
            models=[],
            warnings=["Provider profile is disabled."],
            error={"code": "LLM_PROVIDER_PROFILE_DISABLED", "message": f"Provider profile is disabled: {provider.name}"},
        )

    model_profiles = list(model_profiles)
    try:
        if provider.provider == "lm_studio":
            return _refresh_lm_studio(provider, model_profiles, checked_at)
        if provider.provider == "llama_cpp":
            return _refresh_llama_cpp(provider, model_profiles, checked_at)
        if provider.provider == "openai_compatible":
            return _refresh_openai_compatible(provider, model_profiles, checked_at)
        return _provider_payload(
            provider=provider,
            reachable=False,
            status=UNSUPPORTED,
            mode=provider.provider or "custom",
            checked_at=checked_at,
            models=_unknown_model_statuses(model_profiles),
            warnings=[f"Provider status is unsupported for provider: {provider.provider}"],
        )
    except httpx.HTTPError as exc:
        return _provider_payload(
            provider=provider,
            reachable=False,
            status=PROVIDER_UNREACHABLE,
            mode=provider.provider,
            checked_at=checked_at,
            models=_unknown_model_statuses(model_profiles),
            warnings=[],
            error={"code": PROVIDER_UNREACHABLE, "message": _connect_error_message(provider), "raw": _safe_error(exc)},
        )
    except Exception as exc:
        return _provider_payload(
            provider=provider,
            reachable=False,
            status=MODEL_STATUS_UNKNOWN,
            mode=provider.provider,
            checked_at=checked_at,
            models=_unknown_model_statuses(model_profiles),
            warnings=["Provider status could not be determined."],
            error={"code": MODEL_STATUS_UNKNOWN, "message": "Provider status could not be determined.", "raw": _safe_error(exc)},
        )


def unload_model(
    provider: ProviderProfileSchema,
    model_profiles: Iterable[LLMProfileSchema],
    model_profile_id: str | None = None,
    model_id: str | None = None,
) -> Dict[str, Any]:
    if provider.provider != "lm_studio":
        return _unsupported_unload(provider, model_id=model_id)
    if not provider.enabled:
        return {
            "ok": False,
            "provider": provider.provider,
            "provider_profile_id": provider.id,
            "model_id": model_id or "",
            "unloaded": [],
            "skipped": False,
            "skip_reason": None,
            "errors": [{"code": "LLM_PROVIDER_PROFILE_DISABLED", "message": f"Provider profile is disabled: {provider.name}"}],
        }

    requested_model_id = model_id or ""
    if model_profile_id and not requested_model_id:
        for profile in model_profiles:
            if profile.id == model_profile_id:
                requested_model_id = profile.model_id
                break
    if not requested_model_id:
        return {
            "ok": False,
            "provider": provider.provider,
            "provider_profile_id": provider.id,
            "model_id": requested_model_id,
            "unloaded": [],
            "skipped": False,
            "skip_reason": None,
            "errors": [{"code": MODEL_NOT_AVAILABLE, "message": "model_id is required for unload."}],
        }

    headers = _headers(provider)
    unloaded: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    try:
        with httpx.Client(timeout=float(provider.timeout_seconds or 60)) as client:
            response = client.get(_lm_studio_native_models_url(provider.base_url), headers=headers)
            response.raise_for_status()
            models = _extract_models(response.json())
            target = next((item for item in models if _model_identifier(item) == requested_model_id), None)
            if target is None:
                return {
                    "ok": False,
                    "provider": provider.provider,
                    "provider_profile_id": provider.id,
                    "model_id": requested_model_id,
                    "unloaded": [],
                    "skipped": False,
                    "skip_reason": None,
                    "errors": [{"code": MODEL_NOT_AVAILABLE, "message": "The requested model is not available from this provider."}],
                }
            instances = _loaded_instances(target)
            if not instances:
                return {
                    "ok": True,
                    "provider": provider.provider,
                    "provider_profile_id": provider.id,
                    "model_id": requested_model_id,
                    "unloaded": [],
                    "skipped": False,
                    "skip_reason": None,
                    "message": "model already unloaded",
                    "errors": [],
                }
            for instance in instances:
                instance_id = str(instance.get("id") or "").strip()
                if not instance_id:
                    continue
                unload_response = client.post(
                    _lm_studio_native_unload_url(provider.base_url),
                    headers=headers,
                    json={"instance_id": instance_id},
                )
                try:
                    unload_response.raise_for_status()
                    unloaded.append({"model_id": requested_model_id, "instance_id": instance_id})
                except httpx.HTTPError as exc:
                    errors.append({"code": UNLOAD_FAILED, "message": "Model unload failed.", "raw": _safe_error(exc)})
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "provider": provider.provider,
            "provider_profile_id": provider.id,
            "model_id": requested_model_id,
            "unloaded": unloaded,
            "skipped": False,
            "skip_reason": None,
            "errors": [{"code": PROVIDER_UNREACHABLE, "message": _connect_error_message(provider), "raw": _safe_error(exc)}],
        }
    return {
        "ok": not errors,
        "provider": provider.provider,
        "provider_profile_id": provider.id,
        "model_id": requested_model_id,
        "unloaded": unloaded,
        "skipped": False,
        "skip_reason": None,
        "errors": errors,
    }


def unload_model_for_profile(
    provider_profile_store: Any,
    llm_profile_store: Any,
    provider_profile_id: str | None = None,
    model_profile_id: str | None = None,
    model_id: str | None = None,
    reason: str = "manual",
) -> Dict[str, Any]:
    profiles = llm_profile_store.list() if llm_profile_store is not None else []
    resolved_provider_id = provider_profile_id or ""
    resolved_model_id = model_id or ""
    if model_profile_id:
        for profile in profiles:
            if profile.id == model_profile_id:
                resolved_provider_id = resolved_provider_id or (profile.provider_profile_id or "")
                resolved_model_id = resolved_model_id or profile.model_id
                break
    if not resolved_provider_id:
        return {
            "ok": False,
            "code": MODEL_UNLOAD_UNSUPPORTED,
            "provider": "",
            "provider_profile_id": "",
            "model_id": resolved_model_id,
            "unloaded": [],
            "skipped": False,
            "skip_reason": None,
            "reason": reason,
            "errors": [{"code": MODEL_UNLOAD_UNSUPPORTED, "message": "Provider profile is required for unload."}],
        }
    try:
        provider = provider_profile_store.get(resolved_provider_id)
    except Exception:
        return {
            "ok": False,
            "code": "LLM_PROVIDER_PROFILE_NOT_FOUND",
            "provider": "",
            "provider_profile_id": resolved_provider_id,
            "model_id": resolved_model_id,
            "unloaded": [],
            "skipped": False,
            "skip_reason": None,
            "reason": reason,
            "errors": [{"code": "LLM_PROVIDER_PROFILE_NOT_FOUND", "message": f"Provider profile not found: {resolved_provider_id}"}],
        }
    result = unload_model(provider, profiles, model_profile_id=model_profile_id, model_id=resolved_model_id)
    result.setdefault("provider_profile_id", provider.id)
    result.setdefault("model_id", resolved_model_id)
    result.setdefault("skipped", False)
    result.setdefault("skip_reason", None)
    result["reason"] = reason
    if not result.get("ok") and result.get("errors"):
        first = result["errors"][0]
        if isinstance(first, dict) and first.get("code"):
            result.setdefault("code", first["code"])
    return result


def dedupe_providers(providers: Iterable[ProviderProfileSchema]) -> list[ProviderProfileSchema]:
    seen: set[str] = set()
    result: list[ProviderProfileSchema] = []
    for provider in providers:
        if provider.id in seen:
            continue
        seen.add(provider.id)
        result.append(provider)
    return result


def _refresh_lm_studio(provider: ProviderProfileSchema, model_profiles: list[LLMProfileSchema], checked_at: str) -> Dict[str, Any]:
    headers = _headers(provider)
    with httpx.Client(timeout=float(provider.timeout_seconds or 60)) as client:
        try:
            response = client.get(_lm_studio_native_models_url(provider.base_url), headers=headers)
            response.raise_for_status()
            native_data = response.json()
            native_models = _extract_lm_studio_native_models(native_data)
            if native_models is None:
                fallback = _lm_studio_openai_fallback(client, provider, headers, model_profiles, checked_at)
                fallback["warnings"] = ["LM Studio native API returned an unexpected model list; used OpenAI-compatible fallback."]
                return fallback
            model_items, warnings = _lm_studio_model_items(native_models)
            if native_models and not model_items:
                models = _unknown_model_statuses(model_profiles)
                return _provider_payload(
                    provider=provider,
                    reachable=True,
                    status=MODEL_STATUS_UNKNOWN,
                    mode="lm_studio_native",
                    checked_at=checked_at,
                    models=models,
                    warnings=warnings or ["LM Studio native API returned models, but no model identifiers were recognized."],
                )
            models = _map_model_profiles(model_profiles, model_items, reliable=True)
            return _provider_payload(
                provider=provider,
                reachable=True,
                status=_aggregate_model_status(models),
                mode="lm_studio_native",
                checked_at=checked_at,
                models=models,
                warnings=warnings,
            )
        except httpx.HTTPError:
            return _lm_studio_openai_fallback(client, provider, headers, model_profiles, checked_at)


def _lm_studio_openai_fallback(
    client: httpx.Client,
    provider: ProviderProfileSchema,
    headers: dict[str, str],
    model_profiles: list[LLMProfileSchema],
    checked_at: str,
) -> Dict[str, Any]:
    response = client.get(f"{provider.base_url.rstrip('/')}/models", headers=headers)
    response.raise_for_status()
    fallback_models = [_openai_model_item(item) for item in _extract_models(response.json())]
    models = _map_model_profiles(model_profiles, fallback_models, reliable=False)
    return _provider_payload(
        provider=provider,
        reachable=True,
        status=MODEL_STATUS_UNKNOWN,
        mode="lm_studio_openai_compatible_partial",
        checked_at=checked_at,
        models=models,
        warnings=["LM Studio native API was unavailable; model availability is partial."],
    )


def _refresh_llama_cpp(provider: ProviderProfileSchema, model_profiles: list[LLMProfileSchema], checked_at: str) -> Dict[str, Any]:
    headers = _headers(provider)
    with httpx.Client(timeout=float(provider.timeout_seconds or 60)) as client:
        try:
            response = client.get(f"{_base_origin(provider.base_url)}/models", headers=headers)
            response.raise_for_status()
            router_models = [_llama_router_model_item(item) for item in _extract_models(response.json())]
            models = _map_model_profiles(model_profiles, router_models, reliable=True)
            return _provider_payload(
                provider=provider,
                reachable=True,
                status=_aggregate_model_status(models),
                mode="llama_cpp_router",
                checked_at=checked_at,
                models=models,
                warnings=[],
            )
        except httpx.HTTPError:
            response = client.get(f"{provider.base_url.rstrip('/')}/models", headers=headers)
            response.raise_for_status()
            served_models = [_openai_model_item(item) for item in _extract_models(response.json())]
            served_id = served_models[0]["id"] if served_models else ""
            models = []
            warnings = ["llama.cpp single-server mode reports only the currently served model. Use --alias for a stable model ID if needed."]
            for profile in model_profiles:
                requested = profile.model_id
                if not requested:
                    status = MODEL_STATUS_UNKNOWN
                    available = False
                elif served_id and requested == served_id:
                    status = READY
                    available = True
                elif served_id:
                    status = MODEL_MISMATCH
                    available = False
                else:
                    status = MODEL_STATUS_UNKNOWN
                    available = False
                models.append(
                    {
                        "id": requested,
                        "available": available,
                        "loaded": available,
                        "status": status,
                        "actual_model_id": served_id or None,
                        "loaded_instance_ids": [],
                        "capabilities": {},
                        "raw": {},
                    }
                )
            return _provider_payload(
                provider=provider,
                reachable=True,
                status=_aggregate_model_status(models),
                mode="llama_cpp_single",
                checked_at=checked_at,
                models=models,
                warnings=warnings,
            )


def _refresh_openai_compatible(provider: ProviderProfileSchema, model_profiles: list[LLMProfileSchema], checked_at: str) -> Dict[str, Any]:
    headers = _headers(provider)
    with httpx.Client(timeout=float(provider.timeout_seconds or 60)) as client:
        response = client.get(f"{provider.base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        data = response.json()
    if not _has_model_list(data):
        models = _unknown_model_statuses(model_profiles)
        status = MODEL_STATUS_UNKNOWN
    else:
        provider_models = [_openai_model_item(item) for item in _extract_models(data)]
        models = _map_model_profiles(model_profiles, provider_models, reliable=True, ready_when_available=True)
        status = _aggregate_model_status(models)
    return _provider_payload(
        provider=provider,
        reachable=True,
        status=status,
        mode="openai_compatible",
        checked_at=checked_at,
        models=models,
        warnings=[] if status != MODEL_STATUS_UNKNOWN else ["Provider returned an incomplete model list."],
    )


def _provider_payload(
    provider: ProviderProfileSchema,
    reachable: bool,
    status: str,
    mode: str,
    checked_at: str,
    models: list[dict[str, Any]],
    warnings: list[str],
    error: Optional[dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "provider_profile_id": provider.id,
        "provider_profile_name": provider.name,
        "provider": provider.provider,
        "reachable": reachable,
        "status": status,
        "mode": mode,
        "checked_at": checked_at,
        "models": models,
        "warnings": warnings,
    }
    if error:
        payload["error"] = error
    return payload


def _map_model_profiles(
    model_profiles: list[LLMProfileSchema],
    provider_models: list[dict[str, Any]],
    reliable: bool,
    ready_when_available: bool = False,
) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in provider_models if item.get("id")}
    result: list[dict[str, Any]] = []
    for profile in model_profiles:
        match = by_id.get(profile.model_id)
        if match:
            loaded = match.get("loaded")
            status = READY if ready_when_available else READY if loaded is True else MODEL_NOT_LOADED if loaded is False else MODEL_STATUS_UNKNOWN
            loaded_value = None if ready_when_available else loaded
            if ready_when_available:
                match = {**match, "loaded": loaded_value}
            result.append({**match, "available": True, "status": status})
        elif reliable:
            result.append(
                {
                    "id": profile.model_id,
                    "available": False,
                    "loaded": False,
                    "status": MODEL_NOT_AVAILABLE,
                    "loaded_instance_ids": [],
                    "capabilities": {},
                    "raw": {},
                }
            )
        else:
            result.append(
                {
                    "id": profile.model_id,
                    "available": None,
                    "loaded": None,
                    "status": MODEL_STATUS_UNKNOWN,
                    "loaded_instance_ids": [],
                    "capabilities": {},
                    "raw": {},
                }
            )
    if not model_profiles and ready_when_available:
        return [{**item, "available": True, "loaded": None, "status": READY} for item in provider_models]
    if not model_profiles:
        return provider_models
    return result


def _unknown_model_statuses(model_profiles: Iterable[LLMProfileSchema]) -> list[dict[str, Any]]:
    return [
        {
            "id": profile.model_id,
            "available": None,
            "loaded": None,
            "status": MODEL_STATUS_UNKNOWN,
            "loaded_instance_ids": [],
            "capabilities": {},
            "raw": {},
        }
        for profile in model_profiles
    ]


def _aggregate_model_status(models: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or MODEL_STATUS_UNKNOWN) for item in models}
    if not statuses:
        return READY
    if MODEL_MISMATCH in statuses:
        return MODEL_MISMATCH
    if MODEL_NOT_AVAILABLE in statuses:
        return MODEL_NOT_AVAILABLE
    if MODEL_NOT_LOADED in statuses:
        return MODEL_NOT_LOADED
    if MODEL_STATUS_UNKNOWN in statuses:
        return MODEL_STATUS_UNKNOWN
    return READY


def _lm_studio_model_item(item: dict[str, Any]) -> dict[str, Any]:
    instances = _loaded_instances(item)
    model_id = _lm_studio_model_identifier(item)
    return {
        "id": model_id,
        "name": item.get("display_name") or item.get("name") or model_id,
        "type": _model_type(item),
        "available": True,
        "loaded": bool(instances),
        "loaded_instance_ids": [str(instance.get("id")) for instance in instances if instance.get("id")],
        "capabilities": _capabilities(item),
        "raw": item,
    }


def _llama_router_model_item(item: dict[str, Any]) -> dict[str, Any]:
    status_value = ""
    status = item.get("status")
    if isinstance(status, dict):
        status_value = str(status.get("value") or "").lower()
    loaded = status_value in {"loaded", "ready", "running"}
    return {
        "id": _model_identifier(item),
        "name": item.get("name") or item.get("id"),
        "type": _model_type(item),
        "available": True,
        "loaded": loaded if status_value else None,
        "loaded_instance_ids": [],
        "capabilities": _capabilities(item),
        "raw": item,
    }


def _openai_model_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _model_identifier(item),
        "name": item.get("name") or item.get("display_name") or item.get("id"),
        "type": _model_type(item),
        "available": True,
        "loaded": None,
        "loaded_instance_ids": [],
        "capabilities": _capabilities(item),
        "raw": item,
    }


def _extract_models(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    models = data.get("data")
    if models is None:
        models = data.get("models")
    if not isinstance(models, list):
        return []
    return [item for item in models if isinstance(item, dict) and _model_identifier(item)]


def _extract_lm_studio_native_models(data: Any) -> list[dict[str, Any]] | None:
    if not isinstance(data, dict):
        return None
    if "models" in data:
        models = data.get("models")
    elif "data" in data:
        models = data.get("data")
    else:
        return None
    if not isinstance(models, list):
        return None
    return [item for item in models if isinstance(item, dict)]


def _lm_studio_model_items(models: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    skipped = 0
    for model in models:
        if not _lm_studio_model_identifier(model):
            skipped += 1
            continue
        items.append(_lm_studio_model_item(model))
    warnings = []
    if skipped:
        warnings.append(f"LM Studio native API returned {skipped} model(s) without key or id.")
    return items, warnings


def _has_model_list(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return isinstance(data.get("data"), list) or isinstance(data.get("models"), list)


def _model_identifier(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("model_key") or item.get("key") or item.get("name") or "").strip()


def _lm_studio_model_identifier(item: dict[str, Any]) -> str:
    return str(item.get("key") or item.get("id") or "").strip()


def _model_type(item: dict[str, Any]) -> str:
    value = str(item.get("type") or "").strip().lower()
    return value if value in {"llm", "embedding"} else "unknown"


def _loaded_instances(item: dict[str, Any]) -> list[dict[str, Any]]:
    instances = item.get("loaded_instances")
    if not isinstance(instances, list):
        return []
    return [instance for instance in instances if isinstance(instance, dict)]


def _capabilities(item: dict[str, Any]) -> dict[str, bool]:
    raw = item.get("capabilities")
    if not isinstance(raw, dict):
        return {}
    return {
        "vision": bool(raw.get("vision") or raw.get("image_input")),
        "tools": bool(raw.get("tools") or raw.get("trained_for_tool_use")),
        "reasoning": bool(raw.get("reasoning") or raw.get("reasoning_output")),
    }


def _headers(provider: ProviderProfileSchema) -> dict[str, str]:
    return {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}


def _lm_studio_native_models_url(base_url: str) -> str:
    return f"{_without_trailing_v1(base_url)}/api/v1/models"


def _lm_studio_native_unload_url(base_url: str) -> str:
    return f"{_without_trailing_v1(base_url)}/api/v1/models/unload"


def _without_trailing_v1(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/api/v1"):
        return trimmed[:-7]
    if trimmed.endswith("/v1"):
        trimmed = trimmed[:-3]
    return trimmed


def _base_origin(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _connect_error_message(provider: ProviderProfileSchema) -> str:
    return f"Cannot connect to {provider.name} at {provider.base_url}."


def _safe_error(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def _unsupported_unload(provider: ProviderProfileSchema, model_id: str | None = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "code": MODEL_UNLOAD_UNSUPPORTED,
        "provider": provider.provider,
        "provider_profile_id": provider.id,
        "model_id": model_id or "",
        "unloaded": [],
        "skipped": False,
        "skip_reason": None,
        "errors": [{"code": MODEL_UNLOAD_UNSUPPORTED, "message": "Model unload is not supported by this provider."}],
    }
