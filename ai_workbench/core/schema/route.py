from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RouteKind(str, Enum):
    RESUME = "resume"
    COMMAND = "command"
    AGENT = "agent"
    ERROR = "error"


class RouteTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RouteKind
    session_id: str
    raw_input: str
    target_id: Optional[str] = None
    action_id: Optional[str] = None
    args: str = ""
    run_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

