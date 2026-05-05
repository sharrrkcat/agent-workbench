from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MessageSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    session_id: str
    role: Literal["user", "assistant", "agent", "system", "tool", "command"]
    content: Any
    agent_id: Optional[str] = None
    command_name: Optional[str] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    output_type: str = "text"
    parent_message_id: Optional[str] = None
    available_actions: list = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
