from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin

import httpx

from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.network_policy import NetworkPolicyError


MAX_NETWORK_BYTES = 1024 * 1024


async def fetch_bytes(url: str, policy: Any, *, max_bytes: int = MAX_NETWORK_BYTES) -> tuple[bytes, str, str]:
    current = url
    max_bytes = min(max_bytes, policy.max_response_bytes)
    redirects = 0
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            while True:
                target = httpx.URL(current)
                current, addresses = await asyncio.to_thread(policy.resolve_url, str(target))
                pinned = target.copy_with(host=addresses[0])
                async with client.stream("GET", pinned, headers={"Host": target.netloc.decode("ascii"), "Accept-Encoding": "identity"},
                                         extensions={"sni_hostname": target.host}) as response:
                    status_code = response.status_code
                    headers = response.headers
                    if status_code in {301, 302, 303, 307, 308}:
                        redirects += 1
                        policy.validate_redirect_count(redirects)
                        location = headers.get("location")
                        if not location:
                            raise ToolExecutionError("NETWORK_REDIRECT_INVALID", "Redirect response did not include a location.")
                        current = urljoin(current, location)
                        continue
                    if status_code >= 400:
                        raise ToolExecutionError("NETWORK_HTTP_ERROR", f"Network request returned HTTP {status_code}.")
                    if headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                        raise ToolExecutionError("NETWORK_CONTENT_ENCODING_FORBIDDEN", "The service must return an uncompressed response.")
                    content_length = headers.get("content-length")
                    if content_length is not None:
                        try:
                            too_large = int(content_length) > max_bytes
                        except ValueError:
                            too_large = False
                        if too_large:
                            raise ToolExecutionError("NETWORK_RESPONSE_TOO_LARGE", "Network response exceeds the 1 MiB limit.")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ToolExecutionError("NETWORK_RESPONSE_TOO_LARGE", "Network response exceeds the 1 MiB limit.")
                        chunks.append(chunk)
                    return b"".join(chunks), current, headers.get("content-type", "")
    except ToolExecutionError:
        raise
    except NetworkPolicyError as exc:
        raise ToolExecutionError(exc.code, exc.message) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ToolExecutionError("NETWORK_REQUEST_FAILED", "Network request failed.") from exc
