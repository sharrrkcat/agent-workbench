import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workbench.core.config_schema import ConfigFieldSchema, parse_config_schema
from ai_workbench.core.schema.action import ActionSchema
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.model_lifecycle import ModelLifecyclePolicy


AGENT_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")
COMMAND_ALIAS_FIELDS = {
    "command",
    "commands",
    "slash_command",
    "slash_commands",
    "slash_command_alias",
    "slash_command_aliases",
    "command_alias",
    "command_aliases",
    "aliases",
}


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: Literal["prompt", "script"]
    description: str = ""
    avatar: str = ""
    entry: Optional[str] = None
    actions: List[ActionSchema]
    model: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    context_policy: ContextPolicy
    model_lifecycle: ModelLifecyclePolicy
    capabilities: List[str] = Field(default_factory=list)
    config_schema: List[ConfigFieldSchema] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_command_alias_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            found = sorted(COMMAND_ALIAS_FIELDS.intersection(data.keys()))
            if found:
                raise ValueError(
                    "Agent manifests must not declare slash command alias fields; "
                    f"found: {', '.join(found)}. Commands belong in Capability manifests."
                )
            if "config_schema" in data:
                data = dict(data)
                data["config_schema"] = parse_config_schema(data.get("config_schema"))
        return data

    @model_validator(mode="after")
    def validate_agent(self) -> "AgentSchema":
        if not AGENT_ID_RE.match(self.id):
            raise ValueError("agent id must match ^[a-zA-Z][a-zA-Z0-9_\\-]*$")

        action_ids = [action.id for action in self.actions]
        if "default" not in action_ids:
            raise ValueError("agent actions must include a 'default' action")

        duplicates = sorted({action_id for action_id in action_ids if action_ids.count(action_id) > 1})
        if duplicates:
            raise ValueError(f"agent action ids must be unique; duplicates: {', '.join(duplicates)}")

        if self.type == "script" and not self.entry:
            raise ValueError("script agents require an entry field")

        return self
