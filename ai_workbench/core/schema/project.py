"""Project types share metadata, with distinct Workspace and Timeline settings."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, StrictBool, TypeAdapter, field_serializer, field_validator

from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from ai_workbench.core.session import ChatSettings
from ai_workbench.core.time import isoformat_utc, utc_now


class ProjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    context_policy: ContextPolicy
    model_profile_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Project name must not be empty")
        return value.strip()


class WorkspaceInput(ProjectInput):
    kind: Literal["workspace"]
    agent_persona_id: str
    cogita_persona_id: Literal[USER_PERSONA_ID]
    harness_enabled: StrictBool
    tools_allowed: list[str] = Field(max_length=128)
    system_prompt: str = Field(default="", max_length=100000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("tools_allowed")
    @classmethod
    def unique_tools(cls, value: list[str]) -> list[str]:
        return ChatSettings.unique_tools(value)


class TimelineInput(ProjectInput):
    kind: Literal["timeline"]
    character_persona_id: str
    user_persona_id: str
    worldbook_ids: list[str] = Field(default_factory=list, max_length=128)


ProjectCreate = Annotated[WorkspaceInput | TimelineInput, Field(discriminator="kind")]


class ProjectMetadata(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class WorkspaceProject(WorkspaceInput, ProjectMetadata):
    pass


class TimelineProject(TimelineInput, ProjectMetadata):
    pass


Project = Annotated[WorkspaceProject | TimelineProject, Field(discriminator="kind")]
project_adapter = TypeAdapter(Project)
