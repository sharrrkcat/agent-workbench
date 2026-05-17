from __future__ import annotations

from itertools import count
import re
from typing import Any, Literal, Mapping, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from ai_workbench.core.forms import validate_action_form_block


TextFormat = Literal["plain", "markdown"]
MessagePartType = Literal[
    "text",
    "json",
    "file",
    "image",
    "audio",
    "video",
    "media_group",
    "form",
    "command_buttons",
    "notice",
    "error",
]

_LOCAL_ATTACHMENT_URL_RE = re.compile(r"^/api/attachments/[A-Za-z0-9_-]+\.[A-Za-z0-9]+$")


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
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("image url is required")
        return cleaned


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

    @field_validator("url")
    @classmethod
    def clean_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("audio url is required")
        return cleaned

    @field_validator("mime_type")
    @classmethod
    def validate_audio_mime_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned.startswith("audio/"):
            raise ValueError("audio mime_type must be audio/*")
        return cleaned

    @model_validator(mode="after")
    def validate_source_contract(self) -> "AudioPart":
        if self.source == "attachment":
            if not self.attachment_id:
                raise ValueError("audio attachment source requires attachment_id")
            lowered = self.url.lower()
            if lowered.startswith(("http://", "https://", "file:", "data:", "javascript:", "blob:")):
                raise ValueError("audio attachment url must be a local attachment URL")
            if not _LOCAL_ATTACHMENT_URL_RE.match(self.url):
                raise ValueError("audio attachment url must use /api/attachments/<id>.<ext>")
            return self
        if self.attachment_id:
            raise ValueError("audio url source must not include attachment_id")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("audio url source must use http:// or https://")
        return self


class VideoPart(_PartBase):
    type: Literal["video"]
    source: Literal["attachment"] = "attachment"
    attachment_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str | None = None
    title: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    poster_url: str | None = None

    @field_validator("url", "poster_url")
    @classmethod
    def validate_local_attachment_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        lowered = cleaned.lower()
        if lowered.startswith(("http://", "https://", "file:", "data:", "javascript:")):
            raise ValueError("video url must be a local attachment URL")
        if not _LOCAL_ATTACHMENT_URL_RE.match(cleaned):
            raise ValueError("video url must use /api/attachments/<id>.<ext>")
        return cleaned

    @field_validator("mime_type")
    @classmethod
    def validate_video_mime_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned.startswith("video/"):
            raise ValueError("video mime_type must be video/*")
        return cleaned


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


class FormPart(_PartBase):
    type: Literal["form"]
    form_id: str
    title: str
    description: str | None = None
    fields: list[dict[str, Any]]
    sections: list[dict[str, Any]] | None = None
    ui: dict[str, Any] | None = None
    submit: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def validate_form(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            raise ValueError("form part must be an object")
        data = dict(value)
        form = validate_action_form_block({"type": "action_form", **{key: item for key, item in data.items() if key not in {"id", "type"}}})
        return {"id": data.get("id"), "type": "form", **{key: item for key, item in form.items() if key != "type"}}


class CommandButton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    message: str = Field(min_length=1)


class CommandButtonsPart(_PartBase):
    type: Literal["command_buttons"]
    buttons: list[CommandButton] = Field(min_length=1)


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
    "form": TypeAdapter(FormPart),
    "command_buttons": TypeAdapter(CommandButtonsPart),
    "notice": TypeAdapter(NoticePart),
    "error": TypeAdapter(ErrorPart),
}


def make_text_part(text: str, *, format: TextFormat = "markdown", part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "text", "format": format, "text": text})


def make_json_part(data: Any, *, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "json", "data": data})


def make_file_part(
    content: str | None = None,
    *,
    mode: Literal["inline_text", "attachment_ref"] = "inline_text",
    attachment_id: str | None = None,
    filename: str | None = None,
    language: str | None = None,
    mime_type: str | None = None,
    size: int | None = None,
    truncated: bool = False,
    path: str | None = None,
    part_id: str | None = None,
) -> dict[str, Any]:
    return validate_message_part(
        _drop_none(
            {
                "id": part_id or "part_1",
                "type": "file",
                "mode": mode,
                "content": content,
                "attachment_id": attachment_id,
                "filename": filename,
                "language": language,
                "mime_type": mime_type,
                "size": size,
                "truncated": truncated,
                "path": path,
            }
        )
    )


def make_image_part(
    url: str | None = None,
    *,
    attachment_id: str | None = None,
    alt: str | None = None,
    title: str | None = None,
    caption: str | None = None,
    part_id: str | None = None,
) -> dict[str, Any]:
    return validate_message_part(_drop_none({"id": part_id or "part_1", "type": "image", "url": url, "attachment_id": attachment_id, "alt": alt, "title": title, "caption": caption}))


def make_audio_part(
    *,
    attachment_id: str,
    url: str,
    mime_type: str,
    filename: str | None = None,
    title: str | None = None,
    duration_ms: int | None = None,
    part_id: str | None = None,
) -> dict[str, Any]:
    return validate_message_part(
        _drop_none(
            {
                "id": part_id or "part_1",
                "type": "audio",
                "source": "attachment",
                "attachment_id": attachment_id,
                "url": url,
                "mime_type": mime_type,
                "filename": filename,
                "title": title,
                "duration_ms": duration_ms,
            }
        )
    )


def make_video_part(
    *,
    attachment_id: str,
    url: str,
    mime_type: str,
    filename: str | None = None,
    title: str | None = None,
    size_bytes: int | None = None,
    duration_ms: int | None = None,
    width: int | None = None,
    height: int | None = None,
    poster_url: str | None = None,
    part_id: str | None = None,
) -> dict[str, Any]:
    return validate_message_part(
        _drop_none(
            {
                "id": part_id or "part_1",
                "type": "video",
                "source": "attachment",
                "attachment_id": attachment_id,
                "url": url,
                "mime_type": mime_type,
                "filename": filename,
                "title": title,
                "size_bytes": size_bytes,
                "duration_ms": duration_ms,
                "width": width,
                "height": height,
                "poster_url": poster_url,
            }
        )
    )


def make_media_group_part(items: Sequence[Mapping[str, Any]], *, layout: Literal["gallery"] = "gallery", part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "media_group", "layout": layout, "items": [dict(item) for item in items]})


def make_form_part(form: Mapping[str, Any], *, part_id: str | None = None) -> dict[str, Any]:
    data = dict(form)
    data.pop("type", None)
    return validate_message_part({"id": part_id or "part_1", "type": "form", **data})


def make_command_buttons_part(buttons: Sequence[Mapping[str, Any]], *, part_id: str | None = None) -> dict[str, Any]:
    return validate_message_part({"id": part_id or "part_1", "type": "command_buttons", "buttons": [dict(button) for button in buttons]})


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
    validated: list[dict[str, Any]] = []
    for raw_part in parts:
        data = dict(raw_part)
        if not data.get("id"):
            data["id"] = f"part_{next(counter)}"
        part_id = str(data["id"])
        if part_id in used:
            raise MessagePartValidationError(f"duplicate message part id: {part_id}")
        used.add(part_id)
        validated.append(validate_message_part(data))
    return validated


def capability_output_to_parts(output: Mapping[str, Any] | None, content: Any) -> list[dict[str, Any]]:
    declaration = output or {}
    kind = declaration.get("part_type") if isinstance(declaration, Mapping) else None
    kind = str(kind or _infer_part_type(content)).strip()
    if kind == "parts":
        if not isinstance(content, Sequence) or isinstance(content, (str, bytes, bytearray)):
            raise MessagePartValidationError("parts output must be a list")
        return validate_message_parts(content)
    if kind == "text":
        text_format = str(declaration.get("format") or "plain")
        if text_format not in {"plain", "markdown"}:
            raise MessagePartValidationError(f"unsupported text output format: {text_format}")
        return validate_message_parts([{"type": "text", "format": text_format, "text": "" if content is None else str(content)}])
    if kind == "json":
        return validate_message_parts([{"type": "json", "data": content}])
    if kind == "file":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("file output must be an object")
        mode = str(declaration.get("mode") or content.get("mode") or "inline_text")
        return validate_message_parts([{"type": "file", "mode": mode, **dict(content)}])
    if kind == "image":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("image output must be an object")
        return validate_message_parts([{"type": "image", **dict(content)}])
    if kind == "audio":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("audio output must be an object")
        return validate_message_parts([{"type": "audio", **dict(content)}])
    if kind == "video":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("video output must be an object")
        return validate_message_parts([{"type": "video", **dict(content)}])
    if kind == "media_group":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("media_group output must be an object")
        images = content.get("images")
        if images is None:
            images = content.get("items")
        if not isinstance(images, list):
            raise MessagePartValidationError("media_group images/items must be a list")
        layout = str(declaration.get("layout") or content.get("layout") or "gallery")
        return validate_message_parts([{"type": "media_group", "layout": layout, "items": [{"type": "image", **dict(image)} for image in images]}])
    if kind == "error":
        if isinstance(content, Mapping):
            return validate_message_parts([{"type": "error", "code": content.get("code"), "message": str(content.get("message") or content.get("code") or "Error")}])
        return validate_message_parts([{"type": "error", "message": "" if content is None else str(content)}])
    raise MessagePartValidationError(f"unsupported output part_type: {kind}")


def command_result_to_parts(output: Mapping[str, Any] | None, content: Any) -> list[dict[str, Any]]:
    return capability_output_to_parts(output, content)


def text_from_parts(parts: Sequence[Mapping[str, Any]] | None) -> str:
    if not parts:
        return ""
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        part_type = part.get("type")
        if part_type == "text":
            chunks.append(str(part.get("text") or ""))
        elif part_type == "error":
            chunks.append(str(part.get("message") or ""))
        elif part_type == "notice":
            chunks.append(str(part.get("text") or ""))
    return "\n\n".join(chunk for chunk in chunks if chunk)


def _infer_part_type(content: Any) -> str:
    if isinstance(content, list):
        return "parts"
    if isinstance(content, Mapping):
        if content.get("type") in _PART_ADAPTERS:
            return "parts"
        if "url" in content:
            return "image"
        if "images" in content or "items" in content:
            return "media_group"
        return "json"
    return "text"


def blocks_to_parts(blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw_parts: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise MessagePartValidationError("message block must be an object")
        block_type = block.get("type")
        if block_type == "text":
            raw_parts.append({"type": "text", "format": "plain", "text": block.get("text", "")})
        elif block_type == "markdown":
            raw_parts.append({"type": "text", "format": "markdown", "text": block.get("text", "")})
        elif block_type == "image":
            raw_parts.append({"type": "image", **{key: value for key, value in block.items() if key != "type"}})
        elif block_type == "file_content":
            raw_parts.append({"type": "file", "mode": "inline_text", **{key: value for key, value in block.items() if key != "type"}})
        elif block_type == "action_form":
            raw_parts.append({"type": "form", **{key: value for key, value in block.items() if key != "type"}})
        elif block_type == "command_buttons":
            raw_parts.append({"type": "command_buttons", "buttons": block.get("buttons")})
        else:
            raise MessagePartValidationError(f"unsupported message block type: {block_type}")
    return validate_message_parts(raw_parts)


def _drop_none(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
