"""Check or export the HTTP contract without opening the application database."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Each exception identifies a JSON-valued field, never an entire HTTP payload.
OPAQUE_SCHEMA_PATHS: dict[str, str] = {
    "components/schemas/ApprovalRequestedPayload/properties/arguments": "Arguments of the tool awaiting approval.",
    "components/schemas/AttachmentResponse/properties/metadata": "Optional attachment metadata.",
    "components/schemas/CatalogEntryResponse/properties/options_schema": "JSON Schema for code-owned runtime options.",
    "components/schemas/ChatResult/properties/data": "Direct tool results may have tool-specific JSON keys.",
    "components/schemas/HistoryResult/properties/data": "A retried chat may produce a direct tool result.",
    "components/schemas/ChunkPreview/properties/metadata": "Chunk provenance and location metadata.",
    "components/schemas/ChunkResponse/properties/metadata": "Chunk provenance and location metadata.",
    "components/schemas/DirectToolRequest/properties/arguments": "Validated by the named built-in tool's JSON Schema.",
    "components/schemas/ErrorDetail/properties/details": "Error-code-specific public JSON diagnostics.",
    "components/schemas/JsonPart/properties/data": "User-supplied JSON message content.",
    "components/schemas/KnowledgeSourceResponse/properties/metadata": "Source provenance and attachment references.",
    "components/schemas/MessageResponse/properties/metadata": "Public message and speaker diagnostics.",
    "components/schemas/RunResponse/properties/metadata": "Public run diagnostics and configuration summaries.",
    "components/schemas/RunStepResponse/properties/metadata": "Step-specific public diagnostics.",
    "components/schemas/SessionResponse/properties/title_generation_metadata": "Auxiliary-title outcome diagnostics.",
    "components/schemas/ToolCallPart/properties/arguments": "Arguments validated by the selected tool schema.",
    "components/schemas/ToolCatalogItem/properties/parameters": "The tool's Draft 2020-12 argument schema.",
    "components/schemas/ToolResultPart/properties/data": "Finite JSON result of the selected built-in tool.",
    "components/schemas/Documented__AttachmentInput/properties/metadata": "Optional finite JSON upload/reference metadata.",
    "components/schemas/Documented__ErrorDetail/properties/details": "Error-code-specific public JSON diagnostics.",
    "components/schemas/Documented__FunctionSpec/properties/parameters": "Caller-provided function argument JSON Schema.",
    "components/schemas/Documented__JSONSchema/properties/schema": "Caller-provided structured-output JSON Schema.",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
JSON_VALUE_SCHEMAS = {"JsonValue-Input", "JsonValue-Output", "Documented__JsonValue"}


def http_operations(app) -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute

    # Hidden business routes must fail coverage rather than silently disappear.
    return {(route.path_format, method.lower()) for route in app.routes
            if isinstance(route, APIRoute) and route.path.startswith(("/api/", "/v1/"))
            for method in route.methods}


def check_route_contracts(app, document: dict) -> list[str]:
    from fastapi.routing import APIRoute

    errors = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(("/api/", "/v1/")):
            continue
        for method in route.methods:
            operation = document.get("paths", {}).get(route.path_format, {}).get(method.lower(), {})
            has_input = route.body_field is not None or "requestBody" in (route.openapi_extra or {})
            manual_input = route.dependant.request_param_name and method in {"POST", "PUT", "PATCH"}
            if (has_input or manual_input) and not operation.get("requestBody", {}).get("content"):
                errors.append(f"{method} {route.path_format}: request body is undocumented")
            response = operation.get("responses", {}).get(str(route.status_code or 200), {})
            if route.response_model is not None and "application/json" not in response.get("content", {}):
                errors.append(f"{method} {route.path_format}: JSON success schema is missing")
            for status, response in operation.get("responses", {}).items():
                if status.startswith("2") and "application/json" in response.get("content", {}) and route.response_model is None:
                    errors.append(f"{method} {route.path_format}: JSON success response lacks runtime validation")
    return errors


async def build_document() -> tuple[dict, set[tuple[str, str]]]:
    from ai_workbench.api.main import create_app

    with TemporaryDirectory(prefix="workbench-openapi-") as directory:
        app = create_app(use_memory=True, root=directory, frontend_dist=Path(directory) / "frontend")
        async with app.router.lifespan_context(app):
            document = app.openapi()
            errors = check_route_contracts(app, document)
            if errors:
                raise ValueError("\n".join(errors))
            return document, http_operations(app)


def resolve_ref(document: dict, reference: str) -> Any:
    if not isinstance(reference, str):
        raise ValueError("Schema references must be strings")
    if not reference.startswith("#/"):
        raise ValueError(f"External schema reference is not supported: {reference}")
    value: Any = document
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _check_schema(document: dict, schema: Any, path: str, errors: list[str], used: set[str], field_path: str | None = None) -> None:
    if not isinstance(schema, dict):
        if schema is True:
            errors.append(f"{path}: undocumented open JSON structure")
        return
    if "$ref" in schema:
        try:
            resolve_ref(document, schema["$ref"])
        except (KeyError, ValueError) as exc:
            errors.append(f"{path}: unresolved reference {exc}")
        if isinstance(schema["$ref"], str) and schema["$ref"].rsplit("/", 1)[-1] in JSON_VALUE_SCHEMAS:
            component = path.split("/")[2] if path.startswith("components/schemas/") else None
            if component not in JSON_VALUE_SCHEMAS:
                if field_path in OPAQUE_SCHEMA_PATHS and OPAQUE_SCHEMA_PATHS[field_path]:
                    used.add(field_path)
                else:
                    errors.append(f"{field_path or path}: undocumented arbitrary JSON field")
    opaque = not set(schema).intersection({"type", "$ref", "anyOf", "oneOf", "allOf", "enum", "const"}) or (schema.get("type") == "object" and not schema.get("properties")
                            and schema.get("additionalProperties", True) is True)
    if opaque:
        # Intentional JSON fields use the finite recursive JsonValue type, never {}.
        errors.append(f"{path}: undocumented open JSON structure")
    for key in ("properties", "$defs", "patternProperties"):
        for name, child in schema.get(key, {}).items():
            child_path = f"{path}/{key}/{name}"
            _check_schema(document, child, child_path, errors, used,
                          child_path if key == "properties" else field_path)
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for index, child in enumerate(schema.get(key, [])):
            _check_schema(document, child, f"{path}/{key}/{index}", errors, used, field_path)
    for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains"):
        if key in schema:
            _check_schema(document, schema[key], f"{path}/{key}", errors, used, field_path)


def _check_references(document: dict, value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference is not None:
            try:
                resolve_ref(document, reference)
            except (KeyError, ValueError, TypeError) as exc:
                errors.append(f"{path}: unresolved reference {reference}: {exc}")
        for key, child in value.items():
            _check_references(document, child, f"{path}/{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_references(document, child, f"{path}/{index}", errors)


def _shaped_payload(document: dict, schema: Any, seen: frozenset[str] = frozenset()) -> bool:
    if not isinstance(schema, dict):
        return False
    if "$ref" in schema:
        reference = schema["$ref"]
        if reference in seen:
            return False
        return _shaped_payload(document, resolve_ref(document, reference), seen | {reference})
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return all(_shaped_payload(document, value, seen) for value in schema[key])
    if schema.get("type") == "object":
        return bool(schema.get("properties"))
    if schema.get("type") == "array":
        return _shaped_payload(document, schema.get("items", {}), seen)
    return schema.get("type") in {"string", "integer", "number", "boolean", "null"}


def check_document(document: dict, expected: set[tuple[str, str]]) -> list[str]:
    from openapi_spec_validator import validate

    errors: list[str] = []
    _check_references(document, document, "", errors)
    try:
        validate(document)
    except Exception as exc:
        errors.append(f"OpenAPI validation failed: {exc}")
    actual = {(path, method) for path, item in document["paths"].items() for method in item if method in HTTP_METHODS}
    if actual != expected:
        errors.append(f"Route coverage differs: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    used: set[str] = set()
    operation_ids: set[str] = set()
    for name, schema in document.get("components", {}).get("schemas", {}).items():
        _check_schema(document, schema, f"components/schemas/{name}", errors, used)
    for path, method in sorted(actual):
        operation = document["paths"][path][method]
        operation_id = operation.get("operationId")
        if not operation_id or operation_id in operation_ids:
            errors.append(f"{method} {path}: missing or duplicate operationId")
        operation_ids.add(operation_id)
        if not operation.get("tags") or not operation.get("summary"):
            errors.append(f"{method} {path}: missing tag or summary")
        containers = [("requestBody", operation.get("requestBody", {}))]
        containers.extend((f"responses/{code}", response) for code, response in operation.get("responses", {}).items())
        for label, container in containers:
            for media, content in container.get("content", {}).items():
                schema = content.get("schema", {})
                location = f"paths/{path}/{method}/{label}/content/{media}/schema"
                _check_schema(document, schema, location, errors, used)
                if media == "application/json":
                    try:
                        if not _shaped_payload(document, schema):
                            errors.append(f"{method} {path} {label}: unstructured JSON payload")
                    except (KeyError, ValueError):
                        pass
        for parameter in operation.get("parameters", []):
            _check_schema(document, parameter.get("schema", {}),
                          f"paths/{path}/{method}/parameters/{parameter['name']}", errors, used)
    for path in sorted(OPAQUE_SCHEMA_PATHS.keys() - used):
        errors.append(f"Stale open JSON exception: {path}")
    return errors


def render_document(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Validate the complete HTTP contract without writing a file")
    export = commands.add_parser("export", help="Validate and write deterministic OpenAPI JSON")
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document, expected = asyncio.run(build_document())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    errors = check_document(document, expected)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if args.command == "export":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(render_document(document))
        print(f"Exported {len(expected)} HTTP operations to {args.output}")
    else:
        print(f"OpenAPI {document['openapi']}: {len(document['paths'])} paths, {len(expected)} HTTP operations; checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
