"""AnySearch's authenticated Search and Extract API boundary."""

from typing import Generic, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workbench.core.harness.network import MAX_NETWORK_BYTES
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.web_schemas import WebFetchArguments, WebFetchResult, WebPage, WebSearchRequest, WebSearchResult


ANYSEARCH_URL = "https://api.anysearch.com/v1"
Payload = TypeVar("Payload")


class _Response(BaseModel, Generic[Payload]):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    code: int
    data: Payload


class _SearchMetadata(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    search_time_ms: float | None = Field(default=None, ge=0)


class _SearchData(BaseModel):
    model_config = ConfigDict(strict=True)
    results: list[WebPage]
    metadata: _SearchMetadata = Field(default_factory=_SearchMetadata)


class _FetchData(WebPage):
    content: str


HTTP_ERRORS = {
    400: ("WEB_REQUEST_REJECTED", "The web service rejected the request."),
    401: ("WEB_AUTH_FAILED", "The web service API key is invalid or no longer authorized."),
    402: ("WEB_QUOTA_EXHAUSTED", "The web service quota is exhausted."),
    403: ("WEB_AUTH_FAILED", "The web service API key is invalid or no longer authorized."),
    415: ("WEB_REQUEST_REJECTED", "The web service rejected the request."),
    422: ("WEB_EXTRACTION_FAILED", "The web service could not extract this page."),
    429: ("WEB_RATE_LIMITED", "The web service rate limit was reached. Try again later."),
}


def _request_id(payload: object) -> str | None:
    value = payload.get("request_id") if isinstance(payload, dict) else None
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            return None
    return None


class AnySearchProvider:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def _post(self, endpoint: str, body: dict, api_key: str, schema: type[_Response]):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                async with client.stream("POST", f"{ANYSEARCH_URL}/{endpoint}", json=body,
                                         headers={"Authorization": f"Bearer {api_key}", "Accept-Encoding": "identity"}) as response:
                    if response.headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                        raise ToolExecutionError("WEB_RESPONSE_INVALID", "The web service returned an unsupported response encoding.")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_NETWORK_BYTES:
                            raise ToolExecutionError("WEB_RESPONSE_TOO_LARGE", "The web service response exceeds the 1 MiB limit.")
                        raw.extend(chunk)
                    try:
                        payload = strict_json_loads(raw.decode("utf-8"))
                    except (ValueError, RecursionError):
                        payload = None
                    request_id = _request_id(payload)
                    details = {"http_status": response.status_code, **({"request_id": request_id} if request_id else {})}
                    if not response.is_success:
                        code, message = HTTP_ERRORS.get(response.status_code,
                            ("WEB_SERVICE_UNAVAILABLE", "The web service is unavailable.") if response.status_code >= 500 else
                            ("WEB_REQUEST_FAILED", "The web service request failed."))
                        raise ToolExecutionError(code, message, details)
                    try:
                        parsed = schema.model_validate(payload)
                    except ValidationError as exc:
                        raise ToolExecutionError("WEB_RESPONSE_INVALID", "The web service returned an invalid response.", details) from exc
                    if parsed.code != 0:
                        raise ToolExecutionError("WEB_REQUEST_FAILED", "The web service request failed.", details)
                    return parsed.data, request_id
        except httpx.TimeoutException as exc:
            raise ToolExecutionError("TOOL_TIMEOUT", "Tool execution timed out.") from exc
        except httpx.HTTPError as exc:
            raise ToolExecutionError("WEB_REQUEST_FAILED", "The web service request failed.") from exc

    async def search(self, arguments: WebSearchRequest, api_key: str) -> WebSearchResult:
        data, request_id = await self._post("search", {**arguments.model_dump(exclude_none=True), "format": "markdown"},
                                           api_key, _Response[_SearchData])
        return WebSearchResult(provider="anysearch", query=arguments.query, results=data.results,
                               request_id=request_id, search_time_ms=data.metadata.search_time_ms)

    async def fetch(self, arguments: WebFetchArguments, api_key: str) -> WebFetchResult:
        body = arguments.model_dump()
        # Extract accepts at most 16 KiB of UTF-8 JSON, including the URL's JSON escaping.
        request = httpx.Request("POST", ANYSEARCH_URL, json=body)
        if len(request.content) > 16 * 1024:
            raise ToolExecutionError("TOOL_INVALID_ARGUMENTS", "The page URL exceeds the web service request limit.")
        data, request_id = await self._post("extract", body, api_key, _Response[_FetchData])
        return WebFetchResult(provider="anysearch", request_id=request_id, **data.model_dump())
