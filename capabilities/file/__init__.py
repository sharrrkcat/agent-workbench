import base64
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


class CapabilityRuntime:
    def read_text(self, text: str) -> str:
        path = _resolve_allowed_file(text)
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise ValueError("File is too large for /read-file. Maximum size is 1 MB.")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Only UTF-8 text files are supported by /read-file.") from exc

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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
