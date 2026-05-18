from __future__ import annotations

from datetime import datetime, timezone
import re
from time import perf_counter
from urllib.parse import urlparse, urlunparse

import httpx


CONFIG_DEFAULTS = {
    "enable_web_search_command": True,
    "searxng_base_url": "http://localhost:8888",
    "timeout_seconds": 10,
    "max_results": 8,
    "language": "auto",
    "safe_search": "default",
    "result_filter_enabled": True,
    "domain_blocklist": "",
    "domain_allowlist": "",
    "dedupe_results": True,
    "dedupe_same_domain_title": True,
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
        return _normalize_response(cleaned_query, payload, max_results=max_results, config=config)

    def test_search(self, query: str, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        cleaned_query = str(query or "").strip()
        started = perf_counter()
        base_url = str(config.get("searxng_base_url") or "").strip().rstrip("/")
        try:
            normalized = self.search_results(cleaned_query, context={"capability_config": config})
        except ValueError as exc:
            return {
                "ok": False,
                "provider": "searxng",
                "base_url": base_url,
                "query": cleaned_query,
                "elapsed_ms": _elapsed_ms(started),
                "result_count": 0,
                "first_result": None,
                "sample_results": [],
                "warnings": [],
                "diagnostics": _empty_diagnostics(),
                "error_code": _diagnostic_error_code(str(exc)),
                "error_message": _diagnostic_error_message(str(exc)),
            }
        results = normalized.get("results") if isinstance(normalized.get("results"), list) else []
        sample_results = results[:3]
        return {
            "ok": True,
            "provider": normalized.get("provider") or "searxng",
            "base_url": _validate_base_url(config.get("searxng_base_url")),
            "query": normalized.get("query") or cleaned_query,
            "elapsed_ms": _elapsed_ms(started),
            "result_count": len(results),
            "first_result": sample_results[0] if sample_results else None,
            "sample_results": sample_results,
            "warnings": normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else [],
            "diagnostics": normalized.get("diagnostics") if isinstance(normalized.get("diagnostics"), dict) else _empty_diagnostics(),
        }


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


def _normalize_response(query: str, payload: dict, max_results: int, config: dict | None = None) -> dict:
    config = config or {}
    warnings: list[str] = []
    candidates: list[dict] = []
    skipped_invalid_urls = 0
    raw_results = payload.get("results") or []
    for raw_result in raw_results:
        if not isinstance(raw_result, dict):
            continue
        raw_url = str(raw_result.get("url") or "").strip()
        parsed = urlparse(raw_url)
        host = _result_host(parsed)
        if parsed.scheme not in {"http", "https"} or not host:
            skipped_invalid_urls += 1
            continue
        candidates.append(
            {
                "rank": len(candidates) + 1,
                "title": _clean_text(raw_result.get("title")),
                "url": raw_url,
                "domain": host,
                "snippet": _snippet(raw_result),
                "published_at": _published_at(raw_result),
                "source": _clean_text(raw_result.get("engine") or raw_result.get("source") or raw_result.get("category")),
            }
        )
    if skipped_invalid_urls:
        warnings.append(f"skipped {skipped_invalid_urls} result(s) with invalid URL")
    quality = _apply_result_quality(candidates, config=config, max_results=max_results, warnings=warnings)
    results = quality["results"]
    diagnostics = quality["diagnostics"]
    return {
        "kind": "web_search_results",
        "schema": "web_search.results.v1",
        "query": query,
        "provider": "searxng",
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "warnings": warnings,
        "diagnostics": {
            **diagnostics,
            "raw_result_count": len(raw_results),
            "normalized_count": len(candidates),
            "final_count": len(results),
        },
    }


def _apply_result_quality(candidates: list[dict], *, config: dict, max_results: int, warnings: list[str]) -> dict:
    filter_enabled = bool(config.get("result_filter_enabled", True))
    allow_patterns = _domain_patterns(config.get("domain_allowlist"), warnings)
    block_patterns = _domain_patterns(config.get("domain_blocklist"), warnings)
    dedupe_urls = bool(config.get("dedupe_results", True))
    dedupe_titles = bool(config.get("dedupe_same_domain_title", True))
    diagnostics = _empty_diagnostics()
    diagnostics["filters_applied"] = {
        "result_filter_enabled": filter_enabled,
        "domain_allowlist": filter_enabled and bool(allow_patterns),
        "domain_blocklist": filter_enabled and bool(block_patterns),
        "dedupe_results": dedupe_urls,
        "dedupe_same_domain_title": dedupe_titles,
    }
    diagnostics["warnings"] = warnings
    seen_urls: set[str] = set()
    seen_domain_titles: set[tuple[str, str]] = set()
    results: list[dict] = []
    for candidate in candidates:
        domain = str(candidate.get("domain") or "").lower()
        if filter_enabled and allow_patterns and not _matches_domain_patterns(domain, allow_patterns):
            diagnostics["allowlist_excluded_count"] += 1
            continue
        if filter_enabled and block_patterns and _matches_domain_patterns(domain, block_patterns):
            diagnostics["blocked_count"] += 1
            continue
        if dedupe_urls:
            canonical_url = _canonical_url(candidate.get("url"))
            if canonical_url and canonical_url in seen_urls:
                diagnostics["deduped_count"] += 1
                continue
            if canonical_url:
                seen_urls.add(canonical_url)
        if dedupe_titles:
            title_key = _normalized_title(candidate.get("title"))
            if title_key:
                domain_title_key = (domain, title_key)
                if domain_title_key in seen_domain_titles:
                    diagnostics["deduped_count"] += 1
                    continue
                seen_domain_titles.add(domain_title_key)
        result = dict(candidate)
        result["rank"] = len(results) + 1
        results.append(result)
        if len(results) >= max_results:
            break
    diagnostics["filtered_count"] = diagnostics["allowlist_excluded_count"] + diagnostics["blocked_count"]
    return {"results": results, "diagnostics": diagnostics}


def _empty_diagnostics() -> dict:
    return {
        "raw_result_count": 0,
        "normalized_count": 0,
        "filtered_count": 0,
        "blocked_count": 0,
        "allowlist_excluded_count": 0,
        "deduped_count": 0,
        "final_count": 0,
        "filters_applied": {},
        "warnings": [],
    }


def _domain_patterns(value: object, warnings: list[str]) -> list[str]:
    if isinstance(value, list):
        lines = [str(item) for item in value]
    else:
        lines = str(value or "").splitlines()
    patterns: list[str] = []
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        pattern = _normalize_domain_pattern(raw)
        if not pattern:
            if "invalid_domain_filter_pattern" not in warnings:
                warnings.append("invalid_domain_filter_pattern")
            continue
        patterns.append(pattern)
    return patterns


def _normalize_domain_pattern(value: str) -> str | None:
    raw = value.strip().lower()
    if not raw:
        return None
    if "://" in raw:
        parsed = urlparse(raw)
        raw = parsed.hostname or ""
    else:
        raw = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        if raw.startswith("["):
            return None
        raw = raw.rsplit(":", 1)[0]
    raw = raw.strip().rstrip(".")
    if raw.startswith("*."):
        raw = raw[2:]
    elif raw.startswith("."):
        raw = raw[1:]
    if not raw or "*" in raw:
        return None
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", raw):
        return None
    return raw


def _matches_domain_patterns(domain: str, patterns: list[str]) -> bool:
    host = domain.strip().lower().rstrip(".")
    if not host:
        return False
    return any(host == pattern or host.endswith(f".{pattern}") for pattern in patterns)


def _result_host(parsed) -> str:
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    return host


def _canonical_url(value: object) -> str:
    raw_url = str(value or "").strip()
    parsed = urlparse(raw_url)
    host = _result_host(parsed)
    if parsed.scheme not in {"http", "https"} or not host:
        return ""
    netloc = host
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        netloc = f"{host}:{port}"
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    elif path == "/":
        path = ""
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _normalized_title(value: object) -> str:
    return " ".join(str(value or "").lower().split())


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
        {"type": "json", "data": normalized},
    ]


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((perf_counter() - started) * 1000)))


def _diagnostic_error_code(message: str) -> str:
    if message == "query required":
        return "query_required"
    if message == "invalid base url":
        return "invalid_base_url"
    if message == "searxng unreachable":
        return "searxng_unreachable"
    if message == "timeout":
        return "timeout"
    if message == "invalid response":
        return "invalid_response"
    return "search_failed"


def _diagnostic_error_message(message: str) -> str:
    if message.startswith("search failed:"):
        return message
    return {
        "query required": "query required",
        "invalid base url": "invalid base url",
        "searxng unreachable": "searxng unreachable",
        "timeout": "timeout",
        "invalid response": "invalid response",
    }.get(message, "search failed")


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
