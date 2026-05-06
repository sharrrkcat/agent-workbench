import re
from typing import Any

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


class ImageAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: str = "image"
    mime_type: str
    name: str = ""
    size: int = Field(ge=0, le=MAX_IMAGE_ATTACHMENT_BYTES)
    data_url: str = Field(min_length=1)
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
    def validate_data_url(cls, value: str) -> str:
        cleaned = value.strip()
        match = _DATA_URL_RE.match(cleaned)
        if not match:
            raise ValueError("Attachment data_url must be an allowed image base64 data URL.")
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
        data_mime = _data_url_mime_type(attachment.data_url)
        if data_mime != attachment.mime_type:
            raise ValueError("Attachment MIME type does not match data_url MIME type.")
        attachments.append(attachment.model_dump(exclude_none=True))
    return attachments


def _data_url_mime_type(data_url: str) -> str:
    match = _DATA_URL_RE.match(data_url.strip())
    return match.group("mime").lower() if match else ""

