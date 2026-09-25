"""Ordinary configuration and sparse Workspace overrides have separate identities."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, TypeAdapter, field_serializer, field_validator

from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID
from ai_workbench.core.time import isoformat_utc, utc_now


class SessionGenerationParameters(StrictModel):
    temperature: float | None = Field(default=None, ge=0, le=2)


SessionKind = Literal["ordinary", "workspace", "timeline"]


class ChatSettings(StrictModel):
    model_profile_id: str | None = None
    persona_id: str = COGITA_PERSONA_ID
    context_policy: ContextPolicy = Field(default_factory=lambda: ContextPolicy(mode="session"))
    generation: SessionGenerationParameters = Field(default_factory=SessionGenerationParameters)
    harness_enabled: StrictBool = False
    tools_allowed: list[str] = Field(default_factory=list, max_length=128)
    @field_validator("tools_allowed")
    @classmethod
    def unique_tools(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Tool names must be unique")
        return value

    @field_serializer("generation")
    def serialize_generation(self, value: SessionGenerationParameters) -> dict[str, Any]:
        return value.model_dump(exclude_none=True)


class WorkspaceOverrides(StrictModel):
    """Null means inheritance; false, zero and an empty tool list are overrides."""

    persona_id: str | None = None
    model_profile_id: str | None = None
    context_policy: ContextPolicy | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    harness_enabled: StrictBool | None = None
    tools_allowed: list[str] | None = Field(default=None, max_length=128)

    @field_validator("tools_allowed")
    @classmethod
    def unique_tools(cls, value: list[str] | None) -> list[str] | None:
        return ChatSettings.unique_tools(value) if value is not None else None


class SessionBase(StrictModel):
    session_id: str
    title: str = ""
    waiting_run_id: str | None = None
    title_generation_state: Literal["pending", "done", "skipped", "failed", "manual"] = "pending"
    title_generation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class OrdinarySession(SessionBase, ChatSettings):
    kind: Literal["ordinary"] = "ordinary"
    project_id: None = None


class WorkspaceSession(SessionBase):
    kind: Literal["workspace"] = "workspace"
    project_id: str
    overrides: WorkspaceOverrides = Field(default_factory=WorkspaceOverrides)

    @field_serializer("overrides")
    def serialize_overrides(self, value: WorkspaceOverrides) -> dict[str, Any]:
        return value.model_dump(exclude_none=True)


# Timeline is a reserved identity, not a constructible conversation in this release.
Session = Annotated[OrdinarySession | WorkspaceSession, Field(discriminator="kind")]
session_adapter = TypeAdapter(Session)


def parse_session(values: dict) -> OrdinarySession | WorkspaceSession:
    return session_adapter.validate_python(values)
