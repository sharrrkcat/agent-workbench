import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


COMMAND_NAME_RE = re.compile(r"^/[a-zA-Z][a-zA-Z0-9_\-]*$")


class CommandSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    method: str
    description: str = ""
    safe: bool = False
    confirm: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not COMMAND_NAME_RE.match(value):
            raise ValueError(
                "command name must start with '/' and match ^/[a-zA-Z][a-zA-Z0-9_\\-]*$"
            )
        return value


class CommandRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    capability_id: str
    method: str
    description: str = ""
    safe: bool = False
    confirm: Optional[str] = None

