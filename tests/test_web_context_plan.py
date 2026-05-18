import asyncio

import httpx
import pytest

from ai_workbench.core.settings import AppSettings
from ai_workbench.core.utility_llm import UtilityLLMError
from ai_workbench.core.web_context import PageFetchResult, build_web_context, fetch_web_context_page, resolve_web_context_plan, validate_web_context_plan_slots


class FakeWebPlanUtility:
    def __init__(self, payload=None, *, error: Exception | None = None, available: bool = True) -> None:
        self.payload = payload or {}
        self.error = error
        self.available = available
        self.calls: list[str] = []

    def status(self, settings):
        return {"available": self.available}

    async def extract_web_context_plan_json(self, text: str, settings):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.payload


@pytest.mark.parametrize(
    ("settings", "expected_reason"),
    [
        (AppSettings(web_context_enabled=False), "web_context_disabled"),
        (AppSettings(web_context_enabled=True), None),
    ],
)
def test_web_context_plan_disabled_and_forced(settings, expected_reason) -> None:
    plan = asyncio.run(async_resolve(settings=settings, text="latest alpha status", eligible=True, intent={"enabled": False}))

    if expected_reason:
        assert plan.should_search is False
        assert plan.skipped_reason == expected_reason
    else:
        assert plan.should_search is True
        assert plan.query == "latest alpha status"
        assert plan.query_source == "raw_user_text_forced"


def test_web_context_plan_shadow_ignores_shadow_prediction() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="shadow")
    plan = asyncio.run(
        async_resolve(
            settings=settings,
            text="hello",
            intent={"enabled": True, "mode": "shadow", "predicted_intent": "knowledge_query", "executed": True},
        )
    )

    assert plan.should_search is True
    assert plan.query == "hello"
    assert plan.query_source == "raw_user_text_forced_shadow_mode"


def test_web_context_plan_auto_skips_selected_knowledge_and_pet() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")

    knowledge = asyncio.run(async_resolve(settings=settings, intent={"enabled": True, "mode": "auto", "predicted_intent": "knowledge_query", "executed": True}))
    pet = asyncio.run(async_resolve(settings=settings, intent={"enabled": True, "mode": "auto", "predicted_intent": "pet_command", "would_execute": True}))

    assert knowledge.skipped_reason == "knowledge_query_selected"
    assert pet.skipped_reason == "pet_command_selected"


def test_web_context_plan_blocks_unexecuted_knowledge_query_candidate_without_resolver() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")
    utility = FakeWebPlanUtility({"should_search": True, "query": "Star Wars Cal Kestis", "reason": "external_fact_question", "confidence": "high"})

    plan = asyncio.run(
        async_resolve(
            settings=settings,
            text="根据现有的 Star Wars 知识库回答 Cal Kestis 的经历",
            intent={
                "enabled": True,
                "mode": "auto",
                "predicted_intent": "knowledge_query",
                "utility_ok": True,
                "slots": {"intent": "knowledge_query", "query": "Cal Kestis 的经历"},
                "not_executed_reason": "semantic_confidence_too_low",
                "warnings": ["semantic_confidence_too_low"],
                "auto_executable": False,
                "executed": False,
                "would_execute": False,
            },
            utility=utility,
        )
    )

    assert plan.should_search is False
    assert plan.skipped_reason == "knowledge_query_candidate_blocked"
    assert plan.warnings == ["knowledge_query_below_threshold"]
    assert plan.intent_influence == "knowledge_query:semantic_confidence_too_low"
    assert utility.calls == []


def test_web_context_plan_auto_uses_web_query_slots_and_original_text() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")

    slots = asyncio.run(
        async_resolve(
            settings=settings,
            text="search latest OpenAI",
            intent={"enabled": True, "mode": "auto", "predicted_intent": "web_query", "validation_ok": True, "slots": {"query": "OpenAI latest"}},
        )
    )
    original = asyncio.run(
        async_resolve(
            settings=settings,
            text="search latest OpenAI",
            intent={"enabled": True, "mode": "auto", "predicted_intent": "web_query", "validation_ok": True, "slots": {"use_original_query": True}},
        )
    )

    assert slots.query == "OpenAI latest"
    assert slots.query_source == "intent_web_query_slots"
    assert original.query == "search latest OpenAI"
    assert original.query_source == "intent_web_query_original_text"


def test_web_context_plan_auto_chat_uses_resolver_true_and_false_examples() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")
    fortnite_text = "帮我搜一下堡垒之夜最新的联动内容，我现在特别想知道，我好久没有玩堡垒之夜了，堡垒之夜确实是一个很好玩的游戏，不过我很久没有打了，还是有一点想玩"
    gold_text = "我最近有点不想搞这个了，昨天刚出门买了一点花，昨天晚上又买了一点猫粮，准备喂给家里的小猫吃。不过今天早上的金价波动也太大了，金价的最新消息一出来我就绷不住了。不过还是小猫好，小猫会一直呆在我身边"

    search = asyncio.run(
        async_resolve(
            settings=settings,
            text=fortnite_text,
            utility=FakeWebPlanUtility({"should_search": True, "query": "堡垒之夜 最新 联动 内容", "reason": "explicit_search_request", "confidence": "high"}),
        )
    )
    skip = asyncio.run(
        async_resolve(
            settings=settings,
            text=gold_text,
            utility=FakeWebPlanUtility({"should_search": False, "query": "", "reason": "incidental_mentions_only", "confidence": "high"}),
        )
    )

    assert search.should_search is True
    assert search.query == "堡垒之夜 最新 联动 内容"
    assert search.query != fortnite_text
    assert search.query_source == "web_context_plan_resolver"
    assert skip.should_search is False
    assert skip.skipped_reason == "incidental_mentions_only"


def test_web_context_plan_time_sensitive_fact_question_searches() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")

    plan = asyncio.run(
        async_resolve(
            settings=settings,
            text="你知道昨天晚上的流星雨吗",
            utility=FakeWebPlanUtility({"should_search": True, "query": "昨天晚上 流星雨", "reason": "time_sensitive_fact_question", "confidence": "high"}),
        )
    )

    assert plan.should_search is True
    assert plan.resolver_used is True
    assert plan.resolver_reason == "time_sensitive_fact_question"
    assert "流星雨" in (plan.query or "")


def test_web_context_plan_personal_preference_and_continuation_skip() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")

    food = asyncio.run(
        async_resolve(
            settings=settings,
            text="我不是很喜欢吃西湖醋鱼",
            utility=FakeWebPlanUtility({"should_search": False, "query": "", "reason": "personal_preference_or_emotion", "confidence": "high"}),
        )
    )
    continuation = asyncio.run(
        async_resolve(
            settings=settings,
            text="我没想到，原来你是这样的人啊！",
            utility=FakeWebPlanUtility({"should_search": False, "query": "", "reason": "conversation_continuation", "confidence": "high"}),
        )
    )

    assert food.should_search is False
    assert food.skipped_reason == "personal_preference_or_emotion"
    assert continuation.should_search is False
    assert continuation.skipped_reason == "conversation_continuation"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"should_search": True, "query": "", "reason": "explicit_search_request", "confidence": "high"}, "web_context_plan_slots_failed"),
        ({"should_search": True, "query": "OpenAI latest", "reason": "explicit_search_request", "confidence": "low"}, "web_context_plan_low_confidence"),
        ({"should_search": True, "query": "x" * 161, "reason": "explicit_search_request", "confidence": "high"}, "web_context_plan_query_too_long"),
        ({"should_search": False, "query": "ignored", "reason": "personal_preference_or_emotion", "confidence": "high"}, "personal_preference_or_emotion"),
        ({"should_search": True, "query": "OpenAI latest", "reason": "unknown", "confidence": "high"}, "web_context_plan_slots_failed"),
    ],
)
def test_web_context_plan_validator_failures(payload, reason) -> None:
    plan = validate_web_context_plan_slots(payload)

    assert plan.should_search is False
    assert plan.skipped_reason == reason


def test_web_context_plan_utility_unavailable() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")
    plan = asyncio.run(async_resolve(settings=settings, utility=FakeWebPlanUtility(available=False)))

    assert plan.should_search is False
    assert plan.skipped_reason == "web_context_plan_utility_unavailable"
    assert "web_context_plan_utility_unavailable" in plan.warnings


def test_web_context_plan_invalid_json_error_is_compact_warning() -> None:
    settings = AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto")
    utility = FakeWebPlanUtility(error=UtilityLLMError("utility_llm_invalid_json", "bad json"))

    plan = asyncio.run(async_resolve(settings=settings, utility=utility))

    assert plan.should_search is False
    assert plan.skipped_reason == "web_context_plan_invalid_json"
    assert plan.warnings == ["web_context_plan_invalid_json"]


def test_web_context_page_fetching_disabled_does_not_fetch_pages() -> None:
    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://example.com/a")]}

    def fail_fetch(**kwargs):
        raise AssertionError("page fetch should not run when disabled")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=False),
            query="latest alpha",
            search_fn=search,
            page_fetch_fn=fail_fetch,
        )
    )

    assert result.metadata["injected"] is True
    assert "Page excerpt:" not in result.rendered_text
    assert "page_fetch_enabled" not in result.metadata


def test_web_context_page_fetching_fetches_top_final_results_only() -> None:
    calls: list[str] = []

    def search(query, context=None):
        return {
            "provider": "searxng",
            "results": [
                web_result("https://kept.test/one", title="One"),
                web_result("https://kept.test/two", title="Two"),
                web_result("https://kept.test/three", title="Three"),
            ],
        }

    def fetch(url, **kwargs):
        calls.append(url)
        return PageFetchResult(status="fetched", title=f"Fetched {len(calls)}", excerpt=f"Extracted page text {len(calls)}.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_fetch_max_pages=2),
            query="latest alpha",
            search_fn=search,
            page_fetch_fn=fetch,
        )
    )

    refs = result.metadata["source_refs"]
    assert calls == ["https://kept.test/one", "https://kept.test/two"]
    assert "Page excerpt: Extracted page text 1." in result.rendered_text
    assert refs[0]["page_fetch_status"] == "fetched"
    assert refs[1]["page_fetch_status"] == "fetched"
    assert refs[2]["page_fetch_status"] == "skipped"
    assert result.metadata["pages_attempted"] == 2
    assert result.metadata["pages_fetched"] == 2


def test_web_context_page_fetch_non_html_falls_back_to_snippet() -> None:
    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://example.com/data.json", snippet="Snippet fallback.")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="unsupported", warning="page_fetch_unsupported_content_type")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True),
            query="latest alpha",
            search_fn=search,
            page_fetch_fn=fetch,
        )
    )

    ref = result.metadata["source_refs"][0]
    assert "Snippet: Snippet fallback." in result.rendered_text
    assert "Page excerpt:" not in result.rendered_text
    assert ref["page_fetch_status"] == "unsupported"
    assert ref["page_fetch_warning"] == "page_fetch_unsupported_content_type"


def test_web_context_page_fetch_timeout_and_http_failure_continue() -> None:
    outcomes = [
        PageFetchResult(status="timeout", warning="page_fetch_timeout"),
        PageFetchResult(status="failed", warning="page_fetch_http_500"),
    ]

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://example.com/a"), web_result("https://example.com/b")]}

    def fetch(url, **kwargs):
        return outcomes.pop(0)

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True),
            query="latest alpha",
            search_fn=search,
            page_fetch_fn=fetch,
        )
    )

    assert result.metadata["injected"] is True
    assert result.metadata["pages_failed"] == 2
    assert result.metadata["source_refs"][0]["page_fetch_status"] == "timeout"
    assert result.metadata["source_refs"][1]["page_fetch_status"] == "failed"
    assert "Page excerpt:" not in result.rendered_text


def test_web_context_page_fetch_all_failed_still_injects_snippets() -> None:
    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://example.com/a", snippet="Snippet survives.")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="failed", warning="page_fetch_failed")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True),
            query="latest alpha",
            search_fn=search,
            page_fetch_fn=fetch,
        )
    )

    assert result.metadata["injected"] is True
    assert "Snippet: Snippet survives." in result.rendered_text
    assert result.metadata["source_refs"][0]["page_fetch_status"] == "failed"


def test_web_context_metadata_keeps_page_fetch_compact() -> None:
    long_excerpt = "E" * 1500

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://example.com/a")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="fetched", title="Page", excerpt=long_excerpt)

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True),
            query="latest alpha",
            search_fn=search,
            page_fetch_fn=fetch,
        )
    )

    ref = result.metadata["source_refs"][0]
    assert ref["page_excerpt_chars"] == 1500
    assert len(ref["page_excerpt_preview"]) == 700
    assert long_excerpt not in str(result.metadata)
    assert "<html" not in str(result.metadata).lower()
    assert "# Retrieved Web" not in str(result.metadata)


def test_fetch_web_context_page_html_extraction_removes_scripts_and_limits_bytes() -> None:
    html = (
        b"<html><head><title>Actual title</title><meta name='description' content='Description text.'></head>"
        b"<body><script>secret()</script><style>.x{}</style><p>Visible first paragraph.</p>"
        + b"A" * 500
        + b"</body></html>"
    )
    client = mock_client(lambda request: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=html, request=request))

    page = fetch_web_context_page(
        url="https://example.com/page",
        timeout_seconds=5,
        max_bytes=220,
        excerpt_chars=1000,
        client=client,
    )

    assert page.status == "fetched"
    assert page.title == "Actual title"
    assert "Description text." in page.excerpt
    assert "Visible first paragraph." in page.excerpt
    assert "secret()" not in page.excerpt
    assert len(page.excerpt) < 260


def test_fetch_web_context_page_blocks_private_literal_ip() -> None:
    page = fetch_web_context_page(url="http://127.0.0.1/private", timeout_seconds=5, max_bytes=100000, excerpt_chars=500)

    assert page.status == "blocked"
    assert page.warning == "page_fetch_blocked_private_ip"


def test_fetch_web_context_page_reports_non_html_timeout_and_status() -> None:
    non_html = mock_client(lambda request: httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request))
    forbidden = mock_client(lambda request: httpx.Response(403, headers={"content-type": "text/html"}, content=b"no", request=request))

    def timeout_handler(request):
        raise httpx.TimeoutException("slow", request=request)

    timeout = mock_client(timeout_handler)

    assert fetch_web_context_page(url="https://example.com/data", timeout_seconds=5, max_bytes=100000, excerpt_chars=500, client=non_html).status == "unsupported"
    assert fetch_web_context_page(url="https://example.com/nope", timeout_seconds=5, max_bytes=100000, excerpt_chars=500, client=forbidden).warning == "page_fetch_http_403"
    assert fetch_web_context_page(url="https://example.com/slow", timeout_seconds=1, max_bytes=100000, excerpt_chars=500, client=timeout).status == "timeout"


async def async_resolve(settings: AppSettings, text: str = "hello", eligible: bool = True, intent=None, utility=None):
    return await resolve_web_context_plan(
        settings=settings,
        current_user_text=text,
        eligible=eligible,
        intent_routing=intent or {"enabled": True, "mode": "auto", "predicted_intent": "chat"},
        utility_llm_service=utility or FakeWebPlanUtility({"should_search": False, "query": "", "reason": "conversation_continuation", "confidence": "high"}),
    )


def web_result(url: str, *, title: str = "Alpha", snippet: str = "Alpha snippet.") -> dict:
    parsed = httpx.URL(url)
    return {
        "rank": 1,
        "title": title,
        "url": url,
        "domain": parsed.host or "example.com",
        "snippet": snippet,
        "published_at": None,
        "source": "searxng",
    }


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
