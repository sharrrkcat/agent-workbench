from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    run_id: str
    data: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class RunResult(CommandResult):
    pass


class CapabilityCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
