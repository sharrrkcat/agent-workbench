"""Validated, transport-neutral message parts.

Phase 1 keeps only presentation/data parts.  Forms and command buttons were
part of the removed extension protocol and are intentionally rejected.
"""

from __future__ import annotations

from itertools import count
from typing import Any, Literal, Mapping, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator, field_validator


TextFormat = Literal["plain", "markdown"]
MessagePartType = Literal["text", "json", "file", "image", "audio", "video", "media_group", "notice", "error"]


class MessagePartValidationError(ValueError):
    pass


class _PartBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    type: MessagePartType


class TextPart(_PartBase):
    type: Literal["text"]
    format: TextFormat = "markdown"
    text: str


class JsonPart(_PartBase):
    type: Literal["json"]
    data: dict[str, Any] | list[Any]


class FilePart(_PartBase):
    type: Literal["file"]
    mode: Literal["inline_text", "attachment_ref"] = "inline_text"
    content: str | None = None
    attachment_id: str | None = None
    filename: str | None = None
    language: str | None = None
    mime_type: str | None = None
    size: int | None = None
    truncated: bool = False
    path: str | None = None

    @model_validator(mode="after")
    def require_content_or_ref(self) -> "FilePart":
        if self.mode == "inline_text" and self.content is None:
            raise ValueError("file inline_text content is required")
        if self.mode == "attachment_ref" and not self.attachment_id:
            raise ValueError("file attachment_ref attachment_id is required")
        return self


class ImagePart(_PartBase):
    type: Literal["image"]
    url: str | None = None
    attachment_id: str | None = None
    alt: str | None = None
    title: str | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def require_url_or_ref(self) -> "ImagePart":
        if not self.url and not self.attachment_id:
            raise ValueError("image url or attachment_id is required")
        return self

    @field_validator("url")
    @classmethod
    def clean_url(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else value


class AudioPart(_PartBase):
    type: Literal["audio"]
    source: Literal["attachment", "url"] = "attachment"
    attachment_id: str | None = None
    url: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str | None = None
    title: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)

    @field_validator("mime_type")
    @classmethod
    def validate_audio_mime_type(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.startswith("audio/"):
            raise ValueError("audio mime_type must be audio/*")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> "AudioPart":
        if self.source == "url":
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("audio url source must use http:// or https://")
        elif not self.attachment_id:
            raise ValueError("audio attachment source requires attachment_id")
        return self


class VideoPart(_PartBase):
    type: Literal["video"]
    source: Literal["attachment", "url"] = "attachment"
    attachment_id: str | None = None
    url: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str | None = None
    title: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    poster_url: str | None = None

    @field_validator("mime_type")
    @classmethod
    def validate_video_mime_type(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.startswith("video/"):
            raise ValueError("video mime_type must be video/*")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> "VideoPart":
        if self.source == "url":
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("video url source must use http:// or https://")
        elif not self.attachment_id:
            raise ValueError("video attachment source requires attachment_id")
        return self


class MediaGroupImageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"] = "image"
    url: str | None = None
    attachment_id: str | None = None
    alt: str | None = None
    title: str | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def require_url_or_ref(self) -> "MediaGroupImageItem":
        if not self.url and not self.attachment_id:
            raise ValueError("media_group image url or attachment_id is required")
        return self


class MediaGroupPart(_PartBase):
    type: Literal["media_group"]
    layout: Literal["gallery"] = "gallery"
    items: list[MediaGroupImageItem] = Field(min_length=1)


class NoticePart(_PartBase):
    type: Literal["notice"]
    level: Literal["info", "warning", "success"] = "info"
    text: str


class ErrorPart(_PartBase):
    type: Literal["error"]
    message: str
    code: str | None = None


_PART_ADAPTERS = {
    "text": TypeAdapter(TextPart),
    "json": TypeAdapter(JsonPart),
    "file": TypeAdapter(FilePart),
    "image": TypeAdapter(ImagePart),
    "audio": TypeAdapter(AudioPart),
    "video": TypeAdapter(VideoPart),
    "media_group": TypeAdapter(MediaGroupPart),
    "notice": TypeAdapter(NoticePart),
    "error": TypeAdapter(ErrorPart),
}


def make_text_part(text: str, *, format: TextFormat = "markdown", part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "text", "format": format, "text": text})


def make_json_part(data: Any, *, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "json", "data": data})


def make_file_part(content: str | None = None, *, mode: Literal["inline_text", "attachment_ref"] = "inline_text", attachment_id: str | None = None, filename: str | None = None, language: str | None = None, mime_type: str | None = None, size: int | None = None, truncated: bool = False, path: str | None = None, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part(_drop_none({"id": part_id or "part_1", "type": "file", "mode": mode, "content": content, "attachment_id": attachment_id, "filename": filename, "language": language, "mime_type": mime_type, "size": size, "truncated": truncated, "path": path}))


def make_image_part(url: str | None = None, *, attachment_id: str | None = None, alt: str | None = None, title: str | None = None, caption: str | None = None, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part(_drop_none({"id": part_id or "part_1", "type": "image", "url": url, "attachment_id": attachment_id, "alt": alt, "title": title, "caption": caption}))


def make_audio_part(*, attachment_id: str, url: str, mime_type: str, filename: str | None = None, title: str | None = None, duration_ms: int | None = None, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part(_drop_none({"id": part_id or "part_1", "type": "audio", "source": "attachment", "attachment_id": attachment_id, "url": url, "mime_type": mime_type, "filename": filename, "title": title, "duration_ms": duration_ms}))


def make_video_part(*, attachment_id: str, url: str, mime_type: str, filename: str | None = None, title: str | None = None, size_bytes: int | None = None, duration_ms: int | None = None, width: int | None = None, height: int | None = None, poster_url: str | None = None, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part(_drop_none({"id": part_id or "part_1", "type": "video", "source": "attachment", "attachment_id": attachment_id, "url": url, "mime_type": mime_type, "filename": filename, "title": title, "size_bytes": size_bytes, "duration_ms": duration_ms, "width": width, "height": height, "poster_url": poster_url}))


def make_media_group_part(items: Sequence[Mapping[str, Any]], *, layout: Literal["gallery"] = "gallery", part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "media_group", "layout": layout, "items": [dict(item) for item in items]})


def make_notice_part(text: str, *, level: Literal["info", "warning", "success"] = "info", part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "notice", "level": level, "text": text})


def make_error_part(message: str, *, code: str | None = None, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part(_drop_none({"id": part_id or "part_1", "type": "error", "message": message, "code": code}))


def validate_message_part(part: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(part, Mapping):
        raise MessagePartValidationError("message part must be an object")
    part_type = part.get("type")
    adapter = _PART_ADAPTERS.get(part_type)
    if adapter is None:
        raise MessagePartValidationError(f"unsupported message part type: {part_type}")
    try:
        return adapter.validate_python(dict(part)).model_dump(exclude_none=True)
    except Exception as exc:
        raise MessagePartValidationError(str(exc) or "invalid message part") from exc


def validate_message_parts(parts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes, bytearray)):
        raise MessagePartValidationError("message parts must be a list")
    counter = count(1)
    used: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in parts:
        data = dict(raw)
        data.setdefault("id", f"part_{next(counter)}")
        if str(data["id"]) in used:
            raise MessagePartValidationError(f"duplicate message part id: {data['id']}")
        used.add(str(data["id"]))
        result.append(validate_message_part(data))
    return result


def text_from_parts(parts: Sequence[Mapping[str, Any]] | None) -> str:
    if not parts:
        return ""
    values: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        if part.get("type") == "text":
            values.append(str(part.get("text") or ""))
        elif part.get("type") == "notice":
            values.append(str(part.get("text") or ""))
        elif part.get("type") == "error":
            values.append(str(part.get("message") or ""))
    return "\n\n".join(item for item in values if item)


def _drop_none(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
