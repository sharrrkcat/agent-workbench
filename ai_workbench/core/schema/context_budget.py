"""Model-window configuration and public per-call budget statistics."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContextLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    window_tokens: int | None = Field(default=None, ge=512)
    output_tokens: int | None = Field(default=None, ge=1)


class ContextBudgetStats(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    configured_window_tokens: int = Field(ge=512)
    window_tokens: int = Field(ge=1)
    input_budget_tokens: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    counting: Literal["native", "estimated"]
    output_tokens: int = Field(ge=1)
    margin_tokens: int = Field(ge=0)
    removed_turns: int = Field(ge=0)
