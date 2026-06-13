from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import threading
from time import perf_counter
import traceback
from typing import Any
from uuid import uuid4


REQUEST_ID_HEADER = "X-Request-ID"
INFERENCE_LOG_RELATIVE_PATH = Path("data") / "logs" / "inference" / "inference.jsonl"
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
MAX_LOG_STRING_CHARS = 500
MAX_LOG_DEPTH = 5

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_DATA_URL_RE = re.compile(r"data:[^;,\s]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)
_LONG_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{80,}={0,2}(?![A-Za-z0-9+/])")
_SIMPLE_IMAGE_BASE64_RE = re.compile(r"\bA{4,}={0,2}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]+=*", re.IGNORECASE)
_API_KEY_RE = re.compile(r"(?i)\b(api[_-]?key|x-api-key|authorization)\b\s*[:=]\s*[\"']?[^\"'\s,;}]+")
_SECRET_TOKEN_RE = re.compile(r"(?i)\b[\w.-]*secret[\w.-]*\b")
_GENERATED_TEXT_RE = re.compile(r"(?i)generated\s+text[^.;\n]*")
_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"',;}]+")
_POSIX_PATH_RE = re.compile(r"(?<!:)\/(?:tmp|var|home|Users|mnt|private)\/[^\s\"',;}]+")

_current_request_id: ContextVar[str | None] = ContextVar("inference_request_id", default=None)
_write_lock = threading.Lock()


def current_request_id() -> str | None:
    return _current_request_id.get()


def set_current_request_id(value: str):
    return _current_request_id.set(value)


def reset_current_request_id(token: Any) -> None:
    _current_request_id.reset(token)


def resolve_request_id(raw_value: str | None) -> str:
    if raw_value:
        value = raw_value.strip()
        if _REQUEST_ID_RE.fullmatch(value):
            return value
    return str(uuid4())


def is_inference_observability_path(path: str) -> bool:
    return path == "/v1" or path.startswith("/v1/") or path == "/api/inference" or path.startswith("/api/inference/")


def inference_route_family(path: str) -> str:
    return "openai_compatible" if path == "/v1" or path.startswith("/v1/") else "workbench_native"


def monotonic_time() -> float:
    return perf_counter()


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def inference_log_path(repo_root: str | Path | None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return root / INFERENCE_LOG_RELATIVE_PATH


def log_access_event(
    *,
    repo_root: str | Path | None,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    error_code: str | None = None,
) -> None:
    _write_event(
        repo_root,
        {
            "event": "access",
            "request_id": current_request_id(),
            "route_family": inference_route_family(path),
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "error_code": error_code,
        },
    )


def log_inference_failure(
    *,
    repo_root: str | Path | None,
    endpoint: str,
    status_code: int,
    error_code: str,
    exception: BaseException,
    context: dict[str, Any] | None = None,
) -> None:
    _write_event(
        repo_root,
        {
            "event": "inference_failure",
            "request_id": current_request_id(),
            "route_family": inference_route_family(endpoint),
            "endpoint": endpoint,
            "status_code": status_code,
            "error_code": error_code,
            "context": context or {},
            "exception": exception_chain(exception, repo_root=repo_root),
        },
    )


def log_unhandled_exception(
    *,
    repo_root: str | Path | None,
    method: str,
    path: str,
    exception: BaseException,
) -> None:
    _write_event(
        repo_root,
        {
            "event": "unhandled_exception",
            "request_id": current_request_id(),
            "route_family": inference_route_family(path),
            "method": method,
            "path": path,
            "exception": exception_chain(exception, repo_root=repo_root),
        },
    )


def exception_chain(exception: BaseException, *, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = exception
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(
            {
                "type": type(current).__name__,
                "message": sanitize_text(str(current), repo_root=repo_root),
                "stack": _compact_traceback(current, repo_root=repo_root),
            }
        )
        current = current.__cause__ or current.__context__
    return chain


def sanitize_for_log(value: Any, *, repo_root: str | Path | None = None, _depth: int = 0) -> Any:
    if _depth > MAX_LOG_DEPTH:
        return "<nested>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text(value, repo_root=repo_root)
    if isinstance(value, Path):
        return sanitize_text(str(value), repo_root=repo_root)
    if isinstance(value, dict):
        return {
            sanitize_text(str(key), repo_root=repo_root): sanitize_for_log(item, repo_root=repo_root, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_log(item, repo_root=repo_root, _depth=_depth + 1) for item in list(value)[:100]]
    return sanitize_text(str(value), repo_root=repo_root)


def sanitize_text(value: str, *, repo_root: str | Path | None = None) -> str:
    text = value
    for root in _path_roots(repo_root):
        root_text = str(root)
        if root_text:
            text = text.replace(root_text, "<path>")
            text = text.replace(root_text.replace("\\", "/"), "<path>")
            text = text.replace(root_text.replace("/", "\\"), "<path>")
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    text = _API_KEY_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _DATA_URL_RE.sub("data:<redacted>;base64,<redacted>", text)
    text = _LONG_BASE64_RE.sub("<base64>", text)
    text = _SIMPLE_IMAGE_BASE64_RE.sub("<base64>", text)
    text = _SECRET_TOKEN_RE.sub("<secret>", text)
    text = _GENERATED_TEXT_RE.sub("<generated_text>", text)
    text = _WINDOWS_PATH_RE.sub("<path>", text)
    text = _POSIX_PATH_RE.sub("<path>", text)
    if len(text) > MAX_LOG_STRING_CHARS:
        text = f"{text[:MAX_LOG_STRING_CHARS]}...<truncated>"
    return text


def _write_event(repo_root: str | Path | None, event: dict[str, Any]) -> None:
    path = inference_log_path(repo_root)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **event,
    }
    safe_payload = sanitize_for_log(payload, repo_root=repo_root)
    line = json.dumps(safe_payload, ensure_ascii=True, separators=(",", ":"))
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        return


def _rotate_if_needed(path: Path) -> None:
    if not path.exists() or path.stat().st_size < MAX_LOG_FILE_BYTES:
        return
    oldest = path.with_name(f"{path.name}.{LOG_BACKUP_COUNT}")
    if oldest.exists():
        oldest.unlink()
    for index in range(LOG_BACKUP_COUNT - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            source.replace(target)
    path.replace(path.with_name(f"{path.name}.1"))


def _compact_traceback(exception: BaseException, *, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    frames = traceback.extract_tb(exception.__traceback__)
    return [
        {
            "file": _safe_frame_path(frame.filename, repo_root=repo_root),
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in frames[-8:]
    ]


def _safe_frame_path(filename: str, *, repo_root: str | Path | None = None) -> str:
    path = Path(filename)
    if repo_root is not None:
        try:
            return str(path.resolve().relative_to(Path(repo_root).resolve())).replace("\\", "/")
        except Exception:
            pass
    return path.name


def _path_roots(repo_root: str | Path | None) -> list[Path]:
    roots: list[Path] = []
    for value in (repo_root, Path.cwd(), tempfile.gettempdir()):
        if value is None:
            continue
        try:
            roots.append(Path(value).resolve())
        except Exception:
            continue
    return roots
