import json
import math
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FormValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ActionFormOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | int | float | bool
    label: Optional[str] = None


class ActionFormField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: Literal["text", "textarea", "integer", "float", "boolean", "enum", "json"]
    label: Optional[str] = None
    description: Optional[str] = None
    help: Optional[str] = None
    required: bool = False
    value: Any = None
    default: Any = None
    placeholder: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    step: Optional[float] = None
    options: list[ActionFormOption] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field name is required")
        return cleaned

    @field_validator("options")
    @classmethod
    def require_enum_options(cls, value: list[ActionFormOption], info):
        if info.data.get("type") == "enum" and not value:
            raise ValueError("enum fields require options")
        return value


class ActionFormSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = "Submit"
    agent_id: Optional[str] = None
    action_id: str = Field(min_length=1)
    message: Optional[str] = None

    @field_validator("action_id")
    @classmethod
    def clean_action_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("submit.action_id is required")
        return cleaned


class ActionFormBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["action_form"]
    form_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: Optional[str] = None
    fields: list[ActionFormField] = Field(min_length=1)
    submit: ActionFormSubmit

    @field_validator("form_id", "title")
    @classmethod
    def clean_required_string(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value is required")
        return cleaned

    @field_validator("fields")
    @classmethod
    def require_unique_field_names(cls, fields: list[ActionFormField]) -> list[ActionFormField]:
        seen: set[str] = set()
        for field in fields:
            if field.name in seen:
                raise ValueError(f"duplicate field name: {field.name}")
            seen.add(field.name)
        return fields


def validate_action_form_block(value: Any) -> dict[str, Any]:
    try:
        return ActionFormBlock.model_validate(value).model_dump(exclude_none=True)
    except Exception as exc:
        raise FormValidationError("FORM_INVALID", str(exc) or "Invalid action_form payload.") from exc


def find_action_form_block(content: Any, form_id: str) -> dict[str, Any] | None:
    if isinstance(content, dict) and content.get("type") == "action_form" and content.get("form_id") == form_id:
        return validate_action_form_block(content)
    blocks = content.get("blocks") if isinstance(content, dict) else None
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "action_form" and block.get("form_id") == form_id:
            return validate_action_form_block(block)
    return None


def validate_action_form_values(form: dict[str, Any], submitted: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(submitted, dict):
        raise FormValidationError("FORM_VALIDATION_FAILED", "Submitted form values must be an object.")
    parsed_form = ActionFormBlock.model_validate(form)
    allowed = {field.name for field in parsed_form.fields}
    unknown = sorted(key for key in submitted.keys() if key not in allowed)
    if unknown:
        raise FormValidationError("FORM_VALIDATION_FAILED", f"Unknown form field: {unknown[0]}", {"fields": unknown})
    return {field.name: _coerce_field_value(field, submitted[field.name] if field.name in submitted else _fallback_value(field)) for field in parsed_form.fields}


def _fallback_value(field: ActionFormField) -> Any:
    if field.value is not None:
        return field.value
    if field.default is not None:
        return field.default
    return None


def _coerce_field_value(field: ActionFormField, value: Any) -> Any:
    if field.type in {"text", "textarea"}:
        return _coerce_text(field, value)
    if field.type == "integer":
        return _coerce_integer(field, value)
    if field.type == "float":
        return _coerce_float(field, value)
    if field.type == "boolean":
        if not isinstance(value, bool):
            raise _field_error(field, "must be a boolean")
        return value
    if field.type == "enum":
        option_values = [option.value for option in field.options]
        if value not in option_values:
            raise _field_error(field, "must be one of the declared options")
        return value
    if field.type == "json":
        return _coerce_json(field, value)
    raise _field_error(field, "has unsupported type")


def _coerce_text(field: ActionFormField, value: Any) -> str | None:
    if value is None:
        if field.required:
            raise _field_error(field, "is required")
        return None
    if not isinstance(value, str):
        raise _field_error(field, "must be a string")
    if field.required and value == "":
        raise _field_error(field, "is required")
    if field.min_length is not None and len(value) < field.min_length:
        raise _field_error(field, f"must be at least {field.min_length} characters")
    if field.max_length is not None and len(value) > field.max_length:
        raise _field_error(field, f"must be at most {field.max_length} characters")
    return value


def _coerce_integer(field: ActionFormField, value: Any) -> int | None:
    if value is None or value == "":
        if field.required:
            raise _field_error(field, "is required")
        return None
    if isinstance(value, bool):
        raise _field_error(field, "must be an integer")
    try:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        parsed = int(value)
    except (TypeError, ValueError):
        raise _field_error(field, "must be an integer")
    _check_numeric_bounds(field, parsed)
    if field.step not in (None, 0):
        base = field.minimum or 0
        if (parsed - base) % int(field.step) != 0:
            raise _field_error(field, f"must match step {field.step}")
    return parsed


def _coerce_float(field: ActionFormField, value: Any) -> float | None:
    if value is None or value == "":
        if field.required:
            raise _field_error(field, "is required")
        return None
    if isinstance(value, bool):
        raise _field_error(field, "must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise _field_error(field, "must be a number")
    if not math.isfinite(parsed):
        raise _field_error(field, "must be a finite number")
    _check_numeric_bounds(field, parsed)
    return parsed


def _coerce_json(field: ActionFormField, value: Any) -> Any:
    if value is None or value == "":
        if field.required:
            raise _field_error(field, "is required")
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise _field_error(field, "must be valid JSON")
    if not isinstance(value, (dict, list)):
        raise _field_error(field, "must be a JSON object or array")
    return value


def _check_numeric_bounds(field: ActionFormField, value: float) -> None:
    if field.minimum is not None and value < field.minimum:
        raise _field_error(field, f"must be at least {field.minimum}")
    if field.maximum is not None and value > field.maximum:
        raise _field_error(field, f"must be at most {field.maximum}")


def _field_error(field: ActionFormField, message: str) -> FormValidationError:
    return FormValidationError("FORM_VALIDATION_FAILED", f"Field '{field.name}' {message}.", {"field": field.name})
