import base64
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx


TEXT_LIMIT_BYTES = 1 * 1024 * 1024
IMAGE_LIMIT_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
TEXT_MIME_TYPES = {"application/json", "application/xml", "application/yaml", "application/x-yaml"}
CONFIG_DEFAULTS = {
    "enable_http_get": True,
    "enable_fetch_image": True,
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

    def get_text(self, text: str, context: dict | None = None) -> str:
        config = _runtime_config(context)
        if not bool(config["enable_http_get"]):
            raise ValueError("Command disabled: /http-get and /fetch-page are disabled in HTTP Capability settings.")
        response = _get(text, limit=_mb_to_bytes(config["max_text_response_size_mb"]), config=config, client=self._client)
        mime_type = _content_type(response)
        if not _is_text_mime_type(mime_type):
            raise ValueError("Content type not allowed for text response.")
        return response.content.decode(response.encoding or "utf-8", errors="replace")

    def fetch_page(self, text: str, context: dict | None = None) -> str:
        config = _runtime_config(context)
        if not bool(config["enable_http_get"]):
            raise ValueError("Command disabled: /http-get and /fetch-page are disabled in HTTP Capability settings.")
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
        if not bool(config["enable_fetch_image"]):
            raise ValueError("Command disabled: /fetch-image is disabled in HTTP Capability settings.")
        limit = _mb_to_bytes(config["max_image_response_size_mb"])
        response = _get(text, limit=limit, config=config, client=self._client)
        mime_type = _content_type(response)
        if not mime_type.startswith("image/"):
            raise ValueError("Image expected: HTTP response is not an image.")
        if len(response.content) > limit:
            raise ValueError(f"Response too large. Maximum size is {_format_mb(config['max_image_response_size_mb'])}.")
        encoded = base64.b64encode(response.content).decode("ascii")
        host = urlparse(str(response.url)).netloc
        return {
            "url": f"data:{mime_type};base64,{encoded}",
            "alt": f"Fetched image from {host}",
            "title": host,
            "caption": f"Fetched from {host} - {mime_type} - {len(response.content)} bytes",
        }


def _runtime_config(context: dict | None) -> dict:
    config = dict(CONFIG_DEFAULTS)
    provided = (context or {}).get("capability_config") if isinstance(context, dict) else None
    if isinstance(provided, dict):
        config.update(provided)
    return config


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
        response = active_client.get(
            url,
            timeout=float(config["timeout_seconds"]),
            follow_redirects=bool(config["allow_redirects"]),
        )
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
    return response


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
