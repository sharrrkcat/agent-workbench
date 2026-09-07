"""Database persona data and the resolved configuration of one chat run."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, StrictBool, field_serializer, field_validator

from ai_workbench.core.models.schema import GenerationParameters, StrictModel
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.time import isoformat_utc, utc_now


CHAT_PERSONA_ID = "00000000-0000-4000-8000-000000000001"
TRANSLATE_PERSONA_ID = "00000000-0000-4000-8000-000000000002"


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


class Persona(PersonaInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_time(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class SessionPersona(StrictModel):
    persona_id: str
    enabled: StrictBool = True


class ResolvedChatConfig(StrictModel):
    persona_id: str
    persona_name: str
    avatar_attachment_id: str | None = None
    system_prompt: str
    context_mode: Literal["single_assistant", "group_transcript"]
    group_transcript_instruction: str
    context_policy: ContextPolicy
    model_profile_id: str | None
    model_source: Literal["session"]
    generation: GenerationParameters
    harness_enabled: bool
    tools_allowed: list[str]
    knowledge_base_ids: list[str]
    worldbook_ids: list[str]

    def public_summary(self) -> dict:
        return self.model_dump(mode="json", exclude={"system_prompt", "group_transcript_instruction"})


def seed_personas() -> list[Persona]:
    return [
        Persona(id=CHAT_PERSONA_ID, name="Chat", system_prompt="You are a helpful assistant."),
        Persona(id=TRANSLATE_PERSONA_ID, name="Translate",
                system_prompt="Translate the user's text accurately. Return only the translation."),
    ]
