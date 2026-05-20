from __future__ import annotations

import json
import ipaddress
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ai_workbench.core.config_schema import resolve_config
from ai_workbench.core.settings import AppSettings, DEFAULT_WEB_CONTEXT_PROMPT
from ai_workbench.core.utility_llm import UtilityLLMError, extract_json_object


MAX_METADATA_QUERY_CHARS = 240
MAX_PLAN_QUERY_CHARS = 160
MAX_SOURCE_SNIPPET_PREVIEW_CHARS = 700
MAX_PAGE_EXCERPT_PREVIEW_CHARS = 700
MAX_JUDGE_USER_TEXT_CHARS = 1200
MAX_JUDGE_REASON_CHARS = 160
MIN_USEFUL_PAGE_TEXT_CHARS = 80
WEB_SEARCH_CAPABILITY_ID = "web_search"
HTML_MIME_TYPES = {"text/html", "application/xhtml+xml"}
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
JUDGE_RELEVANCE_ORDER = {"low": 1, "medium": 2, "high": 3}
JUDGE_SOURCE_ROLES = {
    "reference",
    "official",
    "news",
    "documentation",
    "background",
    "primary_source",
    "noise",
    "off_topic",
    "weak_match",
}
JUDGE_CONFIDENCES = {"low", "medium", "high"}
JUDGE_REJECT_ROLES = {"noise", "off_topic", "weak_match"}
JUDGE_RETAIN_ROLES = {"reference", "official", "news", "documentation", "background", "primary_source"}
GATE_BACKENDS = {"follow_agent_model_profile", "specific_model_profile", "utility_llm"}
GATE_QUALITY_ORDER = {"low": 1, "medium": 2, "high": 3}
GATE_CONFIDENCES = {"low", "medium", "high"}
GATE_COVERAGES = {"direct_answer", "supporting_background", "partial", "boilerplate", "off_topic", "insufficient"}
GATE_ACCEPT_COVERAGES = {"direct_answer", "supporting_background", "partial"}
GATE_REASON_CHARS = 200
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


@dataclass
class PageFetchResult:
    status: str
    title: str = ""
    excerpt: str = ""
    warning: str | None = None


@dataclass(frozen=True)
class PageExcerptGateResult:
    use_excerpt: bool
    evidence_quality: str
    confidence: str
    coverage: str
    need_more: bool
    reason: str


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
    llm_runtime: Any = None,
    llm_model_config: dict[str, Any] | None = None,
    search_fn: Callable[..., dict[str, Any]] | None = None,
    page_fetch_fn: Callable[..., PageFetchResult] | None = None,
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
        web_max_results = max(1, min(int(getattr(resolved_settings, "web_context_max_results", 5) or 5), 10))
        capability_max_results = max(1, int(config.get("max_results", 8) or 8))
        judge_candidate_limit = max(1, min(int(getattr(resolved_settings, "web_context_candidate_judge_max_candidates", 8) or 8), 12))
        judge_enabled = bool(getattr(resolved_settings, "web_context_candidate_judge_enabled", False))
        requested_results = max(web_max_results, judge_candidate_limit) if judge_enabled else web_max_results
        final_max_results = min(web_max_results, capability_max_results)
        config["max_results"] = min(requested_results, capability_max_results)
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
    search_diagnostics = _compact_search_diagnostics(response.get("diagnostics") if isinstance(response, dict) else None)
    if not results:
        no_results_warning = "web_results_filtered_empty" if _diagnostics_filtered_any(search_diagnostics) else "No web results."
        skipped_reason = "web_results_filtered_empty" if no_results_warning == "web_results_filtered_empty" else "no_results"
        return WebContextResult(
            metadata={**metadata_base, "provider": provider, "result_count": 0, "source_refs": [], "warnings": [*warnings, no_results_warning], "skipped_reason": skipped_reason, "search_diagnostics": search_diagnostics},
            warnings=[*warnings, no_results_warning],
        )

    judge_summary: dict[str, Any] = _candidate_judge_disabled_summary(results)
    if bool(getattr(resolved_settings, "web_context_candidate_judge_enabled", False)):
        results, judge_summary = await _judge_web_candidates(
            results=results,
            settings=resolved_settings,
            original_user_text=query,
            plan=plan,
            utility_llm_service=utility_llm_service,
        )
        judge_warnings = [str(item) for item in judge_summary.get("warnings", []) if str(item)]
        if judge_warnings:
            warnings = [*warnings, *judge_warnings]
        if not results:
            return WebContextResult(
                metadata={
                    **metadata_base,
                    "provider": provider,
                    "result_count": 0,
                    "source_refs": [],
                    "warnings": warnings,
                    "skipped_reason": "web_candidate_judge_rejected_all",
                    "search_diagnostics": search_diagnostics,
                    "candidate_judge": judge_summary,
                },
                warnings=warnings,
            )

    results = results[:final_max_results]
    judge_summary = _finalize_candidate_judge_summary(judge_summary, final_result_count=len(results))
    source_refs = [_source_ref(item, index) for index, item in enumerate(results, start=1)]

    page_fetch_summary: dict[str, Any] = {}
    if bool(getattr(resolved_settings, "web_context_fetch_pages_enabled", False)):
        results, source_refs, page_fetch_summary = await _fetch_pages_for_results(
            results=results,
            source_refs=source_refs,
            settings=resolved_settings,
            original_user_text=query,
            plan=plan,
            page_fetch_fn=page_fetch_fn,
            utility_llm_service=utility_llm_service,
            llm_runtime=llm_runtime,
            llm_model_config=llm_model_config,
        )
        if page_fetch_summary.get("page_fetch_warnings"):
            warnings = [*warnings, *page_fetch_summary["page_fetch_warnings"]]
        gate_summary = page_fetch_summary.get("page_excerpt_gate") if isinstance(page_fetch_summary.get("page_excerpt_gate"), dict) else {}
        if gate_summary.get("warnings"):
            warnings = [*warnings, *[str(item) for item in gate_summary["warnings"] if str(item)]]

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
            "search_diagnostics": search_diagnostics,
            "candidate_judge": judge_summary,
            **page_fetch_summary,
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
    allowed = {"enabled", "attempted", "injected", "provider", "result_count", "warnings", "skipped_reason", "truncated", "query", "query_source", "resolver", "intent_influence", "search_diagnostics", "candidate_judge", "page_fetch_enabled", "pages_attempted", "pages_fetched", "pages_failed", "page_fetch_warnings", "page_excerpt_gate"}
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
    page_title = str(result.get("page_title") or "").strip()
    result_title = str(result.get("title") or "").strip()
    if page_title and page_title != result_title:
        lines.append(f"Page title: {page_title}")
    page_excerpt = str(result.get("page_excerpt") or "").strip()
    if page_excerpt:
        lines.append(f"Page excerpt: {page_excerpt}")
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
    judge = result.get("_candidate_judge") if isinstance(result.get("_candidate_judge"), dict) else {}
    if judge:
        ref["candidate_judge_state"] = str(judge.get("state") or "retained")
        if judge.get("relevance"):
            ref["candidate_judge_relevance"] = str(judge.get("relevance") or "")
        if judge.get("source_role"):
            ref["candidate_judge_role"] = str(judge.get("source_role") or "")
        if judge.get("confidence"):
            ref["candidate_judge_confidence"] = str(judge.get("confidence") or "")
        reason = str(judge.get("reason") or "").strip()
        if reason:
            ref["candidate_judge_reason"] = reason[:MAX_JUDGE_REASON_CHARS]
    return ref


def _candidate_judge_disabled_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "enabled": False,
        "used": False,
        "mode": "conservative_reject_only",
        "schema": "rejected_items_v1",
        "candidate_count": len(results),
        "retained_count": len(results),
        "rejected_count": 0,
        "unjudged_count": 0,
        "invalid_item_count": 0,
        "fallback_used": False,
        "warnings": [],
    }


def _finalize_candidate_judge_summary(summary: dict[str, Any], *, final_result_count: int) -> dict[str, Any]:
    return summary


async def _judge_web_candidates(
    *,
    results: list[dict[str, Any]],
    settings: AppSettings,
    original_user_text: str,
    plan: WebContextPlan,
    utility_llm_service: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    max_candidates = max(1, min(int(getattr(settings, "web_context_candidate_judge_max_candidates", 8) or 8), 12))
    candidate_results = results[:max_candidates]
    base_summary = {
        "enabled": True,
        "used": False,
        "mode": "conservative_reject_only",
        "schema": "rejected_items_v1",
        "candidate_count": len(results),
        "retained_count": len(results),
        "rejected_count": 0,
        "unjudged_count": 0,
        "invalid_item_count": 0,
        "fallback_used": True,
        "warnings": [],
    }
    warning = _candidate_judge_unavailable_reason(utility_llm_service, settings)
    if warning:
        return results, {**base_summary, "warnings": [warning]}
    candidates = [_judge_candidate_payload(item, index) for index, item in enumerate(candidate_results, start=1)]
    try:
        if callable(getattr(utility_llm_service, "extract_web_candidate_judgements_json", None)):
            data = await utility_llm_service.extract_web_candidate_judgements_json(
                user_text=_short_for_judge(original_user_text),
                query=str(plan.query or ""),
                query_source=str(plan.query_source or ""),
                candidates=candidates,
                settings=settings,
            )
        else:
            raw = await utility_llm_service.generate(
                _web_candidate_judge_prompt(
                    user_text=_short_for_judge(original_user_text),
                    query=str(plan.query or ""),
                    query_source=str(plan.query_source or ""),
                    candidates=candidates,
                ),
                settings,
                max_new_tokens=768,
            )
            data = extract_json_object(getattr(raw, "text", raw))
    except UtilityLLMError as exc:
        code = "web_candidate_judge_invalid_json" if exc.code == "utility_llm_invalid_json" else "web_candidate_judge_unavailable"
        return results, {**base_summary, "warnings": [code]}
    except Exception:
        return results, {**base_summary, "warnings": ["web_candidate_judge_unavailable"]}
    selected, summary = _validate_candidate_judge_response(
        data,
        results=candidate_results,
    )
    if summary.get("fallback_used"):
        return results, summary
    unjudged_tail = [{**item, "_candidate_judge": {"state": "unjudged"}} for item in results[max_candidates:]]
    if unjudged_tail:
        summary = {
            **summary,
            "candidate_count": int(summary.get("candidate_count") or 0) + len(unjudged_tail),
            "retained_count": int(summary.get("retained_count") or 0) + len(unjudged_tail),
            "unjudged_count": int(summary.get("unjudged_count") or 0) + len(unjudged_tail),
        }
    return [*selected, *unjudged_tail], summary


def _candidate_judge_unavailable_reason(utility_llm_service: Any, settings: AppSettings) -> str | None:
    if utility_llm_service is None:
        return "web_candidate_judge_unavailable"
    status = getattr(utility_llm_service, "status", None)
    if not callable(status):
        return None
    try:
        if not bool(status(settings).get("available")):
            return "web_candidate_judge_unavailable"
    except Exception:
        return "web_candidate_judge_unavailable"
    return None


def _validate_candidate_judge_response(
    data: Any,
    *,
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(data, dict) or set(data.keys()) != {"rejected_items"} or not isinstance(data.get("rejected_items"), list):
        return results, {
            "enabled": True,
            "used": False,
            "mode": "conservative_reject_only",
            "schema": "rejected_items_v1",
            "candidate_count": len(results),
            "retained_count": len(results),
            "rejected_count": 0,
            "unjudged_count": 0,
            "invalid_item_count": 0,
            "fallback_used": True,
            "warnings": ["web_candidate_judge_slots_failed"],
        }
    by_id = {f"C{index}": item for index, item in enumerate(results, start=1)}
    warnings: list[str] = []
    judgements: dict[str, dict[str, Any]] = {}
    reason_counts: dict[str, int] = {}
    invalid_item_count = 0
    for raw_item in data.get("rejected_items", []):
        if not isinstance(raw_item, dict):
            invalid_item_count += 1
            warnings.append("web_candidate_judge_slots_failed")
            continue
        candidate_id = str(raw_item.get("candidate_id") or "").strip()
        if candidate_id not in by_id:
            warnings.append("web_candidate_judge_unknown_candidate_id")
            continue
        relevance = str(raw_item.get("relevance") or "").strip().lower()
        source_role = str(raw_item.get("source_role") or "").strip().lower()
        confidence = str(raw_item.get("confidence") or "").strip().lower()
        reason = _short_judge_reason(raw_item.get("reason"))
        item_warnings: list[str] = []
        if relevance not in JUDGE_RELEVANCE_ORDER:
            item_warnings.append("web_candidate_judge_unknown_relevance")
        if source_role not in JUDGE_SOURCE_ROLES:
            item_warnings.append("web_candidate_judge_unknown_role")
        if confidence not in JUDGE_CONFIDENCES:
            item_warnings.append("web_candidate_judge_unknown_confidence")
        if not reason:
            item_warnings.append("web_candidate_judge_empty_reason")
        if item_warnings:
            invalid_item_count += 1
            warnings.extend(item_warnings)
            judgements[candidate_id] = {"state": "retained"}
            continue
        if source_role in JUDGE_RETAIN_ROLES:
            warnings.append("web_candidate_judge_retain_role_conflict")
        if relevance != "low":
            warnings.append("web_candidate_judge_reject_relevance_conflict")
        should_reject = (
            relevance == "low"
            and source_role in JUDGE_REJECT_ROLES
            and confidence == "high"
        )
        state = "rejected" if should_reject else "retained"
        judgements[candidate_id] = {
            "relevance": relevance,
            "source_role": source_role,
            "confidence": confidence,
            "reason": reason,
            "state": state,
        }
        if should_reject:
            reason_counts[source_role] = reason_counts.get(source_role, 0) + 1
    unjudged_ids = [candidate_id for candidate_id in by_id if candidate_id not in judgements]
    if unjudged_ids:
        warnings.append("web_candidate_judge_missing_candidate")
    retained: list[dict[str, Any]] = []
    rejected_count = 0
    for candidate_id, result in by_id.items():
        judge = judgements.get(candidate_id)
        if not judge:
            retained.append({**result, "_candidate_judge": {"state": "unjudged"}})
            continue
        if judge.get("state") == "rejected":
            rejected_count += 1
            continue
        retained.append({**result, "_candidate_judge": judge})
    retained_count = len(retained)
    summary: dict[str, Any] = {
        "enabled": True,
        "used": True,
        "mode": "conservative_reject_only",
        "schema": "rejected_items_v1",
        "candidate_count": len(results),
        "retained_count": retained_count,
        "rejected_count": rejected_count,
        "unjudged_count": len(unjudged_ids),
        "invalid_item_count": invalid_item_count,
        "fallback_used": False,
        "warnings": sorted(set(warnings)),
    }
    if reason_counts:
        summary["rejected_reason_counts"] = reason_counts
    return retained, summary


def _judge_candidate_payload(result: dict[str, Any], index: int) -> dict[str, Any]:
    parsed = urlparse(str(result.get("url") or ""))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?..."
    if len(path) > 96:
        path = path[:93].rstrip("/") + "..."
    return {
        "candidate_id": f"C{index}",
        "rank": int(result.get("rank") or index),
        "title": _short_judge_text(result.get("title"), 180),
        "domain": _short_judge_text(result.get("domain") or parsed.hostname or "", 120),
        "path": path,
        "snippet_preview": _short_judge_text(result.get("snippet"), 420),
        "source": _short_judge_text(result.get("source"), 80),
    }


def _web_candidate_judge_prompt(*, user_text: str, query: str, query_source: str, candidates: list[dict[str, Any]]) -> str:
    schema = {
        "rejected_items": [
            {
                "candidate_id": "C1",
                "relevance": "low",
                "confidence": "high",
                "source_role": "off_topic",
                "reason": "short rejection reason under 160 chars",
            }
        ]
    }
    return (
        "Conservatively reject only clearly unhelpful web search candidates for the current user question.\n"
        "Return strict JSON only. Do not explain outside JSON.\n"
        f"Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        "Use the current question, search query, title, domain, short path, snippet preview, and source label only.\n"
        "Candidates are retained by default. Return only candidates that should be rejected.\n"
        "Omit all candidates that should be retained or are uncertain. The runtime will retain every omitted candidate.\n"
        "Do not list every candidate. Do not output useful candidates.\n"
        "Reject only obvious noise, off-topic candidates, or weak matches that cannot reasonably help answer the question; such items must use relevance=low, confidence=high, and source_role noise/off_topic/weak_match.\n"
        "Do not reject because a candidate only partially matches keywords, lacks exact keyword overlap, or does not fully cover every term.\n"
        "Do not treat any site type as fixed noise. Judge only this question and candidate semantics.\n"
        "Useful candidates can provide the requested object, event, price, version, news, official information, documentation, primary source, background, product, media, social post, image, video, or audio-generation information when relevant to the user request.\n"
        "If the user asks for images, video, buying options, audio generation, social posts, or product info, those page types can be relevant.\n"
        "Never reject solely because the candidate is a product, video, image, social, or generator page.\n\n"
        f"User question:\n{user_text}\n\n"
        f"Web Context query: {query}\n"
        f"Query source: {query_source}\n\n"
        f"Candidates:\n{json.dumps(candidates, ensure_ascii=False)}"
    )


def _short_for_judge(value: Any) -> str:
    return _short_judge_text(value, MAX_JUDGE_USER_TEXT_CHARS)


def _short_judge_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _short_judge_reason(value: Any) -> str:
    return _short_judge_text(value, MAX_JUDGE_REASON_CHARS)


async def _fetch_pages_for_results(
    *,
    results: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    settings: AppSettings,
    original_user_text: str,
    plan: WebContextPlan,
    page_fetch_fn: Callable[..., PageFetchResult] | None,
    utility_llm_service: Any = None,
    llm_runtime: Any = None,
    llm_model_config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    max_pages = max(1, min(int(getattr(settings, "web_context_fetch_max_pages", 6) or 6), 10))
    target_excerpts = max(1, min(int(getattr(settings, "web_context_target_page_excerpts", 2) or 2), 5))
    timeout = max(1.0, min(float(getattr(settings, "web_context_fetch_timeout_seconds", 5) or 5), 20.0))
    max_bytes = max(100000, min(int(getattr(settings, "web_context_fetch_max_bytes", 1048576) or 1048576), 5000000))
    per_page_chars = max(500, min(int(getattr(settings, "web_context_page_excerpt_chars", 2000) or 2000), 8000))
    total_chars = max(1000, min(int(getattr(settings, "web_context_total_page_excerpt_chars", 6000) or 6000), 20000))
    gate_enabled = bool(getattr(settings, "web_context_page_excerpt_gate_enabled", False))
    gate_backend = str(getattr(settings, "web_context_page_excerpt_gate_backend", "follow_agent_model_profile") or "follow_agent_model_profile")
    fetcher = page_fetch_fn or fetch_web_context_page
    next_results = [dict(item) for item in results]
    next_refs = [dict(item) for item in source_refs]
    warnings: list[str] = []
    attempted = 0
    fetched = 0
    failed = 0
    accepted = 0
    rejected = 0
    gate_failed = 0
    stopped_reason = "candidates_exhausted"
    remaining_excerpt_chars = total_chars
    gate_warnings: list[str] = []
    accepted_evidence: list[dict[str, Any]] = []
    for index, (result, ref) in enumerate(zip(next_results, next_refs)):
        if attempted >= max_pages:
            ref["page_fetch_status"] = "skipped"
            if gate_enabled:
                ref["page_excerpt_gate_status"] = "skipped"
                ref["page_excerpt_injected"] = False
            stopped_reason = "max_pages_attempted"
            continue
        if gate_enabled and accepted >= target_excerpts:
            ref["page_fetch_status"] = "skipped"
            ref["page_excerpt_gate_status"] = "skipped"
            ref["page_excerpt_injected"] = False
            stopped_reason = "target_accepted_excerpts"
            continue
        if remaining_excerpt_chars <= 0:
            ref["page_fetch_status"] = "skipped"
            if gate_enabled:
                ref["page_excerpt_gate_status"] = "skipped"
                ref["page_excerpt_injected"] = False
            stopped_reason = "excerpt_budget_exhausted"
            continue
        url = str(result.get("url") or "")
        attempted += 1
        try:
            page = fetcher(url=url, timeout_seconds=timeout, max_bytes=max_bytes, excerpt_chars=min(per_page_chars, remaining_excerpt_chars))
        except Exception:
            page = PageFetchResult(status="failed", warning="page_fetch_failed")
        status = page.status
        ref["page_fetch_status"] = status
        if page.title:
            ref["page_title"] = page.title
        if page.excerpt:
            excerpt = page.excerpt[: max(0, remaining_excerpt_chars)].strip()
            if excerpt:
                ref["page_excerpt_preview"] = _short_page_preview(excerpt)
                ref["page_excerpt_chars"] = len(excerpt)
                if not gate_enabled:
                    result["page_excerpt"] = excerpt
                    ref["page_excerpt_gate_status"] = "disabled"
                    ref["page_excerpt_injected"] = True
                    remaining_excerpt_chars = max(0, remaining_excerpt_chars - len(excerpt))
                else:
                    gate = await run_page_excerpt_gate(
                        settings=settings,
                        original_user_text=original_user_text,
                        plan=plan,
                        candidate=result,
                        ref=ref,
                        page_title=page.title,
                        page_excerpt=excerpt,
                        accepted_evidence=accepted_evidence,
                        utility_llm_service=utility_llm_service,
                        llm_runtime=llm_runtime,
                        llm_model_config=llm_model_config,
                    )
                    if gate.get("accepted"):
                        gate_result = gate["result"]
                        result["page_excerpt"] = excerpt
                        ref["page_excerpt_gate_status"] = "accepted"
                        ref["page_excerpt_injected"] = True
                        ref["page_excerpt_quality"] = gate_result.evidence_quality
                        ref["page_excerpt_confidence"] = gate_result.confidence
                        ref["page_excerpt_coverage"] = gate_result.coverage
                        ref["page_excerpt_gate_reason"] = gate_result.reason
                        remaining_excerpt_chars = max(0, remaining_excerpt_chars - len(excerpt))
                        accepted += 1
                        accepted_evidence.append(_accepted_gate_evidence(ref, excerpt))
                        if not gate_result.need_more and accepted >= 1:
                            stopped_reason = "enough_evidence"
                            for rest in next_refs[index + 1 :]:
                                rest["page_fetch_status"] = "skipped"
                                rest["page_excerpt_gate_status"] = "skipped"
                                rest["page_excerpt_injected"] = False
                            break
                    else:
                        gate_status = str(gate.get("status") or "rejected")
                        ref["page_excerpt_gate_status"] = gate_status
                        ref["page_excerpt_injected"] = False
                        gate_result = gate.get("result")
                        if isinstance(gate_result, PageExcerptGateResult):
                            ref["page_excerpt_quality"] = gate_result.evidence_quality
                            ref["page_excerpt_confidence"] = gate_result.confidence
                            ref["page_excerpt_coverage"] = gate_result.coverage
                            ref["page_excerpt_gate_reason"] = gate_result.reason
                        warning = str(gate.get("warning") or "")
                        if warning:
                            ref["page_excerpt_gate_warning"] = warning
                            gate_warnings.append(warning)
                        if gate_status == "failed":
                            gate_failed += 1
                        else:
                            rejected += 1
            elif gate_enabled:
                ref["page_excerpt_gate_status"] = "skipped"
                ref["page_excerpt_injected"] = False
        elif gate_enabled:
            ref["page_excerpt_gate_status"] = "skipped"
            ref["page_excerpt_injected"] = False
        if page.title:
            result["page_title"] = page.title
        if page.warning:
            ref["page_fetch_warning"] = page.warning
            if page.warning not in warnings:
                warnings.append(page.warning)
        if status == "fetched":
            fetched += 1
        elif status != "skipped":
            failed += 1
        if remaining_excerpt_chars <= 0:
            for rest in next_refs[index + 1 :]:
                rest["page_fetch_status"] = "skipped"
                if gate_enabled:
                    rest["page_excerpt_gate_status"] = "skipped"
                    rest["page_excerpt_injected"] = False
            stopped_reason = "excerpt_budget_exhausted"
            break
    if gate_enabled and accepted >= target_excerpts and stopped_reason == "candidates_exhausted":
        stopped_reason = "target_accepted_excerpts"
    if attempted >= max_pages and stopped_reason == "candidates_exhausted" and len(next_results) > attempted:
        stopped_reason = "max_pages_attempted"
    gate_summary = {
        "enabled": gate_enabled,
        "backend": gate_backend if gate_backend in GATE_BACKENDS else "follow_agent_model_profile",
        "attempted": accepted + rejected + gate_failed,
        "accepted": accepted,
        "rejected": rejected,
        "failed": gate_failed,
        "stopped_reason": stopped_reason,
        "warnings": sorted(set(gate_warnings)),
    }
    return next_results, next_refs, {
        "page_fetch_enabled": True,
        "pages_attempted": attempted,
        "pages_fetched": fetched,
        "pages_failed": failed,
        "page_fetch_warnings": warnings,
        "page_excerpt_gate": gate_summary,
    }


async def run_page_excerpt_gate(
    *,
    settings: AppSettings,
    original_user_text: str,
    plan: WebContextPlan,
    candidate: dict[str, Any],
    ref: dict[str, Any],
    page_title: str,
    page_excerpt: str,
    accepted_evidence: list[dict[str, Any]],
    utility_llm_service: Any = None,
    llm_runtime: Any = None,
    llm_model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    backend = str(getattr(settings, "web_context_page_excerpt_gate_backend", "follow_agent_model_profile") or "follow_agent_model_profile")
    if backend not in GATE_BACKENDS:
        backend = "follow_agent_model_profile"
    prompt = _page_excerpt_gate_prompt(
        settings=settings,
        original_user_text=original_user_text,
        plan=plan,
        candidate=candidate,
        ref=ref,
        page_title=page_title,
        page_excerpt=page_excerpt,
        accepted_evidence=accepted_evidence,
    )
    try:
        data = await _call_page_excerpt_gate_backend(
            backend=backend,
            prompt=prompt,
            settings=settings,
            utility_llm_service=utility_llm_service,
            llm_runtime=llm_runtime,
            llm_model_config=llm_model_config,
        )
    except UtilityLLMError as exc:
        warning = "page_excerpt_gate_invalid_json" if exc.code == "utility_llm_invalid_json" else "page_excerpt_gate_unavailable"
        return {"accepted": False, "status": "failed", "warning": warning}
    except (json.JSONDecodeError, ValueError):
        return {"accepted": False, "status": "failed", "warning": "page_excerpt_gate_invalid_json"}
    except Exception:
        return {"accepted": False, "status": "failed", "warning": "page_excerpt_gate_unavailable"}
    result, warning = validate_page_excerpt_gate_response(data, min_quality=str(getattr(settings, "web_context_page_excerpt_gate_min_quality", "medium") or "medium"))
    if result is None:
        return {"accepted": False, "status": "failed", "warning": warning or "page_excerpt_gate_invalid_json"}
    accepted = _page_excerpt_gate_accepts(result, min_quality=str(getattr(settings, "web_context_page_excerpt_gate_min_quality", "medium") or "medium"))
    return {"accepted": accepted, "status": "accepted" if accepted else "rejected", "result": result}


async def _call_page_excerpt_gate_backend(
    *,
    backend: str,
    prompt: str,
    settings: AppSettings,
    utility_llm_service: Any,
    llm_runtime: Any,
    llm_model_config: dict[str, Any] | None,
) -> dict[str, Any]:
    if backend == "utility_llm":
        if utility_llm_service is None:
            raise UtilityLLMError("page_excerpt_gate_unavailable", "Utility LLM is unavailable.")
        if callable(getattr(utility_llm_service, "extract_page_excerpt_gate_json", None)):
            return await utility_llm_service.extract_page_excerpt_gate_json(prompt=prompt, settings=settings)
        raw = await utility_llm_service.generate(prompt, settings, max_new_tokens=320)
        return extract_json_object(getattr(raw, "text", raw))
    if backend == "specific_model_profile":
        profile_id = str(getattr(settings, "web_context_page_excerpt_gate_model_profile_id", "") or "").strip()
        if not profile_id:
            raise UtilityLLMError("model_profile_not_configured", "Page Excerpt Gate Model Profile is not configured.")
        if utility_llm_service is None or not callable(getattr(utility_llm_service, "generate_with_model_profile", None)):
            raise UtilityLLMError("model_profile_generation_failed", "Model Profile gate backend is unavailable.")
        raw = await utility_llm_service.generate_with_model_profile(prompt, profile_id=profile_id, max_new_tokens=320)
        return extract_json_object(getattr(raw, "text", raw))
    if llm_runtime is None or not isinstance(llm_model_config, dict):
        raise UtilityLLMError("model_profile_generation_failed", "Follow-Agent gate backend is unavailable.")
    model_config = dict(llm_model_config)
    model_config.update({"stream": False, "temperature": 0, "top_p": 1, "max_tokens": min(int(model_config.get("max_tokens") or 320), 320)})
    chat = getattr(llm_runtime, "chat", None)
    if callable(chat):
        raw = chat(messages=[{"role": "user", "content": prompt}], model_config=model_config, stream=False)
    else:
        generate = getattr(llm_runtime, "generate")
        raw = generate(prompt=prompt, model_config=model_config, stream=False)
    if hasattr(raw, "__await__"):
        raw = await raw
    return extract_json_object(_extract_gate_llm_text(raw))


def validate_page_excerpt_gate_response(data: Any, *, min_quality: str) -> tuple[PageExcerptGateResult | None, str | None]:
    if not isinstance(data, dict):
        return None, "page_excerpt_gate_invalid_json"
    required = ("use_excerpt", "evidence_quality", "confidence", "coverage", "need_more", "reason")
    if any(key not in data for key in required):
        return None, "page_excerpt_gate_schema_invalid"
    if not isinstance(data.get("use_excerpt"), bool) or not isinstance(data.get("need_more"), bool):
        return None, "page_excerpt_gate_schema_invalid"
    quality = str(data.get("evidence_quality") or "").strip().lower()
    confidence = str(data.get("confidence") or "").strip().lower()
    coverage = str(data.get("coverage") or "").strip().lower()
    reason = _short_judge_text(data.get("reason"), GATE_REASON_CHARS)
    if quality not in GATE_QUALITY_ORDER:
        return None, "page_excerpt_gate_unknown_quality"
    if confidence not in GATE_CONFIDENCES:
        return None, "page_excerpt_gate_unknown_confidence"
    if coverage not in GATE_COVERAGES:
        return None, "page_excerpt_gate_unknown_coverage"
    if not reason:
        return None, "page_excerpt_gate_empty_reason"
    return PageExcerptGateResult(
        use_excerpt=bool(data["use_excerpt"]),
        evidence_quality=quality,
        confidence=confidence,
        coverage=coverage,
        need_more=bool(data["need_more"]),
        reason=reason,
    ), None


def _page_excerpt_gate_accepts(result: PageExcerptGateResult, *, min_quality: str) -> bool:
    threshold = GATE_QUALITY_ORDER.get(min_quality, GATE_QUALITY_ORDER["medium"])
    return (
        result.use_excerpt
        and GATE_QUALITY_ORDER.get(result.evidence_quality, 0) >= threshold
        and result.confidence in {"medium", "high"}
        and result.coverage in GATE_ACCEPT_COVERAGES
    )


def _page_excerpt_gate_prompt(
    *,
    settings: AppSettings,
    original_user_text: str,
    plan: WebContextPlan,
    candidate: dict[str, Any],
    ref: dict[str, Any],
    page_title: str,
    page_excerpt: str,
    accepted_evidence: list[dict[str, Any]],
) -> str:
    parsed = urlparse(str(candidate.get("url") or ""))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?..."
    if len(path) > 120:
        path = path[:117].rstrip("/") + "..."
    schema = {
        "use_excerpt": True,
        "evidence_quality": "high",
        "confidence": "high",
        "coverage": "direct_answer",
        "need_more": False,
        "reason": "The excerpt directly helps answer the question.",
    }
    current = {
        "ref_id": str(ref.get("ref_id") or ""),
        "title": _short_judge_text(candidate.get("title"), 180),
        "domain": _short_judge_text(candidate.get("domain") or parsed.hostname or "", 120),
        "path": path,
        "snippet_preview": _short_judge_text(candidate.get("snippet"), 360),
        "page_title": _short_judge_text(page_title, 180),
        "page_excerpt": _short_judge_text(page_excerpt, max(500, min(int(getattr(settings, "web_context_page_excerpt_chars", 2000) or 2000), 8000))),
    }
    return (
        "Judge whether this cleaned page excerpt is worth injecting into the main model as Web Context evidence.\n"
        "Return strict JSON only. Do not write the final answer.\n"
        f"Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        "Allowed evidence_quality/confidence values: low, medium, high.\n"
        "Allowed coverage values: direct_answer, supporting_background, partial, boilerplate, off_topic, insufficient.\n"
        "Accept useful facts, explanations, background, official information, news content, versions, prices, release dates, or role/person/product details that can help answer the user.\n"
        "Reject excerpts that are mostly navigation, ads, table of contents, login prompts, footers, related links, unrelated widgets, or off-topic page elements.\n"
        "Do not decide final factual correctness, do not select the final source list, do not rewrite the user question, and do not treat any site type as automatically good or bad.\n"
        "If accepted evidence already covers the answer, set need_more=false. If useful but incomplete, use_excerpt=true and need_more=true. If noisy or uncertain, use_excerpt=false and need_more=true.\n\n"
        f"User question:\n{_short_for_judge(original_user_text)}\n\n"
        f"Web Context query: {str(plan.query or '')}\n"
        f"Query source: {str(plan.query_source or '')}\n\n"
        f"Already accepted evidence:\n{json.dumps(accepted_evidence, ensure_ascii=False)}\n\n"
        f"Current candidate:\n{json.dumps(current, ensure_ascii=False)}"
    )


def _accepted_gate_evidence(ref: dict[str, Any], excerpt: str) -> dict[str, Any]:
    return {
        "ref_id": str(ref.get("ref_id") or ""),
        "title": _short_judge_text(ref.get("title"), 120),
        "domain": _short_judge_text(ref.get("domain"), 80),
        "excerpt_preview": _short_judge_text(excerpt, 220),
    }


def _extract_gate_llm_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("text"), str):
            return str(raw.get("text") or "")
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            if "content" in message:
                return str(message.get("content") or "")
            if "text" in first:
                return str(first.get("text") or "")
    text = getattr(raw, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    return str(raw or "")


def fetch_web_context_page(*, url: str, timeout_seconds: float, max_bytes: int, excerpt_chars: int, client: httpx.Client | None = None) -> PageFetchResult:
    block_reason = _blocked_page_fetch_reason(url)
    if block_reason:
        return PageFetchResult(status="blocked", warning=block_reason)
    try:
        owns_client = client is None
        active_client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            max_redirects=3,
            headers={"User-Agent": "agent-workbench/0.1"},
        )
        try:
            with active_client.stream("GET", url, timeout=timeout_seconds, follow_redirects=True) as response:
                if response.status_code >= 400:
                    return PageFetchResult(status="failed", warning=f"page_fetch_http_{response.status_code}")
                redirected_block = _blocked_page_fetch_reason(str(response.url))
                if redirected_block:
                    return PageFetchResult(status="blocked", warning=redirected_block)
                mime_type = _content_type(response)
                if mime_type not in HTML_MIME_TYPES:
                    return PageFetchResult(status="unsupported", warning="page_fetch_unsupported_content_type")
                content = _read_limited_response(response, max_bytes)
        finally:
            if owns_client:
                active_client.close()
    except httpx.TimeoutException:
        return PageFetchResult(status="timeout", warning="page_fetch_timeout")
    except httpx.HTTPError:
        return PageFetchResult(status="failed", warning="page_fetch_failed")
    html = content.decode(_encoding_from_headers(response.headers), errors="replace")
    extracted = extract_html_page_text(html, excerpt_chars=excerpt_chars)
    warning = extracted.get("warning")
    excerpt = str(extracted.get("excerpt") or "").strip()
    if not excerpt:
        return PageFetchResult(status="failed", title=str(extracted.get("title") or ""), warning=warning or "page_extract_failed")
    return PageFetchResult(status="fetched", title=str(extracted.get("title") or ""), excerpt=excerpt, warning=warning)


def extract_html_page_text(html: str, *, excerpt_chars: int) -> dict[str, str]:
    parser = _HTMLPageTextExtractor()
    parser.feed(str(html or ""))
    title = _collapse_ws(parser.title)
    description = _collapse_ws(parser.description)
    body = _collapse_ws(" ".join(parser.body_parts))
    text = " ".join(part for part in (description, body) if part).strip()
    excerpt = text[:excerpt_chars].rstrip()
    result = {"title": title, "excerpt": excerpt}
    if len(body) < MIN_USEFUL_PAGE_TEXT_CHARS:
        result["warning"] = "page_text_too_short"
    return result


class _HTMLPageTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body_parts: list[str] = []
        self.title_parts: list[str] = []
        self.description = ""
        self.skip_depth = 0
        self.in_title = False
        self.in_body = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag_name = tag.lower()
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag_name in {"script", "style", "noscript", "svg", "canvas", "iframe", "template"}:
            self.skip_depth += 1
        if tag_name == "title":
            self.in_title = True
        if tag_name == "body":
            self.in_body = True
        if tag_name == "meta" and attrs_dict.get("name", "").lower() == "description":
            self.description = attrs_dict.get("content", "")
        if self.in_body and tag_name in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.body_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in {"script", "style", "noscript", "svg", "canvas", "iframe", "template"} and self.skip_depth:
            self.skip_depth -= 1
        if tag_name == "title":
            self.in_title = False
        if tag_name == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        elif self.in_body:
            self.body_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts)


def _blocked_page_fetch_reason(raw_url: str) -> str | None:
    parsed = urlparse(str(raw_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return "page_fetch_blocked_scheme"
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return "page_fetch_blocked_empty_host"
    if host == "localhost" or host.endswith(".localhost"):
        return "page_fetch_blocked_localhost"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "page_fetch_blocked_private_ip"
    return None


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _encoding_from_headers(headers: httpx.Headers) -> str:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else "utf-8"


def _read_limited_response(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if not chunk:
            continue
        remaining = limit - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= limit:
            break
    return b"".join(chunks)


def _collapse_ws(value: str) -> str:
    return " ".join(str(value or "").split())


def _short_page_preview(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= MAX_PAGE_EXCERPT_PREVIEW_CHARS:
        return text
    return text[: MAX_PAGE_EXCERPT_PREVIEW_CHARS - 3].rstrip() + "..."


def _compact_search_diagnostics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    diagnostics: dict[str, Any] = {}
    for key in ("filtered_count", "deduped_count"):
        item = value.get(key)
        if isinstance(item, int) and item > 0:
            diagnostics[key] = item
    filters = value.get("filters_applied")
    if isinstance(filters, dict):
        compact_filters = {
            key: bool(filters.get(key))
            for key in ("domain_allowlist", "domain_blocklist", "dedupe_results", "dedupe_same_domain_title")
            if bool(filters.get(key))
        }
        if compact_filters:
            diagnostics["filters_applied"] = compact_filters
    warnings = [str(item) for item in value.get("warnings", [])] if isinstance(value.get("warnings"), list) else []
    if warnings:
        diagnostics["warnings"] = warnings
    return diagnostics


def _diagnostics_filtered_any(value: dict[str, Any]) -> bool:
    return bool(
        isinstance(value, dict)
        and (
            int(value.get("filtered_count") or 0) > 0
            or int(value.get("deduped_count") or 0) > 0
        )
    )


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
