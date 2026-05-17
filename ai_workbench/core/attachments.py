import base64
import binascii
import mimetypes
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workbench.core.time import isoformat_utc, utc_now


ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}
ALLOWED_AUDIO_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/ogg",
    "audio/mp4",
    "audio/flac",
    "audio/webm",
}
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".webm"}
ALLOWED_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/webm",
    "video/ogg",
}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogv"}
MAX_IMAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_FILE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_CONFIGURABLE_ATTACHMENT_BYTES = 100 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10
MAX_IMAGE_ATTACHMENTS_PER_MESSAGE = 6
TEXT_READ_LIMIT_BYTES = 1024 * 1024

ALLOWED_TEXT_EXTENSIONS = {
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
}

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.+]+/[-\w.+]+);base64,(?P<data>[a-zA-Z0-9+/=\s]+)$")
_LOCAL_ATTACHMENT_RE = re.compile(r"^local://attachments/(?P<name>[a-f0-9-]+\.[a-z0-9]+)$")
_ATTACHMENT_NAME_RE = re.compile(r"^[a-f0-9-]+\.[a-z0-9]+$")
_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/flac": ".flac",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "application/octet-stream": ".bin",
}
_EXTENSION_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".mp4": "video/mp4",
    ".ogv": "video/ogg",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".tsx": "text/tsx",
    ".jsx": "text/jsx",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".xml": "application/xml",
    ".html": "text/html",
    ".css": "text/css",
    ".env": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".sql": "application/sql",
    ".sh": "application/x-sh",
    ".ps1": "text/plain",
    ".bat": "application/bat",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".bin": "application/octet-stream",
}


class ImageAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: str = "image"
    mime_type: str
    name: str = ""
    size: int = Field(ge=0)
    data_url: str | None = Field(default=None, min_length=1)
    uri: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    created_at: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value != "image":
            raise ValueError("Only image attachments are supported.")
        return value

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported image MIME type.")
        return cleaned

    @field_validator("data_url")
    @classmethod
    def validate_data_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        match = _DATA_URL_RE.match(cleaned)
        if not match:
            raise ValueError("Attachment data_url must be an allowed image base64 data URL.")
        return cleaned

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not _LOCAL_ATTACHMENT_RE.match(cleaned):
            raise ValueError("Attachment uri must use local://attachments/<id>.<ext>.")
        return cleaned


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["image", "file", "audio", "video"]
    mime_type: str
    name: str = ""
    size: int = Field(ge=0, le=MAX_CONFIGURABLE_ATTACHMENT_BYTES)
    data_url: str | None = Field(default=None, min_length=1)
    uri: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    created_at: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Attachment MIME type is required.")
        return cleaned

    @field_validator("data_url")
    @classmethod
    def validate_data_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        match = _DATA_URL_RE.match(cleaned)
        if not match:
            raise ValueError("Attachment data_url must be a base64 data URL.")
        return cleaned

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not _LOCAL_ATTACHMENT_RE.match(cleaned):
            raise ValueError("Attachment uri must use local://attachments/<id>.<ext>.")
        return cleaned


def validate_image_attachments(value: Any) -> list[dict[str, Any]]:
    return validate_attachments(value, max_attachments=MAX_IMAGE_ATTACHMENTS_PER_MESSAGE, images_only=True)


def validate_attachments(value: Any, max_attachments: int | None = None, images_only: bool = False, settings: Any = None) -> list[dict[str, Any]]:
    max_attachments = max_attachments or getattr(settings, "max_attachments_per_message", MAX_ATTACHMENTS_PER_MESSAGE)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("attachments must be a list.")
    if len(value) > max_attachments:
        raise ValueError(f"At most {max_attachments} attachments are allowed.")

    attachments: list[dict[str, Any]] = []
    for item in value:
        attachment = Attachment.model_validate(item)
        if images_only and attachment.type != "image":
            raise ValueError("Only image attachments are supported.")
        if bool(attachment.data_url) == bool(attachment.uri):
            raise ValueError("Attachment must include exactly one of data_url or uri.")
        if attachment.data_url:
            data_mime = _data_url_mime_type(attachment.data_url)
            if data_mime != attachment.mime_type:
                raise ValueError("Attachment MIME type does not match data_url MIME type.")
            attachments.append(save_attachment_from_data_url(attachment.model_dump(exclude_none=True), settings=settings))
        else:
            data = attachment.model_dump(exclude_none=True)
            _validate_attachment_metadata(data, settings=settings)
            attachments.append(data)
    return attachments


def _data_url_mime_type(data_url: str) -> str:
    match = _DATA_URL_RE.match(data_url.strip())
    return match.group("mime").lower() if match else ""


def attachments_root() -> Path:
    configured = os.getenv("AGENT_WORKBENCH_ATTACHMENTS_DIR")
    root = Path(configured) if configured else Path("./data/attachments")
    return root.resolve()


def save_attachment_from_data_url(attachment: dict[str, Any], settings: Any = None) -> dict[str, Any]:
    parsed = Attachment.model_validate(attachment)
    if not parsed.data_url:
        raise ValueError("Attachment data_url is required.")
    attachment_bytes, mime_type = _decode_data_url(parsed.data_url)
    if mime_type != parsed.mime_type:
        raise ValueError("Attachment MIME type does not match data_url MIME type.")
    inferred_type = infer_attachment_type(parsed.name, mime_type)
    if parsed.type != inferred_type:
        raise ValueError("Attachment type does not match MIME type or extension.")
    _validate_attachment_payload(parsed.name, mime_type, attachment_bytes, inferred_type, settings=settings)
    _validate_attachment_size(max(parsed.size, len(attachment_bytes)), inferred_type, settings=settings)

    attachment_id = str(uuid4())
    extension = _extension_for_attachment(parsed.name, mime_type)
    filename = f"{attachment_id}{extension}"
    target_dir = attachments_root() / _attachment_subdir(inferred_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / filename).resolve()
    target.write_bytes(attachment_bytes)

    data = parsed.model_dump(exclude_none=True, exclude={"data_url"})
    data.update(
        {
            "id": attachment_id,
            "type": inferred_type,
            "mime_type": mime_type,
            "size": len(attachment_bytes),
            "uri": f"local://attachments/{filename}",
            "url": f"/api/attachments/{filename}",
            "created_at": isoformat_utc(utc_now()),
        }
    )
    return data


def save_attachment_from_file(path: str | Path, name: str | None = None, mime_type: str | None = None, settings: Any = None) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError("Attachment file not found.")
    display_name = name or source.name
    guessed_mime = (mime_type or mimetypes.guess_type(display_name)[0] or _mime_type_for_extension(Path(display_name).suffix)).lower()
    data = source.read_bytes()
    attachment_type = infer_attachment_type(display_name, guessed_mime)
    _validate_attachment_payload(display_name, guessed_mime, data, attachment_type, settings=settings)
    return _store_attachment_bytes(display_name, guessed_mime, data, attachment_type)


def save_attachment_from_upload(name: str, mime_type: str, data: bytes, settings: Any = None) -> dict[str, Any]:
    attachment_type = infer_attachment_type(name, mime_type)
    _validate_attachment_payload(name, mime_type, data, attachment_type, settings=settings)
    return _store_attachment_bytes(name, mime_type.strip().lower(), data, attachment_type)


def save_generated_attachment_bytes(
    data: bytes,
    filename: str,
    mime_type: str,
    kind: Literal["image", "file", "audio", "video"] = "file",
    metadata: dict[str, Any] | None = None,
    settings: Any = None,
    max_size_bytes: int | None = None,
    max_size_label: str | None = None,
) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise ValueError("Generated attachment data must be bytes.")
    if not data:
        raise ValueError("Generated attachment is empty.")
    attachment_type = _normalize_attachment_kind(kind)
    safe_name = sanitize_attachment_filename(filename)
    cleaned_mime = (mime_type or "").strip().lower()
    if not cleaned_mime:
        raise ValueError("Generated attachment MIME type is required.")
    _validate_generated_attachment_payload(
        safe_name,
        cleaned_mime,
        data,
        attachment_type,
        settings=settings,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
    )
    stored = _store_attachment_bytes(safe_name, cleaned_mime, data, attachment_type)
    if metadata:
        stored["metadata"] = dict(metadata)
    return stored


def save_generated_attachment_base64(
    data_base64: str,
    filename: str,
    mime_type: str,
    kind: Literal["image", "file", "audio", "video"] = "file",
    metadata: dict[str, Any] | None = None,
    settings: Any = None,
    max_size_bytes: int | None = None,
    max_size_label: str | None = None,
) -> dict[str, Any]:
    data, detected_mime = _decode_base64_payload(data_base64)
    cleaned_mime = (mime_type or detected_mime or "").strip().lower()
    if detected_mime and cleaned_mime != detected_mime:
        raise ValueError("Generated attachment MIME type does not match data URL MIME type.")
    return save_generated_attachment_bytes(
        data=data,
        filename=filename,
        mime_type=cleaned_mime,
        kind=kind,
        metadata=metadata,
        settings=settings,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
    )


def save_generated_attachment_file(
    source_path: str | Path,
    filename: str | None = None,
    mime_type: str | None = None,
    kind: Literal["image", "file", "audio", "video"] = "file",
    metadata: dict[str, Any] | None = None,
    settings: Any = None,
    max_size_bytes: int | None = None,
    max_size_label: str | None = None,
) -> dict[str, Any]:
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("Generated attachment source file not found.")
    safe_name = sanitize_attachment_filename(filename or source.name)
    cleaned_mime = (mime_type or mimetypes.guess_type(safe_name)[0] or _mime_type_for_extension(Path(safe_name).suffix)).strip().lower()
    if not cleaned_mime:
        raise ValueError("Generated attachment MIME type is required.")
    attachment_type = _normalize_attachment_kind(kind)
    size = source.stat().st_size
    _validate_generated_attachment_file(
        safe_name,
        cleaned_mime,
        size,
        attachment_type,
        settings=settings,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
    )
    stored = _store_attachment_file(source, safe_name, cleaned_mime, attachment_type, size)
    if metadata:
        stored["metadata"] = dict(metadata)
    return stored


def _store_attachment_bytes(name: str, mime_type: str, data: bytes, attachment_type: str) -> dict[str, Any]:
    attachment_id = str(uuid4())
    extension = _extension_for_attachment(name, mime_type)
    filename = f"{attachment_id}{extension}"
    target_dir = attachments_root() / _attachment_subdir(attachment_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / filename).resolve()
    target.write_bytes(data)
    uri = f"local://attachments/{filename}"
    return {
        "id": attachment_id,
        "type": attachment_type,
        "mime_type": mime_type,
        "name": name or filename,
        "size": len(data),
        "uri": uri,
        "url": f"/api/attachments/{filename}",
        "created_at": isoformat_utc(utc_now()),
    }


def _store_attachment_file(source: Path, name: str, mime_type: str, attachment_type: str, size: int) -> dict[str, Any]:
    attachment_id = str(uuid4())
    extension = _extension_for_attachment(name, mime_type)
    filename = f"{attachment_id}{extension}"
    target_dir = attachments_root() / _attachment_subdir(attachment_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / filename).resolve()
    try:
        target.relative_to(target_dir.resolve())
    except ValueError as exc:
        raise ValueError("Attachment path is outside the attachment directory.") from exc
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    uri = f"local://attachments/{filename}"
    return {
        "id": attachment_id,
        "type": attachment_type,
        "mime_type": mime_type,
        "name": name or filename,
        "size": size,
        "uri": uri,
        "url": f"/api/attachments/{filename}",
        "created_at": isoformat_utc(utc_now()),
    }


def resolve_attachment_uri(uri_or_id: str) -> Path:
    value = str(uri_or_id or "").strip()
    if value.startswith("local://attachments/"):
        match = _LOCAL_ATTACHMENT_RE.match(value)
        if not match:
            raise ValueError("Invalid local attachment URI.")
        filename = match.group("name")
    else:
        filename = value
        if not _ATTACHMENT_NAME_RE.match(filename):
            raise ValueError("Invalid attachment id.")

    suffix = Path(filename).suffix.lower()
    for subdir in _attachment_subdirs_for_suffix(suffix):
        root = (attachments_root() / subdir).resolve()
        path = (root / filename).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Attachment path is outside the attachment directory.") from exc
        if path.is_file():
            return path
    root = (attachments_root() / _attachment_subdirs_for_suffix(suffix)[0]).resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Attachment path is outside the attachment directory.") from exc
    return path


def read_attachment_as_data_url(attachment: dict[str, Any]) -> str:
    parsed = ImageAttachment.model_validate(attachment)
    if parsed.data_url:
        return parsed.data_url
    if not parsed.uri:
        raise ValueError("Attachment does not include readable image data.")

    path = resolve_attachment_uri(parsed.uri)
    if not path.is_file():
        raise FileNotFoundError("Attachment file not found.")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_ATTACHMENT_BYTES:
        raise ValueError("Attachment image is too large. Maximum size is 10 MB.")
    mime_type = _mime_type_for_attachment_path(path)
    if mime_type != parsed.mime_type:
        raise ValueError("Attachment MIME type does not match file extension.")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def read_attachment_bytes(attachment: dict[str, Any]) -> bytes:
    parsed = Attachment.model_validate(attachment)
    if parsed.data_url:
        data, _mime_type = _decode_data_url(parsed.data_url)
        return data
    if not parsed.uri:
        raise ValueError("Attachment does not include readable data.")
    path = resolve_attachment_uri(parsed.uri)
    if not path.is_file():
        raise FileNotFoundError("Attachment file not found.")
    return path.read_bytes()


def read_attachment_text(attachment: dict[str, Any], limit: int = TEXT_READ_LIMIT_BYTES) -> dict[str, Any]:
    parsed = Attachment.model_validate(attachment)
    data = read_attachment_bytes(parsed.model_dump(exclude_none=True))
    if not is_text_attachment(parsed.model_dump(exclude_none=True)):
        raise ValueError("Attachment is not a supported text file.")
    truncated = len(data) > limit
    sample = data[:limit]
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            text = sample.decode(encoding)
            return {
                "filename": parsed.name or None,
                "language": language_for_filename(parsed.name),
                "mime_type": parsed.mime_type,
                "content": text,
                "size": len(data),
                "truncated": truncated,
            }
        except UnicodeDecodeError:
            continue
    raise ValueError("Unsupported file encoding. Only UTF-8 text files are readable.")


def infer_attachment_type(name: str | None, mime_type: str | None) -> Literal["image", "file", "audio", "video"]:
    cleaned_mime = (mime_type or "").strip().lower()
    suffix = Path(name or "").suffix.lower()
    if cleaned_mime in ALLOWED_IMAGE_MIME_TYPES or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return "image"
    if cleaned_mime in ALLOWED_AUDIO_MIME_TYPES:
        return "audio"
    if cleaned_mime in ALLOWED_VIDEO_MIME_TYPES or suffix in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    if suffix in ALLOWED_AUDIO_EXTENSIONS:
        return "audio"
    return "file"


def sanitize_attachment_filename(filename: str) -> str:
    name = Path(str(filename or "")).name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = name.strip("._-")
    if not name:
        name = "attachment"
    if "." not in name:
        name = f"{name}.bin"
    stem = Path(name).stem[:80] or "attachment"
    suffix = Path(name).suffix.lower()[:16]
    return f"{stem}{suffix}"


def is_text_attachment(attachment: dict[str, Any]) -> bool:
    suffix = Path(str(attachment.get("name") or attachment.get("uri") or "")).suffix.lower()
    mime_type = str(attachment.get("mime_type") or "").lower()
    return suffix in ALLOWED_TEXT_EXTENSIONS or mime_type.startswith("text/") or mime_type in {"application/json", "application/xml", "application/yaml", "application/x-yaml", "application/toml", "application/sql"}


def language_for_filename(name: str | None) -> str:
    suffix = Path(name or "").suffix.lower()
    return {
        ".md": "markdown",
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
        ".env": "dotenv",
        ".log": "log",
        ".csv": "csv",
        ".sql": "sql",
        ".sh": "shell",
        ".ps1": "powershell",
        ".bat": "batch",
        ".ini": "ini",
        ".cfg": "ini",
    }.get(suffix, "text")


def delete_attachment_if_unreferenced(attachment: dict[str, Any], message_store: Any, session_id: str | None = None) -> bool:
    if not isinstance(attachment, dict) or not isinstance(attachment.get("uri"), str):
        return False
    try:
        path = resolve_attachment_uri(attachment["uri"])
    except ValueError:
        return False
    if _attachment_is_referenced(attachment.get("id"), attachment.get("uri"), message_store, session_id):
        return False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def attachment_filename_from_id(attachment_id: str) -> str:
    value = str(attachment_id or "").strip()
    if not _ATTACHMENT_NAME_RE.match(value):
        raise ValueError("Invalid attachment id.")
    return value


def attachment_mime_type(attachment_id: str) -> str:
    return _mime_type_for_attachment_path(resolve_attachment_uri(attachment_id))


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError("Attachment data_url must be a base64 data URL.")
    mime_type = match.group("mime").lower()
    try:
        data = base64.b64decode(re.sub(r"\s+", "", match.group("data")).encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Attachment data_url contains invalid base64.") from exc
    if not data:
        raise ValueError("Attachment is empty.")
    return data, mime_type


def _decode_base64_payload(data_base64: str) -> tuple[bytes, str | None]:
    value = str(data_base64 or "").strip()
    if value.startswith("data:"):
        return _decode_data_url(value)
    try:
        data = base64.b64decode(re.sub(r"\s+", "", value).encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Generated attachment base64 is invalid.") from exc
    if not data:
        raise ValueError("Generated attachment is empty.")
    return data, None


def _normalize_attachment_kind(kind: str) -> Literal["image", "file", "audio", "video"]:
    if kind not in {"image", "file", "audio", "video"}:
        raise ValueError("Generated attachment kind must be 'image', 'file', 'audio', or 'video'.")
    return kind  # type: ignore[return-value]


def _attachment_subdir(attachment_type: str) -> str:
    if attachment_type == "image":
        return "images"
    if attachment_type == "audio":
        return "audios"
    if attachment_type == "video":
        return "videos"
    return "files"


def _attachment_subdirs_for_suffix(suffix: str) -> list[str]:
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return ["images"]
    if suffix in ALLOWED_VIDEO_EXTENSIONS:
        subdirs = ["videos"]
        if suffix in ALLOWED_AUDIO_EXTENSIONS:
            subdirs.append("audios")
        return subdirs
    if suffix in ALLOWED_AUDIO_EXTENSIONS:
        return ["audios"]
    return ["files"]


def _mime_type_for_attachment_path(path: Path) -> str:
    if path.parent.name == "videos":
        video_mime = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".ogv": "video/ogg",
        }.get(path.suffix.lower())
        if video_mime:
            return video_mime
    if path.parent.name == "audios" and path.suffix.lower() == ".webm":
        return "audio/webm"
    mime_type = _EXTENSION_MIME_TYPES.get(path.suffix.lower(), "")
    if not mime_type:
        raise ValueError("Unsupported attachment MIME type.")
    return mime_type


def _mime_type_for_extension(extension: str) -> str:
    return _EXTENSION_MIME_TYPES.get(extension.lower(), "application/octet-stream")


def _extension_for_attachment(name: str | None, mime_type: str) -> str:
    suffix = Path(name or "").suffix.lower()
    if suffix in _EXTENSION_MIME_TYPES:
        return suffix
    if mime_type in _MIME_EXTENSIONS:
        return _MIME_EXTENSIONS[mime_type]
    raise ValueError("Unsupported attachment file type.")


def _validate_attachment_metadata(attachment: dict[str, Any], settings: Any = None) -> None:
    attachment_type = infer_attachment_type(str(attachment.get("name") or ""), str(attachment.get("mime_type") or ""))
    if attachment.get("type") != attachment_type:
        raise ValueError("Attachment type does not match MIME type or extension.")
    _extension_for_attachment(str(attachment.get("name") or attachment.get("uri") or ""), str(attachment.get("mime_type") or ""))
    size = int(attachment.get("size") or 0)
    _validate_attachment_size(size, attachment_type, settings=settings)


def _validate_attachment_payload(name: str | None, mime_type: str, data: bytes, attachment_type: str, settings: Any = None) -> None:
    if attachment_type == "image":
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported image MIME type.")
        _validate_attachment_size(len(data), attachment_type, settings=settings)
        return
    if attachment_type == "audio":
        if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
            raise ValueError("Unsupported audio MIME type.")
        if Path(name or "").suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError("Unsupported audio file type.")
        _validate_attachment_size(len(data), attachment_type, settings=settings)
        return
    if attachment_type == "video":
        if mime_type not in ALLOWED_VIDEO_MIME_TYPES:
            raise ValueError("Unsupported video MIME type.")
        if Path(name or "").suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError("Unsupported video file type.")
        _validate_attachment_size(len(data), attachment_type, settings=settings)
        return
    suffix = Path(name or "").suffix.lower()
    if suffix not in ALLOWED_TEXT_EXTENSIONS:
        raise ValueError("Unsupported file type.")
    _validate_attachment_size(len(data), attachment_type, settings=settings)


def _validate_generated_attachment_payload(
    name: str,
    mime_type: str,
    data: bytes,
    attachment_type: str,
    settings: Any = None,
    max_size_bytes: int | None = None,
    max_size_label: str | None = None,
) -> None:
    if attachment_type == "image" and mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("Unsupported image MIME type.")
    if attachment_type == "file" and infer_attachment_type(name, mime_type) == "image":
        raise ValueError("Generated image attachments must use kind='image'.")
    if attachment_type == "audio":
        if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
            raise ValueError("Unsupported audio MIME type.")
        if Path(name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError("Unsupported audio file type.")
    if attachment_type == "video":
        if mime_type not in ALLOWED_VIDEO_MIME_TYPES:
            raise ValueError("Unsupported video MIME type.")
        if Path(name).suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError("Unsupported video file type.")
    if attachment_type == "file" and infer_attachment_type(name, mime_type) == "audio":
        raise ValueError("Generated audio attachments must use kind='audio'.")
    if attachment_type == "file" and infer_attachment_type(name, mime_type) == "video":
        raise ValueError("Generated video attachments must use kind='video'.")
    _extension_for_attachment(name, mime_type)
    if max_size_bytes is not None and len(data) > max_size_bytes:
        label = max_size_label or f"{max_size_bytes} bytes"
        raise ValueError(f"Generated attachment is too large. Maximum size is {label}.")
    if max_size_bytes is not None:
        return
    _validate_attachment_size(len(data), attachment_type, settings=settings)


def _validate_generated_attachment_file(
    name: str,
    mime_type: str,
    size: int,
    attachment_type: str,
    settings: Any = None,
    max_size_bytes: int | None = None,
    max_size_label: str | None = None,
) -> None:
    if size <= 0:
        raise ValueError("Generated attachment is empty.")
    if attachment_type == "image" and mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("Unsupported image MIME type.")
    if attachment_type == "audio":
        if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
            raise ValueError("Unsupported audio MIME type.")
        if Path(name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError("Unsupported audio file type.")
    if attachment_type == "video":
        if mime_type not in ALLOWED_VIDEO_MIME_TYPES:
            raise ValueError("Unsupported video MIME type.")
        if Path(name).suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError("Unsupported video file type.")
    if attachment_type == "file" and infer_attachment_type(name, mime_type) == "audio":
        raise ValueError("Generated audio attachments must use kind='audio'.")
    if attachment_type == "file" and infer_attachment_type(name, mime_type) == "video":
        raise ValueError("Generated video attachments must use kind='video'.")
    _extension_for_attachment(name, mime_type)
    if max_size_bytes is not None and size > max_size_bytes:
        label = max_size_label or f"{max_size_bytes} bytes"
        raise ValueError(f"Generated attachment is too large. Maximum size is {label}.")
    if max_size_bytes is not None:
        return
    _validate_attachment_size(size, attachment_type, settings=settings)


def _validate_attachment_size(size: int, attachment_type: str, settings: Any = None) -> None:
    if attachment_type == "image":
        max_mb = getattr(settings, "max_image_size_mb", MAX_IMAGE_ATTACHMENT_BYTES // (1024 * 1024))
        max_bytes = getattr(settings, "max_image_size_bytes", max_mb * 1024 * 1024)
        if size > max_bytes:
            raise ValueError(f"Attachment image is too large. Maximum size is {max_mb} MB.")
        return
    max_mb = getattr(settings, "max_file_size_mb", MAX_FILE_ATTACHMENT_BYTES // (1024 * 1024))
    max_bytes = getattr(settings, "max_file_size_bytes", max_mb * 1024 * 1024)
    if size > max_bytes:
        raise ValueError(f"Attachment file is too large. Maximum size is {max_mb} MB.")


def _attachment_is_referenced(attachment_id: Any, uri: Any, message_store: Any, session_id: str | None) -> bool:
    try:
        if hasattr(message_store, "list_all_messages"):
            messages = message_store.list_all_messages()
        elif session_id and hasattr(message_store, "list_messages"):
            messages = message_store.list_messages(session_id)
        else:
            return False
    except Exception:
        return True
    for message in messages:
        attachments = (message.metadata or {}).get("attachments")
        if not isinstance(attachments, list):
            continue
        for item in attachments:
            if not isinstance(item, dict):
                continue
            if attachment_id and item.get("id") == attachment_id:
                return True
            if uri and item.get("uri") == uri:
                return True
    return False
