from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.time import isoformat_utc, utc_now


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class RunStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    kind: Literal["agent", "command", "action", "resume"]
    status: RunStatus = RunStatus.PENDING
    target_id: str
    action_id: Optional[str] = None
    current_step: str = ""
    stage: str = ""
    progress_message: str = ""
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    cancel_requested: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("started_at", "finished_at", "created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return isoformat_utc(value)


class RunStepSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    run_id: str
    parent_step_id: Optional[str] = None
    label: str
    status: RunStepStatus = RunStepStatus.PENDING
    message: str = ""
    order: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("started_at", "finished_at", "created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return isoformat_utc(value)
