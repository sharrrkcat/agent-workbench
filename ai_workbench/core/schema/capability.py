import re
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workbench.core.config_schema import ConfigFieldSchema, parse_config_schema
from ai_workbench.core.schema.command import CommandSchema


CAPABILITY_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")


class CapabilityMethodSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)


class CapabilitySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    methods: List[CapabilityMethodSchema]
    commands: List[CommandSchema] = Field(default_factory=list)
    config_schema: List[ConfigFieldSchema] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_config_schema_fields(cls, data):
        if isinstance(data, dict) and "config_schema" in data:
            data = dict(data)
            data["config_schema"] = parse_config_schema(data.get("config_schema"))
        return data

    @model_validator(mode="after")
    def validate_capability(self) -> "CapabilitySchema":
        if not CAPABILITY_ID_RE.match(self.id):
            raise ValueError("capability id must match ^[a-zA-Z][a-zA-Z0-9_\\-]*$")

        method_ids = [method.id for method in self.methods]
        duplicates = sorted({method_id for method_id in method_ids if method_ids.count(method_id) > 1})
        if duplicates:
            raise ValueError(f"capability method ids must be unique; duplicates: {', '.join(duplicates)}")

        known_methods = set(method_ids)
        missing = sorted({command.method for command in self.commands if command.method not in known_methods})
        if missing:
            raise ValueError(
                "capability commands must reference existing methods; "
                f"missing method ids: {', '.join(missing)}"
            )

        return self
