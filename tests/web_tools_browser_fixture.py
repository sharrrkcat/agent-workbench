"""Local AnySearch transport for browser acceptance; never calls the public API."""

import asyncio
import json

import httpx

from ai_workbench.core.anysearch import AnySearchProvider


WEB_URL = "https://example.com/article?query=" + "long-query-" * 24
WEB_CONTENT = "<script>window.webPageExecuted = true</script>\n" + "Extracted page content with preserved whitespace.\n" * 90


def install_web_fixture(app):
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
                {"url": WEB_URL, "title": "Web article with a long query", "snippet": "Search summary"},
                {"url": "https://example.org/reference", "title": "Reference page"},
                {"url": "https://unused.example.com/", "title": "Unused result"}],
                "metadata": {"search_time_ms": 10}}
        else:
            data = {"url": WEB_URL, "title": "Fetched web article", "content": WEB_CONTENT}
        return httpx.Response(200, json={"code": 0, "message": "success",
            "request_id": "13670951-682a-4b58-8b33-ed0cbe1c3753", "data": data})
    app.state.runtime_state.web_tools.provider = AnySearchProvider(transport=httpx.MockTransport(handle))
