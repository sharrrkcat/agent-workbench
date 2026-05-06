from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MASKED_SECRET = "********"


class ConfigValidationError(ValueError):
    def __init__(self, code: str, message: str, field: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


class ConfigFieldSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["string", "text", "integer", "float", "boolean", "enum", "json"] = "string"
    label: str = ""
    required: bool = False
    default: Any = None
    description: str = ""
    options: List[str] = Field(default_factory=list)
    secret: bool = False

    @model_validator(mode="after")
    def validate_field(self) -> "ConfigFieldSchema":
        if self.type == "enum" and not self.options:
            raise ValueError(f"enum config field requires options: {self.name}")
        return self


def parse_config_schema(raw_schema: Any) -> List[ConfigFieldSchema]:
    if raw_schema is None:
        return []
    if not isinstance(raw_schema, list):
        raise ValueError("config_schema must be a list")
    fields = [ConfigFieldSchema.model_validate(item) for item in raw_schema]
    names = [field.name for field in fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"config_schema field names must be unique; duplicates: {', '.join(duplicates)}")
    return fields


def validate_user_config(schema: List[ConfigFieldSchema], user_config: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(user_config, dict):
        raise ConfigValidationError("CONFIG_VALIDATION_ERROR", "user_config must be a JSON object")

    field_map = {field.name: field for field in schema}
    for key in user_config:
        if key not in field_map:
            raise ConfigValidationError("UNKNOWN_CONFIG_FIELD", f"Unknown config field: {key}", key)

    for field in schema:
        if field.required and field.default is None and field.name not in user_config:
            raise ConfigValidationError("MISSING_REQUIRED_CONFIG", f"Missing required config field: {field.name}", field.name)

    validated: Dict[str, Any] = {}
    for key, value in user_config.items():
        field = field_map[key]
        if value is None:
            validated[key] = value
            continue
        validated[key] = _validate_value(field, value)
    return validated


def resolve_config(schema: List[ConfigFieldSchema], user_config: Dict[str, Any]) -> Dict[str, Any]:
    validated = validate_user_config(schema, user_config)
    resolved: Dict[str, Any] = {}
    for field in schema:
        if field.name in validated:
            value = validated[field.name]
        elif field.default is not None:
            value = field.default
        elif field.required:
            raise ConfigValidationError("MISSING_REQUIRED_CONFIG", f"Missing required config field: {field.name}", field.name)
        else:
            continue
        if value is not None:
            resolved[field.name] = _validate_value(field, value)
        else:
            resolved[field.name] = value
    return resolved


def merge_secret_patch(
    schema: List[ConfigFieldSchema],
    existing_config: Dict[str, Any],
    incoming_config: Dict[str, Any],
) -> Dict[str, Any]:
    secret_fields = {field.name for field in schema if field.secret}
    merged = dict(incoming_config)
    for name in secret_fields:
        if name not in incoming_config and name in existing_config:
            merged[name] = existing_config[name]
            continue
        if incoming_config.get(name) == MASKED_SECRET:
            if name in existing_config:
                merged[name] = existing_config[name]
            else:
                merged.pop(name, None)
    return merged


def mask_config(schema: List[ConfigFieldSchema], user_config: Dict[str, Any]) -> Dict[str, Any]:
    secret_fields = {field.name for field in schema if field.secret}
    masked = dict(user_config)
    for name in secret_fields:
        if masked.get(name):
            masked[name] = MASKED_SECRET
    return masked


def dump_config_schema(schema: List[ConfigFieldSchema]) -> List[Dict[str, Any]]:
    return [field.model_dump() for field in schema]


def _validate_value(field: ConfigFieldSchema, value: Any) -> Any:
    if field.type in {"string", "text"}:
        if not isinstance(value, str):
            raise ConfigValidationError("INVALID_CONFIG_TYPE", f"Config field '{field.name}' must be a string", field.name)
        return value
    if field.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValidationError("INVALID_CONFIG_TYPE", f"Config field '{field.name}' must be an integer", field.name)
        return value
    if field.type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValidationError("INVALID_CONFIG_TYPE", f"Config field '{field.name}' must be a number", field.name)
        return float(value)
    if field.type == "boolean":
        if not isinstance(value, bool):
            raise ConfigValidationError("INVALID_CONFIG_TYPE", f"Config field '{field.name}' must be a boolean", field.name)
        return value
    if field.type == "enum":
        if not isinstance(value, str):
            raise ConfigValidationError("INVALID_CONFIG_TYPE", f"Config field '{field.name}' must be a string", field.name)
        if value not in field.options:
            raise ConfigValidationError("INVALID_CONFIG_OPTION", f"Invalid option for config field '{field.name}': {value}", field.name)
        return value
    if field.type == "json":
        if isinstance(value, (str, int, float, bool)) or value is None:
            raise ConfigValidationError("INVALID_CONFIG_TYPE", f"Config field '{field.name}' must be JSON object or array", field.name)
        return value
    raise ConfigValidationError("CONFIG_VALIDATION_ERROR", f"Unsupported config field type: {field.type}", field.name)
