import base64
import codecs
import os
from pathlib import Path

from ai_workbench.core.attachments import ALLOWED_IMAGE_MIME_TYPES


MAX_TEXT_BYTES = 1 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".env": "dotenv",
    ".log": "log",
    ".txt": "text",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sh": "bash",
    ".sql": "sql",
}
_TEXT_MIME_BY_EXT = {
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".tsx": "text/tsx",
    ".jsx": "text/jsx",
    ".json": "application/json",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/toml",
    ".xml": "application/xml",
    ".html": "text/html",
    ".css": "text/css",
    ".md": "text/markdown",
    ".env": "text/plain",
    ".log": "text/plain",
    ".txt": "text/plain",
    ".ps1": "text/plain",
    ".bat": "text/plain",
    ".cmd": "text/plain",
    ".sh": "text/x-shellscript",
    ".sql": "application/sql",
}


class CapabilityRuntime:
    def read_text(self, text: str) -> dict:
        path = _resolve_allowed_file(text)
        size = path.stat().st_size
        try:
            content, truncated = _read_utf8_prefix(path, MAX_TEXT_BYTES)
        except UnicodeDecodeError as exc:
            raise ValueError("Only UTF-8 text files are supported by /read-file.") from exc
        return {
            "filename": path.name,
            "language": _language_for_path(path),
            "mime_type": _text_mime_type(path),
            "content": content,
            "size": size,
            "truncated": truncated,
        }

    def read_image(self, text: str) -> dict:
        path = _resolve_allowed_file(text)
        mime_type = _image_mime_type(path)
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ValueError("Image is too large for /read-image. Maximum size is 10 MB.")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "url": f"data:{mime_type};base64,{encoded}",
            "alt": f"Local image: {path.name}",
            "title": path.name,
            "caption": f"Loaded from local file - {mime_type} - {size} bytes",
        }


def _resolve_allowed_file(raw_path: str) -> Path:
    value = str(raw_path or "").strip().strip('"')
    if not value:
        raise ValueError("A file path is required.")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    if not resolved.exists():
        raise ValueError("File not found in allowed directories.")
    if not resolved.is_file():
        raise ValueError("Path must point to a file, not a directory.")
    allowed_dirs = _allowed_dirs()
    if not any(_is_relative_to(resolved, allowed_dir) for allowed_dir in allowed_dirs):
        allowed_list = ", ".join(str(path) for path in allowed_dirs)
        raise ValueError(f"File access denied. Allowed directories: {allowed_list}")
    return resolved


def _allowed_dirs() -> list[Path]:
    default = [Path("./data"), Path("./examples"), Path("./agents"), Path("./capabilities")]
    configured = os.getenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", "")
    extras = [Path(item.strip()) for item in configured.split(os.pathsep) if item.strip()]
    return [path.resolve() for path in [*default, *extras]]


def _image_mime_type(path: Path) -> str:
    mime_type = _IMAGE_MIME_BY_EXT.get(path.suffix.lower(), "")
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("Only PNG, JPEG, WebP, GIF, and SVG image files are supported by /read-image.")
    return mime_type


def _read_utf8_prefix(path: Path, limit: int) -> tuple[str, bool]:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    truncated = len(raw) > limit
    chunk = raw[:limit] if truncated else raw
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    return decoder.decode(chunk, final=not truncated), truncated


def _language_for_path(path: Path) -> str:
    if path.name == ".env" or path.name.startswith(".env."):
        return "dotenv"
    return _LANGUAGE_BY_EXT.get(path.suffix.lower(), "text")


def _text_mime_type(path: Path) -> str:
    if path.name == ".env" or path.name.startswith(".env."):
        return "text/plain"
    return _TEXT_MIME_BY_EXT.get(path.suffix.lower(), "text/plain")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
