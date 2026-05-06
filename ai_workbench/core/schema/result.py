from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from ai_workbench.core.schema.message import ImageGalleryPayload, ImagePayload, RichContentPayload


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    run_id: str
    data: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    output_type: str = "text"


class RunResult(CommandResult):
    pass


class CapabilityCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    output_type: str = "text"
