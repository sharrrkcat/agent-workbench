"""Durable facts, explicit ownership and bounded memory operations."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, StrictBool, field_serializer, field_validator, model_validator

from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.time import isoformat_utc, utc_now


MemoryPool = Literal["character", "general"]
MemoryIsolation = Literal["shared", "block_outgoing", "block_incoming", "isolated"]
MemoryStatus = Literal["active", "needs_review", "deleted"]
MEMORY_TOOL_NAMES = frozenset({"memory_list", "memory_search", "memory_read", "memory_write", "memory_forget"})
MEMORY_READ_TOOLS = frozenset({"memory_list", "memory_search", "memory_read"})


class MemoryEvidence(StrictModel):
    message_id: str
    digest: str


class MemoryOrigin(StrictModel):
    character_id: str
    persona_id: str
    session_id: str | None = None
    run_id: str | None = None
    evidence: list[MemoryEvidence] = Field(default_factory=list, max_length=8)


class MemoryPublication(StrictModel):
    memory_id: str
    revision: int = Field(ge=1, strict=True)


class MemoryContent(StrictModel):
    summary: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("summary", "body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Memory text must not be empty")
        return value.strip()


class MemoryCreate(MemoryContent):
    pool: MemoryPool = "character"
    character_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    session_id: str | None = None
    source_message_id: str | None = None
    pinned: StrictBool = False

    @model_validator(mode="after")
    def general_has_no_session(self):
        if self.pool == "general" and self.session_id is not None:
            raise ValueError("General memories do not belong to a Session")
        return self


class MemoryEdit(MemoryContent):
    expected_revision: int = Field(ge=1, strict=True)
    status: Literal["active", "needs_review"] = "active"
    pinned: StrictBool = False


class MemoryRevision(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)


class MemoryEntry(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    revision: int = Field(default=1, ge=1, strict=True)
    pool: MemoryPool
    character_id: str
    persona_id: str
    session_id: str | None = None
    summary: str
    body: str
    status: MemoryStatus = "active"
    managed_by: Literal["user", "model"] = "user"
    pinned: bool = False
    origin: MemoryOrigin
    publication: MemoryPublication | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    observed_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", "observed_at", when_used="json")
    def serialize_time(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class MemoryPreview(StrictModel):
    id: str
    revision: int
    pool: MemoryPool
    character_id: str
    persona_id: str
    session_id: str | None
    summary: str
    status: MemoryStatus
    managed_by: Literal["user", "model"]
    pinned: bool
    observed_at: datetime
    updated_at: datetime

    @field_serializer("observed_at", "updated_at", when_used="json")
    def serialize_time(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @classmethod
    def from_entry(cls, entry: MemoryEntry):
        return cls.model_validate(entry.model_dump(include=set(cls.model_fields)))


class MemoryPage(StrictModel):
    items: list[MemoryPreview]
    total: int
    next_offset: int | None


class MemoryView(StrictModel):
    session_id: str
    character_id: str
    persona_id: str
    imports: bool
    general: bool
    enabled: bool
    version: int


class MemoryWrite(MemoryContent):
    id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    source_message_ids: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def update_revision(self):
        if (self.id is None) != (self.expected_revision is None):
            raise ValueError("Updating a memory requires its id and expected_revision")
        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError("Source messages must be unique")
        return self


class MemoryMutation(StrictModel):
    tool_call_id: str
    operation: Literal["write", "forget"]
    entry: MemoryEntry
    expected_revision: int | None


class MemoryRunState(StrictModel):
    view: MemoryView
    history_version: int
    allowance: int = 0
    references: dict[str, int] = Field(default_factory=dict)
    evidence: list[MemoryEvidence] = Field(default_factory=list)
    mutations: list[MemoryMutation] = Field(default_factory=list, max_length=8)
    read_calls: dict[str, list[str]] = Field(default_factory=dict)


class MemoryContextReference(StrictModel):
    id: str
    revision: int
    character_id: str
    persona_id: str
    session_id: str | None
    pool: MemoryPool
    reason: Literal["pinned", "literal", "recent", "tool"]


class MemoryDeletionPreview(StrictModel):
    revision: str
    local: list[MemoryPreview]
    general: list[MemoryPreview]


class MemoryDeletionChoice(StrictModel):
    expected_revision: str | None = None
    local: Literal["delete", "keep", "transfer", "publish"] | None = None
    general: Literal["delete", "keep"] | None = None
    target_character_id: str | None = None
