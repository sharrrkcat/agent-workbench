import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


COMMAND_NAME_RE = re.compile(r"^/[a-zA-Z][a-zA-Z0-9_\-]*$")
ALLOWED_COMMAND_ARGUMENT_SUGGESTION_PROVIDERS = {"pet_ids"}


class CommandArgumentNextSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str

    @model_validator(mode="before")
    @classmethod
    def validate_shape(cls, data):
        if not isinstance(data, dict):
            raise ValueError("argument_suggestions.next_suggestions must be an object")
        provider = data.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("argument_suggestions.next_suggestions.provider must be a non-empty string")
        if provider not in ALLOWED_COMMAND_ARGUMENT_SUGGESTION_PROVIDERS:
            raise ValueError(f"argument_suggestions.next_suggestions.provider is not allowed: {provider}")
        return data


class CommandArgumentSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: Optional[str] = None
    description: Optional[str] = None
    next_suggestions: Optional[CommandArgumentNextSuggestions] = None

    @model_validator(mode="before")
    @classmethod
    def validate_shape(cls, data):
        if not isinstance(data, dict):
            raise ValueError("argument_suggestions items must be objects")
        value = data.get("value")
        if not isinstance(value, str):
            raise ValueError("argument_suggestions.value must be a non-empty string")
        for field_name in ("label", "description"):
            field_value = data.get(field_name)
            if field_value is not None and not isinstance(field_value, str):
                raise ValueError(f"argument_suggestions.{field_name} must be a string")
        next_suggestions = data.get("next_suggestions")
        if next_suggestions is not None and not isinstance(next_suggestions, dict):
            raise ValueError("argument_suggestions.next_suggestions must be an object")
        return data

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("argument_suggestions.value must be a non-empty string")
        return value


class CommandSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    method: str
    description: str = ""
    safe: bool = False
    confirm: Optional[str] = None
    argument_suggestions: list[CommandArgumentSuggestion] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not COMMAND_NAME_RE.match(value):
            raise ValueError(
                "command name must start with '/' and match ^/[a-zA-Z][a-zA-Z0-9_\\-]*$"
            )
        return value

    @field_validator("argument_suggestions", mode="before")
    @classmethod
    def validate_argument_suggestions_list(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("argument_suggestions must be an array")
        return value


class CommandRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    capability_id: str
    method: str
    description: str = ""
    safe: bool = False
    confirm: Optional[str] = None
    argument_suggestions: list[CommandArgumentSuggestion] = Field(default_factory=list)
