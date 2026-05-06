import base64
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx


TEXT_LIMIT_BYTES = 1 * 1024 * 1024
IMAGE_LIMIT_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
TEXT_MIME_TYPES = {"text/plain", "text/html", "application/json"}


class CapabilityRuntime:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_text(self, text: str) -> str:
        response = _get(text, limit=TEXT_LIMIT_BYTES, client=self._client)
        mime_type = _content_type(response)
        if mime_type not in TEXT_MIME_TYPES:
            raise ValueError("HTTP response is not an allowed text type. Allowed: text/plain, text/html, application/json.")
        return response.content.decode(response.encoding or "utf-8", errors="replace")

    def fetch_page(self, text: str) -> str:
        response = _get(text, limit=TEXT_LIMIT_BYTES, client=self._client)
        mime_type = _content_type(response)
        if mime_type not in TEXT_MIME_TYPES:
            raise ValueError("HTTP response is not an allowed page/text type.")
        content = response.content.decode(response.encoding or "utf-8", errors="replace")
        if mime_type == "text/html":
            return _html_to_text(content)
        return content

    def fetch_image(self, text: str) -> dict:
        response = _get(text, limit=IMAGE_LIMIT_BYTES, client=self._client)
        mime_type = _content_type(response)
        if not mime_type.startswith("image/"):
            raise ValueError("HTTP response is not an image.")
        if len(response.content) > IMAGE_LIMIT_BYTES:
            raise ValueError("HTTP image response is too large. Maximum size is 10 MB.")
        encoded = base64.b64encode(response.content).decode("ascii")
        host = urlparse(str(response.url)).netloc
        return {
            "url": f"data:{mime_type};base64,{encoded}",
            "alt": f"Fetched image from {host}",
            "title": host,
            "caption": f"Fetched from {host} - {mime_type} - {len(response.content)} bytes",
        }


def _get(raw_url: str, limit: int, client: httpx.Client | None = None) -> httpx.Response:
    url = _validate_url(raw_url)
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": "agent-workbench/0.1"},
    )
    try:
        response = active_client.get(url)
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
        mb = limit // (1024 * 1024)
        raise ValueError(f"HTTP response is too large. Maximum size is {mb} MB.")
    return response


def _validate_url(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("HTTP capability only allows http:// and https:// URLs.")
    if not parsed.netloc:
        raise ValueError("HTTP URL must include a host.")
    return url


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


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
