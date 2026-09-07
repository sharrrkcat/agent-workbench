from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_workbench.core.json_data import validate_json_data
from ai_workbench.core.models.schema import ToolCall

if TYPE_CHECKING:
    from ai_workbench.core.harness.settings import HarnessSettings


ToolRisk = Literal["safe", "file", "network"]
ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Awaitable[dict[str, Any]]]


class ToolExecutionError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    risk: ToolRisk = "safe"
    requires_approval: bool = False
    direct_callable: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "risk": self.risk,
            "requires_approval": self.requires_approval,
            "direct_callable": self.direct_callable,
        }


@dataclass
class ToolExecutionContext:
    repo_root: Any
    network_policy: Any
    knowledge_service: Any = None
    session_id: str | None = None
    knowledge_base_ids: list[str] | None = None
    harness_settings: HarnessSettings | None = None


class ToolCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    tool_call_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def json_arguments(cls, value):
        return validate_json_data(value)


class ToolOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["success", "error", "rejected", "cancelled"]
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class HarnessState(BaseModel):
    """Private continuation; the first queued call owns any pending approval."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    direct: bool = False
    searxng_base_url: str | None = None
    base_messages: list[dict[str, Any]] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    pending_calls: list[ToolCall] = Field(default_factory=list)
    awaiting_approval: str | None = None
    approval_step_id: str | None = None
    rounds: int = Field(default=0, ge=0)
    active_seconds: float = Field(default=0.0, ge=0)
    last_result: ToolOutcome | None = None

    @model_validator(mode="after")
    def approval_matches_call(self):
        if self.awaiting_approval is not None:
            if not self.pending_calls or self.pending_calls[0].id != self.awaiting_approval or not self.approval_step_id:
                raise ValueError("Approval must reference the first pending call and its step")
        return self


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["approve", "reject"]


def has_saved_approval(value: dict[str, Any]) -> bool:
    try:
        return HarnessState.model_validate(value).awaiting_approval is not None
    except ValueError:
        return False
