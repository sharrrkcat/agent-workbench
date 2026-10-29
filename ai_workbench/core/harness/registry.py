from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ai_workbench.core.harness.schema import ToolExecutionContext, ToolExecutionError, ToolSpec
from ai_workbench.core.json_data import validate_json_data
from ai_workbench.core.network_policy import NetworkPolicyError


TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not TOOL_NAME_RE.fullmatch(spec.name):
            raise ValueError("Tool names must use lowercase snake_case and be at most 64 characters")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        Draft202012Validator.check_schema(spec.parameters)
        if spec.parameters.get("type") != "object":
            raise ValueError("Tool parameters must describe a JSON object")
        self._tools[spec.name] = deepcopy(spec)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolExecutionError("TOOL_NOT_FOUND", "Tool does not exist.") from exc

    def list(self) -> list[ToolSpec]:
        return [self._tools[name] for name in sorted(self._tools)]

    def catalog(self) -> list[dict[str, Any]]:
        return [deepcopy(item.public()) for item in self.list()]

    def validate_allowlist(self, names: list[str]) -> list[str]:
        if len(names) != len(set(names)):
            raise ValueError("Tool names must be unique")
        for name in names:
            self.get(name)
        return names

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> None:
        spec = self.get(name)
        try:
            validate_json_data(arguments)
            Draft202012Validator(spec.parameters, format_checker=FormatChecker()).validate(arguments)
        except ValidationError as exc:
            raise ToolExecutionError("TOOL_INVALID_ARGUMENTS", "Tool arguments do not match the tool schema.") from exc
        except (ValueError, TypeError, RecursionError) as exc:
            raise ToolExecutionError("TOOL_INVALID_ARGUMENTS", "Tool arguments must be finite JSON data.") from exc

    async def execute(self, name: str, arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
        spec = self.get(name)
        self.validate_arguments(name, arguments)
        try:
            result = await spec.handler(arguments, context)
        except ToolExecutionError:
            raise
        except NetworkPolicyError as exc:
            raise ToolExecutionError(exc.code, exc.message) from exc
        except Exception as exc:
            raise ToolExecutionError("TOOL_EXECUTION_FAILED", "Tool execution failed.") from exc
        if not isinstance(result, dict):
            raise ToolExecutionError("TOOL_PROTOCOL_ERROR", "Tool returned an invalid result.")
        try:
            validate_json_data(result)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ToolExecutionError("TOOL_PROTOCOL_ERROR", "Tool returned invalid JSON data.") from exc
        return result
