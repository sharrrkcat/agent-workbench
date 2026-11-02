"""Private working memory and public, body-free window references."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


CONTEXT_TOOL_NAMES = frozenset({"context_list", "context_search", "context_read", "context_checkpoint_update"})


class RetrievalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RetrievalCheckpoint(RetrievalModel):
    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    text: str = ""
    references: list[str] = Field(default_factory=list, max_length=64)


class RetrievalBoundary(RetrievalModel):
    turn_id: str
    message_id: str
    created_at: datetime
    qq_batch_id: int | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def stored_timestamp(cls, value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value

    @property
    def key(self):
        return self.qq_batch_id if self.qq_batch_id is not None else (self.created_at, self.message_id)


class RetrievalReference(RetrievalModel):
    window_id: str
    previous_window_id: str | None = None
    boundary_message_id: str | None = None
    boundary_qq_batch_id: int | None = None
    transcript_end: int = Field(default=0, ge=0)
    memory_id: str
    progress_id: str | None = None


class SessionRetrievalState(RetrievalModel):
    session_id: str
    history_version: int = Field(ge=0)
    include_attachments: Literal["none", "explicit"]
    window_id: str = Field(default_factory=lambda: str(uuid4()))
    previous_window_id: str | None = None
    boundary: RetrievalBoundary | None = None
    memory: RetrievalCheckpoint = Field(default_factory=RetrievalCheckpoint)


class RunRetrievalState(RetrievalModel):
    session: SessionRetrievalState
    input_id: str | None = None
    history_enabled: bool
    progress: RetrievalCheckpoint = Field(default_factory=RetrievalCheckpoint)
    history_boundaries: list[RetrievalBoundary] = Field(default_factory=list)
    transcript_end: int = Field(default=0, ge=0)
    business_rounds: int = Field(default=0, ge=0, le=8)
    context_rounds: int = Field(default=0, ge=0, le=8)
    input_budget_tokens: int = Field(default=0, ge=0)
    checkpoint_tokens: int = Field(default=0, ge=0)
    checkpoint_body_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    def reference(self):
        boundary = self.session.boundary
        return RetrievalReference(window_id=self.session.window_id, previous_window_id=self.session.previous_window_id,
            boundary_message_id=boundary.message_id if boundary else None,
            boundary_qq_batch_id=boundary.qq_batch_id if boundary else None, transcript_end=self.transcript_end,
            memory_id=self.session.memory.checkpoint_id, progress_id=self.progress.checkpoint_id)


class ResetOutcome(RetrievalModel):
    operation: Literal["reset"] = "reset"
    status: Literal["reset", "not_needed"]
    reason: Literal["no_history", "below_target"] | None = None
    retrieval: RetrievalReference
    input_tokens_before: int | None = None
    input_tokens_after: int
