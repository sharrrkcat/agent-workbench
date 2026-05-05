from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ActionInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    agent_id: str
    action_id: str
    source_message_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    input_text: str = ""
    prefill: Dict[str, Any] = Field(default_factory=dict)

