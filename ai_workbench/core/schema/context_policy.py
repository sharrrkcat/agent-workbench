from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_messages: Optional[int] = Field(default=100, ge=0, le=10000,
        description="History message limit; null includes all available history, zero excludes history. Current input is not counted.")
    max_chars: Optional[int] = Field(default=100000, ge=1, le=1000000)
    include_attachments: Literal["none", "explicit"] = "explicit"
