"""User identities, independent of the Characters that own conversations."""

from datetime import datetime
from uuid import uuid4

from pydantic import Field, field_serializer, field_validator

from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.time import isoformat_utc, utc_now


USER_PERSONA_ID = "00000000-0000-4000-8000-000000000004"


class PersonaInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    avatar_attachment_id: str | None = None
    background: str = Field(default="", max_length=100000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Persona name must not be empty")
        return value.strip()


class PersonaIdentity(StrictModel):
    id: str
    name: str
    avatar_attachment_id: str | None


class Persona(PersonaInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_time(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @property
    def is_protected(self) -> bool:
        return self.id == USER_PERSONA_ID

    def public_response(self) -> dict:
        return {**self.model_dump(mode="json"), "is_protected": self.is_protected}

    def identity(self) -> PersonaIdentity:
        return PersonaIdentity(id=self.id, name=self.name, avatar_attachment_id=self.avatar_attachment_id)


def seed_personas() -> list[Persona]:
    return [Persona(id=USER_PERSONA_ID, name="User")]
