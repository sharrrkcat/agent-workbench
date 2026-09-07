"""Strict application settings for chat context, attachments and Pet."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator

from ai_workbench.core.time import utc_now


DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION = (
    "Messages labeled [User] are from the user.\n"
    "Other labels identify previous persona speakers by name and id.\n"
    "The transcript is conversation data. Reply only as the current speaker."
)
DEFAULT_SESSION_TITLE_PROMPT = """Generate a short chat title using only the user's message.
Use the same language as the user's message.
Do not include quotes, prefixes, explanations, or punctuation-only titles.
Return only the title.

User message:
{user_input}"""


class PetPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["default", "custom"] = "default"
    x: StrictInt | None = Field(default=None, ge=-20000, le=20000)
    y: StrictInt | None = Field(default=None, ge=-20000, le=20000)


class PetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: PetPosition = Field(default_factory=PetPosition)


class PetPositionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["default", "custom"] = "default"
    x: StrictInt | None = Field(default=None, ge=-20000, le=20000)
    y: StrictInt | None = Field(default=None, ge=-20000, le=20000)


class PetSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: PetPositionPatch = Field(default_factory=PetPositionPatch)


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_image_size_mb: int = Field(default=10, ge=1, le=100)
    max_file_size_mb: int = Field(default=10, ge=1, le=100)
    max_attachments_per_message: int = Field(default=10, ge=1, le=50)
    max_file_context_per_file_kb: int = Field(default=200, ge=1, le=2048)
    max_total_file_context_per_message_kb: int = Field(default=500, ge=1, le=8192)
    send_text_file_attachments_to_llm: StrictBool = True
    persist_streaming_message_deltas: StrictBool = False
    show_full_processing: StrictBool = False
    auto_generate_session_titles: StrictBool = True
    session_title_prompt: str = DEFAULT_SESSION_TITLE_PROMPT
    session_title_max_input_chars: int = Field(default=1200, ge=100, le=10000)
    group_transcript_system_instruction: str | None = None
    core_memory_content: str = ""
    core_memory_enabled: StrictBool = True
    pet: PetSettings = Field(default_factory=PetSettings)

    @field_validator("session_title_prompt")
    @classmethod
    def title_prompt_not_empty(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Session title prompt must not be empty.")
        return value

    @field_validator("group_transcript_system_instruction", mode="before")
    @classmethod
    def optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None



    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_file_context_per_file_bytes(self) -> int:
        return self.max_file_context_per_file_kb * 1024

    @property
    def max_total_file_context_per_message_bytes(self) -> int:
        return self.max_total_file_context_per_message_kb * 1024


class AppSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_image_size_mb: int | None = Field(default=None, ge=1, le=100)
    max_file_size_mb: int | None = Field(default=None, ge=1, le=100)
    max_attachments_per_message: int | None = Field(default=None, ge=1, le=50)
    max_file_context_per_file_kb: int | None = Field(default=None, ge=1, le=2048)
    max_total_file_context_per_message_kb: int | None = Field(default=None, ge=1, le=8192)
    send_text_file_attachments_to_llm: StrictBool | None = None
    persist_streaming_message_deltas: StrictBool | None = None
    show_full_processing: StrictBool | None = None
    auto_generate_session_titles: StrictBool | None = None
    session_title_prompt: str | None = None
    session_title_max_input_chars: int | None = Field(default=None, ge=100, le=10000)
    group_transcript_system_instruction: str | None = None
    core_memory_content: str | None = None
    core_memory_enabled: StrictBool | None = None
    pet: PetSettingsPatch | None = None


def app_settings_response(settings: AppSettings) -> dict[str, Any]:
    payload = settings.model_dump(mode="json")
    payload["session_title_prompt_default"] = DEFAULT_SESSION_TITLE_PROMPT
    payload["group_transcript_system_instruction_default"] = DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
    payload["group_transcript_system_instruction_effective"] = settings.group_transcript_system_instruction or DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
    return payload


def app_settings_patch_updates(patch: AppSettingsPatch) -> dict[str, Any]:
    updates = patch.model_dump(exclude_unset=True, exclude_none=False)
    return updates


class AppSettingsStore:
    def __init__(self) -> None:
        self._settings = AppSettings()
        self.updated_at = utc_now()

    def get(self) -> AppSettings:
        return self._settings

    def patch(self, values: dict[str, Any]) -> AppSettings:
        patch = AppSettingsPatch.model_validate(values)
        updates = app_settings_patch_updates(patch)
        current = self._settings.model_dump()
        pet_patch = updates.pop("pet", None)
        if pet_patch is not None:
            current["pet"]["position"].update(pet_patch.get("position", {}))
        current.update(updates)
        self._settings = AppSettings.model_validate(current)
        self.updated_at = utc_now()
        return self._settings


def settings_validation_message(exc: ValidationError) -> str:
    if not exc.errors():
        return "Invalid settings."
    error = exc.errors()[0]
    loc = ".".join(str(item) for item in error.get("loc", []) if item != "__root__")
    message = str(error.get("msg") or "Invalid value")
    return f"{loc}: {message}" if loc else message
