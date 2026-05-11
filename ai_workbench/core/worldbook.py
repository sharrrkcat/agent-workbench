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


class MemoryWorldbookStore:
    def __init__(self) -> None:
        self._settings = WorldbookSettings()
        self._worldbooks: dict[str, Worldbook] = {}
        self._entries: dict[str, WorldbookEntry] = {}
        self._bindings: dict[str, list[SessionWorldbookBinding]] = {}

    def get_settings(self) -> WorldbookSettings:
        return self._settings

    def patch_settings(self, values: dict[str, Any]) -> WorldbookSettings:
        patch = WorldbookSettingsPatch.model_validate(values)
        self._settings = self._settings.model_copy(update={**patch.model_dump(exclude_unset=True), "updated_at": utc_now()})
        return self._settings

    def list_worldbooks(self) -> list[Worldbook]:
        return [_with_counts(worldbook, self._entries.values(), self._bindings) for worldbook in self._worldbooks.values()]

    def create_worldbook(self, worldbook: Worldbook) -> Worldbook:
        self._worldbooks[worldbook.id] = worldbook
        return _with_counts(worldbook, self._entries.values(), self._bindings)

    def get_worldbook(self, worldbook_id: str) -> Worldbook:
        if worldbook_id not in self._worldbooks:
            raise KeyError(f"unknown worldbook: {worldbook_id}")
        return _with_counts(self._worldbooks[worldbook_id], self._entries.values(), self._bindings)

    def update_worldbook(self, worldbook_id: str, values: dict[str, Any]) -> Worldbook:
        current = self.get_worldbook(worldbook_id)
        updated = current.model_copy(update={**values, "updated_at": utc_now()})
        self._worldbooks[worldbook_id] = Worldbook.model_validate(updated.model_dump(exclude={"entry_count", "active_binding_count"}))
        return self.get_worldbook(worldbook_id)

    def delete_worldbook(self, worldbook_id: str) -> Worldbook:
        deleted = self.get_worldbook(worldbook_id)
        self._worldbooks.pop(worldbook_id, None)
        self._entries = {entry_id: entry for entry_id, entry in self._entries.items() if entry.worldbook_id != worldbook_id}
        for session_id, bindings in list(self._bindings.items()):
            self._bindings[session_id] = [binding for binding in bindings if binding.worldbook_id != worldbook_id]
        return deleted

    def list_entries(self, worldbook_id: str) -> list[WorldbookEntry]:
        self.get_worldbook(worldbook_id)
        return sorted(
            [entry for entry in self._entries.values() if entry.worldbook_id == worldbook_id],
            key=lambda item: (item.sort_order, item.created_at),
        )

    def create_entry(self, entry: WorldbookEntry) -> WorldbookEntry:
        self.get_worldbook(entry.worldbook_id)
        self._entries[entry.id] = entry
        return entry

    def get_entry(self, entry_id: str) -> WorldbookEntry:
        if entry_id not in self._entries:
            raise KeyError(f"unknown worldbook entry: {entry_id}")
        return self._entries[entry_id]

    def update_entry(self, entry_id: str, values: dict[str, Any]) -> WorldbookEntry:
        current = self.get_entry(entry_id)
        updated = current.model_copy(update={**values, "updated_at": utc_now()})
        self._entries[entry_id] = WorldbookEntry.model_validate(updated.model_dump())
        return self._entries[entry_id]

    def delete_entry(self, entry_id: str) -> WorldbookEntry:
        entry = self.get_entry(entry_id)
        self._entries.pop(entry_id, None)
        return entry

    def reorder_entries(self, worldbook_id: str, entry_ids: list[str]) -> list[WorldbookEntry]:
        existing = self.list_entries(worldbook_id)
        if {entry.id for entry in existing} != set(entry_ids):
            raise ValueError("Reorder ids must exactly match entries in this worldbook.")
        for index, entry_id in enumerate(entry_ids):
            self._entries[entry_id] = self._entries[entry_id].model_copy(update={"sort_order": (index + 1) * 10, "updated_at": utc_now()})
        return self.list_entries(worldbook_id)

    def list_session_bindings(self, session_id: str) -> list[SessionWorldbookBinding]:
        bindings = self._bindings.get(session_id, [])
        return sorted([self._binding_with_worldbook(binding) for binding in bindings], key=lambda item: (item.sort_order, item.created_at))

    def replace_session_bindings(self, session_id: str, worldbook_ids: list[str]) -> tuple[list[SessionWorldbookBinding], list[str]]:
        warnings: list[str] = []
        bindings: list[SessionWorldbookBinding] = []
        seen: set[str] = set()
        now = utc_now()
        for index, worldbook_id in enumerate(worldbook_ids):
            if worldbook_id in seen:
                continue
            worldbook = self.get_worldbook(worldbook_id)
            if not worldbook.enabled:
                warnings.append(f"Worldbook is disabled and was not bound: {worldbook_id}")
                continue
            seen.add(worldbook_id)
            bindings.append(
                SessionWorldbookBinding(
                    id=str(uuid4()),
                    session_id=session_id,
                    worldbook_id=worldbook_id,
                    enabled=True,
                    sort_order=(index + 1) * 10,
                    created_at=now,
                    updated_at=now,
                    worldbook=worldbook,
                )
            )
        self._bindings[session_id] = bindings
        return self.list_session_bindings(session_id), warnings

    def delete_session_bindings(self, session_id: str) -> None:
        self._bindings.pop(session_id, None)

    def _binding_with_worldbook(self, binding: SessionWorldbookBinding) -> SessionWorldbookBinding:
        worldbook = self._worldbooks.get(binding.worldbook_id)
        return binding.model_copy(update={"worldbook": _with_counts(worldbook, self._entries.values(), self._bindings) if worldbook else None})


def _with_counts(worldbook: Worldbook, entries, bindings: dict[str, list[SessionWorldbookBinding]]) -> Worldbook:
    entry_count = sum(1 for entry in entries if entry.worldbook_id == worldbook.id)
    active_binding_count = sum(
        1
        for session_bindings in bindings.values()
        for binding in session_bindings
        if binding.worldbook_id == worldbook.id and binding.enabled
    )
    return worldbook.model_copy(update={"entry_count": entry_count, "active_binding_count": active_binding_count})
