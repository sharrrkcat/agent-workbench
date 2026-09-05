"""Auxiliary tasks use only the explicit model selection."""

from __future__ import annotations

import re

from pydantic import BaseModel, ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ChatRequest

UTILITY_MODEL_UNAVAILABLE = "UTILITY_MODEL_UNAVAILABLE"
UTILITY_OUTPUT_INVALID = "UTILITY_OUTPUT_INVALID"


class UtilityLlmError(ModelError):
    pass


class UtilityLLMService:
    def __init__(self, *, model_manager, app_settings_store):
        self.model_manager = model_manager
        self.app_settings_store = app_settings_store

    async def generate_text(self, prompt: str, *, max_tokens: int | None = None, temperature: float | None = None) -> str:
        profile_id = self.model_manager.settings.get().utility_model_profile_id
        if not profile_id:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, "Select an auxiliary model.", 503)
        values = {k: v for k, v in {"max_tokens": max_tokens, "temperature": temperature}.items() if v is not None}
        try:
            profile = self.model_manager.profile(profile_id, "llm")
            response = await self.model_manager.chat(profile.id, ChatRequest(
                model=profile.alias, messages=[{"role": "user", "content": prompt}], **values,
            ))
        except ModelError as exc:
            raise UtilityLlmError(UTILITY_MODEL_UNAVAILABLE, exc.message, exc.status) from exc
        if response.message.tool_calls or not isinstance(response.message.content, str) or not response.message.content.strip():
            raise UtilityLlmError(UTILITY_OUTPUT_INVALID, "Auxiliary model returned no text.")
        return response.message.content.strip()

    async def generate_json(self, prompt: str, schema: type[BaseModel], **parameters):
        raw = await self.generate_text(prompt, **parameters)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            raise UtilityLlmError(UTILITY_OUTPUT_INVALID, "Auxiliary output does not match the requested schema.") from exc

    async def generate_title(self, user_text: str) -> str | None:
        settings = self.app_settings_store.get()
        prompt = settings.session_title_prompt.replace("{user_input}", user_text[:settings.session_title_max_input_chars])
        try:
            return normalize_title(await self.generate_text(prompt, max_tokens=64, temperature=0)) or None
        except UtilityLlmError:
            return None


def normalize_title(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    text = text.strip("`\"'“”‘’").splitlines()[0].strip() if text else ""
    text = re.sub(r"^(?:title|chat title|session title|标题)\s*[:：-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[.!?。！？]+$", "", text).strip()
    return text[:80]
