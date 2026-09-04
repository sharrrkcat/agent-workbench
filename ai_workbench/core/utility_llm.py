"""Small auxiliary LLM service used for titles and validated JSON tasks."""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ai_workbench.core.settings import DEFAULT_SESSION_TITLE_PROMPT


T = TypeVar("T", bound=BaseModel)

UTILITY_MODEL_UNAVAILABLE = "UTILITY_MODEL_UNAVAILABLE"
UTILITY_OUTPUT_INVALID = "UTILITY_OUTPUT_INVALID"


class UtilityLlmService(Protocol):
    async def generate_text(self, prompt: str, *, max_tokens: int | None = None, temperature: float | None = None) -> str: ...
    async def generate_json(self, prompt: str, schema: type[T], *, max_tokens: int | None = None, temperature: float | None = None) -> T: ...
    async def generate_title(self, user_text: str) -> str | None: ...
    def unload(self) -> dict: ...


class UtilityLlmError(RuntimeError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


class UtilityLLMService:
    """Adapter around the normal LLM runtime.

    There is deliberately one configuration source: ``utility_model_profile_id``
    on AppSettings.  The service never scans model directories and never asks
    the model to perform routing.
    """

    def __init__(self, *, llm_runtime: Any = None, llm_profile_store: Any = None, provider_profile_store: Any = None, app_settings_store: Any = None) -> None:
        self.llm_runtime = llm_runtime
        self.llm_profile_store = llm_profile_store
        self.provider_profile_store = provider_profile_store
        self.app_settings_store = app_settings_store

    def _profile(self) -> Any:
        settings = self.app_settings_store.get() if self.app_settings_store is not None else None
        profile_id = getattr(settings, "utility_model_profile_id", None) if settings is not None else None
        if not profile_id:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "Utility model profile is not configured.")
        if self.llm_profile_store is None:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "Utility model profile store is unavailable.")
        try:
            profile = self.llm_profile_store.get_by_id_or_alias(profile_id)
        except KeyError as exc:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, f"Utility model profile not found: {profile_id}") from exc
        if not getattr(profile, "enabled", False) or not getattr(profile, "model_id", ""):
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "Utility model profile is unavailable.")
        return profile

    def _model_config(self, profile: Any, *, max_tokens: int | None, temperature: float | None) -> dict[str, Any]:
        provider = None
        provider_id = getattr(profile, "provider_profile_id", None)
        if provider_id and self.provider_profile_store is not None:
            try:
                provider = self.provider_profile_store.get(provider_id)
            except KeyError as exc:
                raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, f"Utility provider profile not found: {provider_id}") from exc
            if not getattr(provider, "enabled", False):
                raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "Utility provider profile is disabled.")
        config = {
            "provider": getattr(provider, "provider", None) or getattr(profile, "provider", "openai_compatible"),
            "base_url": getattr(provider, "base_url", None) or getattr(profile, "base_url", ""),
            "api_key": getattr(provider, "api_key", None) or getattr(profile, "api_key", ""),
            "model": getattr(profile, "model_id", ""),
            "model_id": getattr(profile, "model_id", ""),
            "timeout": getattr(provider, "timeout_seconds", None) or getattr(profile, "timeout", None) or 60,
            "stream": False,
        }
        if max_tokens is not None:
            config["max_tokens"] = max_tokens
        if temperature is not None:
            config["temperature"] = temperature
        return config

    async def generate_text(self, prompt: str, *, max_tokens: int | None = None, temperature: float | None = None) -> str:
        profile = self._profile()
        if self.llm_runtime is None:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "LLM runtime is unavailable.")
        config = self._model_config(profile, max_tokens=max_tokens, temperature=temperature)
        try:
            method = getattr(self.llm_runtime, "chat", None) or getattr(self.llm_runtime, "generate", None)
            if method is None:
                raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "LLM runtime does not provide a generation method.")
            if getattr(method, "__name__", "") == "generate":
                value = method(prompt=prompt, model_config=config, stream=False)
            else:
                value = method(messages=[{"role": "user", "content": prompt}], model_config=config, stream=False)
            if inspect.isawaitable(value):
                value = await value
            text = _extract_text(value)
            if not text:
                raise UtilityLlmError(UTILITY_OUTPUT_INVALID, "Utility LLM returned empty text.")
            return text
        except UtilityLlmError:
            raise
        except Exception as exc:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, str(exc) or "Utility LLM generation failed.") from exc

    async def generate_json(self, prompt: str, schema: type[T], *, max_tokens: int | None = None, temperature: float | None = None) -> T:
        raw = await self.generate_text(prompt, max_tokens=max_tokens, temperature=temperature)
        try:
            value = _parse_json_value(raw)
            return schema.model_validate(value)
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise UtilityLlmError(UTILITY_OUTPUT_INVALID, "Utility LLM output is not valid for the requested schema.") from exc

    async def generate_title(self, user_text: str) -> str | None:
        settings = self.app_settings_store.get() if self.app_settings_store is not None else None
        template = getattr(settings, "session_title_prompt", DEFAULT_SESSION_TITLE_PROMPT)
        prompt = str(template).format(user_input=str(user_text or "")[: int(getattr(settings, "session_title_max_input_chars", 1200) or 1200)])
        try:
            raw = await self.generate_text(prompt, max_tokens=64, temperature=0)
        except UtilityLlmError:
            return None
        title = normalize_title(raw)
        return title or None

    def unload(self) -> dict:
        runtime = self.llm_runtime
        unload = getattr(runtime, "unload", None) if runtime is not None else None
        if not callable(unload):
            return {"ok": True, "status": "unsupported"}
        try:
            value = unload()
            if inspect.isawaitable(value):
                # unload is intentionally synchronous in the public protocol;
                # async providers may expose a best-effort status instead. Close
                # coroutine objects so a provider implementation does not emit
                # an un-awaited coroutine warning when the result is discarded.
                close = getattr(value, "close", None)
                if callable(close):
                    close()
                return {"ok": True, "status": "requested"}
            return value if isinstance(value, dict) else {"ok": True, "status": "unloaded"}
        except Exception as exc:
            return {"ok": False, "status": "failed", "error": str(exc) or "unload failed"}


# Spelling aliases used by older internal callers are intentionally local and
# do not expose a public route or configuration namespace.
UtilityLlm = UtilityLLMService


def normalize_title(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    text = text.strip("`\"'“”‘’").splitlines()[0].strip() if text else ""
    text = re.sub(r"^(?:title|chat title|session title|标题)\s*[:：-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[.!?。！？]+$", "", text).strip()
    return text[:80]


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            return value["content"].strip()
        choices = value.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            if isinstance(message.get("content"), str):
                return message["content"].strip()
            if isinstance(first.get("text"), str):
                return first["text"].strip()
    return str(value or "").strip()


def _parse_json_value(value: str) -> Any:
    text = str(value or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for start, char in enumerate(text):
            if char not in "[{":
                continue
            closing = "}" if char == "{" else "]"
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(text)):
                current = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif current == "\\":
                        escaped = True
                    elif current == '"':
                        in_string = False
                    continue
                if current == '"':
                    in_string = True
                elif current == char:
                    depth += 1
                elif current == closing:
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start:index + 1])
    raise ValueError("invalid JSON")
