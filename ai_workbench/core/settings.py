"""Strict application settings for chat context, attachments and Pet."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

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
    x: int | None = None
    y: int | None = None

    @field_validator("x", "y")
    @classmethod
    def coordinate_range(cls, value: int | None) -> int | None:
        if value is not None and not -20000 <= value <= 20000:
            raise ValueError("position coordinates are out of range")
        return value


class PetBubbleTexts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idle: str = ""
    waiting: str = "等你一下"
    done: str = "完成啦"
    failed: str = "出错了"
    cancelled: str = "已取消"
    interrupted: str = "已中断"
    wake: str = "我来啦"
    tuck: str = "先睡一会儿"
    status: str = "我在这里"
    select: str = "换好啦"
    reload: str = "重新扫描完成"
    no_pet: str = "还没有可用的宠物"
    import_success: str = "导入成功"
    import_failed: str = "导入失败"
    delete_success: str = "已删除"
    delete_failed: str = "删除失败"


class PetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pet_enabled: StrictBool = True
    default_pet_id: str = ""
    pet_scale: float = Field(default=0.5, ge=0.5, le=2.0)
    show_status_bubble: StrictBool = True
    bubble_offset_x: int = Field(default=12, ge=-240, le=240)
    bubble_offset_y: int = Field(default=-12, ge=-240, le=240)
    jump_on_hover: StrictBool = True
    running_prefix: str = "正在"
    position: PetPosition = Field(default_factory=PetPosition)
    bubble_texts: PetBubbleTexts = Field(default_factory=PetBubbleTexts)


class PetPositionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["default", "custom"] | None = None
    x: int | None = Field(default=None, ge=-20000, le=20000)
    y: int | None = Field(default=None, ge=-20000, le=20000)


class PetBubbleTextsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idle: str | None = None
    waiting: str | None = None
    done: str | None = None
    failed: str | None = None
    cancelled: str | None = None
    interrupted: str | None = None
    wake: str | None = None
    tuck: str | None = None
    status: str | None = None
    select: str | None = None
    reload: str | None = None
    no_pet: str | None = None
    import_success: str | None = None
    import_failed: str | None = None
    delete_success: str | None = None
    delete_failed: str | None = None


class PetSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pet_enabled: StrictBool | None = None
    default_pet_id: str | None = None
    pet_scale: float | None = Field(default=None, ge=0.5, le=2.0)
    show_status_bubble: StrictBool | None = None
    bubble_offset_x: int | None = Field(default=None, ge=-240, le=240)
    bubble_offset_y: int | None = Field(default=None, ge=-240, le=240)
    jump_on_hover: StrictBool | None = None
    running_prefix: str | None = None
    position: PetPositionPatch | None = None
    bubble_texts: PetBubbleTextsPatch | None = None


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_image_size_mb: int = Field(default=10, ge=1, le=100)
    max_file_size_mb: int = Field(default=10, ge=1, le=100)
    max_attachments_per_message: int = Field(default=10, ge=1, le=50)
    max_file_context_per_file_kb: int = Field(default=200, ge=1, le=2048)
    max_total_file_context_per_message_kb: int = Field(default=500, ge=1, le=8192)
    send_text_file_attachments_to_llm: StrictBool = True
    persist_streaming_message_deltas: StrictBool = False
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
            pet_values = current["pet"] if isinstance(current.get("pet"), dict) else self._settings.pet.model_dump()
            pet_data = pet_patch if isinstance(pet_patch, dict) else {}
            for key in ("position", "bubble_texts"):
                nested = pet_data.pop(key, None)
                if isinstance(nested, dict):
                    pet_values[key] = {**(pet_values.get(key) or {}), **nested}
            pet_values.update(pet_data)
            current["pet"] = pet_values
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
