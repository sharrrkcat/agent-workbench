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

    @model_validator(mode="after")
    def validate_output_contract(self) -> "CapabilityMethodSchema":
        if not self.output:
            return self
        if "type" in self.output:
            raise ValueError("capability method output.type is not supported; use output.part_type")
        part_type = self.output.get("part_type")
        allowed = {"text", "json", "file", "image", "audio", "video", "media_group", "parts"}
        if part_type is not None and part_type not in allowed:
            raise ValueError(f"unsupported output.part_type: {part_type}")
        if part_type == "text" and self.output.get("format", "plain") not in {"plain", "markdown"}:
            raise ValueError("output.format must be plain or markdown")
        if part_type == "file" and self.output.get("mode", "inline_text") not in {"inline_text", "attachment_ref"}:
            raise ValueError("output.mode must be inline_text or attachment_ref")
        if part_type == "media_group" and self.output.get("layout", "gallery") != "gallery":
            raise ValueError("output.layout must be gallery")
        return self


class CapabilitySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    methods: List[CapabilityMethodSchema]
    commands: List[CommandSchema] = Field(default_factory=list)
    config_schema: List[ConfigFieldSchema] = Field(default_factory=list)
    permissions: Dict[str, Any] = Field(default_factory=dict)
    agent_overrides: Dict[str, Any] = Field(default_factory=dict)

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
