"""Private rolling checkpoints and public source identities."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.time import utc_now


class CompactionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    checkpoint_id: str
    boundary_message_id: str
    covered_messages: int = Field(ge=1)
    model_profile_id: str
    step_id: str


class ContextCheckpoint(CompactionReference):
    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    summary: str = Field(min_length=1)
    boundary_created_at: datetime
    history_version: int = Field(ge=0)
    include_attachments: Literal["none", "explicit"]
    format_version: Literal[1] = 1
    created_at: datetime = Field(default_factory=utc_now)
    input_tokens_before: int | None = Field(default=None, ge=0)
    input_tokens_after: int = Field(ge=0)
    counting: Literal["native", "estimated"]

    def reference(self) -> CompactionReference:
        return CompactionReference.model_validate(self.model_dump(include=set(CompactionReference.model_fields)))


class CompactionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["compacted", "not_needed"]
    reason: Literal["no_history", "below_target"] | None = None
    checkpoint: CompactionReference | None = None
    input_tokens_before: int | None = Field(default=None, ge=0)
    input_tokens_after: int | None = Field(default=None, ge=0)
