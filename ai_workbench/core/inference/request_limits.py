from fastapi import Request

from ai_workbench.core.inference.errors import InferenceErrorCode
from ai_workbench.core.inference.settings import StatelessInferenceSettings


def check_content_length(request: Request, settings: StatelessInferenceSettings) -> InferenceErrorCode | None:
    raw = request.headers.get("content-length")
    if not raw:
        return None
    try:
        content_length = int(raw)
    except ValueError:
        return InferenceErrorCode.INVALID_REQUEST
    if content_length > settings.max_request_bytes:
        return InferenceErrorCode.REQUEST_TOO_LARGE
    return None
