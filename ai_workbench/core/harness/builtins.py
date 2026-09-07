from __future__ import annotations

import base64
import binascii
import asyncio
from pathlib import Path
from pathlib import PureWindowsPath
from urllib.parse import urlencode

from ai_workbench.core.harness.network import fetch_bytes, fetch_json, text_from_response
from ai_workbench.core.harness.schema import ToolExecutionContext, ToolExecutionError, ToolSpec
from ai_workbench.core.harness.registry import public_url
from ai_workbench.core.network_policy import NetworkPolicyError


FILE_MAX_BYTES = 200_000
CODEC_MAX_BYTES = 1024 * 1024


async def read_file(arguments: dict, context: ToolExecutionContext) -> dict:
    return await asyncio.to_thread(_read_file, arguments, context)


def _read_file(arguments: dict, context: ToolExecutionContext) -> dict:
    raw = str(arguments["path"])
    normalized = raw.replace("\\", "/")
    windows_path = PureWindowsPath(raw)
    path = Path(normalized)
    if "\x00" in raw or ":" in raw or path.is_absolute() or windows_path.is_absolute() or windows_path.drive or any(part == ".." for part in path.parts):
        raise ToolExecutionError("FILE_PATH_FORBIDDEN", "File path must stay inside an allowed data directory.")
    max_bytes = min(int(arguments.get("max_bytes", FILE_MAX_BYTES)), FILE_MAX_BYTES)
    base = Path(context.repo_root).resolve()
    roots = [base / "data" / "knowledge", base / "data" / "attachments"]
    resolved = (base / path).resolve()
    if not any(_inside(resolved, root) for root in roots):
        raise ToolExecutionError("FILE_PATH_FORBIDDEN", "Only Knowledge and attachment files may be read.")
    if not resolved.is_file():
        raise ToolExecutionError("FILE_NOT_FOUND", "File was not found.")
    try:
        with resolved.open("rb") as handle:
            data = handle.read(max_bytes + 1)
            actual_size = resolved.stat().st_size
    except OSError as exc:
        raise ToolExecutionError("FILE_READ_FAILED", "File could not be read.") from exc
    truncated = len(data) > max_bytes
    content = data[:max_bytes].decode("utf-8", errors="replace")
    return {"path": resolved.relative_to(base).as_posix(), "content": content, "size_bytes": actual_size, "truncated": truncated or actual_size > max_bytes}


async def web_search(arguments: dict, context: ToolExecutionContext) -> dict:
    settings = context.harness_settings
    base = getattr(settings, "searxng_base_url", None)
    if not base:
        raise ToolExecutionError("TOOL_NOT_CONFIGURED", "Configure a SearXNG JSON service before using web_search.")
    query = str(arguments["query"]).strip()
    limit = int(arguments.get("limit", 5))
    url = f"{str(base).rstrip('/')}/search?{urlencode({'q': query, 'format': 'json'})}"
    data, final_url = await fetch_json(url, context.network_policy)
    rows = []
    results = data.get("results")
    if not isinstance(results, list):
        raise ToolExecutionError("NETWORK_INVALID_JSON", "Search service must return a results array.")
    for item in results:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        try:
            result_url = context.network_policy.validate_url(str(item["url"]), resolve_dns=False)
        except NetworkPolicyError:
            continue
        result_url = public_url(result_url)
        rows.append({"title": str(item.get("title") or ""), "url": result_url, "snippet": str(item.get("content") or item.get("snippet") or "")})
        if len(rows) >= limit:
            break
    return {"query": query, "results": rows, "service_url": public_url(final_url)}


async def fetch_url(arguments: dict, context: ToolExecutionContext) -> dict:
    url = context.network_policy.validate_url(arguments["url"], resolve_dns=False)
    data, final_url, content_type = await fetch_bytes(url, context.network_policy)
    if content_type and not any(value in content_type.lower() for value in ("text/", "json", "xml", "javascript")):
        raise ToolExecutionError("NETWORK_CONTENT_TYPE_FORBIDDEN", "Only text responses may be fetched.")
    text, truncated = text_from_response(data, content_type)
    max_chars = min(int(arguments.get("max_chars", len(text))), 200_000)
    return {"url": public_url(url), "final_url": public_url(final_url), "content_type": content_type, "content": text[:max_chars], "truncated": truncated or len(text) > max_chars}


async def knowledge_search(arguments: dict, context: ToolExecutionContext) -> dict:
    if context.knowledge_service is None or not context.session_id:
        raise ToolExecutionError("KNOWLEDGE_UNAVAILABLE", "Knowledge search is unavailable for this session.")
    allowed = set(context.knowledge_base_ids or [])
    requested = arguments.get("knowledge_base_ids")
    ids = list(requested) if requested is not None else list(context.knowledge_base_ids or [])
    if not set(ids).issubset(allowed):
        raise ToolExecutionError("KNOWLEDGE_SCOPE_FORBIDDEN", "Knowledge search is limited to the active session bindings.")
    return await context.knowledge_service.search(query=str(arguments["query"]).strip(), knowledge_base_ids=ids, session_id=context.session_id, top_k=arguments.get("top_k"), max_context_chars=arguments.get("max_context_chars"), include_debug=False)


async def base64_encode(arguments: dict, _context: ToolExecutionContext) -> dict:
    value = str(arguments["value"])
    data = value.encode("utf-8")
    if len(data) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_INPUT_TOO_LARGE", "Codec input exceeds the 1 MiB limit.")
    encoded = base64.b64encode(data)
    if len(encoded) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_OUTPUT_TOO_LARGE", "Codec output exceeds the 1 MiB limit.")
    return {"value": encoded.decode("ascii"), "encoding": "base64", "input_bytes": len(data)}


async def base64_decode(arguments: dict, _context: ToolExecutionContext) -> dict:
    value = str(arguments["value"])
    if len(value.encode("utf-8")) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_INPUT_TOO_LARGE", "Codec input exceeds the 1 MiB limit.")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolExecutionError("CODEC_INVALID_BASE64", "Value is not valid base64.") from exc
    if len(data) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_OUTPUT_TOO_LARGE", "Codec output exceeds the 1 MiB limit.")
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("CODEC_INVALID_UTF8", "Decoded bytes are not valid UTF-8 text.") from exc
    return {"value": decoded, "encoding": "utf-8", "output_bytes": len(data)}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def register_builtin_tools(registry) -> None:
    obj = {"type": "object"}
    registry.register(ToolSpec("read_file", "Read a UTF-8 file from the allowed data directories.", {**obj, "properties": {"path": {"type": "string", "minLength": 1}, "max_bytes": {"type": "integer", "minimum": 1, "maximum": FILE_MAX_BYTES}}, "required": ["path"], "additionalProperties": False}, read_file, "file", True, True))
    registry.register(ToolSpec("web_search", "Search a configured SearXNG JSON service.", {**obj, "properties": {"query": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"], "additionalProperties": False}, web_search, "network", True, True))
    registry.register(ToolSpec("fetch_url", "Fetch a public text URL.", {**obj, "properties": {"url": {"type": "string", "format": "uri", "pattern": r"^https?://\S+$"}, "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000}}, "required": ["url"], "additionalProperties": False}, fetch_url, "network", True, True))
    registry.register(ToolSpec("knowledge_search", "Search the active session Knowledge bindings.", {**obj, "properties": {"query": {"type": "string", "minLength": 1}, "knowledge_base_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 128}, "top_k": {"type": "integer", "minimum": 1, "maximum": 100}, "max_context_chars": {"type": "integer", "minimum": 100, "maximum": 200000}}, "required": ["query"], "additionalProperties": False}, knowledge_search, "safe", False, True))
    for name, description, handler in (("base64_encode", "Encode UTF-8 text as base64.", base64_encode), ("base64_decode", "Decode base64 as UTF-8 text.", base64_decode)):
        registry.register(ToolSpec(name, description, {**obj, "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False}, handler, "safe", False, True))
