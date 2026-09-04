"""Static prompt target contract used by the chat runner."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.schema.context_policy import ContextPolicy


class PromptTarget(BaseModel):
    """A code-defined prompt target; it is not a user-extensible record."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    system_prompt: str = ""
    context_policy: ContextPolicy = Field(default_factory=lambda: ContextPolicy(mode="session"))
    model_profile_id: str | None = None
    generation: dict[str, Any] = Field(default_factory=dict)
    public: bool = False


__all__ = ["PromptTarget"]
