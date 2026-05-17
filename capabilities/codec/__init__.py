import base64
import binascii
import re
from typing import Any

from ai_workbench.core.attachments import read_attachment_as_data_url, save_generated_attachment_bytes


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.+]+/[-\w.+]+);base64,(?P<data>.*)$", re.DOTALL)
_SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}
_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}
_DEFAULT_CONFIG = {
    "max_text_input_chars": 200000,
    "max_decoded_bytes_mb": 25,
    "max_attachment_encode_mb": 10,
    "enable_attachment_encode": True,
}


class CapabilityRuntime:
    def encode(
        self,
        args: str = "",
        context: dict[str, Any] | None = None,
        *,
        codec: str | None = None,
        text: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_codec, payload = _resolve_codec_payload(
            args=args,
            codec=codec,
            text=text,
            usage="Usage: /encode base64 <text>",
        )
        _require_base64(selected_codec)
        config = _resolved_config(context)

        if payload == "":
            return [_encode_current_image_attachment(context or {}, config)]

        _ensure_text_input_limit(payload, config)
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        return [_inline_file_part("base64.txt", encoded, size=len(encoded))]

    def decode(
        self,
        args: str = "",
        context: dict[str, Any] | None = None,
        *,
        codec: str | None = None,
        text: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_codec, payload = _resolve_codec_payload(
            args=args,
            codec=codec,
            text=text,
            usage="Usage: /decode base64 <base64-or-data-url>",
        )
        _require_base64(selected_codec)
        config = _resolved_config(context)
        if not payload:
            raise ValueError("Usage: /decode base64 <base64-or-data-url>")
        _ensure_text_input_limit(payload, config)

        decoded, declared_mime = _decode_base64_payload(payload, config)
        image_mime = declared_mime if declared_mime and declared_mime.startswith("image/") else _detect_image_mime_type(decoded)
        if image_mime:
            if image_mime not in _SUPPORTED_IMAGE_MIME_TYPES:
                raise ValueError(f"Unsupported image MIME type: {image_mime}")
            attachment = save_generated_attachment_bytes(
                decoded,
                filename=f"decoded{_IMAGE_EXTENSIONS[image_mime]}",
                mime_type=image_mime,
                kind="image",
                metadata={"source": "codec.decode", "codec": "base64"},
                max_size_bytes=_max_decoded_bytes(config),
                max_size_label=f"{config['max_decoded_bytes_mb']} MB",
            )
            return [
                {
                    "type": "image",
                    "attachment_id": attachment["id"],
                    "url": attachment["url"],
                    "alt": "Decoded Base64 image",
                    "title": attachment["name"],
                    "caption": f"Decoded {image_mime} image.",
                }
            ]

        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Unsupported binary decoded result. This round supports UTF-8 text and supported images only.") from exc

        return [_inline_file_part("decoded.txt", text, size=len(decoded))]


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()


def _resolve_codec_payload(*, args: str, codec: str | None, text: str | None, usage: str) -> tuple[str, str]:
    if codec is not None:
        return codec.strip().lower(), "" if text is None else str(text)

    value = str(args or "").strip()
    if not value:
        raise ValueError(usage)
    parts = value.split(maxsplit=1)
    selected_codec = parts[0].strip().lower()
    payload = parts[1] if len(parts) > 1 else ""
    if not selected_codec:
        raise ValueError(usage)
    return selected_codec, payload.strip()


def _require_base64(codec: str) -> None:
    if codec != "base64":
        raise ValueError(f"Unsupported codec: {codec}. Currently only base64 is supported.")


def _resolved_config(context: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(_DEFAULT_CONFIG)
    if isinstance(context, dict) and isinstance(context.get("capability_config"), dict):
        for key in config:
            if key in context["capability_config"]:
                config[key] = context["capability_config"][key]
    config["max_text_input_chars"] = int(config["max_text_input_chars"])
    config["max_decoded_bytes_mb"] = int(config["max_decoded_bytes_mb"])
    config["max_attachment_encode_mb"] = int(config["max_attachment_encode_mb"])
    config["enable_attachment_encode"] = bool(config["enable_attachment_encode"])
    return config


def _ensure_text_input_limit(payload: str, config: dict[str, Any]) -> None:
    max_chars = config["max_text_input_chars"]
    if len(payload) > max_chars:
        raise ValueError(f"Codec text payload is too large. Maximum length is {max_chars} characters.")


def _max_decoded_bytes(config: dict[str, Any]) -> int:
    return config["max_decoded_bytes_mb"] * 1024 * 1024


def _max_attachment_encode_bytes(config: dict[str, Any]) -> int:
    return config["max_attachment_encode_mb"] * 1024 * 1024


def _decode_base64_payload(payload: str, config: dict[str, Any]) -> tuple[bytes, str | None]:
    value = str(payload or "").strip()
    declared_mime = None
    if value.startswith("data:"):
        if ";base64," not in value:
            raise ValueError("Invalid data URL. Expected data:<mime>;base64,<payload>.")
        match = _DATA_URL_RE.match(value)
        if not match:
            raise ValueError("Invalid data URL. Expected data:<mime>;base64,<payload>.")
        declared_mime = match.group("mime").lower()
        value = match.group("data")

    compact = re.sub(r"\s+", "", value)
    if not compact:
        raise ValueError("Usage: /decode base64 <base64-or-data-url>")

    estimated_bytes = (len(compact) * 3) // 4 - compact.count("=")
    if estimated_bytes > _max_decoded_bytes(config):
        raise ValueError(f"Decoded payload is too large. Maximum size is {config['max_decoded_bytes_mb']} MB.")

    try:
        decoded = base64.b64decode(compact.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Invalid Base64 input.") from exc
    if not decoded:
        raise ValueError("Decoded payload is empty.")
    if len(decoded) > _max_decoded_bytes(config):
        raise ValueError(f"Decoded payload is too large. Maximum size is {config['max_decoded_bytes_mb']} MB.")
    return decoded, declared_mime


def _encode_current_image_attachment(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if not config["enable_attachment_encode"]:
        raise ValueError("Image attachment Base64 encoding is disabled for this Capability.")

    attachments = context.get("attachments") if isinstance(context, dict) else []
    images = [item for item in attachments or [] if isinstance(item, dict) and item.get("type") == "image"]
    if not images:
        raise ValueError("Usage: /encode base64 <text>")
    if len(images) > 1:
        raise ValueError("Multiple image attachments found. Attach exactly one image for /encode base64.")

    image = images[0]
    size = int(image.get("size") or 0)
    max_bytes = _max_attachment_encode_bytes(config)
    if size > max_bytes:
        raise ValueError(f"Image attachment is too large to encode. Maximum size is {config['max_attachment_encode_mb']} MB.")
    data_url = read_attachment_as_data_url(image).strip()
    encoded_payload = data_url.split(",", 1)[1] if "," in data_url else ""
    estimated_bytes = (len(encoded_payload) * 3) // 4 - encoded_payload.count("=")
    if estimated_bytes > max_bytes:
        raise ValueError(f"Image attachment is too large to encode. Maximum size is {config['max_attachment_encode_mb']} MB.")
    return _inline_file_part("image-data-url.txt", data_url, size=len(data_url))


def _inline_file_part(filename: str, content: str, *, size: int) -> dict[str, Any]:
    return {
        "type": "file",
        "mode": "inline_text",
        "filename": filename,
        "mime_type": "text/plain",
        "content": content,
        "size": size,
        "truncated": False,
    }


def _detect_image_mime_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"

    stripped = data.lstrip()
    lowered = stripped[:256].lower()
    if lowered.startswith(b"<svg") or (lowered.startswith(b"<?xml") and b"<svg" in lowered):
        return "image/svg+xml"
    return None
