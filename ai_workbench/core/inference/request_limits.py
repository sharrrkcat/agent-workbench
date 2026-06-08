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


async def read_limited_body(request: Request, settings: StatelessInferenceSettings) -> bytes:
    chunks: list[bytes] = []
    total = 0
    limit = settings.max_request_bytes
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            from ai_workbench.core.inference.errors import raise_openai_inference_error

            raise_openai_inference_error(413, InferenceErrorCode.REQUEST_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


async def read_limited_json(request: Request, settings: StatelessInferenceSettings) -> object:
    import json

    raw = await read_limited_body(request, settings)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        from ai_workbench.core.inference.errors import raise_openai_inference_error

        raise_openai_inference_error(400, InferenceErrorCode.INVALID_REQUEST)
