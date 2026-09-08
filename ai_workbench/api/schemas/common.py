from copy import deepcopy
from datetime import datetime
import re
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, create_model
from pydantic_core import PydanticUndefined

from ai_workbench.core.json_data import JsonValue


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _timestamp(value: str | datetime) -> str:
    # Existing endpoints use both UTC Z and +00:00, with microsecond precision.
    text = value.isoformat() if isinstance(value, datetime) else value
    if not isinstance(text, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", text
    ):
        raise ValueError("Expected an ISO datetime")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


ApiTimestamp = Annotated[str, BeforeValidator(_timestamp), WithJsonSchema({
    "type": "string",
    "description": "ISO 8601 timestamp with original microsecond precision. SQLite model records may contain unzoned UTC text.",
    "anyOf": [{"type": "string", "format": "date-time"},
              {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$"}],
})]
JsonObject = dict[str, JsonValue]


class ErrorDetail(ApiModel):
    code: str
    message: str
    type: Literal["model_error"] | None = None
    details: JsonObject | None = Field(default=None, description="Public JSON diagnostic fields specific to the error code.")


class ErrorResponse(ApiModel):
    error: ErrorDetail


class DeletedResponse(ApiModel):
    deleted: bool


class TextResponse(ApiModel):
    text: str


def public_model(name: str, source: type[BaseModel], *, omit: set[str] | frozenset[str] = frozenset(), fields: dict | None = None) -> type[BaseModel]:
    """Project public fields without inheriting private fields or mutating validators."""
    selected = {}
    for key, original in source.model_fields.items():
        if key in omit:
            continue
        annotation = original.annotation
        if annotation is datetime:
            annotation = ApiTimestamp
        elif set(get_args(annotation)) == {datetime, type(None)}:
            annotation = ApiTimestamp | None
        selected[key] = (annotation, deepcopy(original))
    return create_model(name, __base__=ApiModel, **{**selected, **(fields or {})})


def patch_model(name: str, source: type[BaseModel], *, omit: set[str] | None = None, fields: dict | None = None) -> type[BaseModel]:
    """Omission is optional; explicit null still follows each source field's type."""
    selected = {}
    for key, original in source.model_fields.items():
        if key in (omit or set()):
            continue
        field = deepcopy(original)
        field.default = PydanticUndefined
        field.default_factory = lambda: None
        selected[key] = (field.annotation, field)
    return create_model(name, __base__=ApiModel, **{**selected, **(fields or {})})


def error_responses(*statuses: int) -> dict:
    return {status: {"model": ErrorResponse, "description": "Application error; see error.code and error.message."}
            for status in statuses}
