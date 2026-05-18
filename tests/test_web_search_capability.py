import httpx
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.capability_registry import CapabilityRegistry
from capabilities.web_search import CapabilityRuntime as WebSearchRuntime
from tests.test_api import create_session
from tests.test_prompt_agent_execution import FakeLLMRuntime


def search_data(results: list[dict], config: dict | None = None) -> dict:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": results}, request=request)

    runtime = WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))
    parts = runtime.search("query", context={"capability_config": {"searxng_base_url": "https://searxng.test", **(config or {})}})
    return parts[0]["data"]


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
    assert data["diagnostics"]["raw_result_count"] == 4
    assert data["diagnostics"]["normalized_count"] == 3
    assert data["diagnostics"]["final_count"] == 2


def test_web_search_domain_blocklist_filters_root_and_subdomain() -> None:
    data = search_data(
        [
            {"title": "Root", "url": "https://example.com/root"},
            {"title": "Sub", "url": "https://news.example.com/story"},
            {"title": "Keep", "url": "https://keep.test/story"},
        ],
        {"domain_blocklist": "example.com"},
    )

    assert [result["domain"] for result in data["results"]] == ["keep.test"]
    assert data["diagnostics"]["blocked_count"] == 2
    assert data["diagnostics"]["filtered_count"] == 2


def test_web_search_wildcard_pattern_and_url_pattern_normalization() -> None:
    data = search_data(
        [
            {"title": "Root", "url": "https://example.com/root"},
            {"title": "Sub", "url": "https://news.example.com/story"},
            {"title": "Keep", "url": "https://keep.test/story"},
        ],
        {"domain_blocklist": "https://*.example.com/path"},
    )

    assert [result["domain"] for result in data["results"]] == ["keep.test"]
    assert data["diagnostics"]["blocked_count"] == 2


def test_web_search_allowlist_keeps_matching_domains_only() -> None:
    data = search_data(
        [
            {"title": "One", "url": "https://one.test/page"},
            {"title": "Two", "url": "https://two.test/page"},
            {"title": "Sub", "url": "https://news.two.test/page"},
        ],
        {"domain_allowlist": ".two.test"},
    )

    assert [result["domain"] for result in data["results"]] == ["two.test", "news.two.test"]
    assert data["diagnostics"]["allowlist_excluded_count"] == 1


def test_web_search_allowlist_then_blocklist_order() -> None:
    data = search_data(
        [
            {"title": "Root", "url": "https://example.com/page"},
            {"title": "Blocked Sub", "url": "https://news.example.com/page"},
            {"title": "Other", "url": "https://other.test/page"},
        ],
        {"domain_allowlist": "example.com", "domain_blocklist": "news.example.com"},
    )

    assert [result["domain"] for result in data["results"]] == ["example.com"]
    assert data["diagnostics"]["allowlist_excluded_count"] == 1
    assert data["diagnostics"]["blocked_count"] == 1


def test_web_search_invalid_pattern_warns_without_failing() -> None:
    data = search_data(
        [{"title": "One", "url": "https://one.test/page"}],
        {"domain_blocklist": "bad pattern\none.test"},
    )

    assert data["results"] == []
    assert "invalid_domain_filter_pattern" in data["warnings"]
    assert "invalid_domain_filter_pattern" in data["diagnostics"]["warnings"]


def test_web_search_dedupes_canonical_url_and_same_domain_title() -> None:
    data = search_data(
        [
            {"title": "Same", "url": "https://Example.test/path/#fragment"},
            {"title": "Other", "url": "https://example.test/path"},
            {"title": "Repeated Title", "url": "https://example.test/a"},
            {"title": "  repeated   title  ", "url": "https://example.test/b"},
        ],
    )

    assert [result["url"] for result in data["results"]] == ["https://Example.test/path/#fragment", "https://example.test/a"]
    assert data["diagnostics"]["deduped_count"] == 2


def test_web_search_dedupe_can_be_disabled() -> None:
    data = search_data(
        [
            {"title": "Same", "url": "https://example.test/path#one"},
            {"title": "Other", "url": "https://example.test/path#two"},
            {"title": "Repeated", "url": "https://example.test/a"},
            {"title": "Repeated", "url": "https://example.test/b"},
        ],
        {"dedupe_results": False, "dedupe_same_domain_title": False},
    )

    assert len(data["results"]) == 4
    assert data["diagnostics"]["deduped_count"] == 0


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
    assert resolved["result_filter_enabled"] is True
    assert resolved["domain_blocklist"] == ""
    assert resolved["domain_allowlist"] == ""
    assert resolved["dedupe_results"] is True
    assert resolved["dedupe_same_domain_title"] is True

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
    assert parts[0]["data"]["diagnostics"]["final_count"] == 1

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
                "domain_blocklist": "two.test",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "searxng"
    assert data["base_url"] == "https://draft-searxng.test"
    assert data["query"] == "agent workbench"
    assert data["result_count"] == 3
    assert data["first_result"] == {
        "rank": 1,
        "title": "One",
        "url": "https://one.test/page",
        "domain": "one.test",
        "snippet": "first",
        "published_at": None,
        "source": "duckduckgo",
    }
    assert [result["title"] for result in data["sample_results"]] == ["One", "Three", "Four"]
    assert data["diagnostics"]["filtered_count"] == 1
    assert data["diagnostics"]["blocked_count"] == 1
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
    assert data["diagnostics"]["final_count"] == 0


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
        assert "diagnostics" in data


def test_prompt_agent_web_context_uses_web_search_filtering_config() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Blocked", "url": "https://blocked.test/page", "content": "blocked"},
                    {"title": "Kept", "url": "https://kept.test/page", "content": "kept"},
                ]
            },
            request=request,
        )

    app = create_app(llm_runtime=FakeLLMRuntime(response="answer [W1]"), use_memory=True)
    app.state.runtime_state.runtimes.replace("web_search", WebSearchRuntime(client=httpx.Client(transport=httpx.MockTransport(handler))))
    client = TestClient(app)
    session = create_session(client)
    client.patch("/api/settings/general", json={"web_context_enabled": True})
    client.patch(
        "/api/capability-configs/web_search",
        json={"user_config": {"searxng_base_url": "https://searxng.test", "domain_blocklist": "blocked.test"}},
    )

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "latest kept news"})
    assistant = response.json()["messages"][-1]
    web_context = assistant["metadata"]["web_context"]

    assert response.json()["run"]["status"] == "DONE"
    assert web_context["result_count"] == 1
    assert [ref["domain"] for ref in web_context["source_refs"]] == ["kept.test"]
    assert web_context["search_diagnostics"]["filtered_count"] == 1
    assert "blocked.test" not in str(web_context["source_refs"])
