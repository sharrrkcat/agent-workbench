from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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

    @staticmethod
    def public_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(arguments)
        if name == "read_file" and isinstance(result.get("path"), str):
            value = result["path"].replace("\\", "/")
            if ":" in value or value.startswith("/") or any(part == ".." for part in value.split("/")):
                result["path"] = "[blocked path]"
        if name == "fetch_url" and isinstance(result.get("url"), str):
            result["url"] = public_url(result["url"])
        return result

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


def public_url(value: str) -> str:
    """Do not echo URL credentials or common authentication query parameters."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "[invalid URL]"
        if parsed.username is not None or parsed.password is not None:
            return "[blocked URL credentials]"
        secret_keys = {"key", "api_key", "apikey", "token", "access_token", "secret", "password", "signature"}
        query = [(key, "[redacted]" if key.lower() in secret_keys else item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)]
        return urlunsplit(parsed._replace(query=urlencode(query))) if query else value
    except ValueError:
        return "[invalid URL]"
