"""Every conversation belongs to one immutable Character."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, field_serializer

from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.schema.chat_config import SessionOverrides
from ai_workbench.core.time import isoformat_utc, utc_now


SessionKind = Literal["normal", "qqbot"]


class SessionBase(StrictModel):
    session_id: str
    character_id: str
    history_version: int = 0
    title: str = ""
    waiting_run_id: str | None = None
    title_generation_state: Literal["pending", "done", "skipped", "failed", "manual"] = "pending"
    title_generation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class NormalSession(SessionBase):
    kind: Literal["normal"] = "normal"
    overrides: SessionOverrides = Field(default_factory=SessionOverrides)

    @field_serializer("overrides")
    def serialize_overrides(self, value: SessionOverrides) -> dict[str, Any]:
        return value.model_dump(exclude_none=True)


class QQSession(SessionBase):
    kind: Literal["qqbot"] = "qqbot"
    target_kind: Literal["group", "friend"]
    target_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")


Session = Annotated[NormalSession | QQSession, Field(discriminator="kind")]
session_adapter = TypeAdapter(Session)


def parse_session(values: dict) -> Session:
    return session_adapter.validate_python(values)
