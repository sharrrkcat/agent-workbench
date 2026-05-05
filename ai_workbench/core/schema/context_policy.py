from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "current_message", "recent_messages", "session", "selected_message"]
    max_messages: Optional[int] = None
    max_chars: Optional[int] = None
    include_system_prompt: bool = True
    include_attachments: Literal["none", "explicit"] = "none"
    include_last_agent_message: bool = False
    include_original_user_message: bool = False

