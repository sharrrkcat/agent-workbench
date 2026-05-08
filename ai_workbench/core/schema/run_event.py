from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.time import isoformat_utc


class RunEventSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    session_id: str
    type: str
    message: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_serializer("created_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""
