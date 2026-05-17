import base64
import binascii
from io import BytesIO
import re
from typing import Any
from urllib.parse import quote, unquote

import segno

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
    "max_qr_text_chars": 2000,
    "qr_scale": 8,
}
_SUPPORTED_CODECS = ("base64", "base64url", "url", "unicode", "hex", "qr")
_SUPPORTED_CODECS_DISPLAY = ", ".join(_SUPPORTED_CODECS)
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]*={0,2}$")
_INVALID_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_HEX_WHITESPACE_RE = re.compile(r"\s+")


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
        )
        _require_supported_codec(selected_codec)
        config = _resolved_config(context)

        if payload == "":
            if selected_codec == "qr":
                raise ValueError("Usage: /encode qr <text>")
            if selected_codec != "base64":
                raise ValueError(f"Usage: /encode {selected_codec} <text>")
            return [_encode_current_image_attachment(context or {}, config)]

        if selected_codec == "qr":
            return [_encode_qr(payload, config)]

        _ensure_text_input_limit(payload, config)
        if selected_codec == "base64":
            encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
            return [_inline_file_part("base64.txt", encoded, size=len(encoded))]
        if selected_codec == "base64url":
            encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
            return [_inline_file_part("base64url.txt", encoded, size=len(encoded))]
        if selected_codec == "url":
            encoded = quote(payload, safe="-_.~", encoding="utf-8", errors="strict")
            return [_inline_file_part("url-encoded.txt", encoded, size=len(encoded))]
        if selected_codec == "unicode":
            encoded = _encode_unicode_escapes(payload)
            return [_inline_file_part("unicode-escaped.txt", encoded, size=len(encoded))]
        if selected_codec == "hex":
            encoded = payload.encode("utf-8").hex()
            return [_inline_file_part("hex.txt", encoded, size=len(encoded))]

        raise ValueError(_unsupported_codec_message(selected_codec))

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
        )
        _require_supported_codec(selected_codec)
        config = _resolved_config(context)
        if selected_codec == "qr":
            raise ValueError("QR decode is not implemented in this round. Supported decode codecs: base64, base64url, url, unicode, hex.")
        if not payload:
            raise ValueError(f"Usage: /decode {selected_codec} <payload>")
        _ensure_text_input_limit(payload, config)

        if selected_codec == "base64url":
            decoded = _decode_base64url_payload(payload, config)
            return [_inline_file_part("decoded.txt", _decode_utf8_text(decoded), size=len(decoded))]
        if selected_codec == "url":
            decoded = _decode_url_payload(payload)
            return [_inline_file_part("url-decoded.txt", decoded, size=len(decoded.encode("utf-8")))]
        if selected_codec == "unicode":
            decoded = _decode_unicode_escapes(payload)
            return [_inline_file_part("unicode-decoded.txt", decoded, size=len(decoded.encode("utf-8")))]
        if selected_codec == "hex":
            decoded = _decode_hex_payload(payload, config)
            return [_inline_file_part("decoded.txt", _decode_utf8_text(decoded), size=len(decoded))]

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

        text = _decode_utf8_text(decoded, message="Unsupported binary decoded result. This round supports UTF-8 text and supported images only.")

        return [_inline_file_part("decoded.txt", text, size=len(decoded))]


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()


def _resolve_codec_payload(*, args: str, codec: str | None, text: str | None) -> tuple[str, str]:
    if codec is not None:
        return codec.strip().lower(), "" if text is None else str(text)

    value = str(args or "").strip()
    if not value:
        raise ValueError(f"Usage: /encode <codec> <payload> or /decode <codec> <payload>. Supported codecs: {_SUPPORTED_CODECS_DISPLAY}.")
    parts = value.split(maxsplit=1)
    selected_codec = parts[0].strip().lower()
    payload = parts[1] if len(parts) > 1 else ""
    if not selected_codec:
        raise ValueError(f"Usage: /encode <codec> <payload> or /decode <codec> <payload>. Supported codecs: {_SUPPORTED_CODECS_DISPLAY}.")
    return selected_codec, payload


def _require_supported_codec(codec: str) -> None:
    if codec not in _SUPPORTED_CODECS:
        raise ValueError(_unsupported_codec_message(codec))


def _unsupported_codec_message(codec: str) -> str:
    return f"Unsupported codec: {codec}. Supported codecs: {_SUPPORTED_CODECS_DISPLAY}."


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
    config["max_qr_text_chars"] = int(config["max_qr_text_chars"])
    config["qr_scale"] = int(config["qr_scale"])
    return config


def _ensure_text_input_limit(payload: str, config: dict[str, Any]) -> None:
    max_chars = config["max_text_input_chars"]
    if len(payload) > max_chars:
        raise ValueError(f"Codec text payload is too large. Maximum length is {max_chars} characters.")


def _max_decoded_bytes(config: dict[str, Any]) -> int:
    return config["max_decoded_bytes_mb"] * 1024 * 1024


def _max_attachment_encode_bytes(config: dict[str, Any]) -> int:
    return config["max_attachment_encode_mb"] * 1024 * 1024


def _encode_qr(payload: str, config: dict[str, Any]) -> dict[str, Any]:
    max_chars = config["max_qr_text_chars"]
    if len(payload) > max_chars:
        raise ValueError(f"QR text payload is too large. Maximum length is {max_chars} characters.")

    scale = config["qr_scale"]
    try:
        buffer = BytesIO()
        qr = segno.make(payload, encoding="utf-8")
        qr.save(buffer, kind="png", scale=scale)
    except Exception as exc:
        raise ValueError("Failed to generate QR code image.") from exc

    attachment = save_generated_attachment_bytes(
        buffer.getvalue(),
        filename="qr.png",
        mime_type="image/png",
        kind="image",
        metadata={"source": "codec.encode", "codec": "qr"},
    )
    return {
        "type": "image",
        "attachment_id": attachment["id"],
        "url": attachment["url"],
        "alt": "Generated QR code",
        "title": attachment["name"],
        "caption": "Generated QR code image.",
    }


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


def _decode_base64url_payload(payload: str, config: dict[str, Any]) -> bytes:
    value = str(payload or "").strip()
    compact = re.sub(r"\s+", "", value)
    if not compact:
        raise ValueError("Usage: /decode base64url <payload>")
    if not _BASE64URL_RE.fullmatch(compact) or "=" in compact.rstrip("="):
        raise ValueError("Invalid Base64URL input. Use only A-Z, a-z, 0-9, '-', '_', and optional trailing '=' padding.")
    unpadded = compact.rstrip("=")
    if len(unpadded) % 4 == 1:
        raise ValueError("Invalid Base64URL input. Length cannot be 1 modulo 4.")
    padded = unpadded + ("=" * ((4 - len(unpadded) % 4) % 4))
    estimated_bytes = (len(padded) * 3) // 4 - padded.count("=")
    if estimated_bytes > _max_decoded_bytes(config):
        raise ValueError(f"Decoded payload is too large. Maximum size is {config['max_decoded_bytes_mb']} MB.")
    try:
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Invalid Base64URL input.") from exc
    if len(decoded) > _max_decoded_bytes(config):
        raise ValueError(f"Decoded payload is too large. Maximum size is {config['max_decoded_bytes_mb']} MB.")
    return decoded


def _decode_url_payload(payload: str) -> str:
    value = str(payload or "")
    match = _INVALID_PERCENT_RE.search(value)
    if match:
        raise ValueError(f"Invalid URL percent escape at position {match.start()}. Expected '%' followed by two hex digits.")
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid URL percent-encoded UTF-8 input.") from exc


def _encode_unicode_escapes(value: str) -> str:
    pieces: list[str] = []
    for char in value:
        codepoint = ord(char)
        if char == "\n":
            pieces.append(r"\n")
        elif char == "\t":
            pieces.append(r"\t")
        elif char == "\r":
            pieces.append(r"\r")
        elif 0x20 <= codepoint <= 0x7E:
            pieces.append(char)
        elif codepoint <= 0xFFFF:
            pieces.append(f"\\u{codepoint:04x}")
        else:
            codepoint -= 0x10000
            high = 0xD800 + (codepoint >> 10)
            low = 0xDC00 + (codepoint & 0x3FF)
            pieces.append(f"\\u{high:04x}\\u{low:04x}")
    return "".join(pieces)


def _decode_unicode_escapes(value: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            pieces.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            raise ValueError("Invalid Unicode escape: trailing backslash.")
        marker = value[index + 1]
        if marker in {"n", "t", "r", "b", "f", "\\", '"', "/"}:
            pieces.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "\\": "\\", '"': '"', "/": "/"}[marker])
            index += 2
            continue
        if marker == "u":
            codepoint, next_index = _read_hex_escape(value, index, digits=4, marker="u")
            if 0xD800 <= codepoint <= 0xDBFF:
                if next_index + 6 <= len(value) and value[next_index : next_index + 2] == "\\u":
                    low, after_low = _read_hex_escape(value, next_index, digits=4, marker="u")
                    if 0xDC00 <= low <= 0xDFFF:
                        pieces.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)))
                        index = after_low
                        continue
                raise ValueError("Invalid Unicode escape: high surrogate must be followed by a low surrogate.")
            if 0xDC00 <= codepoint <= 0xDFFF:
                raise ValueError("Invalid Unicode escape: low surrogate without preceding high surrogate.")
            pieces.append(chr(codepoint))
            index = next_index
            continue
        if marker == "U":
            codepoint, next_index = _read_hex_escape(value, index, digits=8, marker="U")
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise ValueError("Invalid Unicode escape: code point is out of range.")
            pieces.append(chr(codepoint))
            index = next_index
            continue
        raise ValueError(f"Invalid Unicode escape: unsupported escape '\\{marker}'.")
    return "".join(pieces)


def _read_hex_escape(value: str, start: int, *, digits: int, marker: str) -> tuple[int, int]:
    hex_start = start + 2
    hex_end = hex_start + digits
    raw = value[hex_start:hex_end]
    if len(raw) != digits or not re.fullmatch(r"[0-9A-Fa-f]+", raw):
        raise ValueError(f"Invalid Unicode escape: expected \\{marker}{'X' * digits}.")
    return int(raw, 16), hex_end


def _decode_hex_payload(payload: str, config: dict[str, Any]) -> bytes:
    compact = _HEX_WHITESPACE_RE.sub("", str(payload or ""))
    if not compact:
        raise ValueError("Usage: /decode hex <payload>")
    if len(compact) % 2:
        raise ValueError("Invalid hex input. Hex payload must contain an even number of digits.")
    if not re.fullmatch(r"[0-9A-Fa-f]+", compact):
        raise ValueError("Invalid hex input. Use only hex digits and whitespace separators.")
    estimated_bytes = len(compact) // 2
    if estimated_bytes > _max_decoded_bytes(config):
        raise ValueError(f"Decoded payload is too large. Maximum size is {config['max_decoded_bytes_mb']} MB.")
    return bytes.fromhex(compact)


def _decode_utf8_text(
    decoded: bytes,
    *,
    message: str = "Unsupported binary decoded result. This round supports UTF-8 text only for this codec.",
) -> str:
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(message) from exc


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
