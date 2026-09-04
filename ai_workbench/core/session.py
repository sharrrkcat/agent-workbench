from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.time import isoformat_utc, utc_now


class Session(BaseModel):
    """A conversation container with no executable-agent identity."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str = ""
    context_mode: Literal["single_assistant", "group_transcript"] = "single_assistant"
    waiting_run_id: str | None = None
    llm_profile_id: str | None = None
    last_announced_llm_profile_id: str | None = None
    title_generation_state: Literal["pending", "done", "skipped", "failed", "manual"] = "pending"
    title_generation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""
