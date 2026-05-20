import asyncio

import httpx
import pytest

from ai_workbench.core.settings import AppSettings
from ai_workbench.core.utility_llm import UtilityLLMError
from ai_workbench.core.web_context import PageFetchResult, build_web_context, clean_web_page_html, extract_html_page_text, fetch_web_context_page, resolve_web_context_plan, run_page_excerpt_gate, validate_page_excerpt_gate_response, validate_web_context_plan_slots


class FakeWebPlanUtility:
    def __init__(
        self,
        payload=None,
        *,
        error: Exception | None = None,
        available: bool = True,
        judge_payload=None,
        judge_error: Exception | None = None,
        gate_payloads=None,
        gate_error: Exception | None = None,
    ) -> None:
        self.payload = payload or {}
        self.error = error
        self.available = available
        self.calls: list[str] = []
        self.judge_payload = judge_payload
        self.judge_error = judge_error
        self.judge_calls: list[dict] = []
        self.gate_payloads = list(gate_payloads or [])
        self.gate_error = gate_error
        self.gate_prompts: list[str] = []

    def status(self, settings):
        return {"available": self.available}

    async def extract_web_context_plan_json(self, text: str, settings):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.payload

    async def extract_web_candidate_judgements_json(self, **kwargs):
        self.judge_calls.append(kwargs)
        if self.judge_error:
            raise self.judge_error
        return self.judge_payload or {"rejected_items": []}

    async def extract_page_excerpt_gate_json(self, *, prompt: str, settings):
        self.gate_prompts.append(prompt)
        if self.gate_error:
            raise self.gate_error
        return self.gate_payloads.pop(0) if self.gate_payloads else gate_payload(True, need_more=False)

    async def generate_with_model_profile(self, prompt: str, *, profile_id: str, max_new_tokens: int = 256):
        self.gate_prompts.append(f"profile={profile_id}\n{prompt}")
        if self.gate_error:
            raise self.gate_error
        payload = self.gate_payloads.pop(0) if self.gate_payloads else gate_payload(True, need_more=False)
        text = payload if isinstance(payload, str) else __import__("json").dumps(payload)
        return type("Raw", (), {"text": text})()


class FakeGateRuntime:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": self.text}}]}


class PromptCapturingUtility:
    def __init__(self, payload=None) -> None:
        self.payload = payload or {}
        self.prompts: list[str] = []

    def status(self, settings):
        return {"available": True}

    async def generate(self, prompt, settings, max_new_tokens=128):
        self.prompts.append(prompt)
        text = __import__("json").dumps(self.payload)
        return type("Raw", (), {"text": text})()


def gate_payload(
    use_excerpt: bool,
    *,
    quality: str = "high",
    confidence: str = "high",
    coverage: str = "direct_answer",
    need_more: bool = True,
    reason: str = "useful evidence",
) -> dict:
    return {
        "use_excerpt": use_excerpt,
        "evidence_quality": quality,
        "confidence": confidence,
        "coverage": coverage,
        "need_more": need_more,
        "reason": reason,
    }


def gate_json(**overrides) -> str:
    use_excerpt = bool(overrides.pop("use_excerpt", True))
    need_more = bool(overrides.pop("need_more", False))
    payload = gate_payload(use_excerpt, need_more=need_more, **overrides)
    return __import__("json").dumps(payload)


def fenced_gate_json(**overrides) -> str:
    return f"```json\n{gate_json(**overrides)}\n```"


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


def test_web_context_plan_resolver_uses_custom_prompt_and_current_time() -> None:
    utility = PromptCapturingUtility(
        {
            "should_search": True,
            "query": "latest release",
            "reason": "time_sensitive_fact_question",
            "confidence": "high",
        }
    )
    plan = asyncio.run(
        async_resolve(
            settings=AppSettings(web_context_enabled=True, intent_routing_enabled=True, intent_routing_mode="auto", web_context_plan_resolver_prompt="CUSTOM PLAN BODY"),
            text="what is the latest release?",
            intent={"enabled": True, "mode": "auto", "predicted_intent": "chat"},
            utility=utility,
        )
    )

    assert plan.should_search is True
    prompt = utility.prompts[0]
    assert "CUSTOM PLAN BODY" in prompt
    assert "Current local time:" in prompt
    assert "Current UTC time:" in prompt
    assert "Schema:" in prompt
    assert "should_search" in prompt


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


def test_web_context_candidate_judge_disabled_keeps_round8_behavior() -> None:
    utility = FakeWebPlanUtility(judge_payload={"rejected_items": []})

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://example.com/a"), web_result("https://example.com/b")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=False),
            query="latest alpha",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert [ref["ref_id"] for ref in result.metadata["source_refs"]] == ["W1", "W2"]
    assert utility.judge_calls == []
    assert result.metadata["candidate_judge"]["enabled"] is False


def test_web_context_injection_uses_custom_prompt_and_current_time_without_metadata_prompt() -> None:
    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://source.test", snippet="fresh source")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_prompt="CUSTOM INJECTION BODY"),
            query="latest source",
            search_fn=search,
        )
    )

    assert "# Retrieved Web" in result.rendered_text
    assert "CUSTOM INJECTION BODY" in result.rendered_text
    assert "Current local time:" in result.rendered_text
    assert "Current UTC time:" in result.rendered_text
    assert "CUSTOM INJECTION BODY" not in str(result.metadata)
    assert "Current local time:" not in str(result.metadata)


def test_web_context_candidate_judge_receives_compact_candidates_and_rejects_only_noise() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={
            "rejected_items": [
                {"candidate_id": "C2", "relevance": "low", "confidence": "high", "source_role": "weak_match", "reason": "generic"},
            ]
        }
    )

    def search(query, context=None):
        return {
            "provider": "searxng",
            "results": [
                web_result("https://ref.test/wiki", title="Reference result", snippet="Explains the character background."),
                web_result("https://weak.test/list", title="Generic list", snippet="Broadly related links."),
                web_result("https://news.test/story", title="News result", snippet="Reports the latest collaboration."),
            ],
        }

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="latest collaboration news",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    call = utility.judge_calls[0]
    assert "latest collaboration news" in call["user_text"]
    assert [item["candidate_id"] for item in call["candidates"]] == ["C1", "C2", "C3"]
    assert "page_excerpt" not in str(call["candidates"])
    assert "Agent prompt" not in str(call["candidates"])
    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["ref.test", "news.test"]
    assert result.metadata["source_refs"][0]["candidate_judge_state"] == "unjudged"
    assert result.metadata["source_refs"][1]["candidate_judge_state"] == "unjudged"
    assert result.metadata["candidate_judge"]["schema"] == "rejected_items_v1"
    assert result.metadata["candidate_judge"]["mode"] == "conservative_reject_only"
    assert result.metadata["candidate_judge"]["retained_count"] == 2
    assert result.metadata["candidate_judge"]["rejected_count"] == 1


def test_web_context_candidate_judge_uses_custom_prompt_with_fixed_schema_and_time() -> None:
    utility = PromptCapturingUtility({"rejected_items": []})

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://candidate.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True, web_context_candidate_judge_prompt="CUSTOM JUDGE BODY"),
            query="latest candidate",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    prompt = utility.prompts[0]
    assert result.metadata["candidate_judge"]["schema"] == "rejected_items_v1"
    assert "CUSTOM JUDGE BODY" in prompt
    assert "Current local time:" in prompt
    assert "Current UTC time:" in prompt
    assert "rejected_items_v1" in prompt
    assert "use_source" in prompt
    assert "raw JSON only" in prompt


def test_web_context_candidate_judge_keeps_low_confidence_and_medium_relevance_rejects() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={
            "rejected_items": [
                {"candidate_id": "C1", "relevance": "low", "confidence": "medium", "source_role": "weak_match", "reason": "not confident enough"},
                {"candidate_id": "C2", "relevance": "medium", "confidence": "high", "source_role": "weak_match", "reason": "medium relevance"},
                {"candidate_id": "C3", "relevance": "high", "confidence": "high", "source_role": "news", "reason": "also"},
            ]
        }
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://a.test"), web_result("https://b.test"), web_result("https://c.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(
                web_context_enabled=True,
                web_context_candidate_judge_enabled=True,
                web_context_candidate_judge_min_relevance="high",
            ),
            query="buy product info",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["a.test", "b.test", "c.test"]
    assert result.metadata["candidate_judge"]["retained_count"] == 3
    assert result.metadata["candidate_judge"]["rejected_count"] == 0


def test_web_context_max_results_caps_final_sources_without_candidate_judge_max_selected() -> None:
    seen_config: dict = {}
    utility = FakeWebPlanUtility(judge_payload={"rejected_items": []})

    def search(query, context=None):
        seen_config.update((context or {}).get("capability_config") or {})
        return {"provider": "searxng", "results": [web_result("https://one.test"), web_result("https://two.test"), web_result("https://three.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_max_results=2, web_context_candidate_judge_enabled=True, web_context_candidate_judge_max_candidates=3),
            query="latest news",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert seen_config["max_results"] == 3
    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["one.test", "two.test"]
    assert result.metadata["candidate_judge"]["retained_count"] == 3


def test_web_context_candidate_judge_all_rejected_skips_web_injection() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={"rejected_items": [{"candidate_id": "C1", "relevance": "low", "confidence": "high", "source_role": "off_topic", "reason": "not evidence"}]}
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://noise.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="fictional character background",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert result.rendered_text == ""
    assert result.metadata["injected"] is False
    assert result.metadata["skipped_reason"] == "web_candidate_judge_rejected_all"
    assert result.metadata["source_refs"] == []


@pytest.mark.parametrize("error,warning", [(UtilityLLMError("utility_llm_invalid_json", "bad"), "web_candidate_judge_invalid_json"), (RuntimeError("offline"), "web_candidate_judge_unavailable")])
def test_web_context_candidate_judge_failure_falls_back(error, warning) -> None:
    utility = FakeWebPlanUtility(judge_error=error)

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://fallback.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="latest news",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert result.metadata["injected"] is True
    assert result.metadata["source_refs"][0]["domain"] == "fallback.test"
    assert result.metadata["candidate_judge"]["fallback_used"] is True
    assert warning in result.metadata["candidate_judge"]["warnings"]


def test_web_context_candidate_judge_unavailable_falls_back() -> None:
    utility = FakeWebPlanUtility(available=False)

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://fallback.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="latest news",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert utility.judge_calls == []
    assert result.metadata["source_refs"][0]["domain"] == "fallback.test"
    assert "web_candidate_judge_unavailable" in result.metadata["candidate_judge"]["warnings"]


def test_web_context_candidate_judge_unknown_and_missing_candidates_are_compact_warnings() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={
            "rejected_items": [
                {"candidate_id": "C99", "relevance": "low", "confidence": "high", "source_role": "off_topic", "reason": "unknown"},
            ]
        }
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://kept.test"), web_result("https://missing.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="who is Mark Grayson",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["kept.test", "missing.test"]
    assert result.metadata["source_refs"][0]["candidate_judge_state"] == "unjudged"
    assert result.metadata["source_refs"][1]["candidate_judge_state"] == "unjudged"
    assert result.metadata["candidate_judge"]["unjudged_count"] == 2
    assert "web_candidate_judge_unknown_candidate_id" in result.metadata["candidate_judge"]["warnings"]
    assert "web_candidate_judge_missing_candidate" in result.metadata["candidate_judge"]["warnings"]
    assert "missing.test" not in str(result.metadata["candidate_judge"])


def test_web_context_candidate_judge_invalid_item_and_unknown_slots_retain_candidates() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={
            "rejected_items": [
                "not an object",
                {"candidate_id": "C1", "relevance": "unknown", "confidence": "high", "source_role": "weak_match", "reason": "bad relevance"},
                {"candidate_id": "C2", "relevance": "low", "confidence": "medium", "source_role": "unknown", "reason": "bad role"},
                {"candidate_id": "C3", "relevance": "low", "confidence": "unknown", "source_role": "weak_match", "reason": "bad confidence"},
            ]
        }
    )

    def search(query, context=None):
        return {
            "provider": "searxng",
            "results": [
                web_result("https://a.test"),
                web_result("https://b.test"),
                web_result("https://c.test"),
            ],
        }

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="latest official info",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["a.test", "b.test", "c.test"]
    judge = result.metadata["candidate_judge"]
    assert judge["retained_count"] == 3
    assert judge["rejected_count"] == 0
    assert judge["invalid_item_count"] == 4
    assert "web_candidate_judge_slots_failed" in judge["warnings"]
    assert "web_candidate_judge_unknown_relevance" in judge["warnings"]
    assert "web_candidate_judge_unknown_role" in judge["warnings"]
    assert "web_candidate_judge_unknown_confidence" in judge["warnings"]


def test_web_context_candidate_judge_empty_reason_and_reference_role_retain_candidates() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={
            "rejected_items": [
                {"candidate_id": "C1", "relevance": "low", "confidence": "high", "source_role": "weak_match", "reason": ""},
                {"candidate_id": "C2", "relevance": "low", "confidence": "high", "source_role": "official", "reason": "official source"},
                {"candidate_id": "C3", "relevance": "low", "confidence": "high", "source_role": "noise", "reason": "x" * 220},
            ]
        }
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://empty.test"), web_result("https://official.test"), web_result("https://noise.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="latest official info",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["empty.test", "official.test"]
    assert result.metadata["source_refs"][0]["candidate_judge_state"] == "retained"
    assert result.metadata["source_refs"][1]["candidate_judge_state"] == "retained"
    judge = result.metadata["candidate_judge"]
    assert judge["rejected_count"] == 1
    assert judge["invalid_item_count"] == 1
    assert "web_candidate_judge_empty_reason" in judge["warnings"]
    assert "web_candidate_judge_retain_role_conflict" in judge["warnings"]


def test_web_context_candidate_judge_old_items_schema_falls_back_without_positive_selection() -> None:
    utility = FakeWebPlanUtility(
        judge_payload={
            "items": [
                {"candidate_id": "C1", "use_source": True, "relevance": "high", "confidence": "high", "source_role": "reference", "reason": "positive selection"},
            ]
        }
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://one.test"), web_result("https://two.test")]}

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True),
            query="latest news",
            search_fn=search,
            utility_llm_service=utility,
        )
    )

    assert [ref["domain"] for ref in result.metadata["source_refs"]] == ["one.test", "two.test"]
    judge = result.metadata["candidate_judge"]
    assert judge["fallback_used"] is True
    assert "web_candidate_judge_slots_failed" in judge["warnings"]


def test_web_context_page_fetching_fetches_retained_candidates_after_reject_only_judge() -> None:
    calls: list[str] = []
    utility = FakeWebPlanUtility(
        judge_payload={
            "rejected_items": [
                {"candidate_id": "C1", "relevance": "low", "confidence": "high", "source_role": "weak_match", "reason": "weak"},
            ]
        }
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://skip.test"), web_result("https://fetch.test")]}

    def fetch(url, **kwargs):
        calls.append(url)
        return PageFetchResult(status="fetched", excerpt="Selected page text.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True, web_context_fetch_pages_enabled=True, web_context_fetch_max_pages=2),
            query="latest official info",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )

    assert calls == ["https://fetch.test"]
    assert result.metadata["source_refs"][0]["domain"] == "fetch.test"


def test_web_context_page_fetching_fetches_unjudged_retained_candidates() -> None:
    calls: list[str] = []
    utility = FakeWebPlanUtility(judge_payload={"rejected_items": []})

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://judged.test"), web_result("https://unjudged.test")]}

    def fetch(url, **kwargs):
        calls.append(url)
        return PageFetchResult(status="fetched", excerpt=f"Fetched {url}.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_candidate_judge_enabled=True, web_context_fetch_pages_enabled=True, web_context_fetch_max_pages=2),
            query="latest official info",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )

    assert calls == ["https://judged.test", "https://unjudged.test"]
    assert result.metadata["source_refs"][0]["candidate_judge_state"] == "unjudged"
    assert result.metadata["source_refs"][1]["candidate_judge_state"] == "unjudged"
    assert result.metadata["candidate_judge"]["unjudged_count"] == 2


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


def test_page_excerpt_gate_rejects_first_and_progressively_accepts_until_enough() -> None:
    calls: list[str] = []
    utility = FakeWebPlanUtility(
        gate_payloads=[
            gate_payload(False, quality="low", confidence="high", coverage="boilerplate", reason="navigation only"),
            gate_payload(True, quality="medium", confidence="high", coverage="partial", need_more=True, reason="partial facts"),
            gate_payload(True, quality="high", confidence="high", coverage="direct_answer", need_more=False, reason="direct answer"),
        ]
    )

    def search(query, context=None):
        return {
            "provider": "searxng",
            "results": [
                web_result("https://one.test", title="One"),
                web_result("https://two.test", title="Two"),
                web_result("https://three.test", title="Three"),
                web_result("https://four.test", title="Four"),
            ],
        }

    def fetch(url, **kwargs):
        calls.append(url)
        return PageFetchResult(status="fetched", title=f"Page {len(calls)}", excerpt=f"Useful page excerpt {len(calls)}.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(
                web_context_enabled=True,
                web_context_fetch_pages_enabled=True,
                web_context_page_excerpt_gate_enabled=True,
                web_context_page_excerpt_gate_backend="utility_llm",
                web_context_fetch_max_pages=5,
                web_context_target_page_excerpts=3,
            ),
            query="release date",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )

    refs = result.metadata["source_refs"]
    assert calls == ["https://one.test", "https://two.test", "https://three.test"]
    assert "Useful page excerpt 1." not in result.rendered_text
    assert "Useful page excerpt 2." in result.rendered_text
    assert "Useful page excerpt 3." in result.rendered_text
    assert refs[0]["page_excerpt_gate_status"] == "rejected"
    assert refs[0]["page_excerpt_injected"] is False
    assert refs[0]["page_excerpt_preview"] == "Useful page excerpt 1."
    assert refs[1]["page_excerpt_gate_status"] == "accepted"
    assert refs[2]["page_excerpt_gate_status"] == "accepted"
    assert refs[3]["page_fetch_status"] == "skipped"
    assert result.metadata["page_excerpt_gate"]["attempted"] == 3
    assert result.metadata["page_excerpt_gate"]["accepted"] == 2
    assert result.metadata["page_excerpt_gate"]["rejected"] == 1
    assert result.metadata["page_excerpt_gate"]["stopped_reason"] == "enough_evidence"


def test_page_excerpt_gate_stops_at_target_and_max_attempts() -> None:
    calls: list[str] = []
    utility = FakeWebPlanUtility(gate_payloads=[gate_payload(True, need_more=True), gate_payload(True, need_more=True)])

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://a.test"), web_result("https://b.test"), web_result("https://c.test")]}

    def fetch(url, **kwargs):
        calls.append(url)
        return PageFetchResult(status="fetched", excerpt=f"Accepted {url}.")

    target = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="utility_llm", web_context_target_page_excerpts=1, web_context_fetch_max_pages=3),
            query="latest",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )
    assert calls == ["https://a.test"]
    assert target.metadata["page_excerpt_gate"]["stopped_reason"] == "target_accepted_excerpts"

    calls.clear()
    utility = FakeWebPlanUtility(gate_payloads=[gate_payload(False), gate_payload(False)])
    maxed = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="utility_llm", web_context_fetch_max_pages=2),
            query="latest",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )
    assert calls == ["https://a.test", "https://b.test"]
    assert maxed.metadata["page_excerpt_gate"]["accepted"] == 0
    assert maxed.metadata["page_excerpt_gate"]["stopped_reason"] == "max_pages_attempted"


@pytest.mark.parametrize(
    ("payload", "warning"),
    [
        ({"not": "valid"}, "page_excerpt_gate_schema_invalid"),
        (gate_payload(True, confidence="low"), None),
        (gate_payload(True, quality="low"), None),
        (gate_payload(True, coverage="boilerplate"), None),
        (gate_payload(True, coverage="off_topic"), None),
        (gate_payload(True, coverage="insufficient"), None),
        (gate_payload(True, quality="high", confidence="high", coverage="direct_answer"), None),
    ],
)
def test_page_excerpt_gate_validation_acceptance_rules(payload, warning) -> None:
    result, actual_warning = validate_page_excerpt_gate_response(payload, min_quality="medium")
    if warning:
        assert result is None
        assert actual_warning == warning
        return
    assert result is not None
    should_accept = payload["confidence"] != "low" and payload["evidence_quality"] != "low" and payload["coverage"] == "direct_answer"
    assert (result.use_excerpt and result.confidence in {"medium", "high"} and result.evidence_quality in {"medium", "high"} and result.coverage == "direct_answer") is should_accept


@pytest.mark.parametrize(
    "raw",
    [
        gate_json(),
        f"```json\n{gate_json()}\n```",
        f"```\n{gate_json()}\n```",
    ],
)
def test_page_excerpt_gate_accepts_bare_and_fenced_json(raw) -> None:
    runtime = FakeGateRuntime(raw)

    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Direct evidence.",
            accepted_evidence=[],
            llm_runtime=runtime,
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "accepted"
    assert gate["accepted"] is True
    assert runtime.calls[0]["stream"] is False


@pytest.mark.parametrize(
    ("settings", "utility", "llm_runtime", "llm_model_config"),
    [
        (
            AppSettings(web_context_page_excerpt_gate_backend="utility_llm"),
            FakeWebPlanUtility(gate_payloads=[fenced_gate_json()]),
            None,
            None,
        ),
        (
            AppSettings(web_context_page_excerpt_gate_backend="specific_model_profile", web_context_page_excerpt_gate_model_profile_id="profile-a"),
            FakeWebPlanUtility(gate_payloads=[fenced_gate_json()]),
            None,
            None,
        ),
        (
            AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            None,
            FakeGateRuntime(fenced_gate_json()),
            {"model": "test"},
        ),
    ],
)
def test_page_excerpt_gate_all_backends_accept_fenced_json(settings, utility, llm_runtime, llm_model_config) -> None:
    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=settings,
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Direct evidence.",
            accepted_evidence=[],
            utility_llm_service=utility,
            llm_runtime=llm_runtime,
            llm_model_config=llm_model_config,
        )
    )

    assert gate["status"] == "accepted"
    assert gate["accepted"] is True


def test_page_excerpt_gate_accepts_wrapped_balanced_json() -> None:
    raw = f"Here is the JSON:\n{gate_json(quality='medium', confidence='medium', coverage='partial', need_more=True)}"

    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Partial evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(raw),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "accepted"
    assert gate["accepted"] is True


def test_page_excerpt_gate_repairs_unescaped_newlines_inside_reason_string() -> None:
    raw = (
        "```json\n"
        '{"use_excerpt":true,"evidence_quality":"high","confidence":"high","coverage":"direct_answer",'
        '"need_more":false,"reason":"Line one\nLine two"}'
        "\n```"
    )

    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Direct evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(raw),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "accepted"
    assert gate["accepted"] is True
    assert gate["parse_warning"] == "page_excerpt_gate_repaired_json_string_controls"
    assert gate["result"].reason == "Line one Line two"


def test_page_excerpt_gate_repairs_bullet_like_lines_inside_reason_string_as_rejected() -> None:
    raw = (
        "```json\n"
        '{"use_excerpt":false,"evidence_quality":"low","confidence":"high","coverage":"off_topic",'
        '"need_more":true,"reason":"Mostly navigation\n- Related links\n- Footer"}'
        "\n```"
    )

    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Noisy evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(raw),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "rejected"
    assert gate["accepted"] is False
    assert gate["parse_warning"] == "page_excerpt_gate_repaired_json_string_controls"
    assert "warning" not in gate


def test_page_excerpt_gate_repair_does_not_touch_structural_control_chars() -> None:
    raw = (
        "```json\n"
        "{\n"
        '"use_excerpt":true,\n'
        '"evidence_quality":"high",\n'
        '"confidence":"high",\n'
        '"coverage":"direct_answer",\n'
        '"need_more":false,\n'
        '"reason":"Direct evidence."\n'
        "}\n"
        "```"
    )

    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Direct evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(raw),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "accepted"
    assert "parse_warning" not in gate


def test_page_excerpt_gate_invalid_after_repair_is_failed() -> None:
    raw = (
        "```json\n"
        '{"use_excerpt":true,"evidence_quality":"high","confidence":"high","coverage":"direct_answer",'
        '"need_more":false,"reason":"Line one\nLine two",}'
        "\n```"
    )

    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Direct evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(raw),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "failed"
    assert gate["warning"] == "page_excerpt_gate_invalid_json"


def test_page_excerpt_gate_repair_warning_is_compact_summary_metadata() -> None:
    raw = (
        '{"use_excerpt":true,"evidence_quality":"high","confidence":"high","coverage":"direct_answer",'
        '"need_more":false,"reason":"Line one\nLine two"}'
    )

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://repair.test", snippet="Search summary.")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="fetched", excerpt="Direct evidence.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            query="latest",
            search_fn=search,
            page_fetch_fn=fetch,
            llm_runtime=FakeGateRuntime(raw),
            llm_model_config={"model": "test"},
        )
    )

    ref = result.metadata["source_refs"][0]
    assert ref["page_excerpt_gate_status"] == "accepted"
    assert "page_excerpt_gate_warning" not in ref
    assert "page_excerpt_gate_repaired_json_string_controls" in result.metadata["page_excerpt_gate"]["warnings"]
    assert "Line one" not in str(result.metadata["page_excerpt_gate"])


def test_page_excerpt_gate_prompt_limits_reason_format() -> None:
    utility = FakeWebPlanUtility(gate_payloads=[gate_payload(True, need_more=False)])

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://prompt.test")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="fetched", excerpt="Direct evidence.")

    asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="utility_llm", web_context_page_excerpt_gate_prompt="CUSTOM GATE BODY"),
            query="latest",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )

    prompt = utility.gate_prompts[0]
    assert "CUSTOM GATE BODY" in prompt
    assert "Current local time:" in prompt
    assert "Current UTC time:" in prompt
    assert "Return raw JSON only" in prompt
    assert "Do not include markdown" in prompt
    assert "Do not explain outside JSON" in prompt
    assert "reason value must be one short sentence" in prompt
    assert "Do not use bullet points" in prompt
    assert "Do not use line breaks in reason" in prompt


@pytest.mark.parametrize(
    ("payload", "expected_warning"),
    [
        ("not json", "page_excerpt_gate_invalid_json"),
        ("```json\n[1]\n```", "page_excerpt_gate_invalid_json"),
        ('{"use_excerpt":true,"evidence_quality":"high","confidence":"high","coverage":"direct_answer","need_more":false}', "page_excerpt_gate_schema_invalid"),
        (gate_json(quality="extreme"), "page_excerpt_gate_unknown_quality"),
        (gate_json(confidence="certain"), "page_excerpt_gate_unknown_confidence"),
        (gate_json(coverage="exact"), "page_excerpt_gate_unknown_coverage"),
        (gate_json(reason=""), "page_excerpt_gate_empty_reason"),
    ],
)
def test_page_excerpt_gate_invalid_json_or_schema_is_failed(payload, expected_warning) -> None:
    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Direct evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(payload),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "failed"
    assert gate["accepted"] is False
    assert gate["warning"] == expected_warning


@pytest.mark.parametrize(
    "payload",
    [
        gate_payload(False, quality="low", confidence="low", coverage="off_topic"),
        gate_payload(True, confidence="low"),
        gate_payload(True, quality="low"),
        gate_payload(True, coverage="boilerplate"),
        gate_payload(True, coverage="off_topic"),
        gate_payload(True, coverage="insufficient"),
    ],
)
def test_page_excerpt_gate_valid_non_accepted_json_is_rejected(payload) -> None:
    gate = asyncio.run(
        run_page_excerpt_gate(
            settings=AppSettings(web_context_page_excerpt_gate_backend="follow_agent_model_profile"),
            original_user_text="latest alpha",
            plan=asyncio.run(async_resolve(settings=AppSettings(web_context_enabled=True), text="latest alpha")),
            candidate=web_result("https://gate.test"),
            ref={"ref_id": "W1", "title": "Gate", "domain": "gate.test"},
            page_title="Gate page",
            page_excerpt="Noisy evidence.",
            accepted_evidence=[],
            llm_runtime=FakeGateRuntime(__import__("json").dumps(payload)),
            llm_model_config={"model": "test"},
        )
    )

    assert gate["status"] == "rejected"
    assert gate["accepted"] is False
    assert "warning" not in gate


def test_page_excerpt_gate_long_reason_is_truncated_without_failure() -> None:
    result, warning = validate_page_excerpt_gate_response(gate_payload(True, reason="x" * 400), min_quality="medium")

    assert warning is None
    assert result is not None
    assert len(result.reason) == 200
    assert result.reason.endswith("...")


def test_page_excerpt_gate_invalid_or_unavailable_does_not_inject_and_continues() -> None:
    calls: list[str] = []
    utility = FakeWebPlanUtility(gate_payloads=[{"bad": "schema"}, gate_payload(True, coverage="direct_answer", need_more=False)])

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://bad.test"), web_result("https://good.test")]}

    def fetch(url, **kwargs):
        calls.append(url)
        return PageFetchResult(status="fetched", excerpt=f"Excerpt from {url}.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="utility_llm"),
            query="latest",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )
    assert calls == ["https://bad.test", "https://good.test"]
    assert "Excerpt from https://bad.test." not in result.rendered_text
    assert "Excerpt from https://good.test." in result.rendered_text
    assert result.metadata["source_refs"][0]["page_excerpt_gate_status"] == "failed"
    assert result.metadata["source_refs"][0]["page_excerpt_injected"] is False
    assert result.metadata["source_refs"][0]["page_excerpt_preview"] == "Excerpt from https://bad.test."
    assert result.metadata["source_refs"][0]["page_excerpt_gate_warning"] == "page_excerpt_gate_schema_invalid"
    assert result.metadata["page_excerpt_gate"]["accepted"] == 1
    assert result.metadata["page_excerpt_gate"]["rejected"] == 0
    assert result.metadata["page_excerpt_gate"]["failed"] == 1
    assert "page_excerpt_gate_schema_invalid" in result.metadata["page_excerpt_gate"]["warnings"]


def test_page_excerpt_gate_specific_profile_missing_is_warning_not_run_failure() -> None:
    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://profile.test")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="fetched", excerpt="Useful excerpt that should not inject without profile.")

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(
                web_context_enabled=True,
                web_context_fetch_pages_enabled=True,
                web_context_page_excerpt_gate_enabled=True,
                web_context_page_excerpt_gate_backend="specific_model_profile",
            ),
            query="latest",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=FakeWebPlanUtility(),
        )
    )

    assert result.metadata["injected"] is True
    assert "Useful excerpt" not in result.rendered_text
    assert result.metadata["source_refs"][0]["page_excerpt_gate_status"] == "failed"
    assert "page_excerpt_gate_unavailable" in result.metadata["page_excerpt_gate"]["warnings"]


def test_page_excerpt_gate_input_and_metadata_are_compact() -> None:
    utility = FakeWebPlanUtility(gate_payloads=[gate_payload(True, need_more=False, reason="short reason")])

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://compact.test/path", snippet="Snippet")]}

    def fetch(url, **kwargs):
        return PageFetchResult(status="fetched", title="Page", excerpt="Clean excerpt " + ("E" * 1400))

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="utility_llm"),
            query="question with Agent prompt and KB secret",
            search_fn=search,
            page_fetch_fn=fetch,
            utility_llm_service=utility,
        )
    )
    prompt = utility.gate_prompts[0]
    assert "Agent system prompt" not in prompt
    assert "raw HTML" not in prompt
    assert "# Retrieved Web" not in prompt
    assert "assistant replies" not in prompt
    assert "Clean excerpt " in prompt
    ref = result.metadata["source_refs"][0]
    assert ref["page_excerpt_gate_status"] == "accepted"
    assert ref["page_excerpt_gate_reason"] == "short reason"
    assert len(ref["page_excerpt_preview"]) == 700
    assert "E" * 1000 not in str(result.metadata)
    assert "# Retrieved Web" not in str(result.metadata)


def test_enhanced_cleaning_disabled_uses_basic_extraction() -> None:
    html = "<html><head><title>T</title></head><body><nav>Menu Link</nav><p>Article paragraph with enough detail.</p></body></html>"
    basic = extract_html_page_text(html, excerpt_chars=1000)

    page = fetch_web_context_page(
        url="https://example.com/page",
        timeout_seconds=5,
        max_bytes=100000,
        excerpt_chars=1000,
        cleaning_enabled=False,
        client=mock_client(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html, request=request)),
    )

    assert page.status == "fetched"
    assert page.excerpt == basic["excerpt"]
    assert page.cleaning["page_cleaning_status"] == "skipped"


def test_enhanced_cleaning_removes_structural_and_boilerplate_nodes() -> None:
    html = """
    <html><head><title>Article Title</title><meta name="description" content="Meta summary."></head>
    <body>
      <header>Header navigation</header><nav>Home Products Pricing</nav>
      <main><article>
        <h1>Article Title</h1>
        <p>The useful article paragraph explains the release with enough sentence detail.</p>
        <form><input value="secret"><button>Submit</button></form>
      </article></main>
      <aside>Related links</aside><footer>Copyright 2026 Privacy Terms</footer>
      <script>alert("x")</script><style>.ad{}</style>
    </body></html>
    """

    cleaned = clean_web_page_html(final_url="https://example.com", html=html, basic_extracted=extract_html_page_text(html, excerpt_chars=2000), excerpt_chars=2000)

    assert cleaned.page_title == "Article Title"
    assert "Meta summary." in cleaned.excerpt
    assert "useful article paragraph" in cleaned.excerpt
    assert "Header navigation" not in cleaned.excerpt
    assert "Related links" not in cleaned.excerpt
    assert "Copyright" not in cleaned.excerpt
    assert "alert" not in cleaned.excerpt
    assert cleaned.diagnostics.status == "cleaned"


def test_enhanced_cleaning_removes_generic_attribute_boilerplate() -> None:
    html = """
    <body>
      <main>
        <div class="advertisement promo">Buy now subscribe today</div>
        <div id="related-posts"><a href="/a">Related one</a><a href="/b">Related two</a></div>
        <p>This paragraph is the actual body with factual context and a complete sentence.</p>
        <div role="navigation">Breadcrumb Home > News > Story</div>
      </main>
    </body>
    """

    cleaned = clean_web_page_html(final_url="https://example.com", html=html, basic_extracted=extract_html_page_text(html, excerpt_chars=2000), excerpt_chars=2000)

    assert "actual body" in cleaned.excerpt
    assert "Buy now" not in cleaned.excerpt
    assert "Related one" not in cleaned.excerpt
    assert "Breadcrumb" not in cleaned.excerpt
    assert cleaned.diagnostics.dropped_block_count >= 1


def test_enhanced_cleaning_falls_back_to_body_scoring_without_main() -> None:
    html = """
    <body>
      <div class="sidebar"><a>Nav one</a><a>Nav two</a></div>
      <section class="story-content"><p>Fallback content paragraph includes the relevant release details and enough length.</p></section>
    </body>
    """

    cleaned = clean_web_page_html(final_url="https://example.com", html=html, basic_extracted=extract_html_page_text(html, excerpt_chars=2000), excerpt_chars=2000)

    assert "Fallback content paragraph" in cleaned.excerpt
    assert "Nav one" not in cleaned.excerpt


def test_enhanced_cleaning_preserves_cjk_paragraphs_and_useful_lists() -> None:
    html = """
    <body><main>
      <p>这是一个没有空格的中文段落，说明页面中的核心事实和发布时间，应该被保留下来。</p>
      <h2>Release notes</h2>
      <ul>
        <li>Added offline mode for local sessions.</li>
        <li>Fixed Web Context page excerpt cleaning.</li>
      </ul>
    </main></body>
    """

    cleaned = clean_web_page_html(final_url="https://example.com", html=html, basic_extracted=extract_html_page_text(html, excerpt_chars=2000), excerpt_chars=2000)

    assert "中文段落" in cleaned.excerpt
    assert "Added offline mode" in cleaned.excerpt
    assert "Fixed Web Context" in cleaned.excerpt


def test_enhanced_cleaning_drops_link_dense_navigation_and_dedupes() -> None:
    html = """
    <body><main>
      <ul class="tags"><li><a>Tag one</a></li><li><a>Tag two</a></li><li><a>Tag three</a></li></ul>
      <h1>Story</h1><h1>Story</h1>
      <p>Unique article text with enough sentence detail to remain in the excerpt.</p>
      <p>Unique article text with enough sentence detail to remain in the excerpt.</p>
    </main></body>
    """

    cleaned = clean_web_page_html(final_url="https://example.com", html=html, basic_extracted=extract_html_page_text(html, excerpt_chars=2000), excerpt_chars=2000)

    assert "Tag one" not in cleaned.excerpt
    assert cleaned.excerpt.count("Unique article text") == 1
    assert cleaned.diagnostics.duplicate_block_count >= 1


def test_enhanced_cleaning_falls_back_to_basic_when_cleaned_too_short() -> None:
    html = "<body><main><p>Short.</p></main><footer>Footer contact privacy terms.</footer></body>"
    basic = extract_html_page_text(html, excerpt_chars=1000)

    cleaned = clean_web_page_html(final_url="https://example.com", html=html, basic_extracted=basic, excerpt_chars=1000)

    assert cleaned.diagnostics.status == "fallback_basic"
    assert cleaned.diagnostics.warning == "page_cleaning_fallback_to_basic"
    assert cleaned.excerpt == basic["excerpt"]


def test_page_excerpt_gate_receives_cleaned_excerpt_and_injection_uses_it() -> None:
    utility = FakeWebPlanUtility(gate_payloads=[gate_payload(True, need_more=False)])
    noisy_html = """
    <html><body><nav>Home Login Subscribe</nav>
      <main><p>Clean evidence paragraph has the direct answer and enough detail for the model.</p></main>
      <footer>Copyright Privacy Terms</footer>
    </body></html>
    """

    def search(query, context=None):
        return {"provider": "searxng", "results": [web_result("https://clean.test", snippet="Search summary.")]}

    page = fetch_web_context_page(
        url="https://clean.test",
        timeout_seconds=5,
        max_bytes=100000,
        excerpt_chars=2000,
        client=mock_client(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=noisy_html, request=request)),
    )

    result = asyncio.run(
        build_web_context(
            settings=AppSettings(web_context_enabled=True, web_context_fetch_pages_enabled=True, web_context_page_excerpt_gate_enabled=True, web_context_page_excerpt_gate_backend="utility_llm"),
            query="direct answer",
            search_fn=search,
            page_fetch_fn=lambda **kwargs: page,
            utility_llm_service=utility,
        )
    )

    prompt = utility.gate_prompts[0]
    assert "Clean evidence paragraph" in prompt
    assert "Home Login Subscribe" not in prompt
    assert "Clean evidence paragraph" in result.rendered_text
    assert "Copyright Privacy" not in result.rendered_text
    ref = result.metadata["source_refs"][0]
    assert ref["page_cleaning_status"] == "cleaned"
    assert ref["page_cleaning_cleaned_chars"] > 0


def test_cleaning_failure_records_warning_and_main_run_continues(monkeypatch) -> None:
    def boom(**kwargs):
        raise RuntimeError("cleaner failed")

    monkeypatch.setattr("ai_workbench.core.web_context.clean_web_page_html", boom)
    html = "<body><p>Basic body text is long enough to survive the fallback extractor path.</p></body>"

    page = fetch_web_context_page(
        url="https://example.com",
        timeout_seconds=5,
        max_bytes=100000,
        excerpt_chars=1000,
        client=mock_client(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html, request=request)),
    )

    assert page.status == "fetched"
    assert page.cleaning["page_cleaning_status"] == "failed"
    assert page.cleaning["page_cleaning_warning"] == "page_cleaning_failed"
    assert "Basic body text" in page.excerpt


def test_cleaning_metadata_does_not_store_raw_html_or_dropped_text() -> None:
    html = """
    <body><main>
      <div class="advertisement">SECRET DROPPED AD TEXT</div>
      <p>Clean compact evidence remains in the fetched page excerpt.</p>
    </main></body>
    """

    page = fetch_web_context_page(
        url="https://metadata.test",
        timeout_seconds=5,
        max_bytes=100000,
        excerpt_chars=1000,
        client=mock_client(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html, request=request)),
    )

    metadata = str(page.cleaning)
    assert "SECRET DROPPED AD TEXT" not in metadata
    assert "<body" not in metadata
    assert "Clean compact evidence" not in metadata
    assert page.cleaning["page_cleaning_status"] == "cleaned"


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
