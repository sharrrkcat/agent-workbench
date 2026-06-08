from hmac import compare_digest

from fastapi import Request

from ai_workbench.core.inference.errors import InferenceErrorCode


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization") or ""
    prefix = "Bearer "
    if not value.startswith(prefix):
        return None
    token = value[len(prefix) :].strip()
    return token or None


def x_api_key(request: Request) -> str | None:
    token = (request.headers.get("x-api-key") or "").strip()
    return token or None


def check_inference_auth(
    request: Request,
    *,
    require_api_key: bool,
    configured_api_key: str | None,
) -> InferenceErrorCode | None:
    if not require_api_key:
        return None
    if not configured_api_key:
        return InferenceErrorCode.SERVICE_MISCONFIGURED

    bearer = bearer_token(request)
    header_key = x_api_key(request)
    if bearer is None and header_key is None:
        return InferenceErrorCode.AUTH_REQUIRED

    if bearer is not None and header_key is not None and bearer != header_key:
        return InferenceErrorCode.AUTH_INVALID

    supplied = bearer or header_key
    if supplied is None:
        return InferenceErrorCode.AUTH_REQUIRED
    if not compare_digest(supplied, configured_api_key):
        return InferenceErrorCode.AUTH_INVALID
    return None
