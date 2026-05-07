from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RunStepSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    run_id: str
    label: str
    status: RunStepStatus = RunStepStatus.PENDING
    message: str = ""
    order: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
