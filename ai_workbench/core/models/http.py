from __future__ import annotations

import asyncio
import ipaddress
from hmac import compare_digest

from fastapi import Request
from pydantic import ValidationError
from starlette.datastructures import Headers, MutableHeaders

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.observability import (
    REQUEST_ID_HEADER, elapsed_ms, log_access_event, monotonic_time,
    reset_current_request_id, resolve_request_id, set_current_request_id,
)


def guard(request: Request, settings) -> None:
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
        local = address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        local = host == "localhost"
    if not local:
        raise ModelError("LOCALHOST_ONLY", "The inference service accepts only localhost clients.", 403)
    if not settings.external_enabled:
        raise ModelError("SERVICE_DISABLED", "The inference service is disabled.", 503)
    if not settings.external_api_key:
        raise ModelError("SERVICE_MISCONFIGURED", "The inference service requires an API key.", 503)
    authorization = request.headers.get("authorization", "")
    bearer = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    header_key = request.headers.get("x-api-key", "")
    if not bearer and not header_key:
        raise ModelError("AUTH_REQUIRED", "An API key is required.", 401)
    if bearer and header_key and bearer != header_key or not compare_digest((bearer or header_key).encode(), settings.external_api_key.encode()):
        raise ModelError("AUTH_INVALID", "Invalid API key.", 401)


async def read_body(request: Request, settings):
    limit = settings.max_request_mb * 1024 * 1024
    length = request.headers.get("content-length")
    if length is not None:
        try:
            value = int(length)
            if value < 0:
                raise ValueError()
        except ValueError as exc:
            raise ModelError("INVALID_REQUEST", "Invalid Content-Length.") from exc
        if value > limit:
            raise ModelError("REQUEST_TOO_LARGE", "Request exceeds the configured body limit.", 413)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise ModelError("REQUEST_TOO_LARGE", "Request exceeds the configured body limit.", 413)
        body.extend(chunk)
    return bytes(body)


async def read_request(request: Request, settings, schema):
    body = await read_body(request, settings)
    try:
        return schema.model_validate_json(body)
    except ValidationError as exc:
        # Never echo request values (which can include images or credentials).
        first = exc.errors(include_input=False)[0]
        field = ".".join(str(p) for p in first["loc"])
        raise ModelError("INVALID_REQUEST", f"{field}: {first['msg']}") from exc


class InferenceObservabilityMiddleware:
    """Log after the ASGI response finishes, including SSE failures/disconnects."""

    def __init__(self, app, repo_root):
        self.app = app
        self.repo_root = repo_root

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/v1"):
            return await self.app(scope, receive, send)
        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = set_current_request_id(request_id)
        state = scope.setdefault("state", {})
        state["inference_request_id"] = request_id
        start = monotonic_time()
        status = 500
        completed = False

        async def logged_send(message):
            nonlocal status, completed
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True

        try:
            await self.app(scope, receive, logged_send)
        except (asyncio.CancelledError, OSError):
            state["inference_error_code"] = "REQUEST_CANCELLED"
            raise
        except Exception:
            state["inference_error_code"] = "INTERNAL_ERROR"
            raise
        finally:
            log_access_event(repo_root=self.repo_root, method=scope["method"], path=scope["path"],
                             status_code=status, duration_ms=elapsed_ms(start),
                             error_code=state.get("inference_error_code") or (None if completed else "REQUEST_CANCELLED"))
            reset_current_request_id(token)
