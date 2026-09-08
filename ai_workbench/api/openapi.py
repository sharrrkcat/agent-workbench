"""Documentation for bodies deliberately parsed outside FastAPI's body reader."""

from copy import deepcopy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from ai_workbench.api.schemas.common import ErrorResponse
from ai_workbench.api.schemas.inference import ChatCompletionChunk


_DOCUMENTED_MODELS: dict[str, type[BaseModel]] = {}


def schema_ref(model: type[BaseModel]) -> dict:
    previous = _DOCUMENTED_MODELS.setdefault(model.__name__, model)
    if previous is not model:
        raise ValueError(f"Duplicate documented model name: {model.__name__}")
    return {"$ref": f"#/components/schemas/Documented__{model.__name__}"}


def request_body(model: type[BaseModel], media_type: str = "application/json", *, description: str = "") -> dict:
    return {"requestBody": {"required": True, "description": description,
                           "content": {media_type: {"schema": schema_ref(model)}}}}


SSE_EXAMPLE = (
    'data: {"id":"chatcmpl-example","object":"chat.completion.chunk","created":0,"model":"chat-model",'
    '"choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}],"usage":null}\n\n'
    'data: {"id":"chatcmpl-example","object":"chat.completion.chunk","created":0,"model":"chat-model",'
    '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":null}\n\n'
    'data: {"id":"chatcmpl-example","object":"chat.completion.chunk","created":0,"model":"chat-model",'
    '"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
    'data: [DONE]\n\n'
)

SSE_RESPONSE = {"description": "JSON completion when stream=false; SSE text when stream=true.", "content": {
    "text/event-stream": {"x-event-schemas": {"chunk": schema_ref(ChatCompletionChunk), "error": schema_ref(ErrorResponse)},
        "schema": {"type": "string", "description":
        "Each data line contains a ChatCompletionChunk or ErrorResponse JSON payload. "
        "Usage is included only when requested. Exactly one data: [DONE] terminates the stream. "
        "Errors before headers use an HTTP error status; later errors are SSE data followed by [DONE]."},
        "examples": {"completion": {"value": SSE_EXAMPLE}, "failure": {"value":
            'data: {"error":{"code":"PROVIDER_ERROR","message":"Streaming inference failed.","type":"model_error"}}\n\ndata: [DONE]\n\n'}}}}}


BINARY_CONTENT = {media: {"schema": {"type": "string", "format": "binary"}}
                  for media in ("application/octet-stream", "*/*")}
RANGE_HEADERS = {
    "Accept-Ranges": {"schema": {"type": "string", "const": "bytes"}},
    "Content-Length": {"schema": {"type": "integer", "minimum": 0}},
}
ATTACHMENT_RESPONSES = {
    200: {"description": "Complete file bytes. Content-Type is the stored attachment MIME type.",
          "content": BINARY_CONTENT, "headers": RANGE_HEADERS},
    206: {"description": "One requested byte range; multipart ranges are not supported.",
          "content": BINARY_CONTENT, "headers": {**RANGE_HEADERS,
              "Content-Range": {"schema": {"type": "string"}, "example": "bytes 0-4/12"}}},
    416: {"description": "Invalid or unsatisfiable range, with no response body.",
          "headers": {**RANGE_HEADERS, "Content-Range": {"schema": {"type": "string"}, "example": "bytes */12"}}},
}
ATTACHMENT_RANGE = {"parameters": [{"name": "Range", "in": "header", "required": False,
    "schema": {"type": "string"}, "description": "One bytes=start-end, bytes=start- or bytes=-suffix range.",
    "example": "bytes=0-4"}]}


def _references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str) and child.startswith("#/components/schemas/"):
                yield child.rsplit("/", 1)[-1]
            else:
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _prune_unused_schemas(document: dict) -> None:
    # Manual bodies replace generic FastAPI inputs; don't publish their unused components.
    schemas = document["components"]["schemas"]
    pending = list(_references(document["paths"]))
    used = set()
    while pending:
        name = pending.pop()
        if name not in used and name in schemas:
            used.add(name)
            pending.extend(_references(schemas[name]))
    for name in schemas.keys() - used:
        del schemas[name]


def install_openapi(app: FastAPI) -> None:
    error_ref = schema_ref(ErrorResponse)
    schema_ref(ChatCompletionChunk)

    def generate() -> dict:
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = get_openapi(title=app.title, version=app.version, openapi_version=app.openapi_version,
            description=app.description, routes=app.routes, tags=app.openapi_tags, servers=app.servers,
            separate_input_output_schemas=app.separate_input_output_schemas)
        _, definitions = models_json_schema([(model, "validation") for model in _DOCUMENTED_MODELS.values()],
                                            ref_template="#/components/schemas/Documented__{model}")
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in definitions.get("$defs", {}).items():
            key = f"Documented__{name}"
            if key in schemas:
                raise ValueError(f"Conflicting OpenAPI component: {key}")
            schemas[key] = definition
        document["components"]["securitySchemes"] = {
            "BearerAuth": {"type": "http", "scheme": "bearer"},
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "x-api-key"},
        }
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.include_in_schema:
                continue
            for method in route.methods:
                operation = document["paths"][route.path_format][method.lower()]
                if route.openapi_extra and "requestBody" in route.openapi_extra:
                    # Replace the generic dict body instead of deep-merging its object constraints into a $ref.
                    operation["requestBody"] = deepcopy(route.openapi_extra["requestBody"])
                responses = operation["responses"]
                if "422" in responses:
                    response_schema = responses["422"].get("content", {}).get("application/json", {}).get("schema", {})
                    if response_schema.get("$ref", "").endswith("/HTTPValidationError"):
                        responses["422"] = {"description": "Invalid request fields.",
                            "content": {"application/json": {"schema": error_ref}}}
                responses.setdefault("500", {"description": "The server could not produce a valid response. Internal values are omitted.",
                    "content": {"application/json": {"schema": error_ref}}})
                if route.path.startswith("/v1/"):
                    operation["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
                    operation["description"] = (operation.get("description", "") + "\n\n"
                        "The external service must be enabled and the client must be loopback. Supply Bearer or x-api-key; "
                        "when both are supplied they must match. Model values are public aliases. Requests are stateless.").strip()
                    for response in responses.values():
                        response.setdefault("headers", {})["X-Request-Id"] = {"schema": {"type": "string"},
                            "description": "Request correlation identifier."}
        _prune_unused_schemas(document)
        app.openapi_schema = document
        return document

    app.openapi = generate
