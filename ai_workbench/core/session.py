from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.time import isoformat_utc, utc_now


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str = ""
    default_agent_id: str = "chat"
    waiting_run_id: Optional[str] = None
    llm_profile_id: Optional[str] = None
    last_announced_llm_profile_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""
