from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_serializer, model_validator

from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID
from ai_workbench.core.time import isoformat_utc, utc_now


class SessionGenerationParameters(StrictModel):
    temperature: float | None = Field(default=None, ge=0, le=2)


class Session(BaseModel):
    """A conversation container with no executable-agent identity."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str = ""
    waiting_run_id: str | None = None
    model_profile_id: str | None = None
    persona_id: str = COGITA_PERSONA_ID
    context_policy: ContextPolicy = Field(default_factory=lambda: ContextPolicy(mode="session"))
    generation: SessionGenerationParameters = Field(default_factory=SessionGenerationParameters)
    harness_enabled: StrictBool = False
    tools_allowed: list[str] = Field(default_factory=list, max_length=128)
    title_generation_state: Literal["pending", "done", "skipped", "failed", "manual"] = "pending"
    title_generation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_tools(self):
        if len(self.tools_allowed) != len(set(self.tools_allowed)):
            raise ValueError("Tool names must be unique")
        return self

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @field_serializer("generation")
    def serialize_generation(self, value: SessionGenerationParameters) -> dict[str, Any]:
        return value.model_dump(exclude_none=True)
