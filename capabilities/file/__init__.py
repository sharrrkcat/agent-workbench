import base64
import codecs
import os
from pathlib import Path

from ai_workbench.core.attachments import ALLOWED_AUDIO_MIME_TYPES, ALLOWED_IMAGE_MIME_TYPES, save_generated_attachment_bytes


MAX_TEXT_BYTES = 1 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
CONFIG_DEFAULTS = {
    "allowed_directories": ["./data", "./examples", "./agents", "./capabilities"],
    "max_local_text_read_size_mb": 2,
    "max_local_image_read_size_mb": 10,
    "max_local_audio_read_size_mb": 10,
    "allowed_text_extensions": [
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".html",
        ".css",
        ".env",
        ".log",
        ".csv",
        ".sql",
        ".sh",
        ".ps1",
        ".bat",
        ".ini",
        ".cfg",
    ],
    "enable_read_file": True,
    "enable_read_image": True,
    "enable_read_audio_command": True,
}
_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
_AUDIO_MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
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
    def read_text(self, text: str, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        if not bool(config["enable_read_file"]):
            raise ValueError("Command disabled: /read-file is disabled in File Capability settings.")
        path = _resolve_allowed_file(text, config, context=context)
        _ensure_text_extension_allowed(path, config)
        size = path.stat().st_size
        limit = _mb_to_bytes(config["max_local_text_read_size_mb"])
        if context is not None and size > limit:
            raise ValueError(f"File too large for /read-file. Maximum size is {_format_mb(config['max_local_text_read_size_mb'])}.")
        try:
            content, truncated = _read_utf8_prefix(path, limit)
        except UnicodeDecodeError as exc:
            raise ValueError("File must be readable as UTF-8 text for /read-file.") from exc
        return {
            "filename": path.name,
            "language": _language_for_path(path),
            "mime_type": _text_mime_type(path),
            "content": content,
            "size": size,
            "truncated": truncated,
        }

    def read_image(self, text: str, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        if not bool(config["enable_read_image"]):
            raise ValueError("Command disabled: /read-image is disabled in File Capability settings.")
        path = _resolve_allowed_file(text, config, context=context)
        mime_type = _image_mime_type(path)
        size = path.stat().st_size
        limit = _mb_to_bytes(config["max_local_image_read_size_mb"])
        if size > limit:
            raise ValueError(f"File too large for /read-image. Maximum size is {_format_mb(config['max_local_image_read_size_mb'])}.")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "url": f"data:{mime_type};base64,{encoded}",
            "alt": f"Local image: {path.name}",
            "title": path.name,
            "caption": f"Loaded from local file - {mime_type} - {size} bytes",
        }

    def read_audio(self, text: str, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        if not bool(config["enable_read_audio_command"]):
            raise ValueError("Command disabled: /read-audio is disabled in File Capability settings.")
        path = _resolve_allowed_file(text, config, context=context)
        mime_type = _audio_mime_type(path)
        size = path.stat().st_size
        limit = _mb_to_bytes(config["max_local_audio_read_size_mb"])
        if size > limit:
            raise ValueError(f"File too large for /read-audio. Maximum size is {_format_mb(config['max_local_audio_read_size_mb'])}.")
        attachment = save_generated_attachment_bytes(
            data=path.read_bytes(),
            filename=path.name,
            mime_type=mime_type,
            kind="audio",
            metadata={"source": "file_capability"},
            max_size_bytes=limit,
            max_size_label=_format_mb(config["max_local_audio_read_size_mb"]),
        )
        return {
            "source": "attachment",
            "attachment_id": attachment["id"],
            "url": attachment["url"],
            "mime_type": attachment["mime_type"],
            "filename": attachment["name"],
            "title": attachment["name"],
        }


def _runtime_config(context: dict | None) -> dict:
    config = dict(CONFIG_DEFAULTS)
    provided = (context or {}).get("capability_config") if isinstance(context, dict) else None
    if isinstance(provided, dict) and provided:
        config.update(provided)
    else:
        configured = os.getenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", "")
        extras = [item.strip() for item in configured.split(os.pathsep) if item.strip()]
        if extras:
            config["allowed_directories"] = [*CONFIG_DEFAULTS["allowed_directories"], *extras]
    if context is None:
        config["max_local_text_read_size_mb"] = MAX_TEXT_BYTES / (1024 * 1024)
        config["max_local_audio_read_size_mb"] = MAX_AUDIO_BYTES / (1024 * 1024)
    return config


def _resolve_allowed_file(raw_path: str, config: dict, context: dict | None = None) -> Path:
    value = str(raw_path or "").strip().strip('"')
    if not value:
        raise ValueError("File path required.")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = _repo_root(context) / candidate
    resolved = candidate.resolve()
    if not resolved.exists():
        raise ValueError("File not found.")
    if not resolved.is_file():
        raise ValueError("Path must point to a file, not a directory.")
    allowed_dirs = _allowed_dirs(config, context=context)
    if not any(_is_relative_to(resolved, allowed_dir) for allowed_dir in allowed_dirs):
        raise ValueError(f"Path outside allowed directories. File access denied. Allowed directories: {_format_allowed_dirs(allowed_dirs)}")
    return resolved


def _allowed_dirs(config: dict | None = None, context: dict | None = None) -> list[Path]:
    if config is None:
        config = _runtime_config(context)
    raw_dirs = config.get("allowed_directories", [])
    if not isinstance(raw_dirs, list):
        return []
    root = _repo_root(context)
    resolved = []
    for item in raw_dirs:
        path = Path(str(item).strip())
        if not str(path):
            continue
        if not path.is_absolute():
            path = root / path
        resolved.append(path.resolve())
    return resolved


def _image_mime_type(path: Path) -> str:
    mime_type = _IMAGE_MIME_BY_EXT.get(path.suffix.lower(), "")
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("Only PNG, JPEG, WebP, GIF, and SVG image files are supported by /read-image.")
    return mime_type


def _audio_mime_type(path: Path) -> str:
    mime_type = _AUDIO_MIME_BY_EXT.get(path.suffix.lower(), "")
    if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
        raise ValueError("Only WAV, MP3, OGG, M4A, FLAC, and WebM audio files are supported by /read-audio.")
    return mime_type


def _ensure_text_extension_allowed(path: Path, config: dict) -> None:
    allowed = config.get("allowed_text_extensions", [])
    if not isinstance(allowed, list):
        allowed = []
    normalized = {str(item).lower() for item in allowed}
    extension = _text_extension_for_policy(path)
    if extension not in normalized:
        raise ValueError(f"Extension not allowed for /read-file: {extension or '(none)'}.")


def _text_extension_for_policy(path: Path) -> str:
    if path.name == ".env" or path.name.startswith(".env."):
        return ".env"
    return path.suffix.lower()


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


def _repo_root(context: dict | None = None) -> Path:
    value = (context or {}).get("repo_root") if isinstance(context, dict) else None
    if value:
        return Path(str(value)).resolve()
    return Path.cwd().resolve()


def _mb_to_bytes(value: object) -> int:
    return int(float(value) * 1024 * 1024)


def _format_mb(value: object) -> str:
    amount = float(value)
    return f"{amount:g} MB"


def _format_allowed_dirs(allowed_dirs: list[Path]) -> str:
    if not allowed_dirs:
        return "none configured"
    visible = [str(path) for path in allowed_dirs[:4]]
    if len(allowed_dirs) > 4:
        visible.append(f"... +{len(allowed_dirs) - 4} more")
    return ", ".join(visible)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
