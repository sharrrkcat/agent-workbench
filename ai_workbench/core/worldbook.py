from datetime import datetime
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ai_workbench.core.time import utc_now


ActivationMode = Literal["always", "keyword"]
MAX_KEYWORD_PATTERN_CHARS = 500
MAX_KEYWORDS_TEXT_CHARS = 20_000
MAX_ENTRY_CONTENT_CHARS = 200_000
CONTENT_PREVIEW_CHARS = 800


class WorldbookSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = 1
    worldbook_enabled_for_prompt_agents: StrictBool = True
    worldbook_enabled_for_script_agents: StrictBool = False
    worldbook_max_entries_per_call: int = Field(default=20, ge=1, le=200)
    worldbook_max_context_chars: int = Field(default=8000, ge=1000, le=200000)
    worldbook_regex_case_insensitive: StrictBool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorldbookSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worldbook_enabled_for_prompt_agents: StrictBool | None = None
    worldbook_enabled_for_script_agents: StrictBool | None = None
    worldbook_max_entries_per_call: int | None = Field(default=None, ge=1, le=200)
    worldbook_max_context_chars: int | None = Field(default=None, ge=1000, le=200000)
    worldbook_regex_case_insensitive: StrictBool | None = None


class Worldbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    enabled: StrictBool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    entry_count: int = 0
    active_binding_count: int = 0

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Name must not be empty.")
        return text

    @field_validator("description", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value)


class WorldbookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    enabled: StrictBool = True


class WorldbookPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    enabled: StrictBool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return Worldbook(name=value).name


class WorldbookEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    worldbook_id: str
    name: str
    keywords_text: str = Field(default="", max_length=MAX_KEYWORDS_TEXT_CHARS)
    content: str = Field(max_length=MAX_ENTRY_CONTENT_CHARS)
    activation_mode: ActivationMode = "keyword"
    enabled: StrictBool = True
    sort_order: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Name must not be empty.")
        return text

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Content must not be empty.")
        return text

    @field_validator("keywords_text")
    @classmethod
    def _keywords(cls, value: str) -> str:
        text = "" if value is None else str(value)
        validate_keyword_patterns(text)
        return text


class WorldbookEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    keywords_text: str = Field(default="", max_length=MAX_KEYWORDS_TEXT_CHARS)
    content: str = Field(max_length=MAX_ENTRY_CONTENT_CHARS)
    activation_mode: ActivationMode = "keyword"
    enabled: StrictBool = True
    sort_order: int | None = None


class WorldbookEntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    keywords_text: str | None = Field(default=None, max_length=MAX_KEYWORDS_TEXT_CHARS)
    content: str | None = Field(default=None, max_length=MAX_ENTRY_CONTENT_CHARS)
    activation_mode: ActivationMode | None = None
    enabled: StrictBool | None = None
    sort_order: int | None = None


class SessionWorldbookBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    worldbook_id: str
    enabled: StrictBool = True
    sort_order: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    worldbook: Worldbook | None = None


def keyword_patterns(keywords_text: str) -> list[str]:
    return [line.strip() for line in str(keywords_text or "").splitlines() if line.strip()]


def validate_keyword_patterns(keywords_text: str) -> None:
    for pattern in keyword_patterns(keywords_text):
        if len(pattern) > MAX_KEYWORD_PATTERN_CHARS:
            raise ValueError("Keyword regex pattern is too long.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc


def content_preview(content: str) -> str:
    text = str(content or "")
    return text[:CONTENT_PREVIEW_CHARS]
