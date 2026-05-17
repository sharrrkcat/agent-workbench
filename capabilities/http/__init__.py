import base64
import json
import re
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import httpx


TEXT_LIMIT_BYTES = 1 * 1024 * 1024
IMAGE_LIMIT_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
TEXT_MIME_TYPES = {"application/json", "application/xml", "application/yaml", "application/x-yaml", "text/yaml"}
HTML_MIME_TYPES = {"text/html", "application/xhtml+xml"}
SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/mp4",
    "audio/flac",
    "audio/webm",
}
AUDIO_EXTENSION_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}
REJECTED_REMOTE_MEDIA_MIME_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "application/dash+xml",
    "audio/x-scpls",
    "application/rss+xml",
}
REJECTED_REMOTE_MEDIA_EXTENSIONS = {".m3u8", ".mpd", ".pls"}
CONFIG_DEFAULTS = {
    "enable_fetch_url_command": True,
    "allowed_schemes": ["http", "https"],
    "timeout_seconds": 10,
    "max_text_response_size_mb": 1,
    "max_image_response_size_mb": 10,
    "allow_redirects": True,
    "max_redirects": 5,
}


class CapabilityRuntime:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def fetch_url(self, text: str, context: dict | None = None) -> list[dict]:
        config = _runtime_config(context)
        _ensure_fetch_url_enabled(config)
        response = _request_for_fetch_url(text, config=config, client=self._client)
        mime_type = _content_type(response)
        kind = _response_kind(mime_type, str(response.url))
        if kind == "rejected_remote_media":
            raise ValueError("Unsupported remote media source for /fetch-url.")
        if kind == "audio":
            return [{"type": "audio", **_audio_payload(response, mime_type)}]
        if kind == "json":
            _enforce_limit(response, _mb_to_bytes(config["max_text_response_size_mb"]), config["max_text_response_size_mb"])
            try:
                return [{"type": "json", "data": response.json()}]
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON response.") from exc
        if kind == "html":
            _enforce_limit(response, _mb_to_bytes(config["max_text_response_size_mb"]), config["max_text_response_size_mb"])
            content = response.content.decode(response.encoding or "utf-8", errors="replace")
            return [{"type": "text", "format": "markdown", "text": _html_to_text(content)}]
        if kind == "text":
            _enforce_limit(response, _mb_to_bytes(config["max_text_response_size_mb"]), config["max_text_response_size_mb"])
            return [{"type": "text", "format": "plain", "text": response.content.decode(response.encoding or "utf-8", errors="replace")}]
        if kind == "image":
            _enforce_limit(response, _mb_to_bytes(config["max_image_response_size_mb"]), config["max_image_response_size_mb"])
            return [{"type": "image", **_image_payload(response, mime_type)}]
        raise ValueError(f"Unsupported content type for /fetch-url: {mime_type or 'unknown'}.")

    def get_text(self, text: str, context: dict | None = None) -> str:
        config = _runtime_config(context)
        _ensure_fetch_url_enabled(config)
        response = _get(text, limit=_mb_to_bytes(config["max_text_response_size_mb"]), config=config, client=self._client)
        mime_type = _content_type(response)
        if not _is_text_mime_type(mime_type):
            raise ValueError("Content type not allowed for text response.")
        return response.content.decode(response.encoding or "utf-8", errors="replace")

    def fetch_page(self, text: str, context: dict | None = None) -> str:
        config = _runtime_config(context)
        _ensure_fetch_url_enabled(config)
        response = _get(text, limit=_mb_to_bytes(config["max_text_response_size_mb"]), config=config, client=self._client)
        mime_type = _content_type(response)
        if not _is_text_mime_type(mime_type):
            raise ValueError("Content type not allowed for page/text response.")
        content = response.content.decode(response.encoding or "utf-8", errors="replace")
        if mime_type == "text/html":
            return _html_to_text(content)
        return content

    def fetch_image(self, text: str, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        _ensure_fetch_url_enabled(config)
        limit = _mb_to_bytes(config["max_image_response_size_mb"])
        response = _get(text, limit=limit, config=config, client=self._client)
        mime_type = _content_type(response)
        if not mime_type.startswith("image/"):
            raise ValueError("Image expected: HTTP response is not an image.")
        _enforce_limit(response, limit, config["max_image_response_size_mb"])
        return _image_payload(response, mime_type)


def _runtime_config(context: dict | None) -> dict:
    config = dict(CONFIG_DEFAULTS)
    provided = (context or {}).get("capability_config") if isinstance(context, dict) else None
    if isinstance(provided, dict):
        config.update(_strip_legacy_config(provided))
    return config


def _strip_legacy_config(config: dict) -> dict:
    return {key: value for key, value in dict(config).items() if key not in {"enable_http_get", "enable_fetch_image"}}


def _ensure_fetch_url_enabled(config: dict) -> None:
    if not bool(config.get("enable_fetch_url_command", True)):
        raise ValueError("Command disabled: /fetch-url is disabled in HTTP Capability settings.")


def _get(raw_url: str, limit: int, config: dict, client: httpx.Client | None = None) -> httpx.Response:
    url = _validate_url(raw_url, config)
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=float(config["timeout_seconds"]),
        follow_redirects=bool(config["allow_redirects"]),
        max_redirects=int(config["max_redirects"]),
        headers={"User-Agent": "agent-workbench/0.1"},
    )
    try:
        response = active_client.get(url, timeout=float(config["timeout_seconds"]), follow_redirects=bool(config["allow_redirects"]))
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ValueError("HTTP request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"HTTP request failed with status {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise ValueError("HTTP request failed.") from exc
    finally:
        if owns_client:
            active_client.close()
    if len(response.content) > limit:
        raise ValueError(f"Response too large. Maximum size is {_format_bytes_as_mb(limit)}.")
    _validate_url(str(response.url), config)
    return response


def _request_for_fetch_url(raw_url: str, config: dict, client: httpx.Client | None = None) -> httpx.Response:
    url = _validate_url(raw_url, config)
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=float(config["timeout_seconds"]),
        follow_redirects=bool(config["allow_redirects"]),
        max_redirects=int(config["max_redirects"]),
        headers={"User-Agent": "agent-workbench/0.1"},
    )
    try:
        with active_client.stream("GET", url, timeout=float(config["timeout_seconds"]), follow_redirects=bool(config["allow_redirects"])) as response:
            response.raise_for_status()
            _validate_url(str(response.url), config)
            mime_type = _content_type(response)
            kind = _response_kind(mime_type, str(response.url))
            if kind in {"audio", "rejected_remote_media"}:
                return _metadata_response(response)
            limit = _limit_for_fetch_kind(kind, config)
            content = _read_limited_response(response, limit)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=content,
                request=response.request,
                extensions=response.extensions,
            )
    except httpx.TimeoutException as exc:
        raise ValueError("HTTP request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"HTTP request failed with status {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise ValueError("HTTP request failed.") from exc
    finally:
        if owns_client:
            active_client.close()


def _metadata_response(response: httpx.Response) -> httpx.Response:
    return httpx.Response(
        response.status_code,
        headers=response.headers,
        content=b"",
        request=response.request,
        extensions=response.extensions,
    )


def _limit_for_fetch_kind(kind: str, config: dict) -> int:
    if kind == "image":
        return _mb_to_bytes(config["max_image_response_size_mb"])
    return _mb_to_bytes(config["max_text_response_size_mb"])


def _read_limited_response(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise ValueError(f"Response too large. Maximum size is {_format_bytes_as_mb(limit)}.")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_url(raw_url: str, config: dict | None = None) -> str:
    config = config or CONFIG_DEFAULTS
    url = str(raw_url or "").strip()
    if not url:
        raise ValueError("URL required.")
    parsed = urlparse(url)
    allowed_schemes = config.get("allowed_schemes", [])
    if not isinstance(allowed_schemes, list):
        allowed_schemes = []
    allowed = {str(item).lower() for item in allowed_schemes}
    if parsed.scheme not in allowed:
        visible = ", ".join(sorted(allowed)) or "none configured"
        if allowed == {"http", "https"}:
            raise ValueError("Scheme not allowed. HTTP capability only allows http:// and https:// URLs.")
        raise ValueError(f"Scheme not allowed for HTTP Capability: {parsed.scheme or '(none)'}. Allowed schemes: {visible}.")
    if not parsed.netloc:
        raise ValueError("HTTP URL must include a host.")
    return url


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _is_text_mime_type(mime_type: str) -> bool:
    return mime_type.startswith("text/") or mime_type in TEXT_MIME_TYPES


def _response_kind(mime_type: str, url: str) -> str:
    if _is_rejected_remote_media(mime_type, url):
        return "rejected_remote_media"
    if _is_audio_mime_type(mime_type):
        return "audio"
    if _is_json_mime_type(mime_type):
        return "json"
    if mime_type in HTML_MIME_TYPES:
        return "html"
    if mime_type.startswith("image/"):
        return "image"
    if _is_text_mime_type(mime_type):
        return "text"
    return _kind_from_extension(url)


def _is_json_mime_type(mime_type: str) -> bool:
    return mime_type == "application/json" or mime_type.endswith("+json")


def _is_audio_mime_type(mime_type: str) -> bool:
    return mime_type in SUPPORTED_AUDIO_MIME_TYPES


def _is_rejected_remote_media(mime_type: str, url: str) -> bool:
    if mime_type in REJECTED_REMOTE_MEDIA_MIME_TYPES:
        return True
    return _url_suffix(url) in REJECTED_REMOTE_MEDIA_EXTENSIONS


def _kind_from_extension(url: str) -> str:
    suffix = _url_suffix(url)
    if suffix in {".json", ".geojson"}:
        return "json"
    if suffix in {".html", ".htm", ".xhtml"}:
        return "html"
    if suffix in {".txt", ".md", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".log"}:
        return "text"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "image"
    if suffix in AUDIO_EXTENSION_MIME_TYPES:
        return "audio"
    return "unsupported"


def _url_suffix(url: str) -> str:
    return PurePosixPath(urlparse(url).path).suffix.lower()


def _enforce_limit(response: httpx.Response, limit: int, limit_mb: object) -> None:
    if len(response.content) > limit:
        raise ValueError(f"Response too large. Maximum size is {_format_mb(limit_mb)}.")


def _image_payload(response: httpx.Response, mime_type: str) -> dict:
    encoded = base64.b64encode(response.content).decode("ascii")
    host = urlparse(str(response.url)).netloc
    return {
        "url": f"data:{mime_type};base64,{encoded}",
        "alt": f"Fetched image from {host}",
        "title": host,
        "caption": f"Fetched from {host} - {mime_type} - {len(response.content)} bytes",
    }


def _audio_payload(response: httpx.Response, mime_type: str) -> dict:
    url = str(response.url)
    effective_mime = mime_type if _is_audio_mime_type(mime_type) else AUDIO_EXTENSION_MIME_TYPES.get(_url_suffix(url), "audio/mpeg")
    filename = _filename_from_url(url)
    payload = {
        "source": "url",
        "url": url,
        "mime_type": effective_mime,
    }
    if filename:
        payload["filename"] = filename
        payload["title"] = filename
    size_bytes = _content_length(response)
    if size_bytes is not None:
        payload["size_bytes"] = size_bytes
    return payload


def _filename_from_url(url: str) -> str:
    name = PurePosixPath(urlparse(url).path).name
    return unquote(name) if name else ""


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _mb_to_bytes(value: object) -> int:
    return int(float(value) * 1024 * 1024)


def _format_mb(value: object) -> str:
    return f"{float(value):g} MB"


def _format_bytes_as_mb(value: int) -> str:
    return f"{value / (1024 * 1024):g} MB"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
