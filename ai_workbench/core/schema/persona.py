"""Database persona data and the resolved configuration of one chat run."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_serializer, field_validator

from ai_workbench.core.models.schema import GenerationParameters, StrictModel
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.time import isoformat_utc, utc_now


COGITA_PERSONA_ID = "00000000-0000-4000-8000-000000000003"
USER_PERSONA_ID = "00000000-0000-4000-8000-000000000004"
PersonaCollection = Literal["user", "agent", "roleplay_user", "character"]
CreatablePersonaCollection = Literal["agent", "roleplay_user", "character"]


class PersonaInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    avatar_attachment_id: str | None = None
    system_prompt: str = Field(default="", max_length=100000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Persona name must not be empty")
        return value.strip()


class PersonaCreate(PersonaInput):
    collection: CreatablePersonaCollection


class PersonaIdentity(StrictModel):
    id: str
    name: str
    avatar_attachment_id: str | None


class Persona(PersonaInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    collection: PersonaCollection
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_time(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @property
    def is_protected(self) -> bool:
        return self.id in {USER_PERSONA_ID, COGITA_PERSONA_ID}

    @property
    def resource_kind(self) -> Literal["knowledge", "worldbook"]:
        return "knowledge" if self.collection in {"user", "agent"} else "worldbook"

    def public_response(self) -> dict:
        return {**self.model_dump(mode="json"), "is_protected": self.is_protected}

    def identity(self) -> PersonaIdentity:
        return PersonaIdentity(id=self.id, name=self.name, avatar_attachment_id=self.avatar_attachment_id)


class ConfigurationSources(StrictModel):
    persona: Literal["session", "project"]
    context: Literal["session", "project"]
    temperature: Literal["session", "project", "model"]
    harness: Literal["session", "project"]
    tools: Literal["session", "project"]


class ResolvedChatConfig(StrictModel):
    session_kind: Literal["ordinary", "workspace"]
    project_id: str | None
    project_system_prompt: str = ""
    sources: ConfigurationSources
    persona_id: str
    persona_name: str
    avatar_attachment_id: str | None = None
    system_prompt: str
    user_persona_id: str
    user_persona_prompt: str
    context_policy: ContextPolicy
    model_profile_id: str | None
    model_source: Literal["session", "project", "global"]
    generation: GenerationParameters
    harness_enabled: bool
    tools_allowed: list[str]
    knowledge_base_ids: list[str]

    def public_summary(self) -> dict:
        return self.model_dump(mode="json", exclude={"system_prompt", "project_system_prompt", "user_persona_prompt"})


def seed_personas() -> list[Persona]:
    return [
        Persona(id=COGITA_PERSONA_ID, collection="agent", name="Cogita", system_prompt="You are a helpful assistant."),
        Persona(id=USER_PERSONA_ID, collection="user", name="User"),
    ]
