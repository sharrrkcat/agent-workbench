import inspect
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from ai_workbench.core.agent_settings import resolved_runtime_override
from ai_workbench.core.llm_config import LLMConfigError, resolve_llm_config
from ai_workbench.core.settings import AppSettings, DEFAULT_SESSION_TITLE_PROMPT
from ai_workbench.core.time import utc_now


TITLE_MAX_LENGTH = 80
TITLE_ELLIPSIS = "\n...\n"
TITLE_STATES = {"pending", "done", "skipped", "failed", "manual"}


@dataclass
class TitleBackendDecision:
    requested_backend: str
    backend: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    model_profile_resolution: str | None = None
    model_profile_id: str | None = None
    llm_model_config: dict[str, Any] | None = None
    llm_resolution: dict[str, Any] | None = None
    skip_reason: str | None = None
    warnings: list[str] | None = None


TITLE_QUOTE_CHARS = "`\"'“”‘’"


def is_default_session_title(title: str) -> bool:
    value = str(title or "").strip()
    if not value:
        return True
    if value.lower() == "new chat":
        return True
    return re.fullmatch(r"session(?:\s+\d+|[\s-]+[0-9a-f]{6})?", value, flags=re.IGNORECASE) is not None


def truncate_title_input(value: str, limit: int) -> tuple[str, bool]:
    text = value or ""
    safe_limit = max(1, int(limit or 1))
    if len(text) <= safe_limit:
        return text, False
    available = max(0, safe_limit - len(TITLE_ELLIPSIS))
    head_len = available // 2
    tail_len = available - head_len
    return f"{text[:head_len]}{TITLE_ELLIPSIS}{text[-tail_len:] if tail_len else ''}", True


def render_title_prompt(template: str, user_input: str) -> str:
    prompt = str(template or DEFAULT_SESSION_TITLE_PROMPT).strip() or DEFAULT_SESSION_TITLE_PROMPT
    return prompt.format(user_input=user_input)


def normalize_generated_title(title: str) -> str:
    value = str(title or "").strip()
    value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
    value = re.sub(r"\s*```$", "", value).strip()
    value = value.strip(TITLE_QUOTE_CHARS).strip()
    value = value.splitlines()[0].strip() if value else ""
    value = re.sub(r"^(?:title|chat title|session title|标题|会话标题)\s*[:：-]\s*", "", value, flags=re.IGNORECASE).strip()
    value = value.strip(TITLE_QUOTE_CHARS).strip()
    value = value.replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"[.!?。！？]+$", "", value).strip()
    if not value or re.fullmatch(r"[\W_]+", value, flags=re.UNICODE):
        return ""
    return value[:TITLE_MAX_LENGTH].strip()


async def maybe_generate_session_title_before_llm_call(
    *,
    session_id: str,
    source_message_id: str = "",
    fallback_user_text: str = "",
    run_id: str = "",
    session_store: Any,
    message_store: Any,
    run_store: Any,
    event_bus: Any,
    llm_runtime: Any,
    llm_model_config: dict[str, Any],
    llm_resolution: dict[str, Any] | None = None,
    app_settings_store: Any = None,
    utility_llm_service: Any = None,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    llm_profile_store: Any = None,
    provider_profile_store: Any = None,
    capability_registry: Any = None,
    capability_config_store: Any = None,
    llm_defaults_store: Any = None,
    invoked_agent_id: str = "",
    invoked_action_id: str = "",
    unload_model_callback: Any = None,
    current_response_llm_resolution: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if session_store is None or llm_runtime is None:
        return None
    try:
        session = session_store.get_session(session_id)
    except KeyError:
        return None

    state = getattr(session, "title_generation_state", None) or "pending"
    if state != "pending":
        return None

    base_metadata = {
        "state": state,
        "source_message_id": source_message_id or None,
        "attempted_at": utc_now().isoformat(),
        "requested_backend": None,
        "backend": None,
        "fallback_used": False,
        "model_profile_resolution": None,
        "model_profile_id": None,
        "trigger": "first_llm_capable_user_message",
        "trigger_agent_id": invoked_agent_id or None,
        "invoked_agent_id": invoked_agent_id or None,
        "invoked_action_id": invoked_action_id or None,
        "input_override_model_profile_id": _session_model_profile_id(session),
        "unload_after_generation": False,
        "unload_state": "not_requested",
        "warnings": [],
    }

    if not is_default_session_title(session.title):
        metadata = {**base_metadata, "state": "manual", "reason": "non_default_title"}
        _set_title_state(session_store, session_id, "manual", metadata)
        return metadata

    settings = app_settings_store.get() if app_settings_store is not None else AppSettings()
    requested_backend = getattr(settings, "session_title_backend", "utility_llm") or "utility_llm"
    base_metadata.update(
        {
            "requested_backend": requested_backend,
            "unload_after_generation": bool(getattr(settings, "session_title_unload_after_generation", False)),
        }
    )
    if not settings.auto_generate_session_titles:
        metadata = {**base_metadata, "state": "skipped", "reason": "disabled"}
        _set_title_state(session_store, session_id, "skipped", metadata)
        _record_run_title_metadata(run_store, run_id, metadata)
        return metadata

    user_text = _source_user_text(message_store, source_message_id, fallback_user_text)
    original_len = len(user_text)
    used_text, truncated = truncate_title_input(user_text, settings.session_title_max_input_chars)
    metadata = {
        **base_metadata,
        "state": "pending",
        "input_truncated": truncated,
        "truncated": truncated,
        "input_chars_original": original_len,
        "input_chars_used": len(used_text),
    }
    if not used_text.strip():
        failed = {**metadata, "state": "failed", "error": {"code": "TITLE_INPUT_EMPTY", "message": "Title source message was empty."}}
        _set_title_state(session_store, session_id, "failed", failed)
        _record_run_title_metadata(run_store, run_id, failed)
        return failed

    decision = resolve_title_generation_backend(
        settings=settings,
        session=session,
        invoked_agent_id=invoked_agent_id,
        agent_registry=agent_registry,
        agent_config_store=agent_config_store,
        llm_profile_store=llm_profile_store,
        provider_profile_store=provider_profile_store,
        capability_registry=capability_registry,
        capability_config_store=capability_config_store,
        llm_defaults_store=llm_defaults_store,
    )
    metadata = _merge_title_metadata(metadata, _decision_metadata(decision))
    if decision.skip_reason:
        skipped = {**metadata, "state": "skipped", "reason": decision.skip_reason}
        _set_title_state(session_store, session_id, "skipped", skipped)
        _record_run_title_metadata(run_store, run_id, skipped)
        _record_title_warning(event_bus, run_store, session_id, run_id, _warning_text(decision.skip_reason))
        return skipped

    title = ""
    utility_error = None
    utility_backend = str(getattr(settings, "intent_routing_utility_llm_backend", "transformers") or "transformers")
    utility_model_path = getattr(settings, "intent_routing_utility_llm_model_path", "") or ""
    utility_model_profile_id = getattr(settings, "intent_routing_utility_llm_model_profile_id", None)
    utility_configured = bool(utility_model_profile_id) if utility_backend == "model_profile" else bool(utility_model_path)
    if decision.backend == "utility_llm" and utility_llm_service is not None and utility_configured:
        try:
            utility_result = await utility_llm_service.generate_title(used_text, settings)
            title = normalize_generated_title(utility_result.get("title", ""))
            if not title or is_default_session_title(title):
                raise ValueError("Utility LLM returned an empty or default-looking title.")
            metadata["backend"] = utility_result.get("backend") or "utility_llm"
            if utility_result.get("model_path") or utility_model_path:
                metadata["utility_model_path"] = utility_result.get("model_path") or utility_model_path
            if utility_result.get("model_profile_id"):
                metadata["model_profile_id"] = utility_result.get("model_profile_id")
                metadata["model"] = {
                    "profile_id": utility_result.get("model_profile_id"),
                    "profile_name": utility_result.get("model_profile_name"),
                    "provider_profile_id": utility_result.get("provider_profile_id"),
                    "provider": utility_result.get("provider_label"),
                    "model_id": utility_result.get("requested_model_id"),
                }
        except Exception as exc:
            utility_error = str(exc) or "Utility LLM title generation failed."
            metadata["warnings"] = [*metadata.get("warnings", []), "utility_title_generation_failed"]
            decision = resolve_title_generation_backend(
                settings=settings,
                session=session,
                invoked_agent_id=invoked_agent_id,
                agent_registry=agent_registry,
                agent_config_store=agent_config_store,
                llm_profile_store=llm_profile_store,
                provider_profile_store=provider_profile_store,
                capability_registry=capability_registry,
                capability_config_store=capability_config_store,
                llm_defaults_store=llm_defaults_store,
                force_backend="follow_agent_model_profile",
                fallback_used=True,
                fallback_reason="utility_llm_generation_failed",
            )
            metadata = _merge_title_metadata(metadata, _decision_metadata(decision))
            if decision.skip_reason:
                skipped = {
                    **metadata,
                    "state": "skipped",
                    "reason": decision.skip_reason,
                    "utility_error": utility_error,
                }
                _set_title_state(session_store, session_id, "skipped", skipped)
                _record_run_title_metadata(run_store, run_id, skipped)
                _record_title_warning(event_bus, run_store, session_id, run_id, _warning_text(decision.skip_reason))
                return skipped

    if not title:
        try:
            prompt = render_title_prompt(settings.session_title_prompt, used_text)
            model_config = decision.llm_model_config or llm_model_config
            chat = getattr(llm_runtime, "chat", None)
            if callable(chat):
                raw = chat(messages=[{"role": "user", "content": prompt}], model_config=model_config, stream=False)
            else:
                generate = getattr(llm_runtime, "generate")
                raw = generate(prompt=prompt, model_config=model_config, stream=False)
            if inspect.isawaitable(raw):
                raw = await raw
            title = normalize_generated_title(_extract_title_text(raw))
            if not title or is_default_session_title(title):
                raise ValueError("Title generation returned an empty or default-looking title.")
            metadata["backend"] = "model_profile"
            metadata["fallback_used"] = bool(utility_error)
            metadata["model"] = _public_model_metadata(model_config, decision.llm_resolution or llm_resolution or {})
            if utility_error:
                metadata["utility_error"] = utility_error
        except Exception as exc:
            if utility_error:
                message = f"{utility_error}; fallback failed: {exc}"
            else:
                message = str(exc) or "Session title generation failed."
            failed = {
                **metadata,
                "state": "failed",
                "backend": metadata.get("backend") or "model_profile",
                "fallback_used": bool(utility_error),
                "error": {"code": "SESSION_TITLE_GENERATION_FAILED", "message": message},
            }
            if utility_error:
                failed["utility_error"] = utility_error
            _set_title_state(session_store, session_id, "failed", failed)
            _record_run_title_metadata(run_store, run_id, failed)
            _record_title_warning(event_bus, run_store, session_id, run_id, failed["error"]["message"])
            return failed

    try:
        if not title or is_default_session_title(title):
            raise ValueError("Title generation returned an empty or default-looking title.")
    except Exception as exc:
        failed = {
            **metadata,
            "state": "failed",
            "error": {"code": "SESSION_TITLE_GENERATION_FAILED", "message": str(exc) or "Session title generation failed."},
        }
        _set_title_state(session_store, session_id, "failed", failed)
        _record_run_title_metadata(run_store, run_id, failed)
        _record_title_warning(event_bus, run_store, session_id, run_id, failed["error"]["message"])
        return failed

    done = {**metadata, "state": "done", "generated_at": utc_now().isoformat(), "error": None}
    done = _apply_title_unload_policy(
        done,
        settings=settings,
        utility_llm_service=utility_llm_service,
        unload_model_callback=unload_model_callback,
        title_llm_resolution=decision.llm_resolution,
        current_llm_resolution=current_response_llm_resolution or llm_resolution or {},
    )
    session = _set_generated_title(session_store, session_id, title, done)
    _record_run_title_metadata(run_store, run_id, done)
    _emit_session_updated(event_bus, session)
    return done


def resolve_title_generation_backend(
    *,
    settings: Any,
    session: Any,
    invoked_agent_id: str,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    llm_profile_store: Any = None,
    provider_profile_store: Any = None,
    capability_registry: Any = None,
    capability_config_store: Any = None,
    llm_defaults_store: Any = None,
    force_backend: str | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> TitleBackendDecision:
    requested = str(getattr(settings, "session_title_backend", "utility_llm") or "utility_llm")
    backend = force_backend or requested
    if backend == "utility_llm":
        utility_backend = str(getattr(settings, "intent_routing_utility_llm_backend", "transformers") or "transformers")
        model_path = str(getattr(settings, "intent_routing_utility_llm_model_path", "") or "").strip()
        model_profile_id = str(getattr(settings, "intent_routing_utility_llm_model_profile_id", "") or "").strip()
        if utility_backend == "model_profile" and model_profile_id:
            return TitleBackendDecision(requested_backend=requested, backend="utility_llm", warnings=[])
        if utility_backend != "model_profile" and model_path:
            return TitleBackendDecision(requested_backend=requested, backend="utility_llm", warnings=[])
        backend = "follow_agent_model_profile"
        fallback_used = True
        fallback_reason = "utility_llm_unavailable"

    if backend == "specified_model_profile":
        profile_id = str(getattr(settings, "session_title_model_profile_id", "") or "").strip()
        if not profile_id:
            return TitleBackendDecision(
                requested_backend=requested,
                skip_reason="specified_model_profile_missing",
                warnings=["session_title_model_profile_missing"],
            )
        return _resolve_title_profile(
            profile_id=profile_id,
            resolution_source="specified",
            requested_backend=requested,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            llm_profile_store=llm_profile_store,
            provider_profile_store=provider_profile_store,
            capability_registry=capability_registry,
            capability_config_store=capability_config_store,
            llm_defaults_store=llm_defaults_store,
        )

    if backend == "follow_agent_model_profile":
        warnings: list[str] = []
        for resolution, profile_id in _follow_agent_profile_candidates(session, invoked_agent_id, agent_registry, agent_config_store):
            decision = _resolve_title_profile(
                profile_id=profile_id,
                resolution_source=resolution,
                requested_backend=requested,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                llm_profile_store=llm_profile_store,
                provider_profile_store=provider_profile_store,
                capability_registry=capability_registry,
                capability_config_store=capability_config_store,
                llm_defaults_store=llm_defaults_store,
            )
            if not decision.skip_reason:
                decision.warnings = [*warnings, *(decision.warnings or [])]
                return decision
            warnings.extend(decision.warnings or [decision.skip_reason])
        return TitleBackendDecision(
            requested_backend=requested,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            skip_reason="follow_agent_model_profile_unavailable",
            warnings=warnings or ["follow_agent_model_profile_unavailable"],
        )

    return TitleBackendDecision(
        requested_backend=requested,
        skip_reason="session_title_backend_invalid",
        warnings=["session_title_backend_invalid"],
    )


def _resolve_title_profile(
    *,
    profile_id: str,
    resolution_source: str,
    requested_backend: str,
    fallback_used: bool,
    fallback_reason: str | None,
    llm_profile_store: Any,
    provider_profile_store: Any,
    capability_registry: Any,
    capability_config_store: Any,
    llm_defaults_store: Any,
) -> TitleBackendDecision:
    try:
        capability = capability_registry.get("llm") if capability_registry is not None else None
    except KeyError:
        capability = None
    capability_config = capability_config_store.get_config("llm") if capability_config_store is not None else {}
    agent_schema = SimpleNamespace(llm={"profile": profile_id}, model=None)
    try:
        llm_config = resolve_llm_config(
            agent_schema=agent_schema,
            capability_schema=capability,
            capability_config=capability_config,
            llm_profile_store=llm_profile_store,
            provider_profile_store=provider_profile_store,
            llm_defaults_store=llm_defaults_store,
            session_llm_profile_id=None,
            agent_runtime={},
        )
    except LLMConfigError as exc:
        return TitleBackendDecision(
            requested_backend=requested_backend,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            model_profile_resolution=resolution_source,
            model_profile_id=profile_id,
            skip_reason=exc.code.lower(),
            warnings=[exc.code.lower()],
        )
    resolution = _public_model_metadata(llm_config.values, _llm_config_public_resolution(llm_config))
    return TitleBackendDecision(
        requested_backend=requested_backend,
        backend="model_profile",
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        model_profile_resolution=resolution_source,
        model_profile_id=resolution.get("profile_id") or profile_id,
        llm_model_config=llm_config.values,
        llm_resolution=_llm_config_public_resolution(llm_config),
        warnings=[],
    )


def _follow_agent_profile_candidates(session: Any, invoked_agent_id: str, agent_registry: Any, agent_config_store: Any) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(source: str, profile_id: Any) -> None:
        text = str(profile_id or "").strip()
        if text and text not in seen:
            seen.add(text)
            candidates.append((source, text))

    add("input_override", _session_model_profile_id(session))
    default_agent_id = str(getattr(session, "default_agent_id", "") or "")
    add("session_agent", _agent_profile_id(default_agent_id, agent_registry, agent_config_store))
    add("invoked_agent", _agent_profile_id(invoked_agent_id, agent_registry, agent_config_store))
    return candidates


def _agent_profile_id(agent_id: str, agent_registry: Any, agent_config_store: Any) -> str | None:
    if not agent_id or agent_registry is None:
        return None
    try:
        agent = agent_registry.get(agent_id)
    except KeyError:
        return None
    config = agent_config_store.get_config(agent_id) if agent_config_store is not None else {}
    runtime = resolved_runtime_override(config)
    if runtime.get("llm_profile_id"):
        return str(runtime["llm_profile_id"])
    llm = getattr(agent, "llm", None)
    if isinstance(llm, dict) and llm.get("profile"):
        return str(llm["profile"])
    return None


def _session_model_profile_id(session: Any) -> str | None:
    value = getattr(session, "llm_profile_id", None)
    text = str(value or "").strip()
    return text or None


def _decision_metadata(decision: TitleBackendDecision) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "requested_backend": decision.requested_backend,
        "backend": decision.backend,
        "fallback_used": decision.fallback_used,
        "model_profile_resolution": decision.model_profile_resolution,
        "model_profile_id": decision.model_profile_id,
        "warnings": list(decision.warnings or []),
    }
    if decision.fallback_reason:
        metadata["fallback_reason"] = decision.fallback_reason
    return metadata


def _merge_title_metadata(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    warnings = [*base.get("warnings", []), *updates.get("warnings", [])]
    merged = {**base, **updates}
    merged["warnings"] = list(dict.fromkeys(str(item) for item in warnings if str(item or "").strip()))
    return merged


def _llm_config_public_resolution(llm_config: Any) -> dict[str, Any]:
    metadata = dict(getattr(llm_config, "metadata", {}) or {})
    values = dict(getattr(llm_config, "values", {}) or {})
    return {
        "source": metadata.get("source"),
        "profile_id": metadata.get("profile_id"),
        "profile_alias": metadata.get("profile_alias"),
        "profile_key": metadata.get("profile_key") or metadata.get("profile_alias"),
        "profile_name": metadata.get("profile_name"),
        "provider_profile_id": metadata.get("provider_profile_id"),
        "provider_profile_name": metadata.get("provider_profile_name"),
        "provider": metadata.get("provider") or values.get("provider"),
        "model_id": values.get("model_id") or values.get("model"),
    }


def _apply_title_unload_policy(
    metadata: dict[str, Any],
    *,
    settings: Any,
    utility_llm_service: Any,
    unload_model_callback: Any,
    title_llm_resolution: dict[str, Any] | None,
    current_llm_resolution: dict[str, Any],
) -> dict[str, Any]:
    if not bool(getattr(settings, "session_title_unload_after_generation", False)):
        return {**metadata, "unload_state": "not_requested"}
    backend = str(metadata.get("backend") or "")
    if backend == "utility_llm:model_profile":
        return {**metadata, "unload_state": "no_supported_release"}
    if backend.startswith("utility_llm"):
        if utility_llm_service is None or not callable(getattr(utility_llm_service, "unload", None)):
            return {**metadata, "unload_state": "no_supported_release"}
        try:
            utility_llm_service.unload()
            return {**metadata, "unload_state": "released"}
        except Exception:
            return {**metadata, "unload_state": "failed", "warnings": [*metadata.get("warnings", []), "title_model_release_failed"]}
    if backend != "model_profile":
        return {**metadata, "unload_state": "skipped_no_model"}
    if not title_llm_resolution:
        return {**metadata, "unload_state": "skipped_no_model"}
    if _same_llm_target(title_llm_resolution, current_llm_resolution):
        return {**metadata, "unload_state": "deferred_until_run_end"}
    return _release_title_model(metadata, title_llm_resolution, unload_model_callback)


def apply_deferred_title_model_unload(run_store: Any, run_id: str, unload_model_callback: Any, session_store: Any = None) -> dict[str, Any] | None:
    if run_store is None or not run_id:
        return None
    try:
        run = run_store.get_run(run_id)
    except KeyError:
        return None
    metadata = dict(run.metadata or {})
    title_metadata = metadata.get("title_generation")
    if not isinstance(title_metadata, dict) or title_metadata.get("unload_state") != "deferred_until_run_end":
        return None
    resolution = {
        "profile_id": title_metadata.get("model_profile_id"),
        "provider_profile_id": (title_metadata.get("model") or {}).get("provider_profile_id") if isinstance(title_metadata.get("model"), dict) else None,
        "model_id": (title_metadata.get("model") or {}).get("model_id") if isinstance(title_metadata.get("model"), dict) else None,
    }
    updated = _release_title_model(title_metadata, resolution, unload_model_callback)
    metadata["title_generation"] = updated
    run_store.update_metadata(run_id, metadata)
    if session_store is not None:
        try:
            session = session_store.get_session(run.session_id)
            session_store.set_title_generation_state(session.session_id, session.title_generation_state, updated)
        except Exception:
            pass
    return updated


def _release_title_model(metadata: dict[str, Any], resolution: dict[str, Any], unload_model_callback: Any) -> dict[str, Any]:
    if unload_model_callback is None or not callable(unload_model_callback):
        return {**metadata, "unload_state": "no_supported_release"}
    try:
        result = unload_model_callback(
            provider_profile_id=resolution.get("provider_profile_id"),
            model_profile_id=resolution.get("profile_id"),
            model_id=resolution.get("model_id"),
            reason="session_title_generation",
        )
    except Exception:
        return {**metadata, "unload_state": "failed", "warnings": [*metadata.get("warnings", []), "title_model_release_failed"]}
    errors = result.get("errors") if isinstance(result, dict) else None
    code = ""
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        code = str(errors[0].get("code") or "")
    if isinstance(result, dict) and result.get("ok"):
        return {**metadata, "unload_state": "released"}
    if code == "MODEL_UNLOAD_UNSUPPORTED":
        return {**metadata, "unload_state": "no_supported_release"}
    return {**metadata, "unload_state": "failed", "warnings": [*metadata.get("warnings", []), "title_model_release_failed"]}


def _same_llm_target(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right:
        return False
    return bool(left.get("provider_profile_id") and left.get("provider_profile_id") == right.get("provider_profile_id") and left.get("model_id") and left.get("model_id") == right.get("model_id"))


def _warning_text(reason: str) -> str:
    return reason.replace("_", " ")


def _source_user_text(message_store: Any, source_message_id: str, fallback_user_text: str) -> str:
    if message_store is not None and source_message_id:
        try:
            message = message_store.get_message(source_message_id)
            if getattr(message, "role", "") == "user":
                from ai_workbench.core.message_parts import text_from_parts

                return text_from_parts(getattr(message, "parts", None))
        except KeyError:
            pass
    return str(fallback_user_text or "")


def _extract_title_text(raw: Any) -> str:
    if isinstance(raw, dict):
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            if "content" in message:
                return str(message.get("content") or "")
            delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
            if "content" in delta:
                return str(delta.get("content") or "")
        if "content" in raw:
            return str(raw.get("content") or "")
    return str(raw or "")


def _public_model_metadata(model_config: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": resolution.get("profile_id") or model_config.get("profile_id"),
        "profile_name": resolution.get("profile_name") or model_config.get("profile_name"),
        "provider_profile_id": resolution.get("provider_profile_id") or model_config.get("provider_profile_id"),
        "provider": resolution.get("provider") or model_config.get("provider"),
        "model_id": resolution.get("model_id") or model_config.get("model_id") or model_config.get("model"),
    }


def _set_generated_title(session_store: Any, session_id: str, title: str, metadata: dict[str, Any]):
    setter = getattr(session_store, "set_generated_title", None)
    if callable(setter):
        return setter(session_id, title, metadata)
    session = session_store.set_title(session_id, title)
    setter = getattr(session_store, "set_title_generation_state", None)
    if callable(setter):
        return setter(session_id, "done", metadata)
    return session


def _set_title_state(session_store: Any, session_id: str, state: str, metadata: dict[str, Any]):
    setter = getattr(session_store, "set_title_generation_state", None)
    if callable(setter):
        return setter(session_id, state, metadata)
    return session_store.get_session(session_id)


def _record_run_title_metadata(run_store: Any, run_id: str, metadata: dict[str, Any]) -> None:
    if run_store is None or not run_id:
        return
    try:
        run = run_store.get_run(run_id)
        next_metadata = dict(run.metadata or {})
        next_metadata["title_generation"] = metadata
        run_store.update_metadata(run_id, next_metadata)
    except Exception:
        return


def _record_title_warning(event_bus: Any, run_store: Any, session_id: str, run_id: str, warning: str) -> None:
    if run_store is not None and run_id:
        try:
            run = run_store.get_run(run_id)
            metadata = dict(run.metadata or {})
            warnings = list(metadata.get("warnings", []))
            warnings.append(f"Session title generation skipped: {warning}")
            metadata["warnings"] = warnings
            run_store.update_metadata(run_id, metadata)
        except Exception:
            pass
    if event_bus is not None and run_id:
        event_bus.emit(
            "run_warning",
            session_id=session_id,
            run_id=run_id,
            payload={"warning": f"Session title generation skipped: {warning}"},
        )


def _emit_session_updated(event_bus: Any, session: Any) -> None:
    if event_bus is None or session is None:
        return
    try:
        event_bus.emit(
            "session_updated",
            session_id=session.session_id,
            payload={"session": session.model_dump(mode="json")},
        )
    except Exception:
        return
