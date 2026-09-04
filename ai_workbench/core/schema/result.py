from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    run_id: str = ""
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
