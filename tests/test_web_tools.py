"""Authenticated web tools, durable citations and ordinary Harness execution."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

from ai_workbench.api.main import create_app
from ai_workbench.core.anysearch import AnySearchProvider
from ai_workbench.core.harness.network import MAX_NETWORK_BYTES
from ai_workbench.core.harness.schema import HarnessState, ToolExecutionError
from ai_workbench.core.web_schemas import WebSearchRequest, WebToolsSettingsPatch
from ai_workbench.core.web_tools import WebToolsSettingsStore
from ai_workbench.db.models import AppMetadataRecord
from tests.history_helpers import history_messages
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, ok, register_approval_tool, tool_call


REQUEST_ID = str(uuid4())
URL = "https://example.com/article"
DEFAULT_SETTINGS = {"provider": "anysearch", "max_results": 10, "zone": None, "language": None}


def response(data, *, status=200, message="success"):
    return httpx.Response(status, json={"code": 0 if status == 200 else -1,
                                       "message": message, "request_id": REQUEST_ID, "data": data})


class AnySearchFixture:
    def __init__(self):
        self.calls = []
        self.reply = None

    async def handle(self, request):
        self.calls.append(request)
        if self.reply is not None:
            return self.reply
        if request.url.path == "/v1/search":
            return response({"results": [
                {"url": URL, "title": "Article", "snippet": "Summary", "content": "# Evidence"},
                {"url": "https://example.org/", "title": ""}],
                "metadata": {"total_results": 2, "search_time_ms": 12}})
        return response({"url": URL, "title": "Fetched article", "content": "<h1>Untrusted page</h1>\nEvidence."})


@pytest.fixture
def web_env(tmp_path):
    upstream, network = ToolOpenAI(), AnySearchFixture()
    app = create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory)
    app.state.runtime_state.web_tools.provider = AnySearchProvider(transport=httpx.MockTransport(network.handle))
    with TestClient(app) as client:
        yield client, upstream, network


def configure(client, **values):
    ok(client.patch("/api/tools/web/settings", json={"api_key": "test-web-key"}))
    return ok(client.post("/api/sessions", json=values))


def call(client, session, name="web_search", arguments=None):
    return ok(client.post(f"/api/tools/{name}/call", json={"session_id": session["session_id"],
        "arguments": {"query": "release notes"} if arguments is None else arguments}))


def results(payload):
    return [part for message in payload["messages"] for part in message["parts"] if part["type"] == "tool_result"]


def test_settings_are_write_only_strict_and_persisted(web_env, tmp_path):
    client, _, _ = web_env
    assert ok(client.get("/api/tools/web/settings")) == {**DEFAULT_SETTINGS, "has_api_key": False}
    configured = ok(client.patch("/api/tools/web/settings", json={"api_key": " saved-key "}))
    assert configured == {**DEFAULT_SETTINGS, "has_api_key": True}
    assert ok(client.patch("/api/tools/web/settings", json={})) == configured
    for value in [None, False, 3, [], {}, "bad\nkey"]:
        assert client.patch("/api/tools/web/settings", json={"api_key": value}).status_code == 422
    for patch in [{"max_results": value} for value in [None, False, "3", 1.0, 0, 11, 3.5]] + [
        {"zone": "us"}, {"language": " "}, {"language": 1}]:
        assert client.patch("/api/tools/web/settings", json=patch).status_code == 422
    assert client.patch("/api/tools/web/settings", json={"provider": "other"}).status_code == 422
    duplicate = client.patch("/api/tools/web/settings", content='{"api_key":"one","api_key":"two"}',
                             headers={"Content-Type": "application/json"})
    assert duplicate.status_code == 422
    assert ok(client.patch("/api/tools/web/settings", json={"api_key": ""}))["has_api_key"] is False
    schema = ok(client.get("/openapi.json"))["components"]["schemas"]
    assert schema["WebToolsSettingsPatch"]["properties"]["api_key"]["writeOnly"] is True
    assert "api_key" not in schema["WebToolsSettingsResponse"]["properties"]

    engine = create_engine(f"sqlite:///{tmp_path / 'web-settings.db'}")
    SQLModel.metadata.create_all(engine, tables=[AppMetadataRecord.__table__])
    WebToolsSettingsStore(engine).patch(WebToolsSettingsPatch(api_key="persisted-key", max_results=4, zone="intl", language="en"))
    reopened = WebToolsSettingsStore(engine)
    assert reopened.get().api_key == "persisted-key"
    assert (reopened.get().max_results, reopened.get().zone, reopened.get().language) == (4, "intl", "en")
    reopened.patch(WebToolsSettingsPatch())
    assert reopened.public().has_api_key
    reopened.patch(WebToolsSettingsPatch(api_key=""))
    assert not WebToolsSettingsStore(engine).public().has_api_key
    assert WebToolsSettingsStore(engine).public().max_results == 4
    reopened.patch(WebToolsSettingsPatch(zone=None, language=None))
    assert reopened.public().zone is None and reopened.public().language is None
    engine.dispose()


def test_direct_search_and_fetch_without_model_or_approval(web_env):
    client, upstream, network = web_env
    session = configure(client, harness_enabled=False)
    for name in ("web_search", "web_fetch"):
        spec = next(tool for tool in ok(client.get("/api/tools")) if tool["name"] == name)
        assert (spec["risk"], spec["requires_approval"], spec["direct_callable"], spec["scope"]) == ("network", False, True, "general")
    ok(client.patch("/api/tools/web/settings", json={"max_results": 2, "zone": "cn", "language": "zh-CN"}))
    payload = call(client, session, arguments={"query": "发布说明"})
    assert payload["run"]["kind"] == "tool" and payload["run"]["status"] == "DONE"
    assert all(step["kind"] != "approval" for step in payload["run"]["steps"])
    assert payload["session"]["waiting_run_id"] is None and not upstream.calls
    data = results(payload)[0]["data"]
    assert [page["source_id"] for page in data["results"]] == ["W1", "W2"]
    assert data["results"][1]["title"] == ""
    assert data["request_id"] == REQUEST_ID and data["search_time_ms"] == 12
    request = network.calls[0]
    assert request.headers["authorization"] == "Bearer test-web-key"
    assert request.url == "https://api.anysearch.com/v1/search"
    assert json.loads(request.content) == {"query": "发布说明", "max_results": 2, "zone": "cn", "language": "zh-CN", "format": "markdown"}
    payload = call(client, session, "web_fetch", {"url": URL})
    assert results(payload)[0]["data"]["content"].startswith("<h1>")
    assert results(payload)[0]["data"]["source_id"] == "W1"
    assert json.loads(network.calls[-1].content) == {"url": URL}
    assert network.calls[-1].url.path == "/v1/extract"
    persisted = history_messages(ok(client.get(f"/api/sessions/{session['session_id']}/history")))
    assert any(part.get("data", {}).get("source_id") == "W1" for message in persisted for part in message["parts"])
    assert "test-web-key" not in json.dumps(persisted)


@pytest.mark.parametrize("text,body", [
    ("/web_search release notes", {"query": "release notes", "max_results": 10, "format": "markdown"}),
    (f"/web_fetch {URL}", {"url": URL}),
])
def test_slash_calls_use_the_same_handlers(web_env, text, body):
    client, upstream, network = web_env
    session = configure(client)
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": text}))
    assert payload["run"]["status"] == "DONE" and not upstream.calls
    assert json.loads(network.calls[-1].content) == body


@pytest.mark.parametrize("arguments", [{}, {"query": " "}, {"query": 1}, {"query": "x", "max_results": True},
    {"query": "x", "max_results": 0}, {"query": "x", "max_results": 11}, {"query": "x", "max_results": 1.5},
    {"query": "x", "zone": "cn"}, {"query": "x", "language": "en"}, {"query": "x", "tag": "code.doc"}])
def test_invalid_search_inputs_never_dispatch(web_env, arguments):
    client, _, network = web_env
    session = configure(client)
    invalid = client.post("/api/tools/web_search/call", json={"session_id": session["session_id"], "arguments": arguments})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "TOOL_INVALID_ARGUMENTS"
    assert not network.calls


@pytest.mark.parametrize("url", ["http://localhost/a", "http://127.0.0.1/", "http://10.0.0.1/", "https://user:secret@example.com/", "https://example.com:abc/"])
def test_nonpublic_or_credentialed_targets_do_not_dispatch(web_env, url):
    client, _, network = web_env
    payload = call(client, configure(client), "web_fetch", {"url": url})
    assert payload["run"]["status"] == "FAILED"
    assert not network.calls


def test_missing_key_and_permissions(web_env):
    client, upstream, network = web_env
    session = ok(client.post("/api/sessions", json={}))
    assert call(client, session)["run"]["error_code"] == "WEB_NOT_CONFIGURED"
    session = configure(client, tools_allowed=[])
    forbidden = client.post("/api/tools/web_search/call", json={"session_id": session["session_id"], "arguments": {"query": "x"}})
    assert forbidden.status_code == 400 and forbidden.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert not network.calls and not upstream.calls


def test_search_options_are_settings_owned_and_apply_to_later_calls(web_env):
    client, _, network = web_env
    session = configure(client)
    schema = client.app.state.runtime_state.tool_registry.get("web_search").parameters
    assert set(schema["properties"]) == {"query"}
    payload = call(client, session)
    assert payload["run"]["status"] == "DONE"
    assert json.loads(network.calls[-1].content)["max_results"] == 10
    ok(client.patch("/api/tools/web/settings", json={"max_results": 3, "zone": "intl", "language": "en"}))
    call(client, session)
    assert json.loads(network.calls[-1].content) == {"query": "release notes", "max_results": 3, "zone": "intl", "language": "en", "format": "markdown"}


@pytest.mark.parametrize("status,code", [(400, "WEB_REQUEST_REJECTED"), (401, "WEB_AUTH_FAILED"),
    (402, "WEB_QUOTA_EXHAUSTED"), (403, "WEB_AUTH_FAILED"), (415, "WEB_REQUEST_REJECTED"),
    (422, "WEB_EXTRACTION_FAILED"), (429, "WEB_RATE_LIMITED"), (502, "WEB_SERVICE_UNAVAILABLE"), (302, "WEB_REQUEST_FAILED")])
def test_provider_errors_keep_only_safe_diagnostics(web_env, status, code):
    client, _, network = web_env
    network.reply = response(None, status=status, message="username=secret\npassword=private\napi_key=generated-key")
    payload = call(client, configure(client))
    result = results(payload)[0]
    assert result["error_code"] == code
    assert result["data"] == {"http_status": status, "request_id": REQUEST_ID}
    assert "generated-key" not in json.dumps(payload) and "private" not in json.dumps(payload)
    assert len(network.calls) == 1


@pytest.mark.parametrize("reply,code", [
    (httpx.Response(200, text="not JSON"), "WEB_RESPONSE_INVALID"),
    (response({"results": [{"title": "Bad", "url": "javascript:alert(1)"}]}), "WEB_RESPONSE_INVALID"),
    (response({"results": [{"title": 4, "url": URL}]}), "WEB_RESPONSE_INVALID"),
    (httpx.Response(200, content=b'x' * (MAX_NETWORK_BYTES + 1)), "WEB_RESPONSE_TOO_LARGE"),
    (httpx.Response(200, text='{"code":0,"code":0,"data":{"results":[]}}'), "WEB_RESPONSE_INVALID"),
])
def test_invalid_or_oversized_responses(web_env, reply, code):
    client, _, network = web_env
    network.reply = reply
    assert call(client, configure(client))["run"]["error_code"] == code


def test_sources_survive_approval_and_reach_the_model(web_env):
    client, upstream, _ = web_env
    configure_model(client, request_options={"streaming": True})
    state = client.app.state.runtime_state
    register_approval_tool(state.tool_registry)
    session = configure(client, harness_enabled=True)
    upstream.turns = [completion(tool_call("web_search", {"query": "test"}, "search"),
                                 tool_call("test_approval", {"value": "pause"}, "pause")),
                      completion(tool_call("web_fetch", {"url": URL}, "fetch")),
                      completion(content="Evidence [W1] and another source [W2].")]
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Research this"}))
    assert payload["run"]["status"] == "WAITING_FOR_USER"
    run_id = payload["run"]["run_id"]
    continuation = HarnessState.model_validate(state.runs.get_harness_state(run_id))
    assert continuation.web_sources[URL].source_id == "W1"
    assert len(continuation.web_sources) == 2
    assert "test-web-key" not in continuation.model_dump_json()
    payload = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert payload["run"]["status"] == "DONE"
    fetch = next(part for part in results(payload) if part["tool_name"] == "web_fetch")
    assert fetch["data"]["source_id"] == "W1"
    transcript = [json.loads(message["content"]) for message in upstream.calls[-1]["messages"] if message["role"] == "tool"]
    assert transcript[0]["data"]["results"][0]["source_id"] == transcript[-1]["data"]["source_id"] == "W1"
    assert all("[W1]" in tool["function"]["description"] for tool in upstream.calls[-1]["tools"] if tool["function"]["name"].startswith("web_"))
    assert state.runs.get_harness_state(run_id) == {}


def test_empty_results_and_model_recovery(web_env):
    client, upstream, network = web_env
    network.reply = response({"results": []})
    session = configure(client)
    assert results(call(client, session))[0]["data"]["results"] == []
    configure_model(client, request_options={"streaming": False})
    session = configure(client, harness_enabled=True)
    network.reply = response(None, status=429)
    upstream.turns = [completion(tool_call("web_search", {"query": "test"})), completion(content="Search is temporarily unavailable.")]
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Research"}))
    assert payload["run"]["status"] == "DONE" and results(payload)[0]["error_code"] == "WEB_RATE_LIMITED"


def test_cancel_and_timeout_use_harness_lifecycle(tmp_path, monkeypatch):
    from ai_workbench.core.harness import agent_loop

    async def scenario(cancel):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def hold(_request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        app = create_app(root=tmp_path, use_memory=True)
        state = app.state.runtime_state
        state.web_tools.provider = AnySearchProvider(transport=httpx.MockTransport(hold))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            ok(await client.patch("/api/tools/web/settings", json={"api_key": "key"}))
            session = ok(await client.post("/api/sessions", json={}))
            task = asyncio.create_task(client.post("/api/tools/web_search/call", json={"session_id": session["session_id"], "arguments": {"query": "test"}}))
            await asyncio.wait_for(started.wait(), 3)
            if cancel:
                run = state.runs.list_runs(session["session_id"])[0]
                ok(await client.post(f"/api/runs/{run.run_id}/cancel"))
            payload = ok(await asyncio.wait_for(task, 3))
            assert payload["run"]["status"] == ("CANCELLED" if cancel else "FAILED")
            assert payload["run"]["error_code"] == ("RUN_CANCELLED" if cancel else "TOOL_TIMEOUT")
            assert cancelled.is_set()
            assert state.active_runs.active_count() == 0

    asyncio.run(scenario(True))
    monkeypatch.setattr(agent_loop, "TOOL_TIMEOUT_SECONDS", .02)
    asyncio.run(scenario(False))


def test_http_timeout_and_untrusted_request_id():
    async def timeout(request):
        raise httpx.ReadTimeout("private diagnostic", request=request)
    provider = AnySearchProvider(transport=httpx.MockTransport(timeout))
    with pytest.raises(ToolExecutionError, match="timed out"):
        asyncio.run(provider.search(WebSearchRequest(query="test"), "key"))
    provider = AnySearchProvider(transport=httpx.MockTransport(lambda request: httpx.Response(402,
        json={"code": -1, "request_id": "api_key=secret", "message": "password=secret"})))
    with pytest.raises(ToolExecutionError) as error:
        asyncio.run(provider.search(WebSearchRequest(query="test"), "key"))
    assert error.value.details == {"http_status": 402}
