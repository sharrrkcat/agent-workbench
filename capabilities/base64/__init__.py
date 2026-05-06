import base64
import binascii
import re
from typing import Optional, Tuple

from ai_workbench.core.attachments import read_attachment_as_data_url


_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.*)$",
    re.DOTALL,
)

_ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
    "image/bmp",
}

_MAX_IMAGE_BYTES = 10 * 1024 * 1024


class CapabilityRuntime:
    def encode(self, text: str) -> str:
        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    def decode(self, text: str) -> str:
        try:
            decoded = base64.b64decode(text.encode("ascii"), validate=True)
            return decoded.decode("utf-8")
        except (binascii.Error, UnicodeEncodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid base64 input.") from exc

    def decode_image(self, text: str) -> dict:
        """Decode image base64 into an image payload renderable by chat.

        Accepts either a data URL, e.g. ``data:image/png;base64,...``, or raw
        base64 image bytes. The returned payload is intended for a command whose
        manifest declares ``output.type: image``.
        """

        image_bytes, declared_mime = _decode_image_input(text)
        detected_mime = _detect_image_mime_type(image_bytes)
        mime_type = detected_mime or declared_mime

        if not mime_type or mime_type not in _ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported or unknown image type.")

        if declared_mime and declared_mime not in _ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported image MIME type.")

        if detected_mime and declared_mime and detected_mime != declared_mime:
            # SVG data URLs can contain XML declarations and are reliably detected
            # as image/svg+xml. For binary images, prefer strict validation so an
            # incorrect data URL does not mislead downstream renderers.
            raise ValueError(
                f"Image MIME type mismatch: declared {declared_mime}, detected {detected_mime}."
            )

        encoded = base64.b64encode(image_bytes).decode("ascii")
        return {
            "url": f"data:{mime_type};base64,{encoded}",
            "alt": f"Decoded {mime_type} image",
            "title": "Base64 image",
            "caption": f"Decoded from base64 · {mime_type} · {len(image_bytes)} bytes",
        }

    def encode_image(self, text: str, context: dict) -> dict:
        attachments = context.get("attachments") if isinstance(context, dict) else []
        images = [
            item
            for item in attachments or []
            if isinstance(item, dict) and item.get("type") == "image" and (isinstance(item.get("data_url"), str) or isinstance(item.get("uri"), str))
        ]
        if not images:
            raise ValueError("No image attachment found.")

        index = _parse_image_index(text)
        if index < 1 or index > len(images):
            raise ValueError(f"Image attachment index out of range. Available images: {len(images)}.")

        image = images[index - 1]
        data_url = read_attachment_as_data_url(image).strip()
        raw_base64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        return {
            "mime_type": image.get("mime_type") or "",
            "name": image.get("name") or "",
            "size": image.get("size") or 0,
            "index": index,
            "total_images": len(images),
            "note": "Encoded the selected image attachment. Multiple attachments are supported by passing a 1-based index.",
            "data_url": data_url,
            "base64": raw_base64,
        }


def _decode_image_input(text: str) -> Tuple[bytes, Optional[str]]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Image base64 input is required.")

    declared_mime: Optional[str] = None
    match = _DATA_URL_RE.match(cleaned)
    if match:
        declared_mime = match.group("mime").lower()
        cleaned = match.group("data").strip()

    # Be permissive about pasted line wrapping and spaces.
    cleaned = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        raise ValueError("Image base64 input is required.")

    try:
        image_bytes = base64.b64decode(cleaned.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Invalid image base64 input.") from exc

    if not image_bytes:
        raise ValueError("Decoded image is empty.")
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise ValueError("Decoded image is too large. Maximum size is 10 MB.")

    return image_bytes, declared_mime


def _detect_image_mime_type(image_bytes: bytes) -> Optional[str]:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"BM"):
        return "image/bmp"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    stripped = image_bytes.lstrip()
    lowered = stripped[:256].lower()
    if lowered.startswith(b"<svg") or (lowered.startswith(b"<?xml") and b"<svg" in lowered):
        return "image/svg+xml"

    return None


def _parse_image_index(text: str) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        return 1
    try:
        return int(cleaned)
    except ValueError as exc:
        raise ValueError("Image attachment index must be a number.") from exc
