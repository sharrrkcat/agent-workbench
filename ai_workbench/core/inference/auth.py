from fastapi import Request

from ai_workbench.core.inference.errors import InferenceErrorCode


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization") or ""
    prefix = "Bearer "
    if not value.startswith(prefix):
        return None
    token = value[len(prefix) :].strip()
    return token or None


def check_inference_auth_shape(request: Request, *, require_api_key: bool) -> InferenceErrorCode | None:
    if not require_api_key:
        return None
    if bearer_token(request) is None:
        return InferenceErrorCode.AUTH_REQUIRED
    return InferenceErrorCode.AUTH_INVALID
