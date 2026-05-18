from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx


CONFIG_DEFAULTS = {
    "enable_web_search_command": True,
    "searxng_base_url": "http://localhost:8888",
    "timeout_seconds": 10,
    "max_results": 8,
    "language": "auto",
    "safe_search": "default",
}
SAFE_SEARCH_VALUES = {
    "default": None,
    "off": "0",
    "moderate": "1",
    "strict": "2",
}


class CapabilityRuntime:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def search(self, text: str, context: dict | None = None) -> list[dict]:
        config = _runtime_config(context)
        _ensure_web_search_enabled(config)
        normalized = self.search_results(text, context={"capability_config": config})
        return _parts_for_results(normalized)

    def search_results(self, query: str, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        cleaned_query = str(query or "").strip()
        if not cleaned_query:
            raise ValueError("query required")
        base_url = _validate_base_url(config.get("searxng_base_url"))
        timeout = float(config.get("timeout_seconds", CONFIG_DEFAULTS["timeout_seconds"]))
        max_results = int(config.get("max_results", CONFIG_DEFAULTS["max_results"]))
        params = _search_params(cleaned_query, config)
        response = _request_search(base_url, params=params, timeout=timeout, client=self._client)
        payload = _json_payload(response)
        return _normalize_response(cleaned_query, payload, max_results=max_results)


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()


def _runtime_config(context: dict | None) -> dict:
    config = dict(CONFIG_DEFAULTS)
    provided = (context or {}).get("capability_config") if isinstance(context, dict) else None
    if isinstance(provided, dict):
        config.update(provided)
    return config


def _ensure_web_search_enabled(config: dict) -> None:
    if not bool(config.get("enable_web_search_command", True)):
        raise ValueError("command disabled")


def _validate_base_url(raw_url: object) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("invalid base url")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid base url")
    return value


def _search_params(query: str, config: dict) -> dict[str, str]:
    params = {"q": query, "format": "json"}
    language = str(config.get("language") or "").strip()
    if language and language.lower() != "auto":
        params["language"] = language
    safe_search = str(config.get("safe_search") or "default").strip().lower()
    safesearch_value = SAFE_SEARCH_VALUES.get(safe_search)
    if safesearch_value is not None:
        params["safesearch"] = safesearch_value
    return params


def _request_search(base_url: str, params: dict[str, str], timeout: float, client: httpx.Client | None = None) -> httpx.Response:
    owns_client = client is None
    active_client = client or httpx.Client(timeout=timeout, headers={"User-Agent": "agent-workbench/0.1"})
    try:
        response = active_client.get(f"{base_url}/search", params=params, timeout=timeout)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as exc:
        raise ValueError("timeout") from exc
    except httpx.ConnectError as exc:
        raise ValueError("searxng unreachable") from exc
    except httpx.NetworkError as exc:
        raise ValueError("searxng unreachable") from exc
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"search failed: HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ValueError("search failed") from exc
    finally:
        if owns_client:
            active_client.close()


def _json_payload(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("invalid response") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("invalid response")
    return payload


def _normalize_response(query: str, payload: dict, max_results: int) -> dict:
    warnings: list[str] = []
    results: list[dict] = []
    skipped_invalid_urls = 0
    for raw_result in payload.get("results") or []:
        if not isinstance(raw_result, dict):
            continue
        raw_url = str(raw_result.get("url") or "").strip()
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            skipped_invalid_urls += 1
            continue
        results.append(
            {
                "rank": len(results) + 1,
                "title": _clean_text(raw_result.get("title")),
                "url": raw_url,
                "domain": parsed.netloc.lower(),
                "snippet": _snippet(raw_result),
                "published_at": _published_at(raw_result),
                "source": _clean_text(raw_result.get("engine") or raw_result.get("source") or raw_result.get("category")),
            }
        )
        if len(results) >= max_results:
            break
    if skipped_invalid_urls:
        warnings.append(f"skipped {skipped_invalid_urls} result(s) with invalid URL")
    return {
        "query": query,
        "provider": "searxng",
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "warnings": warnings,
    }


def _snippet(raw_result: dict) -> str:
    for key in ("content", "snippet", "description"):
        value = _clean_text(raw_result.get(key))
        if value:
            return value
    return ""


def _published_at(raw_result: dict) -> str | None:
    value = raw_result.get("publishedDate") or raw_result.get("published_at") or raw_result.get("date")
    cleaned = _clean_text(value)
    return cleaned or None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _parts_for_results(normalized: dict) -> list[dict]:
    return [
        {"type": "text", "format": "markdown", "text": _markdown_results(normalized)},
        {"type": "json", "data": normalized},
    ]


def _markdown_results(normalized: dict) -> str:
    query = str(normalized.get("query") or "")
    provider = str(normalized.get("provider") or "searxng")
    lines = [f"Search results for `{query}` via `{provider}`."]
    warnings = normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else []
    for warning in warnings:
        lines.append(f"Warning: {warning}.")
    results = normalized.get("results") if isinstance(normalized.get("results"), list) else []
    if not results:
        lines.append("")
        lines.append("No results.")
        return "\n".join(lines)
    lines.append("")
    for result in results:
        rank = result.get("rank")
        title = result.get("title") or "(untitled)"
        domain = result.get("domain") or ""
        url = result.get("url") or ""
        snippet = result.get("snippet") or ""
        lines.append(f"{rank}. [{title}]({url})")
        lines.append(f"   - Domain: `{domain}`")
        lines.append(f"   - URL: {url}")
        if snippet:
            lines.append(f"   - {snippet}")
    return "\n".join(lines)
