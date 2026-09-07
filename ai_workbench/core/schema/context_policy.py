from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "current_message", "recent_messages", "session", "selected_message"]
    max_messages: Optional[int] = Field(default=None, ge=1, le=10000)
    max_chars: Optional[int] = Field(default=None, ge=1, le=1000000)
    include_system_prompt: StrictBool = True
    include_attachments: Literal["none", "explicit"] = "explicit"
