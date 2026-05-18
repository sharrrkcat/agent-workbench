from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ai_workbench.core.config_schema import resolve_config
from ai_workbench.core.settings import AppSettings, DEFAULT_WEB_CONTEXT_PROMPT
from ai_workbench.core.utility_llm import UtilityLLMError, extract_json_object


MAX_METADATA_QUERY_CHARS = 240
MAX_PLAN_QUERY_CHARS = 160
MAX_SOURCE_SNIPPET_PREVIEW_CHARS = 700
WEB_SEARCH_CAPABILITY_ID = "web_search"
PLAN_REASONS = {
    "explicit_search_request",
    "external_fact_question",
    "time_sensitive_fact_question",
    "incidental_mentions_only",
    "personal_preference_or_emotion",
    "conversation_continuation",
    "insufficient_external_fact_request",
}
PLAN_CONFIDENCES = {"low", "medium", "high"}
KNOWLEDGE_QUERY_BLOCKED_REASONS = {
    "semantic_confidence_too_low",
    "semantic_margin_too_low",
    "validation_failed",
    "no_kb_candidate_or_active_kbs",
    "kb_hint_semantic_conflict",
    "ambiguous_kb_candidate",
}


@dataclass
class WebContextResult:
    rendered_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebContextPlan:
    should_search: bool
    query: str | None = None
    query_source: str | None = None
    skipped_reason: str | None = None
    provider: str | None = None
    warnings: list[str] = field(default_factory=list)
    resolver_used: bool = False
    resolver_reason: str | None = None
    resolver_confidence: str | None = None
    intent_influence: str | None = None

    def compact_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "should_search": self.should_search,
            "query_source": self.query_source,
            "skipped_reason": self.skipped_reason,
            "provider": self.provider,
            "warnings": list(self.warnings),
            "resolver": {
                "used": self.resolver_used,
                "reason": self.resolver_reason,
                "confidence": self.resolver_confidence,
            },
            "intent_influence": self.intent_influence,
        }
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


class WebContextPlanResolver:
    async def resolve(
        self,
        *,
        settings: AppSettings,
        current_user_text: str,
        eligible: bool,
        intent_routing: dict[str, Any] | None = None,
        utility_llm_service: Any = None,
    ) -> WebContextPlan:
        text = str(current_user_text or "").strip()
        if not eligible:
            return WebContextPlan(False, skipped_reason="ineligible_route")
        if not bool(getattr(settings, "web_context_enabled", False)):
            return WebContextPlan(False, skipped_reason="web_context_disabled")
        if not text:
            return WebContextPlan(False, skipped_reason="empty_query", warnings=["Web context skipped: empty query."])

        intent = intent_routing if isinstance(intent_routing, dict) else {}
        if not bool(intent.get("enabled")):
            return WebContextPlan(True, query=text, query_source="raw_user_text_forced", provider="searxng")
        mode = str(intent.get("mode") or getattr(settings, "intent_routing_mode", "shadow") or "shadow")
        if mode == "shadow":
            return WebContextPlan(True, query=text, query_source="raw_user_text_forced_shadow_mode", provider="searxng")
        if mode != "auto":
            return WebContextPlan(True, query=text, query_source="raw_user_text_forced", provider="searxng")

        intent_id = str(intent.get("predicted_intent") or "")
        if intent_id == "pet_command" and _intent_selected(intent):
            return WebContextPlan(False, skipped_reason="pet_command_selected", intent_influence="pet_command")
        if intent_id == "knowledge_query" and (
            _intent_selected(intent)
            or bool(intent.get("temporary_knowledge_base_ids"))
            or bool(intent.get("knowledge_query_override"))
        ):
            return WebContextPlan(False, skipped_reason="knowledge_query_selected", intent_influence="knowledge_query")
        if _knowledge_query_candidate_blocked(intent):
            reason = str(intent.get("not_executed_reason") or intent.get("diagnostic_reason") or "")
            warnings = ["knowledge_query_below_threshold"] if reason in {"semantic_confidence_too_low", "semantic_margin_too_low"} else []
            return WebContextPlan(
                False,
                skipped_reason="knowledge_query_candidate_blocked",
                warnings=warnings,
                intent_influence=_intent_summary(intent),
            )
        if intent_id == "web_query" and bool(intent.get("validation_ok")):
            slots = intent.get("slots") if isinstance(intent.get("slots"), dict) else {}
            slot_query = _valid_query_or_none(slots.get("query"))
            if slot_query:
                return WebContextPlan(
                    True,
                    query=slot_query,
                    query_source="intent_web_query_slots",
                    provider="searxng",
                    intent_influence="web_query",
                )
            if slots.get("use_original_query") is True:
                return WebContextPlan(
                    True,
                    query=text,
                    query_source="intent_web_query_original_text",
                    provider="searxng",
                    intent_influence="web_query",
                )

        return await self._resolve_with_utility(
            settings=settings,
            current_user_text=text,
            utility_llm_service=utility_llm_service,
            intent_routing=intent,
        )

    async def _resolve_with_utility(
        self,
        *,
        settings: AppSettings,
        current_user_text: str,
        utility_llm_service: Any,
        intent_routing: dict[str, Any],
    ) -> WebContextPlan:
        if utility_llm_service is None:
            return WebContextPlan(
                False,
                skipped_reason="web_context_plan_utility_unavailable",
                warnings=["web_context_plan_utility_unavailable"],
                resolver_used=True,
                intent_influence=_intent_summary(intent_routing),
            )
        status = getattr(utility_llm_service, "status", None)
        if callable(status):
            try:
                if not bool(status(settings).get("available")):
                    return WebContextPlan(
                        False,
                        skipped_reason="web_context_plan_utility_unavailable",
                        warnings=["web_context_plan_utility_unavailable"],
                        resolver_used=True,
                        intent_influence=_intent_summary(intent_routing),
                    )
            except Exception:
                return WebContextPlan(
                    False,
                    skipped_reason="web_context_plan_utility_unavailable",
                    warnings=["web_context_plan_utility_unavailable"],
                    resolver_used=True,
                    intent_influence=_intent_summary(intent_routing),
                )
        try:
            if callable(getattr(utility_llm_service, "extract_web_context_plan_json", None)):
                data = await utility_llm_service.extract_web_context_plan_json(current_user_text, settings)
            else:
                raw = await utility_llm_service.generate(_web_context_plan_prompt(current_user_text), settings, max_new_tokens=192)
                data = extract_json_object(getattr(raw, "text", raw))
        except UtilityLLMError as exc:
            code = "web_context_plan_invalid_json" if exc.code == "utility_llm_invalid_json" else "web_context_plan_slots_failed"
            return WebContextPlan(
                False,
                skipped_reason=code,
                warnings=[code],
                resolver_used=True,
                intent_influence=_intent_summary(intent_routing),
            )
        except Exception:
            return WebContextPlan(
                False,
                skipped_reason="web_context_plan_invalid_json",
                warnings=["web_context_plan_invalid_json"],
                resolver_used=True,
                intent_influence=_intent_summary(intent_routing),
            )
        return validate_web_context_plan_slots(data, intent_summary=_intent_summary(intent_routing))


async def resolve_web_context_plan(
    *,
    settings: AppSettings,
    current_user_text: str,
    eligible: bool,
    intent_routing: dict[str, Any] | None = None,
    utility_llm_service: Any = None,
) -> WebContextPlan:
    return await WebContextPlanResolver().resolve(
        settings=settings,
        current_user_text=current_user_text,
        eligible=eligible,
        intent_routing=intent_routing,
        utility_llm_service=utility_llm_service,
    )


def validate_web_context_plan_slots(data: dict[str, Any], *, intent_summary: str | None = None) -> WebContextPlan:
    if not isinstance(data, dict):
        return WebContextPlan(False, skipped_reason="web_context_plan_slots_failed", warnings=["web_context_plan_slots_failed"], resolver_used=True, intent_influence=intent_summary)
    reason = str(data.get("reason") or "").strip()
    confidence = str(data.get("confidence") or "").strip()
    if reason not in PLAN_REASONS or confidence not in PLAN_CONFIDENCES or not isinstance(data.get("should_search"), bool):
        return WebContextPlan(False, skipped_reason="web_context_plan_slots_failed", warnings=["web_context_plan_slots_failed"], resolver_used=True, intent_influence=intent_summary)
    should_search = bool(data.get("should_search"))
    query = str(data.get("query") or "").strip()
    warnings: list[str] = []
    if should_search:
        if not query:
            return WebContextPlan(False, skipped_reason="web_context_plan_slots_failed", warnings=["web_context_plan_slots_failed"], resolver_used=True, resolver_reason=reason, resolver_confidence=confidence, intent_influence=intent_summary)
        if confidence == "low":
            return WebContextPlan(False, skipped_reason="web_context_plan_low_confidence", warnings=["web_context_plan_low_confidence"], resolver_used=True, resolver_reason=reason, resolver_confidence=confidence, intent_influence=intent_summary)
        if len(query) > MAX_PLAN_QUERY_CHARS:
            return WebContextPlan(False, skipped_reason="web_context_plan_query_too_long", warnings=["web_context_plan_query_too_long"], resolver_used=True, resolver_reason=reason, resolver_confidence=confidence, intent_influence=intent_summary)
        return WebContextPlan(True, query=query, query_source="web_context_plan_resolver", provider="searxng", warnings=warnings, resolver_used=True, resolver_reason=reason, resolver_confidence=confidence, intent_influence=intent_summary)
    if query:
        warnings.append("web_context_plan_false_query_ignored")
    return WebContextPlan(False, skipped_reason=reason, warnings=warnings, resolver_used=True, resolver_reason=reason, resolver_confidence=confidence, intent_influence=intent_summary)


def skipped_web_context(*, settings: AppSettings, query: str, reason: str) -> WebContextResult:
    plan = WebContextPlan(False, skipped_reason=reason)
    return WebContextResult(
        metadata=_metadata(
            enabled=bool(getattr(settings, "web_context_enabled", False)),
            attempted=False,
            injected=False,
            query=None,
            skipped_reason=reason,
            plan=plan,
        )
    )


async def build_web_context(
    *,
    app_settings_store: Any = None,
    settings: AppSettings | None = None,
    query: str,
    eligible: bool = True,
    intent_routing: dict[str, Any] | None = None,
    utility_llm_service: Any = None,
    runtime_registry: Any = None,
    capability_registry: Any = None,
    capability_config_store: Any = None,
    search_fn: Callable[..., dict[str, Any]] | None = None,
) -> WebContextResult:
    try:
        resolved_settings = settings or (app_settings_store.get() if app_settings_store is not None else AppSettings())
    except Exception as exc:
        warning = f"Web context settings unavailable: {exc}"
        return WebContextResult(
            metadata=_metadata(enabled=False, attempted=False, injected=False, query=None, skipped_reason="settings_error", warnings=[warning]),
            warnings=[warning],
        )

    plan = await resolve_web_context_plan(
        settings=resolved_settings,
        current_user_text=query,
        eligible=eligible,
        intent_routing=intent_routing,
        utility_llm_service=utility_llm_service,
    )
    if not plan.should_search:
        return WebContextResult(
            metadata=_metadata(
                enabled=bool(getattr(resolved_settings, "web_context_enabled", False)),
                attempted=False,
                injected=False,
                query=None,
                skipped_reason=plan.skipped_reason,
                warnings=plan.warnings,
                plan=plan,
            ),
            warnings=list(plan.warnings),
        )

    query_text = str(plan.query or "").strip()
    metadata_base = _metadata(
        enabled=True,
        attempted=True,
        injected=False,
        query=query_text,
        provider="searxng",
        plan=plan,
    )
    try:
        config = _web_search_config(
            capability_registry=capability_registry,
            capability_config_store=capability_config_store,
        )
        max_results = max(1, min(int(getattr(resolved_settings, "web_context_max_results", 5) or 5), int(config.get("max_results", 8) or 8)))
        config["max_results"] = max_results
        search = search_fn or _search_from_runtime(runtime_registry)
        response = search(query_text, context={"capability_config": config})
    except Exception as exc:
        warning = f"Web search failed: {exc}"
        return WebContextResult(
            metadata={**metadata_base, "result_count": 0, "warnings": [warning], "skipped_reason": "search_failed"},
            warnings=[warning],
        )

    results = [item for item in (response.get("results") if isinstance(response, dict) else []) or [] if isinstance(item, dict)]
    provider = str(response.get("provider") or "searxng") if isinstance(response, dict) else "searxng"
    warnings = [str(item) for item in response.get("warnings", [])] if isinstance(response, dict) and isinstance(response.get("warnings"), list) else []
    source_refs = [_source_ref(item, index) for index, item in enumerate(results, start=1)]
    if not results:
        no_results_warning = "No web results."
        return WebContextResult(
            metadata={**metadata_base, "provider": provider, "result_count": 0, "source_refs": [], "warnings": [*warnings, no_results_warning], "skipped_reason": "no_results"},
            warnings=[*warnings, no_results_warning],
        )

    rendered_text, injected_refs, truncated = _render_web_block(
        results=results,
        source_refs=source_refs,
        instruction=str(getattr(resolved_settings, "web_context_prompt", DEFAULT_WEB_CONTEXT_PROMPT) or DEFAULT_WEB_CONTEXT_PROMPT),
        budget_chars=int(getattr(resolved_settings, "web_context_context_budget_chars", 4000) or 4000),
    )
    if not rendered_text:
        warning = "Web context skipped: context budget exhausted."
        return WebContextResult(
            metadata={**metadata_base, "provider": provider, "result_count": len(results), "source_refs": [], "warnings": [*warnings, warning], "skipped_reason": "context_budget_exhausted"},
            warnings=[*warnings, warning],
        )
    if truncated:
        warnings = [*warnings, "Web context truncated by context budget."]
    return WebContextResult(
        rendered_text=rendered_text,
        metadata={
            **metadata_base,
            "provider": provider,
            "result_count": len(injected_refs),
            "source_refs": injected_refs,
            "injected": True,
            "truncated": truncated,
            "warnings": warnings,
        },
        warnings=warnings,
    )


def append_web_context_to_system(messages: list[dict[str, Any]], rendered_text: str) -> list[dict[str, Any]]:
    if not rendered_text:
        return messages
    next_messages = [dict(message) for message in messages]
    for index, message in enumerate(next_messages):
        if message.get("role") == "system":
            content = str(message.get("content") or "")
            next_messages[index] = {**message, "content": f"{content.rstrip()}\n\n{rendered_text}" if content.strip() else rendered_text}
            return next_messages
    return [{"role": "system", "content": rendered_text}, *next_messages]


def web_context_step_metadata(web_context: dict[str, Any]) -> dict[str, Any]:
    allowed = {"enabled", "attempted", "injected", "provider", "result_count", "warnings", "skipped_reason", "truncated", "query", "query_source", "resolver", "intent_influence"}
    return {key: value for key, value in (web_context or {}).items() if key in allowed}


def web_context_plan_step_metadata(web_context: dict[str, Any]) -> dict[str, Any]:
    allowed = {"enabled", "warnings", "skipped_reason", "query", "query_source", "resolver", "intent_influence"}
    return {key: value for key, value in (web_context or {}).items() if key in allowed}


def should_show_web_context_plan_step(web_context: dict[str, Any]) -> bool:
    if not isinstance(web_context, dict):
        return False
    if web_context.get("enabled") is not True:
        return False
    resolver = web_context.get("resolver") if isinstance(web_context.get("resolver"), dict) else {}
    return bool(
        web_context.get("attempted")
        or web_context.get("query_source")
        or web_context.get("skipped_reason") in {"knowledge_query_selected", "knowledge_query_candidate_blocked", "pet_command_selected"}
        or resolver.get("used")
    )


def web_context_plan_step_message(web_context: dict[str, Any]) -> str:
    if not isinstance(web_context, dict):
        return "skipped"
    source = str(web_context.get("query_source") or "")
    skipped = str(web_context.get("skipped_reason") or "")
    resolver = web_context.get("resolver") if isinstance(web_context.get("resolver"), dict) else {}
    resolver_reason = str(resolver.get("reason") or "")
    resolver_confidence = str(resolver.get("confidence") or "")
    if web_context.get("injected") or web_context.get("attempted"):
        parts = [f"source: {source or 'resolver'}"]
        if resolver_reason:
            parts.append(f"reason: {resolver_reason}")
        if resolver_confidence:
            parts.append(f"confidence: {resolver_confidence}")
        return " / ".join(parts)
    parts = [f"skipped: {skipped or 'not_used'}"]
    if source:
        parts.append(f"source: {source}")
    if resolver_reason:
        parts.append(f"reason: {resolver_reason}")
    if resolver_confidence:
        parts.append(f"confidence: {resolver_confidence}")
    return " / ".join(parts)


def _web_search_config(*, capability_registry: Any, capability_config_store: Any) -> dict[str, Any]:
    if capability_registry is None or capability_config_store is None:
        return {}
    capability = capability_registry.get(WEB_SEARCH_CAPABILITY_ID)
    stored = capability_config_store.get_config(WEB_SEARCH_CAPABILITY_ID)
    return resolve_config(capability.config_schema, dict(stored.get("user_config") or {}))


def _search_from_runtime(runtime_registry: Any) -> Callable[..., dict[str, Any]]:
    if runtime_registry is None:
        raise RuntimeError("Web Search runtime is unavailable.")
    runtime = runtime_registry.get_runtime(WEB_SEARCH_CAPABILITY_ID)
    search = getattr(runtime, "search_results", None)
    if not callable(search):
        raise RuntimeError("Web Search runtime does not support search_results.")
    return search


def _render_web_block(*, results: list[dict[str, Any]], source_refs: list[dict[str, Any]], instruction: str, budget_chars: int) -> tuple[str, list[dict[str, Any]], bool]:
    prompt = str(instruction or DEFAULT_WEB_CONTEXT_PROMPT).strip() or DEFAULT_WEB_CONTEXT_PROMPT
    header = f"# Retrieved Web\n\n{prompt}"
    parts = [header]
    injected_refs: list[dict[str, Any]] = []
    total_chars = len(header)
    truncated = False
    for result, ref in zip(results, source_refs):
        block = _render_result(result, str(ref["ref_id"]))
        available = budget_chars - total_chars - 2
        if available <= 0:
            truncated = True
            break
        if len(block) > available:
            block = block[: max(0, available - 15)].rstrip() + "\n[truncated]"
            truncated = True
        parts.append(block)
        injected_refs.append(ref)
        total_chars += len(block) + 2
        if truncated:
            break
    return ("\n\n".join(parts) if injected_refs else ""), injected_refs, truncated


def _render_result(result: dict[str, Any], ref_id: str) -> str:
    lines = [f"[{ref_id}] {str(result.get('title') or '(untitled)').strip()}"]
    lines.append(f"Domain: {str(result.get('domain') or '').strip()}")
    lines.append(f"URL: {str(result.get('url') or '').strip()}")
    published_at = str(result.get("published_at") or "").strip()
    if published_at:
        lines.append(f"Published: {published_at}")
    snippet = str(result.get("snippet") or "").strip()
    if snippet:
        lines.append(f"Snippet: {snippet}")
    return "\n".join(lines)


def _source_ref(result: dict[str, Any], index: int) -> dict[str, Any]:
    ref = {
        "ref_id": f"W{index}",
        "rank": int(result.get("rank") or index),
        "title": str(result.get("title") or ""),
        "url": str(result.get("url") or ""),
        "domain": str(result.get("domain") or ""),
        "published_at": result.get("published_at") or None,
        "source": str(result.get("source") or ""),
    }
    snippet_preview = _short_snippet(result.get("snippet"))
    if snippet_preview:
        ref["snippet_preview"] = snippet_preview
    return ref


def _short_snippet(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= MAX_SOURCE_SNIPPET_PREVIEW_CHARS:
        return text
    return text[: MAX_SOURCE_SNIPPET_PREVIEW_CHARS - 3].rstrip() + "..."


def _metadata(
    *,
    enabled: bool,
    attempted: bool,
    injected: bool,
    query: str | None,
    provider: str | None = None,
    skipped_reason: str | None = None,
    warnings: list[str] | None = None,
    plan: WebContextPlan | None = None,
) -> dict[str, Any]:
    raw_query = str(query or "").strip()
    metadata: dict[str, Any] = {
        "enabled": enabled,
        "attempted": attempted,
        "injected": injected,
        "query": _short_query(raw_query) if raw_query else None,
        "query_truncated": len(raw_query) > MAX_METADATA_QUERY_CHARS,
        "query_source": plan.query_source if plan else None,
        "result_count": 0,
        "warnings": list(warnings or []),
    }
    if plan is not None:
        metadata["plan"] = plan.compact_dict()
        metadata["resolver"] = {"used": plan.resolver_used, "reason": plan.resolver_reason, "confidence": plan.resolver_confidence}
        if plan.intent_influence:
            metadata["intent_influence"] = plan.intent_influence
    if provider:
        metadata["provider"] = provider
    if skipped_reason:
        metadata["skipped_reason"] = skipped_reason
    return {key: value for key, value in metadata.items() if value is not None}


def _short_query(query: str) -> str:
    text = str(query or "").strip()
    if len(text) <= MAX_METADATA_QUERY_CHARS:
        return text
    keep = (MAX_METADATA_QUERY_CHARS - 3) // 2
    return f"{text[:keep]}...{text[-keep:]}"


def _valid_query_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > MAX_PLAN_QUERY_CHARS:
        return None
    return text


def _intent_selected(intent: dict[str, Any]) -> bool:
    return bool(intent.get("executed") or intent.get("would_execute") or intent.get("auto_executable"))


def _knowledge_query_candidate_blocked(intent: dict[str, Any]) -> bool:
    if str(intent.get("predicted_intent") or "") != "knowledge_query":
        return False
    if _intent_selected(intent):
        return False
    if not bool(intent.get("utility_ok")):
        return False
    slots = intent.get("slots") if isinstance(intent.get("slots"), dict) else {}
    if slots.get("intent") != "knowledge_query":
        return False
    has_query = bool(str(slots.get("query") or "").strip()) or slots.get("use_original_query") is True
    if not has_query:
        return False
    reason = str(intent.get("not_executed_reason") or intent.get("diagnostic_reason") or "")
    return reason in KNOWLEDGE_QUERY_BLOCKED_REASONS


def _intent_summary(intent: dict[str, Any]) -> str | None:
    if not intent:
        return None
    intent_id = str(intent.get("predicted_intent") or "chat")
    reason = str(intent.get("not_executed_reason") or intent.get("diagnostic_reason") or "")
    if reason:
        return f"{intent_id}:{reason}"
    return intent_id


def _web_context_plan_prompt(user_text: str) -> str:
    schema = {
        "should_search": "boolean",
        "query": "string",
        "reason": sorted(PLAN_REASONS),
        "confidence": ["low", "medium", "high"],
    }
    examples = [
        {
            "user": "帮我搜一下堡垒之夜最新的联动内容，我现在特别想知道，我好久没有玩堡垒之夜了，堡垒之夜确实是一个很好玩的游戏，不过我很久没有打了，还是有一点想玩",
            "json": {"should_search": True, "query": "堡垒之夜 最新 联动 内容", "reason": "explicit_search_request", "confidence": "high"},
        },
        {
            "user": "你知道昨天晚上的流星雨吗",
            "json": {"should_search": True, "query": "昨天晚上 流星雨", "reason": "time_sensitive_fact_question", "confidence": "high"},
        },
        {
            "user": "我最近有点不想搞这个了，昨天刚出门买了一点花，昨天晚上又买了一点猫粮，准备喂给家里的小猫吃。不过今天早上的金价波动也太大了，金价的最新消息一出来我就绷不住了。不过还是小猫好，小猫会一直呆在我身边",
            "json": {"should_search": False, "query": "", "reason": "incidental_mentions_only", "confidence": "high"},
        },
        {
            "user": "我不是很喜欢吃西湖醋鱼",
            "json": {"should_search": False, "query": "", "reason": "personal_preference_or_emotion", "confidence": "high"},
        },
        {
            "user": "我没想到，原来你是这样的人啊！",
            "json": {"should_search": False, "query": "", "reason": "conversation_continuation", "confidence": "high"},
        },
    ]
    return (
        "Decide whether this single user message should trigger internal Web Context search.\n"
        "Return strict JSON only. Do not explain.\n"
        f"Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        "Search only when the user requests external facts, current/recent information, news, prices, releases, official information, current status, real-world events, or verification that needs the web.\n"
        "Treat 'do you know / have you heard / did you see' plus yesterday/today/recently and a real-world event as a likely time-sensitive external fact question.\n"
        "When the user explicitly asks to search/check/look up, asks for latest/current status, or asks about a recent collaboration/release, extract a compact query.\n"
        "Do not search when the user is only expressing emotions/preferences, roleplaying, continuing conversation, acknowledging, or incidentally mentioning real entities without asking for information.\n"
        "Long messages can contain either explicit search requests or incidental mentions. Keywords alone are not enough; decide whether the user is asking for information.\n"
        "If should_search=true, query must be the smallest useful search query, not the whole message, and at most 160 characters.\n"
        f"Examples: {json.dumps(examples, ensure_ascii=False)}\n\n"
        f"User message:\n{user_text}"
    )
