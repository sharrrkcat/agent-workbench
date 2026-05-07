import base64
import binascii
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}
MAX_IMAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_FILE_ATTACHMENT_BYTES = 5 * 1024 * 1024
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
}
_EXTENSION_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
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
}


class ImageAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: str = "image"
    mime_type: str
    name: str = ""
    size: int = Field(ge=0, le=MAX_IMAGE_ATTACHMENT_BYTES)
    data_url: str | None = Field(default=None, min_length=1)
    uri: str | None = Field(default=None, min_length=1)
    created_at: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)

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
    type: Literal["image", "file"]
    mime_type: str
    name: str = ""
    size: int = Field(ge=0, le=MAX_IMAGE_ATTACHMENT_BYTES)
    data_url: str | None = Field(default=None, min_length=1)
    uri: str | None = Field(default=None, min_length=1)
    created_at: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)

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


def validate_attachments(value: Any, max_attachments: int = MAX_ATTACHMENTS_PER_MESSAGE, images_only: bool = False) -> list[dict[str, Any]]:
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
            attachments.append(save_attachment_from_data_url(attachment.model_dump(exclude_none=True)))
        else:
            data = attachment.model_dump(exclude_none=True)
            _validate_attachment_metadata(data)
            attachments.append(data)
    return attachments


def _data_url_mime_type(data_url: str) -> str:
    match = _DATA_URL_RE.match(data_url.strip())
    return match.group("mime").lower() if match else ""


def attachments_root() -> Path:
    configured = os.getenv("AGENT_WORKBENCH_ATTACHMENTS_DIR")
    root = Path(configured) if configured else Path("./data/attachments")
    return root.resolve()


def save_attachment_from_data_url(attachment: dict[str, Any]) -> dict[str, Any]:
    parsed = Attachment.model_validate(attachment)
    if not parsed.data_url:
        raise ValueError("Attachment data_url is required.")
    attachment_bytes, mime_type = _decode_data_url(parsed.data_url)
    if mime_type != parsed.mime_type:
        raise ValueError("Attachment MIME type does not match data_url MIME type.")
    inferred_type = infer_attachment_type(parsed.name, mime_type)
    if parsed.type != inferred_type:
        raise ValueError("Attachment type does not match MIME type or extension.")
    _validate_attachment_payload(parsed.name, mime_type, attachment_bytes, inferred_type)

    attachment_id = str(uuid4())
    extension = _extension_for_attachment(parsed.name, mime_type)
    filename = f"{attachment_id}{extension}"
    target_dir = attachments_root() / ("images" if inferred_type == "image" else "files")
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
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    return data


def save_attachment_from_file(path: str | Path, name: str | None = None, mime_type: str | None = None) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError("Attachment file not found.")
    display_name = name or source.name
    guessed_mime = (mime_type or mimetypes.guess_type(display_name)[0] or _mime_type_for_extension(Path(display_name).suffix)).lower()
    data = source.read_bytes()
    attachment_type = infer_attachment_type(display_name, guessed_mime)
    _validate_attachment_payload(display_name, guessed_mime, data, attachment_type)
    return _store_attachment_bytes(display_name, guessed_mime, data, attachment_type)


def save_attachment_from_upload(name: str, mime_type: str, data: bytes) -> dict[str, Any]:
    attachment_type = infer_attachment_type(name, mime_type)
    _validate_attachment_payload(name, mime_type, data, attachment_type)
    return _store_attachment_bytes(name, mime_type.strip().lower(), data, attachment_type)


def _store_attachment_bytes(name: str, mime_type: str, data: bytes, attachment_type: str) -> dict[str, Any]:
    attachment_id = str(uuid4())
    extension = _extension_for_attachment(name, mime_type)
    filename = f"{attachment_id}{extension}"
    target_dir = attachments_root() / ("images" if attachment_type == "image" else "files")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / filename).resolve()
    target.write_bytes(data)
    return {
        "id": attachment_id,
        "type": attachment_type,
        "mime_type": mime_type,
        "name": name or filename,
        "size": len(data),
        "uri": f"local://attachments/{filename}",
        "created_at": datetime.utcnow().isoformat(),
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
    subdir = "images" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"} else "files"
    root = (attachments_root() / subdir).resolve()
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


def infer_attachment_type(name: str | None, mime_type: str | None) -> Literal["image", "file"]:
    cleaned_mime = (mime_type or "").strip().lower()
    suffix = Path(name or "").suffix.lower()
    if cleaned_mime in ALLOWED_IMAGE_MIME_TYPES or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return "image"
    return "file"


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
    return _mime_type_for_attachment_path(Path(attachment_filename_from_id(attachment_id)))


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


def _mime_type_for_attachment_path(path: Path) -> str:
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


def _validate_attachment_metadata(attachment: dict[str, Any]) -> None:
    attachment_type = infer_attachment_type(str(attachment.get("name") or ""), str(attachment.get("mime_type") or ""))
    if attachment.get("type") != attachment_type:
        raise ValueError("Attachment type does not match MIME type or extension.")
    _extension_for_attachment(str(attachment.get("name") or attachment.get("uri") or ""), str(attachment.get("mime_type") or ""))


def _validate_attachment_payload(name: str | None, mime_type: str, data: bytes, attachment_type: str) -> None:
    if attachment_type == "image":
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported image MIME type.")
        if len(data) > MAX_IMAGE_ATTACHMENT_BYTES:
            raise ValueError("Attachment image is too large. Maximum size is 10 MB.")
        return
    suffix = Path(name or "").suffix.lower()
    if suffix not in ALLOWED_TEXT_EXTENSIONS:
        raise ValueError("Unsupported file type.")
    if len(data) > MAX_FILE_ATTACHMENT_BYTES:
        raise ValueError("Attachment file is too large. Maximum size is 5 MB.")


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
