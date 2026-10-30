"""Local AnySearch transport for browser acceptance; never calls the public API."""

import asyncio
import json

import httpx
from fastapi import Body

from ai_workbench.core.anysearch import AnySearchProvider
from ai_workbench.core.harness.schema import ToolExecutionError


WEB_URL = "https://example.com/article?query=" + "long-query-" * 24
WEB_CONTENT = "<script>window.webPageExecuted = true</script>\n" + "\n".join(
    f"Extracted page content with preserved whitespace. Section {i}: supporting facts and release details." for i in range(90))


def install_web_fixture(app):
    overrides = {}

    @app.post("/__test__/web-filter-source")
    def set_source(values: dict = Body(...)):
        if values.get("reset"):
            overrides.clear()
        else:
            overrides[values["url"]] = values
        return {"ok": True}

    async def subscription(url):
        override = overrides.get(url, {})
        if override.get("error"):
            raise ToolExecutionError("NETWORK_HTTP_ERROR", "Network request returned HTTP 503.")
        if "content" in override:
            return override["content"]
        if url.endswith("/invalid.txt"):
            return "# Invalid fixture\n/example/"
        if url.endswith("/failed.txt"):
            raise ToolExecutionError("NETWORK_HTTP_ERROR", "Network request returned HTTP 503.")
        return "---\nname: Browser fixture\n---\n*://blocked.example/*\n"
    app.state.runtime_state.web_tools.filters.download = subscription

    async def handle(request):
        payload = json.loads(request.content)
        query = payload.get("query", "")
        if query == "web-hold":
            await asyncio.Event().wait()
        if query == "web-failure":
            return httpx.Response(429, json={"code": -1, "message": "Fixture private error",
                "request_id": "13670951-682a-4b58-8b33-ed0cbe1c3753"})
        await asyncio.sleep(.2)
        if request.url.path == "/v1/search":
            data = {"results": [] if query == "web-empty" else [
                {"url": WEB_URL, "title": "Web article with a long query", "content": f"{query} {query} {query} Search summary"},
                {"url": "https://example.org/reference", "title": "Reference page", "content": f"{query} {query} Reference"},
                {"url": "https://unused.example.com/", "title": "Unused result", "content": f"{query} Unused result"}],
                "metadata": {"search_time_ms": 10}}
        else:
            data = {"url": WEB_URL, "title": "Fetched web article", "content": WEB_CONTENT}
        return httpx.Response(200, json={"code": 0, "message": "success",
            "request_id": "13670951-682a-4b58-8b33-ed0cbe1c3753", "data": data})
    app.state.runtime_state.web_tools.provider = AnySearchProvider(transport=httpx.MockTransport(handle))
