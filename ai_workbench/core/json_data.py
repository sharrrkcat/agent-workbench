"""Strict JSON data shared by tool inputs, outputs and persisted parts."""

from __future__ import annotations

import json
import math
from typing import Annotated, Any

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr
from typing_extensions import TypeAliasType


# Unlike Pydantic's opaque JsonValue schema, this recursive alias documents all
# JSON shapes in both input and output schemas while rejecting non-finite data.
JsonValue = TypeAliasType("JsonValue", "None | StrictBool | StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)] | StrictStr | list[JsonValue] | dict[str, JsonValue]")


def validate_json_data(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, list):
        for item in value:
            validate_json_data(item)
        return value
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            validate_json_data(item)
        return value
    raise ValueError("Expected finite JSON data")


def strict_json_loads(value: str) -> Any:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = item
        return result

    def invalid_constant(_token):
        raise ValueError("Invalid JSON constant")

    return validate_json_data(json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant))
