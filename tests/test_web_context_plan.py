import asyncio

import pytest

from ai_workbench.core.settings import AppSettings
from ai_workbench.core.utility_llm import UtilityLLMError
from ai_workbench.core.web_context import resolve_web_context_plan, validate_web_context_plan_slots


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


async def async_resolve(settings: AppSettings, text: str = "hello", eligible: bool = True, intent=None, utility=None):
    return await resolve_web_context_plan(
        settings=settings,
        current_user_text=text,
        eligible=eligible,
        intent_routing=intent or {"enabled": True, "mode": "auto", "predicted_intent": "chat"},
        utility_llm_service=utility or FakeWebPlanUtility({"should_search": False, "query": "", "reason": "conversation_continuation", "confidence": "high"}),
    )
