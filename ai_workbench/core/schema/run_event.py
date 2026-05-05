from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class RunEventSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    session_id: str
    type: str
    message: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
