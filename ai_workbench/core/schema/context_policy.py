from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompactionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = True
    trigger_percent: int = Field(default=80, gt=0, lt=100)
    target_percent: int = Field(default=55, gt=0, lt=100)
    max_summary_tokens: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.target_percent >= self.trigger_percent:
            raise ValueError("The compaction target must be below its trigger.")
        return self


class MessageWindowPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_messages: int = Field(default=100, ge=1, le=10000)


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    history_enabled: bool = True
    strategy: Literal["token_budget", "message_window"] = "token_budget"
    include_attachments: Literal["none", "explicit"] = "explicit"
    compaction: CompactionPolicy = Field(default_factory=CompactionPolicy)
    message_window: MessageWindowPolicy = Field(default_factory=MessageWindowPolicy)


class BoundedContextPolicy(BaseModel):
    """Reserved Timeline history; this domain does not compact."""
    model_config = ConfigDict(extra="forbid", strict=True)

    max_messages: Optional[int] = Field(default=100, ge=0, le=10000,
        description="History message limit; null includes all available history, zero excludes history. Current input is not counted.")
    max_chars: Optional[int] = Field(default=100000, ge=1, le=1000000)
    include_attachments: Literal["none", "explicit"] = "explicit"
