from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workbench.core.schema.context_policy import ContextPolicy


class ActionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: Optional[str] = None
    description: str = ""
    instruction: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    context_policy: Optional[ContextPolicy] = None
    llm: Optional[Dict[str, Any]] = None
    attach_to: Optional[str] = None
    callable: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value:
            raise ValueError("action id must not be empty")
        return value
