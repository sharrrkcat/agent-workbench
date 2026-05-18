import httpx
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.capability_registry import CapabilityRegistry
from capabilities.web_search import CapabilityRuntime as WebSearchRuntime
from tests.test_api import create_session
from tests.test_prompt_agent_execution import FakeLLMRuntime


def test_web_search_manifest_is_registered() -> None:
    registry = CapabilityRegistry()
    registry.load_from_directory("capabilities")

    capability = registry.get("web_search")

    assert capability.name == "Web Search"
    assert [method.id for method in capability.methods] == ["search"]
    assert capability.commands[0].name == "/web-search"
    assert capability.methods[0].output == {"part_type": "parts"}


def test_web_search_query_required() -> None:
    runtime = WebSearchRuntime()

    try:
        runtime.search("   ")
    except ValueError as exc:
        assert str(exc) == "query required"
    else:
        raise AssertionError("expected query required")


def test_web_search_command_disabled() -> None:
    runtime = WebSearchRuntime()

    try:
        runtime.search("openai", context={"capability_config": {"enable_web_search_command": False}})
    except ValueError as exc:
        assert str(exc) == "command disabled"
    else:
        raise AssertionError("expected disabled command")


def test_web_search_invalid_base_url() -> None:
    runtime = WebSearchRuntime()

    for value in ["", "ftp://example.test", "http:///missing-host"]:
        try:
            runtime.search("openai", context={"capability_config": {"searxng_base_url": value}})
        except ValueError as exc:
            assert str(exc) == "invalid base url"
        else:
            raise AssertionError(f"expected invalid base URL for {value!r}")


def test_web_search_success_response_normalization() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Result One",
                        "url": "https://Example.test/page",
                        "content": "First snippet",
                        "engine": "duckduckgo",
                        "publishedDate": "2026-05-17",
                    },
                    {
                        "title": "Result Two",
                        "url": "http://second.test/post",
                        "snippet": "Second snippet",
                        "source": "bing",
                    },
                ]
            },
            request=request,
        )

    runtime = WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    parts = runtime.search(
        "qwen latest release",
        context={
            "capability_config": {
                "searxng_base_url": "https://searxng.test/",
                "language": "en",
                "safe_search": "strict",
                "max_results": 8,
            }
        },
    )

    assert [part["type"] for part in parts] == ["json"]
    assert "q=qwen+latest+release" in str(seen["url"])
    assert "language=en" in str(seen["url"])
    assert "safesearch=2" in str(seen["url"])
    data = parts[0]["data"]
    assert data["kind"] == "web_search_results"
    assert data["schema"] == "web_search.results.v1"
    assert data["query"] == "qwen latest release"
    assert data["provider"] == "searxng"
    assert data["warnings"] == []
    assert data["results"] == [
        {
            "rank": 1,
            "title": "Result One",
            "url": "https://Example.test/page",
            "domain": "example.test",
            "snippet": "First snippet",
            "published_at": "2026-05-17",
            "source": "duckduckgo",
        },
        {
            "rank": 2,
            "title": "Result Two",
            "url": "http://second.test/post",
            "domain": "second.test",
            "snippet": "Second snippet",
            "published_at": None,
            "source": "bing",
        },
    ]
    assert all(part["type"] != "text" for part in parts)


def test_web_search_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []}, request=request)

    runtime = WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    parts = runtime.search("nothing", context={"capability_config": {"searxng_base_url": "https://searxng.test"}})

    data = parts[0]["data"]
    assert data["kind"] == "web_search_results"
    assert data["results"] == []
    assert all(part["type"] != "text" for part in parts)


def test_web_search_invalid_response() -> None:
    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", request=request)

    def invalid_shape(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []}, request=request)

    for handler in [invalid_json, invalid_shape]:
        runtime = WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            runtime.search("openai", context={"capability_config": {"searxng_base_url": "https://searxng.test"}})
        except ValueError as exc:
            assert str(exc) == "invalid response"
        else:
            raise AssertionError("expected invalid response")


def test_web_search_timeout_and_unreachable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no service", request=request)

    cases = [(timeout, "timeout"), (unreachable, "searxng unreachable")]
    for handler, expected in cases:
        runtime = WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            runtime.search("openai", context={"capability_config": {"searxng_base_url": "https://searxng.test"}})
        except ValueError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError(f"expected {expected}")


def test_web_search_max_results_and_invalid_url_warning() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Bad", "url": "file:///secret", "content": "skip"},
                    {"title": "One", "url": "https://one.test", "content": "one"},
                    {"title": "Two", "url": "https://two.test", "content": "two"},
                    {"title": "Three", "url": "https://three.test", "content": "three"},
                ]
            },
            request=request,
        )

    runtime = WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    parts = runtime.search(
        "query",
        context={"capability_config": {"searxng_base_url": "https://searxng.test", "max_results": 2}},
    )

    data = parts[0]["data"]
    assert [result["title"] for result in data["results"]] == ["One", "Two"]
    assert data["warnings"] == ["skipped 1 result(s) with invalid URL"]


def test_web_search_config_defaults_patch_and_runtime_enforcement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"title": "Found", "url": "https://result.test", "content": "snippet"}]},
            request=request,
        )

    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    app.state.runtime_state.runtimes.replace("web_search", WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler))))
    client = TestClient(app)
    session = create_session(client)

    defaults = client.get("/api/capability-configs/web_search")
    assert defaults.status_code == 200
    resolved = defaults.json()["resolved_config"]
    assert resolved["enable_web_search_command"] is True
    assert resolved["searxng_base_url"] == "http://localhost:8888"
    assert resolved["timeout_seconds"] == 10.0
    assert resolved["max_results"] == 8
    assert resolved["language"] == "auto"
    assert resolved["safe_search"] == "default"

    patched = client.patch(
        "/api/capability-configs/web_search",
        json={"user_config": {"searxng_base_url": "https://searxng.test", "max_results": 1}},
    )
    assert patched.status_code == 200
    assert patched.json()["resolved_config"]["max_results"] == 1

    result = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/web-search qwen"})
    assert result.json()["run"]["status"] == "DONE"
    parts = result.json()["messages"][-1]["parts"]
    assert [part["type"] for part in parts] == ["json"]
    assert parts[0]["data"]["kind"] == "web_search_results"
    assert parts[0]["data"]["schema"] == "web_search.results.v1"
    assert parts[0]["data"]["results"][0]["domain"] == "result.test"

    required = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/web-search   "})
    assert "query required" in required.json()["run"]["error"]

    client.patch("/api/capability-configs/web_search", json={"user_config": {"enable_web_search_command": False}})
    disabled = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/web-search qwen"})
    assert "command disabled" in disabled.json()["run"]["error"]


def test_web_search_test_search_success_uses_draft_config_without_messages_or_runs() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "One", "url": "https://one.test/page", "content": "first", "engine": "duckduckgo"},
                    {"title": "Two", "url": "https://two.test/page", "content": "second"},
                    {"title": "Three", "url": "https://three.test/page", "content": "third"},
                    {"title": "Four", "url": "https://four.test/page", "content": "fourth"},
                ],
                "untrusted_raw": {"secret": "do not return"},
            },
            request=request,
        )

    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    app.state.runtime_state.runtimes.replace("web_search", WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler))))
    client = TestClient(app)
    session = create_session(client)

    before_messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    before_runs = client.get(f"/api/sessions/{session['session_id']}/runs").json()
    response = client.post(
        "/api/capability-configs/web_search/test-search",
        json={
            "query": "agent workbench",
            "config": {
                "enable_web_search_command": False,
                "searxng_base_url": "https://draft-searxng.test",
                "language": "en",
                "safe_search": "moderate",
                "max_results": 4,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "searxng"
    assert data["base_url"] == "https://draft-searxng.test"
    assert data["query"] == "agent workbench"
    assert data["result_count"] == 4
    assert data["first_result"] == {
        "rank": 1,
        "title": "One",
        "url": "https://one.test/page",
        "domain": "one.test",
        "snippet": "first",
        "published_at": None,
        "source": "duckduckgo",
    }
    assert [result["title"] for result in data["sample_results"]] == ["One", "Two", "Three"]
    assert "untrusted_raw" not in data
    assert "language=en" in str(seen["url"])
    assert "safesearch=1" in str(seen["url"])
    assert client.get(f"/api/sessions/{session['session_id']}/messages").json() == before_messages
    assert client.get(f"/api/sessions/{session['session_id']}/runs").json() == before_runs


def test_web_search_test_search_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []}, request=request)

    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    app.state.runtime_state.runtimes.replace("web_search", WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler))))
    client = TestClient(app)

    response = client.post(
        "/api/capability-configs/web_search/test-search",
        json={"query": "nothing", "config": {"searxng_base_url": "https://searxng.test"}},
    )

    data = response.json()
    assert data["ok"] is True
    assert data["result_count"] == 0
    assert data["first_result"] is None
    assert data["sample_results"] == []


def test_web_search_test_search_structured_failures() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no service", request=request)

    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", request=request)

    cases = [
        (None, {"query": "openai", "config": {"searxng_base_url": "ftp://bad.test"}}, "invalid_base_url"),
        (timeout, {"query": "openai", "config": {"searxng_base_url": "https://searxng.test"}}, "timeout"),
        (unreachable, {"query": "openai", "config": {"searxng_base_url": "https://searxng.test"}}, "searxng_unreachable"),
        (invalid_json, {"query": "openai", "config": {"searxng_base_url": "https://searxng.test"}}, "invalid_response"),
        (None, {"query": "   ", "config": {"searxng_base_url": "https://searxng.test"}}, "query_required"),
    ]
    for handler, payload, expected_code in cases:
        app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
        if handler is not None:
            app.state.runtime_state.runtimes.replace("web_search", WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler))))
        client = TestClient(app)

        response = client.post("/api/capability-configs/web_search/test-search", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["error_code"] == expected_code
        assert data["result_count"] == 0
        assert data["first_result"] is None
        assert data["sample_results"] == []
