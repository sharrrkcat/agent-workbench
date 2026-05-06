import base64
import binascii
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
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
MAX_IMAGE_ATTACHMENTS_PER_MESSAGE = 6

_DATA_URL_RE = re.compile(r"^data:(?P<mime>image/(?:png|jpeg|webp|gif|svg\+xml));base64,(?P<data>[a-zA-Z0-9+/=\s]+)$")
_LOCAL_ATTACHMENT_RE = re.compile(r"^local://attachments/(?P<name>[a-f0-9-]+\.(?:png|jpg|jpeg|webp|gif|svg))$")
_ATTACHMENT_NAME_RE = re.compile(r"^[a-f0-9-]+\.(?:png|jpg|jpeg|webp|gif|svg)$")
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


def validate_image_attachments(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("attachments must be a list.")
    if len(value) > MAX_IMAGE_ATTACHMENTS_PER_MESSAGE:
        raise ValueError(f"At most {MAX_IMAGE_ATTACHMENTS_PER_MESSAGE} image attachments are allowed.")

    attachments: list[dict[str, Any]] = []
    for item in value:
        attachment = ImageAttachment.model_validate(item)
        if bool(attachment.data_url) == bool(attachment.uri):
            raise ValueError("Attachment must include exactly one of data_url or uri.")
        if attachment.data_url:
            data_mime = _data_url_mime_type(attachment.data_url)
            if data_mime != attachment.mime_type:
                raise ValueError("Attachment MIME type does not match data_url MIME type.")
            attachments.append(save_attachment_from_data_url(attachment.model_dump(exclude_none=True)))
        else:
            attachments.append(attachment.model_dump(exclude_none=True))
    return attachments


def _data_url_mime_type(data_url: str) -> str:
    match = _DATA_URL_RE.match(data_url.strip())
    return match.group("mime").lower() if match else ""


def attachments_root() -> Path:
    configured = os.getenv("AGENT_WORKBENCH_ATTACHMENTS_DIR")
    root = Path(configured) if configured else Path("./data/attachments")
    return root.resolve()


def save_attachment_from_data_url(attachment: dict[str, Any]) -> dict[str, Any]:
    parsed = ImageAttachment.model_validate(attachment)
    if not parsed.data_url:
        raise ValueError("Attachment data_url is required.")
    image_bytes, mime_type = _decode_data_url(parsed.data_url)
    if mime_type != parsed.mime_type:
        raise ValueError("Attachment MIME type does not match data_url MIME type.")
    if len(image_bytes) > MAX_IMAGE_ATTACHMENT_BYTES:
        raise ValueError("Attachment image is too large. Maximum size is 10 MB.")

    attachment_id = str(uuid4())
    extension = _MIME_EXTENSIONS[mime_type]
    filename = f"{attachment_id}{extension}"
    target_dir = attachments_root() / "images"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / filename).resolve()
    target.write_bytes(image_bytes)

    data = parsed.model_dump(exclude_none=True, exclude={"data_url"})
    data.update(
        {
            "id": attachment_id,
            "size": len(image_bytes),
            "uri": f"local://attachments/{filename}",
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    return data


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

    root = (attachments_root() / "images").resolve()
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
        raise ValueError("Attachment data_url must be an allowed image base64 data URL.")
    mime_type = match.group("mime").lower()
    try:
        data = base64.b64decode(re.sub(r"\s+", "", match.group("data")).encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Attachment data_url contains invalid base64.") from exc
    if not data:
        raise ValueError("Attachment image is empty.")
    return data, mime_type


def _mime_type_for_attachment_path(path: Path) -> str:
    mime_type = _EXTENSION_MIME_TYPES.get(path.suffix.lower(), "")
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("Unsupported image MIME type.")
    return mime_type


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
