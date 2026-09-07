from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_serializer, model_validator

from ai_workbench.core.models.schema import GenerationParameters
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import CHAT_PERSONA_ID, SessionPersona
from ai_workbench.core.time import isoformat_utc, utc_now


class Session(BaseModel):
    """A conversation container with no executable-agent identity."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str = ""
    context_mode: Literal["single_assistant", "group_transcript"] = "single_assistant"
    waiting_run_id: str | None = None
    model_profile_id: str | None = None
    current_persona_id: str = CHAT_PERSONA_ID
    personas: list[SessionPersona] = Field(default_factory=lambda: [SessionPersona(persona_id=CHAT_PERSONA_ID)], min_length=1, max_length=64)
    context_policy: ContextPolicy = Field(default_factory=lambda: ContextPolicy(mode="session"))
    generation: GenerationParameters = Field(default_factory=GenerationParameters)
    harness_enabled: StrictBool = False
    tools_allowed: list[str] = Field(default_factory=list, max_length=128)
    title_generation_state: Literal["pending", "done", "skipped", "failed", "manual"] = "pending"
    title_generation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_members(self):
        ids = [member.persona_id for member in self.personas]
        if len(ids) != len(set(ids)):
            raise ValueError("Session personas must be unique")
        if not any(member.enabled and member.persona_id == self.current_persona_id for member in self.personas):
            raise ValueError("Current persona must be an enabled session member")
        if len(self.tools_allowed) != len(set(self.tools_allowed)):
            raise ValueError("Tool names must be unique")
        return self

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @field_serializer("generation")
    def serialize_generation(self, value: GenerationParameters) -> dict[str, Any]:
        return value.model_dump(exclude_none=True)
