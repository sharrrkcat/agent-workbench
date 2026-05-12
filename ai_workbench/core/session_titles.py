import inspect
import re
from typing import Any

from ai_workbench.core.settings import AppSettings, DEFAULT_SESSION_TITLE_PROMPT
from ai_workbench.core.time import utc_now


TITLE_MAX_LENGTH = 80
TITLE_ELLIPSIS = "\n...\n"
TITLE_STATES = {"pending", "done", "skipped", "failed", "manual"}
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
        "backend": None,
        "fallback_used": False,
        "warnings": [],
    }

    if not is_default_session_title(session.title):
        metadata = {**base_metadata, "state": "manual", "reason": "non_default_title"}
        _set_title_state(session_store, session_id, "manual", metadata)
        return metadata

    settings = app_settings_store.get() if app_settings_store is not None else AppSettings()
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

    title = ""
    utility_error = None
    utility_model_path = getattr(settings, "intent_routing_utility_llm_model_path", "") or ""
    if utility_llm_service is not None and utility_model_path:
        try:
            utility_result = await utility_llm_service.generate_title(used_text, settings)
            title = normalize_generated_title(utility_result.get("title", ""))
            if not title or is_default_session_title(title):
                raise ValueError("Utility LLM returned an empty or default-looking title.")
            metadata["backend"] = utility_result.get("backend") or "utility_llm"
            metadata["utility_model_path"] = utility_result.get("model_path") or utility_model_path
        except Exception as exc:
            utility_error = str(exc) or "Utility LLM title generation failed."
            metadata["warnings"] = [*metadata.get("warnings", []), "utility_title_generation_failed"]

    if not title:
        try:
            prompt = render_title_prompt(settings.session_title_prompt, used_text)
            chat = getattr(llm_runtime, "chat", None)
            if callable(chat):
                raw = chat(messages=[{"role": "user", "content": prompt}], model_config=llm_model_config, stream=False)
            else:
                generate = getattr(llm_runtime, "generate")
                raw = generate(prompt=prompt, model_config=llm_model_config, stream=False)
            if inspect.isawaitable(raw):
                raw = await raw
            title = normalize_generated_title(_extract_title_text(raw))
            if not title or is_default_session_title(title):
                raise ValueError("Title generation returned an empty or default-looking title.")
            metadata["backend"] = "main_llm"
            metadata["fallback_used"] = bool(utility_error)
            metadata["model"] = _public_model_metadata(llm_model_config, llm_resolution or {})
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
                "backend": metadata.get("backend") or "main_llm",
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
    session = _set_generated_title(session_store, session_id, title, done)
    _record_run_title_metadata(run_store, run_id, done)
    _emit_session_updated(event_bus, session)
    return done


def _source_user_text(message_store: Any, source_message_id: str, fallback_user_text: str) -> str:
    if message_store is not None and source_message_id:
        try:
            message = message_store.get_message(source_message_id)
            if getattr(message, "role", "") == "user":
                return str(message.content or "")
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
