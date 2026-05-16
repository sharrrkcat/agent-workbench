from __future__ import annotations

from itertools import count
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from ai_workbench.core.forms import validate_action_form_block


TextFormat = Literal["plain", "markdown"]
MessagePartType = Literal[
    "text",
    "json",
    "file",
    "image",
    "media_group",
    "form",
    "command_buttons",
    "notice",
    "error",
]


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


def legacy_output_to_parts(output_type: str | None, content: Any) -> list[dict[str, Any]]:
    kind = output_type or "text"
    if kind == "text":
        return validate_message_parts([{"type": "text", "format": "plain", "text": "" if content is None else str(content)}])
    if kind == "markdown":
        return validate_message_parts([{"type": "text", "format": "markdown", "text": "" if content is None else str(content)}])
    if kind == "json":
        return validate_message_parts([{"type": "json", "data": content}])
    if kind == "file_content":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("file_content output must be an object")
        return validate_message_parts([{"type": "file", "mode": "inline_text", **dict(content)}])
    if kind == "image":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("image output must be an object")
        return validate_message_parts([{"type": "image", **dict(content)}])
    if kind == "image_gallery":
        if not isinstance(content, Mapping):
            raise MessagePartValidationError("image_gallery output must be an object")
        images = content.get("images")
        if not isinstance(images, list):
            raise MessagePartValidationError("image_gallery images must be a list")
        return validate_message_parts([{"type": "media_group", "layout": "gallery", "items": [{"type": "image", **dict(image)} for image in images]}])
    if kind == "rich_content":
        if not isinstance(content, Mapping) or not isinstance(content.get("blocks"), list):
            raise MessagePartValidationError("rich_content output must contain blocks")
        return blocks_to_parts(content["blocks"])
    if kind == "error":
        if isinstance(content, Mapping):
            return validate_message_parts([{"type": "error", "code": content.get("code"), "message": str(content.get("message") or content.get("code") or "Error")}])
        return validate_message_parts([{"type": "error", "message": "" if content is None else str(content)}])
    raise MessagePartValidationError(f"unsupported legacy output type: {kind}")


def blocks_to_parts(blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw_parts: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise MessagePartValidationError("rich content block must be an object")
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
            raise MessagePartValidationError(f"unsupported rich content block type: {block_type}")
    return validate_message_parts(raw_parts)


def parts_to_legacy_output(parts: Sequence[Mapping[str, Any]]) -> tuple[str, Any] | None:
    validated = validate_message_parts(parts)
    if not validated:
        return "text", ""
    if len(validated) == 1:
        part = validated[0]
        part_type = part["type"]
        if part_type == "text":
            return ("markdown" if part.get("format") == "markdown" else "text", part.get("text", ""))
        if part_type == "json":
            return "json", part.get("data")
        if part_type == "file":
            return "file_content", {key: value for key, value in part.items() if key not in {"id", "type", "mode", "attachment_id"}}
        if part_type == "image":
            return "image", {key: value for key, value in part.items() if key not in {"id", "type", "attachment_id"}}
        if part_type == "media_group" and part.get("layout") == "gallery":
            return "image_gallery", {"images": [{key: value for key, value in item.items() if key not in {"type", "attachment_id"}} for item in part.get("items", [])]}
        if part_type == "form":
            return "rich_content", {"blocks": [_form_part_to_block(part)]}
        if part_type == "command_buttons":
            return "rich_content", {"blocks": [{"type": "command_buttons", "buttons": part.get("buttons", [])}]}
        if part_type == "notice":
            return "text", part.get("text", "")
        if part_type == "error":
            return "error", _drop_none({"code": part.get("code"), "message": part.get("message", "")})
    blocks: list[dict[str, Any]] = []
    for part in validated:
        block = _part_to_rich_content_block(part)
        if block is None:
            return "json", {"parts": validated}
        blocks.append(block)
    return "rich_content", {"blocks": blocks}


def _part_to_rich_content_block(part: Mapping[str, Any]) -> dict[str, Any] | None:
    part_type = part.get("type")
    if part_type == "text":
        return {"type": "markdown" if part.get("format") == "markdown" else "text", "text": part.get("text", "")}
    if part_type == "image":
        return {"type": "image", **{key: value for key, value in part.items() if key not in {"id", "type", "attachment_id"}}}
    if part_type == "file":
        return {"type": "file_content", **{key: value for key, value in part.items() if key not in {"id", "type", "mode", "attachment_id"}}}
    if part_type == "form":
        return _form_part_to_block(part)
    if part_type == "command_buttons":
        return {"type": "command_buttons", "buttons": part.get("buttons", [])}
    return None


def _form_part_to_block(part: Mapping[str, Any]) -> dict[str, Any]:
    return validate_action_form_block({"type": "action_form", **{key: value for key, value in part.items() if key not in {"id", "type"}}})


def _drop_none(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
