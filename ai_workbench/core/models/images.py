"""Image references for chat context and bounded local model input preparation."""
from __future__ import annotations

import asyncio
import base64
import binascii
from io import BytesIO
import json
import warnings
from typing import Annotated, Any, Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ConfigDict, Field
from typing_extensions import TypedDict

from ai_workbench.core.attachments import attachment_mime_type, resolve_attachment_uri
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import ChatRequest, ImagePart


MAX_LOCAL_CHAT_BYTES = 32 * 1024 * 1024
MAX_TAGGING_BYTES = 32 * 1024 * 1024
MAX_TAGGING_PIXELS = 64_000_000
IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


class ContextText(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    type: Literal["text"]
    text: str


class AttachmentImageRef(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    type: Literal["attachment_image"]
    attachment_id: Annotated[str, Field(min_length=1)]


ContextPart = Annotated[ContextText | AttachmentImageRef, Field(discriminator="type")]


class ContextMessage(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    role: Literal["system", "user", "assistant"]
    content: str | list[ContextPart]


def has_context_images(messages: list[ContextMessage]) -> bool:
    return any(isinstance(message["content"], list)
               and any(part["type"] == "attachment_image" for part in message["content"])
               for message in messages)


async def resolve_context_images(messages: list[ContextMessage], *, vision: bool, max_image_bytes: int) -> list[dict[str, Any]]:
    if not has_context_images(messages):
        return messages
    if not vision:
        raise ModelError("UNSUPPORTED_CAPABILITY", "The selected model does not support images in this context.", 422)
    return await asyncio.to_thread(_resolve_context_images, messages, max_image_bytes)


def _resolve_context_images(messages, max_image_bytes):
    resolved = []
    for message in messages:
        if isinstance(message["content"], str):
            resolved.append(message)
            continue
        parts = []
        for part in message["content"]:
            if part["type"] == "text":
                parts.append(part)
                continue
            try:
                path = resolve_attachment_uri(part["attachment_id"])
                mime = attachment_mime_type(part["attachment_id"])
                if mime not in IMAGE_FORMATS:
                    raise ModelError("INVALID_IMAGE", "Chat images must be static PNG, JPEG or WebP files.", 422)
                with path.open("rb") as image:
                    data = image.read(max_image_bytes + 1)
            except FileNotFoundError as exc:
                raise ModelError("ATTACHMENT_NOT_FOUND", "An image selected for this context is missing.", 404) from exc
            except (OSError, ValueError) as exc:
                raise ModelError("INVALID_IMAGE", "The image attachment cannot be read.", 422) from exc
            if len(data) > max_image_bytes:
                raise ModelError("REQUEST_TOO_LARGE", "An image exceeds the configured attachment size limit.", 413)
            parts.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}})
        resolved.append({**message, "content": parts})
    return resolved


def request_images(request: ChatRequest):
    for message in request.messages:
        if isinstance(message.content, list):
            yield from (part for part in message.content if isinstance(part, ImagePart))


def validate_local_image_options(request: ChatRequest) -> None:
    for part in request_images(request):
        if not part.image_url.url.startswith("data:image/"):
            raise ModelError("UNSUPPORTED_CAPABILITY", "Local image input requires an inline image data URL.", 422)
        if part.image_url.detail != "auto":
            raise ModelError("UNSUPPORTED_CAPABILITY", "Local image input supports only detail=auto.", 422)


def _check_request_size(profile, request):
    # Measure the same merged JSON body sent by OpenAIAdapter to either local server.
    payload = OpenAIAdapter._payload(profile.model_copy(update={"model_ref": "managed"}), request)
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    if size > MAX_LOCAL_CHAT_BYTES:
        raise ModelError("REQUEST_TOO_LARGE", "Local chat requests are limited to 32 MiB. Reduce images or history.", 413)


def prepare_local_images(profile, request: ChatRequest) -> ChatRequest:
    _check_request_size(profile, request)
    prepared = request.model_copy(deep=True)
    for part in request_images(prepared):
        part.image_url.url = _normalized_image(part.image_url.url)
        # Check each expansion before decoding another compressed input.
        _check_request_size(profile, prepared)
    return prepared


def prepare_tagging_images(profile_id: str, images: list[str], thresholds: dict[str, float]) -> list[str]:
    prepared = list(images)

    def check_size():
        body = {"profile_id": profile_id, "images": prepared, "thresholds": thresholds}
        size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        if size > MAX_TAGGING_BYTES:
            raise ModelError("REQUEST_TOO_LARGE", "Image tagging requests are limited to 32 MiB.", 413)

    check_size()
    for index, url in enumerate(prepared):
        prepared[index] = _normalized_image(url, max_pixels=MAX_TAGGING_PIXELS, square_pixels=True)
        check_size()
    return prepared


def prepare_embedding_images(images: list[str]) -> list[str]:
    prepared = list(images)
    for index in range(len(prepared) + 1):
        if len(json.dumps({"inputs": prepared}, ensure_ascii=False).encode("utf-8")) > MAX_TAGGING_BYTES:
            raise ModelError("REQUEST_TOO_LARGE", "Image embedding requests are limited to 32 MiB.", 413)
        if index < len(prepared):
            prepared[index] = _normalized_image(prepared[index], max_pixels=MAX_TAGGING_PIXELS)
    return prepared


def _normalized_image(url: str, *, max_pixels: int | None = None, square_pixels: bool = False) -> str:
    header, separator, encoded = url.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if not separator or header != f"data:{mime};base64" or mime not in IMAGE_FORMATS:
        raise ModelError("INVALID_IMAGE", "Use a base64 PNG, JPEG or WebP image.", 422)
    try:
        data = base64.b64decode(encoded, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format != IMAGE_FORMATS[mime] or getattr(source, "n_frames", 1) != 1:
                    raise ModelError("INVALID_IMAGE", "Use a static image whose MIME type matches its contents.", 422)
                area = max(source.size) ** 2 if square_pixels else source.width * source.height
                if max_pixels is not None and area > max_pixels:
                    message = "A tagging image exceeds 64 million pixels after square padding." if square_pixels else "An image exceeds 64 million pixels."
                    raise ModelError("REQUEST_TOO_LARGE", message, 413)
                oriented = ImageOps.exif_transpose(source)
                rgba = oriented.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                rgb.save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (binascii.Error, ValueError, OSError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ModelError("INVALID_IMAGE", "The image is corrupt or cannot be decoded safely.", 422) from exc
