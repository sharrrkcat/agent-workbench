from dataclasses import dataclass, field
from typing import Any
import re

from ai_workbench.core.agent_settings import resolved_intent_routing_mode
from ai_workbench.core.schema.route import RouteKind, RouteTarget


@dataclass(frozen=True)
class IntentDefinition:
    id: str
    label: str
    description: str
    examples: list[str]
    safe_auto_route: bool = False
    target_agent_id: str | None = None
    keywords: list[str] = field(default_factory=list)


INTENT_DEFINITIONS: tuple[IntentDefinition, ...] = (
    IntentDefinition(
        id="chat",
        label="Chat",
        description="General conversation, writing, translation, and follow-up help.",
        examples=["继续", "解释一下", "还有什么方法", "translate this", "help me write"],
        safe_auto_route=True,
        keywords=["continue", "explain", "translate", "write", "help me", "继续", "解释", "翻译", "写"],
    ),
    IntentDefinition(
        id="image_generation",
        label="Image generation",
        description="Requests to create or draw an image.",
        examples=["帮我生成一张图片", "画一张图", "make an image", "generate a picture", "生成角色立绘"],
        target_agent_id="comfyui_agent",
        keywords=["generate an image", "make an image", "draw", "picture", "image", "生成图片", "生成一张", "画一张", "画图", "立绘"],
    ),
    IntentDefinition(
        id="knowledge_query",
        label="Knowledge query",
        description="Questions that ask for project, document, or knowledge base grounded answers.",
        examples=["知识库里说了什么", "根据项目文档回答", "星球大战知识库里的内容", "what does the documentation say"],
        keywords=["knowledge base", "documentation", "docs say", "project docs", "知识库", "文档", "根据项目", "资料里"],
    ),
    IntentDefinition(
        id="agent_route",
        label="Agent route",
        description="Requests that appear to ask for another agent or specialized route.",
        examples=["找翻译 agent", "交给图片助手", "route this to the image agent"],
        keywords=["agent", "route to", "send to", "交给", "助手", "智能体"],
    ),
    IntentDefinition(
        id="command_like",
        label="Command-like",
        description="Requests that resemble operational commands or cleanup actions.",
        examples=["释放显存", "清理内存", "删除这个", "运行命令"],
        keywords=["free memory", "clear memory", "delete", "run command", "释放显存", "清理内存", "删除", "运行命令"],
    ),
)


class RuleBasedIntentClassifier:
    source = "rule_based_shadow"

    def classify(
        self,
        text: str,
        *,
        settings: Any = None,
        agent_registry: Any = None,
        agent_config_store: Any = None,
        knowledge_store: Any = None,
    ) -> dict[str, Any]:
        normalized = _normalize_text(text)
        if not normalized:
            return self._prediction("chat", 0.0, warnings=["empty_input"])
        if len(normalized) < 3:
            return self._prediction("chat", 0.2, warnings=["short_input"])
        best_intent = "chat"
        best_score = 0.35
        best_meta: dict[str, Any] = {}
        scores: list[tuple[str, float]] = []
        for intent in INTENT_DEFINITIONS:
            score, meta = self._score_intent(normalized, intent, settings=settings)
            scores.append((intent.id, score))
            if score > best_score:
                best_intent = intent.id
                best_score = score
                best_meta = meta
        agent_match = _match_agent_hints(agent_registry, agent_config_store, normalized)
        if agent_match and best_intent not in {"image_generation", "command_like", "knowledge_query"}:
            best_intent = "agent_route"
            best_score = max(best_score, 0.76)
        prediction = self._prediction(best_intent, min(best_score, 0.95))
        warnings = list(prediction.get("warnings") or [])
        close = [item for item in scores if item[0] != best_intent and item[1] >= max(0.55, best_score - 0.08)]
        if close:
            warnings.append("ambiguous_intent")
            prediction["ambiguous_matches"] = [{"intent": intent, "confidence": round(score, 2)} for intent, score in close[:5]]
        if best_meta:
            prediction.update(best_meta)
        if best_intent == "agent_route" and agent_match:
            prediction["target_agent_id"] = agent_match.get("id")
            prediction["agent_match_source"] = agent_match.get("source", "none")
            if agent_match.get("alias"):
                prediction["matched_alias"] = _short_text(str(agent_match["alias"]), 80)
            if agent_match.get("example"):
                prediction["matched_route_example"] = _short_text(str(agent_match["example"]), 120)
            slots = dict(prediction.get("slots") or {})
            slots["target_agent_hint"] = agent_match.get("hint") or agent_match.get("id") or ""
            prediction["slots"] = slots
        kb_hint = _detect_kb_hint(knowledge_store, normalized)
        if kb_hint and best_intent in {"knowledge_query", "chat"}:
            prediction["predicted_intent"] = "knowledge_query"
            prediction["confidence"] = max(float(prediction.get("confidence") or 0.0), 0.72)
            slots = dict(prediction.get("slots") or {})
            slots.setdefault("kb_hint", kb_hint["hint"])
            slots.setdefault("query", str(text or "").strip())
            prediction["slots"] = slots
            prediction["kb_match_source"] = kb_hint["source"]
            if kb_hint.get("alias"):
                prediction["matched_alias"] = _short_text(str(kb_hint["alias"]), 80)
        prediction["warnings"] = warnings
        return prediction

    def _score_intent(self, text: str, intent: IntentDefinition, *, settings: Any = None) -> tuple[float, dict[str, Any]]:
        score = 0.0
        meta: dict[str, Any] = {}
        for keyword in intent.keywords:
            lowered = _normalize_text(keyword)
            if lowered and lowered in text:
                score = max(score, 0.62 + min(len(lowered), 18) / 100)
        builtin_examples = [_normalize_text(item) for item in intent.examples]
        custom_examples = custom_route_examples(settings, intent.id)
        for example in [*builtin_examples, *custom_examples]:
            if not example:
                continue
            if example in text or text in example:
                boost = 0.82 if example in builtin_examples else 0.76
                if boost > score:
                    score = boost
                    if example in custom_examples:
                        meta["custom_examples_used"] = True
                        meta["matched_route_example"] = _short_text(example, 120)
            else:
                overlap = _jaccard_score(text, example)
                if overlap >= 0.45:
                    boost = min(0.74 if example in custom_examples else 0.78, 0.42 + overlap)
                    if boost > score:
                        score = boost
                        if example in custom_examples:
                            meta["custom_examples_used"] = True
                            meta["matched_route_example"] = _short_text(example, 120)
        return score, meta

    def _prediction(self, intent_id: str, confidence: float, warnings: list[str] | None = None) -> dict[str, Any]:
        definition = intent_definition(intent_id) or intent_definition("chat")
        return {
            "predicted_intent": definition.id if definition is not None else "chat",
            "confidence": round(float(confidence), 2),
            "source": self.source,
            "target_agent_id": definition.target_agent_id if definition is not None else None,
            "slots": {},
            "warnings": warnings or [],
        }


def intent_definition(intent_id: str) -> IntentDefinition | None:
    return next((intent for intent in INTENT_DEFINITIONS if intent.id == intent_id), None)


SAFE_AUTO_ROUTE_INTENTS = {"chat", "knowledge_query"}
COMMAND_LIKE_WARNING = "command_like_auto_route_disabled"
SEMANTIC_AUTO_MIN_MARGIN = 0.03
DIAGNOSTIC_ONLY_WARNINGS = {
    "command_like": COMMAND_LIKE_WARNING,
    "agent_route": "agent_route_auto_route_disabled",
    "action_route": "action_route_auto_route_disabled",
    "compound": "compound_intent_not_auto_routed",
    "image_generation": "image_generation_auto_route_deferred_until_action_routing",
}
BLOCKING_AUTO_WARNINGS = {
    "ambiguous_intent",
    "compound_intent_not_auto_routed",
    "semantic_router_profile_missing",
    "semantic_router_profile_disabled",
    "semantic_router_embedding_unavailable",
    "semantic_router_index_build_failed",
    "semantic_router_unavailable",
}
CUSTOM_EXAMPLE_FIELDS = {
    "chat": "intent_routing_chat_examples",
    "image_generation": "intent_routing_image_generation_examples",
    "knowledge_query": "intent_routing_knowledge_query_examples",
    "agent_route": "intent_routing_agent_route_examples",
    "command_like": "intent_routing_command_like_examples",
}
MAX_ROUTE_EXAMPLES = 100
MAX_ROUTE_EXAMPLE_CHARS = 300
MAX_AGENT_ALIASES = 50
MAX_AGENT_ALIAS_CHARS = 120
MAX_AGENT_EXAMPLES = 100
MAX_AGENT_EXAMPLE_CHARS = 300


def custom_route_examples(settings: Any, intent_id: str) -> list[str]:
    field_name = CUSTOM_EXAMPLE_FIELDS.get(intent_id)
    raw = getattr(settings, field_name, "") if settings is not None and field_name else ""
    return [_normalize_text(item) for item in _line_values(raw, MAX_ROUTE_EXAMPLES, MAX_ROUTE_EXAMPLE_CHARS)]


def compact_utility_context(*, settings: Any = None, agent_registry: Any = None, agent_config_store: Any = None, knowledge_store: Any = None) -> dict[str, Any]:
    return {
        "intents": [
            {
                "id": intent.id,
                "examples": [*intent.examples, *_line_values(getattr(settings, CUSTOM_EXAMPLE_FIELDS.get(intent.id, ""), ""), 12, MAX_ROUTE_EXAMPLE_CHARS)][:12],
            }
            for intent in INTENT_DEFINITIONS
        ],
        "agents": _agent_candidates(agent_registry, agent_config_store)[:20],
        "knowledge_bases": _kb_candidates(knowledge_store)[:30],
        "safety": {
            "command_like_auto_execute": False,
            "generic_agent_route_auto_execute": False,
            "image_generation_target": "comfyui_agent",
            "knowledge_query_override_only": True,
        },
    }


def _line_values(value: Any, max_items: int, max_chars: int) -> list[str]:
    items: list[str] = []
    for line in str(value or "").splitlines():
        text = line.strip()
        if not text:
            continue
        items.append(text[:max_chars])
        if len(items) >= max_items:
            break
    return items


def _comma_values(value: Any, max_items: int, max_chars: int) -> list[str]:
    items: list[str] = []
    for part in str(value or "").split(","):
        text = part.strip()
        if not text:
            continue
        items.append(text[:max_chars])
        if len(items) >= max_items:
            break
    return items


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _tokenize(value: str) -> set[str]:
    return {item for item in re.split(r"[\s,.;:!?/\\()\[\]{}\"']+", value) if item}


def _jaccard_score(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _agent_candidates(agent_registry: Any, agent_config_store: Any = None) -> list[dict[str, Any]]:
    if agent_registry is None:
        return []
    try:
        agents = agent_registry.list()
    except Exception:
        return []
    candidates = []
    for agent in agents:
        config = agent_config_store.get_config(agent.id) if agent_config_store is not None else {}
        runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
        candidates.append(
            {
                "id": agent.id,
                "name": getattr(agent, "name", "") or agent.id,
                "type": getattr(agent, "type", ""),
                "aliases": _comma_values(runtime.get("intent_routing_aliases_text", ""), MAX_AGENT_ALIASES, MAX_AGENT_ALIAS_CHARS),
                "examples": _line_values(runtime.get("intent_routing_examples_text", ""), 8, MAX_AGENT_EXAMPLE_CHARS),
            }
        )
    return candidates


def _kb_candidates(knowledge_store: Any) -> list[dict[str, Any]]:
    if knowledge_store is None:
        return []
    try:
        bases = knowledge_store.list_knowledge_bases()
    except Exception:
        return []
    return [
        {
            "id": kb.id,
            "name": getattr(kb, "name", "") or kb.id,
            "aliases": _comma_values(getattr(kb, "aliases_text", ""), 50, 120),
            "description": _short_text(getattr(kb, "description", "") or "", 120),
        }
        for kb in bases
        if getattr(kb, "enabled", False)
    ]


async def build_intent_routing_metadata(
    *,
    session: Any,
    route: RouteTarget,
    agent_registry: Any,
    agent_config_store: Any = None,
    app_settings_store: Any = None,
    knowledge_store: Any = None,
    knowledge_model_backend: Any = None,
    capability_registry: Any = None,
    command_registry: Any = None,
    semantic_router: Any = None,
    classifier: RuleBasedIntentClassifier | None = None,
    utility_llm_service: Any = None,
) -> dict[str, Any] | None:
    settings = app_settings_store.get() if app_settings_store is not None else None
    mode = getattr(settings, "intent_routing_mode", "shadow")
    base = {
        "enabled": bool(getattr(settings, "intent_routing_enabled", False)),
        "mode": mode,
        "evaluated": False,
        "eligible": False,
        "bypassed": True,
    }
    bypass_reason = _bypass_reason(session, route)
    if bypass_reason:
        return {**base, "skip_reason": bypass_reason, "bypass_reason": bypass_reason}
    try:
        agent = agent_registry.get(route.target_id or "")
    except KeyError:
        return {**base, "skip_reason": "agent_not_found", "bypass_reason": "agent_not_found"}
    config = agent_config_store.get_config(agent.id) if agent_config_store is not None else {}
    effective = resolved_intent_routing_mode(agent, config, settings=settings)
    if agent.type != "prompt":
        return {**base, "skip_reason": "default_agent_not_prompt", "bypass_reason": "default_agent_not_prompt"}
    if not bool(effective["enabled"]):
        reason = str(effective.get("reason") or "disabled")
        return {**base, "skip_reason": reason, "bypass_reason": reason}
    if mode not in {"shadow", "auto"}:
        return {**base, "skip_reason": "unsupported_mode", "bypass_reason": "unsupported_mode"}
    prediction = _semantic_prediction(
        text=route.args,
        settings=settings,
        agent_registry=agent_registry,
        agent_config_store=agent_config_store,
        knowledge_store=knowledge_store,
        knowledge_model_backend=knowledge_model_backend,
        capability_registry=capability_registry,
        command_registry=command_registry,
        semantic_router=semantic_router,
        classifier=classifier,
    )
    prediction = await _maybe_apply_utility_slots(
        text=route.args,
        prediction=prediction,
        settings=settings,
        utility_llm_service=utility_llm_service,
        agent_registry=agent_registry,
        agent_config_store=agent_config_store,
        knowledge_store=knowledge_store,
    )
    metadata = _decision_metadata(
        session=session,
        route=route,
        prediction=prediction,
        mode=mode,
        settings=settings,
        agent=agent,
        agent_registry=agent_registry,
        agent_config_store=agent_config_store,
        knowledge_store=knowledge_store,
    )
    return {
        "enabled": True,
        "mode": mode,
        "evaluated": True,
        "eligible": True,
        "bypassed": False,
        **metadata,
    }


def _decision_metadata(
    *,
    session: Any,
    route: RouteTarget,
    prediction: dict[str, Any],
    mode: str,
    settings: Any,
    agent: Any,
    agent_registry: Any,
    agent_config_store: Any,
    knowledge_store: Any,
) -> dict[str, Any]:
    intent_id = str(prediction.get("predicted_intent") or "chat")
    confidence = float(prediction.get("confidence") or 0.0)
    thresholds = _semantic_thresholds_used(settings, prediction)
    slots = _compact_slots(prediction.get("slots") if isinstance(prediction.get("slots"), dict) else {})
    warnings = list(prediction.get("warnings") or [])
    metadata = {
        **prediction,
        "predicted_intent": intent_id,
        "confidence": round(confidence, 2),
        "intent_score": _rounded_optional(prediction.get("semantic_score")) if prediction.get("source") != "rule_based_shadow" else round(confidence, 4),
        "intent_margin": _rounded_optional(prediction.get("semantic_margin")),
        "semantic_score": _rounded_optional(prediction.get("semantic_score")),
        "semantic_margin": _rounded_optional(prediction.get("semantic_margin")),
        "slots": slots,
        "warnings": warnings,
        "route_action": prediction.get("route_action") or "metadata_only",
        "auto_executable": bool(prediction.get("auto_executable", False)),
        "executed": False,
        "would_execute": False,
        "not_executed_reason": None,
        "target_agent_id": prediction.get("target_agent_id") or _candidate_value(prediction.get("agent_candidate"), "agent_id") or route.target_id,
        "target_action_id": prediction.get("target_action_id") or _candidate_value(prediction.get("action_candidate"), "action_id") or route.action_id or "default",
        "target_command": prediction.get("target_command") or _candidate_value(prediction.get("command_candidate"), "command_name"),
        "session_default_agent_id": getattr(session, "default_agent_id", None),
        "session_default_changed": False,
        "session_bindings_changed": False,
        "embedding_model_profile_id": getattr(settings, "intent_routing_embedding_model_profile_id", None),
        "semantic_index_version": prediction.get("semantic_index_version"),
        "kb_match_source": prediction.get("kb_match_source") or _candidate_value(prediction.get("kb_candidate"), "field") or "none",
        "agent_match_source": prediction.get("agent_match_source") or _candidate_value(prediction.get("agent_candidate"), "field") or "none",
        "action_match_source": prediction.get("action_match_source") or _candidate_value(prediction.get("action_candidate"), "field") or "none",
        "command_match_source": prediction.get("command_match_source") or _candidate_value(prediction.get("command_candidate"), "field") or "none",
        "semantic_thresholds_used": thresholds,
        "thresholds_used": {"semantic": thresholds},
    }
    kb_candidate = prediction.get("kb_candidate")
    if isinstance(kb_candidate, dict):
        metadata["kb_id"] = kb_candidate.get("kb_id")
        metadata["kb_name"] = kb_candidate.get("kb_name")
        if kb_candidate.get("field") == "alias" and not metadata.get("matched_alias"):
            metadata["matched_alias"] = _short_text(str(kb_candidate.get("text_preview") or ""), 80)
    agent_candidate = prediction.get("agent_candidate")
    if isinstance(agent_candidate, dict) and agent_candidate.get("field") == "alias":
        metadata["matched_alias"] = _short_text(str(agent_candidate.get("text_preview") or ""), 80)
    if mode != "auto":
        return metadata
    if not bool(getattr(settings, "intent_routing_auto_route_safe_intents", False)):
        metadata["route_action"] = "metadata_only"
        metadata["auto_executable"] = False
        metadata["not_executed_reason"] = "safe_auto_route_disabled"
        metadata["warnings"] = [*warnings, "safe_auto_route_disabled"]
        return metadata
    if intent_id in DIAGNOSTIC_ONLY_WARNINGS:
        metadata["route_action"] = "metadata_only"
        metadata["auto_executable"] = False
        warning = DIAGNOSTIC_ONLY_WARNINGS.get(intent_id, "auto_route_not_supported")
        metadata["diagnostic_reason"] = warning
        metadata["not_executed_reason"] = warning
        metadata["warnings"] = [*warnings, warning]
        return metadata
    score = prediction.get("semantic_score")
    semantic_score = float(score) if isinstance(score, (int, float)) else confidence
    margin_value = prediction.get("semantic_margin")
    semantic_margin = float(margin_value) if isinstance(margin_value, (int, float)) else None
    if semantic_score < thresholds["intent_min_score"]:
        reason = "semantic_intent_score_below_threshold"
        metadata["route_action"] = "fallback_current_agent"
        metadata["auto_executable"] = False
        metadata["not_executed_reason"] = reason
        metadata["warnings"] = _ensure_warning(warnings, reason)
        return metadata
    if semantic_margin is not None and semantic_margin < thresholds["intent_min_margin"]:
        metadata["route_action"] = "fallback_current_agent"
        metadata["auto_executable"] = False
        metadata["not_executed_reason"] = "semantic_margin_below_threshold"
        metadata["warnings"] = _ensure_warning(warnings, "semantic_margin_too_low")
        return metadata
    if any(warning in BLOCKING_AUTO_WARNINGS for warning in warnings):
        metadata["route_action"] = "fallback_current_agent"
        metadata["auto_executable"] = False
        metadata["not_executed_reason"] = _first_blocking_warning(warnings)
        return metadata
    if intent_id not in SAFE_AUTO_ROUTE_INTENTS:
        metadata["route_action"] = "confirmation_needed_future" if intent_id in {"command_like", "agent_route"} else "fallback_current_agent"
        warning = COMMAND_LIKE_WARNING if intent_id == "command_like" else "auto_route_not_supported"
        metadata["auto_executable"] = False
        metadata["not_executed_reason"] = warning
        metadata["warnings"] = [*warnings, warning]
        return metadata
    if intent_id == "chat":
        metadata["route_action"] = "current_prompt_agent"
        metadata["auto_executable"] = True
        metadata["executed"] = True
        metadata["would_execute"] = True
        metadata["not_executed_reason"] = None
        metadata["target_agent_id"] = agent.id
        metadata["target_action_id"] = "default"
        return metadata
    if intent_id == "knowledge_query":
        decision = _knowledge_query_decision(metadata, session, agent, knowledge_store, fallback_query=route.args)
        if decision.get("route_action") == "knowledge_override":
            decision["auto_executable"] = True
            decision["executed"] = True
            decision["would_execute"] = True
            decision["not_executed_reason"] = None
        else:
            decision["auto_executable"] = False
            decision["executed"] = False
            decision["would_execute"] = False
            decision["not_executed_reason"] = _knowledge_not_executed_reason(decision)
        return decision
    return metadata


def _semantic_prediction(
    *,
    text: str,
    settings: Any,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    knowledge_store: Any = None,
    knowledge_model_backend: Any = None,
    capability_registry: Any = None,
    command_registry: Any = None,
    semantic_router: Any = None,
    classifier: RuleBasedIntentClassifier | None = None,
) -> dict[str, Any]:
    try:
        from ai_workbench.core.intent_semantic_router import SemanticRouter

        router = semantic_router or SemanticRouter()
        prediction = router.decide(
            text,
            settings=settings,
            knowledge_store=knowledge_store,
            model_backend=knowledge_model_backend,
            agent_registry=agent_registry,
            agent_config_store=agent_config_store,
            capability_registry=capability_registry,
            command_registry=command_registry,
        )
    except Exception:
        prediction = {"predicted_intent": "chat", "confidence": 0.0, "source": "embedding_semantic_router", "warnings": ["semantic_router_unavailable"]}
    if prediction.get("warnings") and any(str(item).startswith("semantic_router_") for item in prediction.get("warnings") or []):
        prediction = {**prediction, "source": "semantic_router_unavailable", "predicted_intent": "chat", "confidence": 0.0, "route_action": "fallback_current_agent", "auto_executable": False}
        if classifier is not None:
            try:
                debug = classifier.classify(
                    text,
                    settings=settings,
                    agent_registry=agent_registry,
                    agent_config_store=agent_config_store,
                    knowledge_store=knowledge_store,
                )
                prediction["debug_fallback"] = {
                    "source": "rule_based_fallback",
                    "predicted_intent": debug.get("predicted_intent"),
                    "confidence": debug.get("confidence"),
                }
            except Exception:
                pass
    return prediction


def _candidate_value(candidate: Any, key: str) -> Any:
    return candidate.get(key) if isinstance(candidate, dict) else None


def _rounded_optional(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    return None


def _semantic_thresholds_used(settings: Any, prediction: dict[str, Any] | None = None) -> dict[str, float]:
    existing = (prediction or {}).get("semantic_thresholds_used")
    if isinstance(existing, dict):
        return {
            "intent_min_score": round(float(existing.get("intent_min_score", 0.50)), 4),
            "intent_min_margin": round(float(existing.get("intent_min_margin", 0.03)), 4),
            "kb_min_score": round(float(existing.get("kb_min_score", 0.45)), 4),
            "agent_min_score": round(float(existing.get("agent_min_score", 0.45)), 4),
            "command_min_score": round(float(existing.get("command_min_score", 0.45)), 4),
        }

    def value(name: str, default: float) -> float:
        raw = getattr(settings, name, default)
        return default if raw is None else float(raw)

    return {
        "intent_min_score": round(value("intent_routing_semantic_intent_min_score", 0.50), 4),
        "intent_min_margin": round(value("intent_routing_semantic_intent_min_margin", 0.03), 4),
        "kb_min_score": round(value("intent_routing_semantic_kb_min_score", 0.45), 4),
        "agent_min_score": round(value("intent_routing_semantic_agent_min_score", 0.45), 4),
        "command_min_score": round(value("intent_routing_semantic_command_min_score", 0.45), 4),
    }


def _first_blocking_warning(warnings: list[str]) -> str:
    for warning in warnings:
        if warning in BLOCKING_AUTO_WARNINGS:
            if warning == "ambiguous_intent":
                return "semantic_margin_below_threshold"
            return warning
    return "auto_route_blocked"


def _knowledge_not_executed_reason(decision: dict[str, Any]) -> str:
    warnings = list(decision.get("warnings") or [])
    if "ambiguous_kb_candidate" in warnings or "ambiguous_knowledge_base" in warnings:
        return "kb_candidate_ambiguous"
    if "no_kb_candidate_or_active_kbs" in warnings or "no_semantic_kb_candidate" in warnings or "no_matching_knowledge_base" in warnings:
        return "no_kb_candidate"
    if "selected_kb_disabled" in warnings:
        return "selected_kb_disabled"
    if "knowledge_store_unavailable" in warnings:
        return "knowledge_store_unavailable"
    return _first_blocking_warning(warnings) if warnings else "knowledge_override_not_available"


def _image_generation_decision(metadata: dict[str, Any], agent_registry: Any, agent_config_store: Any) -> dict[str, Any]:
    warnings = list(metadata.get("warnings") or [])
    target_agent_id = "comfyui_agent"
    try:
        target_agent = agent_registry.get(target_agent_id)
    except KeyError:
        return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": metadata.get("session_default_agent_id"), "warnings": [*warnings, "comfyui_agent_not_found"]}
    if getattr(target_agent, "type", "") != "script":
        return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": metadata.get("session_default_agent_id"), "warnings": [*warnings, "comfyui_agent_not_script"]}
    if agent_config_store is not None and not agent_config_store.is_enabled(target_agent_id):
        return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": metadata.get("session_default_agent_id"), "warnings": [*warnings, "comfyui_agent_disabled"]}
    return {**metadata, "route_action": "route_agent", "target_agent_id": target_agent_id, "target_action_id": "default", "warnings": warnings}


def _knowledge_query_decision(metadata: dict[str, Any], session: Any, agent: Any, knowledge_store: Any, *, fallback_query: str = "") -> dict[str, Any]:
    warnings = list(metadata.get("warnings") or [])
    slots = metadata.get("slots") if isinstance(metadata.get("slots"), dict) else {}
    query_override = str(slots.get("query") or fallback_query or "").strip()
    if knowledge_store is None:
        return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": [*warnings, "knowledge_store_unavailable"]}
    kb_hint = str(slots.get("kb_hint") or "").strip()
    selected_ids: list[str] = []
    explicit_kb_id = str(metadata.get("kb_id") or "").strip()
    ambiguous_semantic_kb = _semantic_kb_candidate_ambiguous(metadata)
    if ambiguous_semantic_kb:
        warnings.append("ambiguous_kb_candidate")
    if explicit_kb_id and not ambiguous_semantic_kb:
        try:
            kb = knowledge_store.get_knowledge_base(explicit_kb_id)
            if getattr(kb, "enabled", False):
                selected_ids = [kb.id]
                metadata["kb_match_source"] = metadata.get("kb_match_source") or "name"
                if kb_hint and not _kb_hint_matches(kb, kb_hint):
                    selected_ids = []
                    warnings.append("kb_hint_semantic_conflict")
                    metadata["kb_match_source"] = "none"
            else:
                warnings.append("selected_kb_disabled")
        except KeyError:
            warnings.append("no_matching_knowledge_base")
    if not selected_ids:
        if kb_hint and "kb_hint_semantic_conflict" not in warnings:
            match_result = _match_knowledge_bases(knowledge_store, kb_hint)
            selected_ids = match_result["ids"]
            warnings.extend(match_result["warnings"])
            metadata["kb_match_source"] = match_result.get("source", "none")
            if match_result.get("matched_alias"):
                metadata["matched_alias"] = _short_text(str(match_result["matched_alias"]), 80)
            if match_result.get("ambiguous_matches"):
                metadata["ambiguous_matches"] = match_result["ambiguous_matches"]
            if not selected_ids:
                active_ids = _active_session_kb_ids(knowledge_store, getattr(session, "session_id", ""))
                selected_ids = active_ids
                if active_ids:
                    metadata["kb_match_source"] = "active_session"
                if not active_ids:
                    return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": _ensure_warning(warnings, "no_kb_candidate_or_active_kbs")}
        else:
            selected_ids = _active_session_kb_ids(knowledge_store, getattr(session, "session_id", ""))
            if not selected_ids:
                return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": _ensure_warning(warnings, "no_kb_candidate_or_active_kbs")}
            metadata["kb_match_source"] = "active_session"
    return {
        **metadata,
        "route_action": "knowledge_override",
        "target_agent_id": agent.id,
        "target_action_id": "default",
        "temporary_knowledge_base_ids": selected_ids,
        "knowledge_query_override": _short_text(query_override) if query_override else None,
        "warnings": warnings,
    }


def _semantic_kb_candidate_ambiguous(metadata: dict[str, Any]) -> bool:
    top = metadata.get("top_candidates")
    if not isinstance(top, list):
        return False
    kb_candidates: list[dict[str, Any]] = []
    for item in top:
        if not isinstance(item, dict) or item.get("kind") != "knowledge_base":
            continue
        score = item.get("score")
        kb_id = str(item.get("kb_id") or item.get("knowledge_base_id") or "")
        if isinstance(score, (int, float)) and kb_id:
            kb_candidates.append({"kb_id": kb_id, "score": float(score)})
    if len(kb_candidates) < 2:
        return False
    kb_candidates.sort(key=lambda item: item["score"], reverse=True)
    first = kb_candidates[0]
    for candidate in kb_candidates[1:]:
        if candidate["kb_id"] != first["kb_id"] and first["score"] - candidate["score"] < SEMANTIC_AUTO_MIN_MARGIN:
            return True
    return False


def _kb_hint_matches(kb: Any, kb_hint: str) -> bool:
    hint = _normalize_text(kb_hint)
    if not hint:
        return True
    name = _normalize_text(getattr(kb, "name", ""))
    if hint == name or (hint and hint in name) or (name and name in hint):
        return True
    for alias in _comma_values(getattr(kb, "aliases_text", ""), 50, 120):
        alias_norm = _normalize_text(alias)
        if hint == alias_norm or (hint and hint in alias_norm) or (alias_norm and alias_norm in hint):
            return True
    return False


def _ensure_warning(warnings: list[str], warning: str) -> list[str]:
    return warnings if warning in warnings else [*warnings, warning]


def _match_knowledge_bases(knowledge_store: Any, kb_hint: str) -> dict[str, Any]:
    hint = kb_hint.strip()
    normalized = _normalize_text(hint)
    enabled_bases = [kb for kb in knowledge_store.list_knowledge_bases() if getattr(kb, "enabled", False)]
    exact = [kb for kb in enabled_bases if getattr(kb, "name", "") == hint]
    if exact:
        return {"ids": [exact[0].id], "warnings": [], "source": "name"}
    ci_exact = [kb for kb in enabled_bases if _normalize_text(getattr(kb, "name", "")) == normalized]
    if ci_exact:
        return _single_or_ambiguous(ci_exact, "name")
    alias_exact: list[tuple[Any, str]] = []
    for kb in enabled_bases:
        for alias in _comma_values(getattr(kb, "aliases_text", ""), 50, 120):
            if alias == hint or _normalize_text(alias) == normalized:
                alias_exact.append((kb, alias))
    if alias_exact:
        return _single_or_ambiguous([kb for kb, _ in alias_exact], "alias", matched_alias=alias_exact[0][1])
    name_substring = [kb for kb in enabled_bases if normalized and normalized in _normalize_text(getattr(kb, "name", ""))]
    if name_substring:
        return _single_or_ambiguous(name_substring, "name")
    alias_substring: list[tuple[Any, str]] = []
    for kb in enabled_bases:
        for alias in _comma_values(getattr(kb, "aliases_text", ""), 50, 120):
            alias_norm = _normalize_text(alias)
            if normalized and (normalized in alias_norm or alias_norm in normalized):
                alias_substring.append((kb, alias))
    if alias_substring:
        return _single_or_ambiguous([kb for kb, _ in alias_substring], "alias", matched_alias=alias_substring[0][1])
    description = [kb for kb in enabled_bases if normalized and normalized in _normalize_text(getattr(kb, "description", ""))]
    if description:
        return _single_or_ambiguous(description, "description")
    return {"ids": [], "warnings": ["no_matching_knowledge_base"], "source": "none"}


def _single_or_ambiguous(matches: list[Any], source: str, matched_alias: str | None = None) -> dict[str, Any]:
    unique = []
    seen: set[str] = set()
    for item in matches:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    if len(unique) == 1:
        return {"ids": [unique[0].id], "warnings": [], "source": source, "matched_alias": matched_alias}
    return {
        "ids": [],
        "warnings": ["ambiguous_knowledge_base"],
        "source": source,
        "matched_alias": matched_alias,
        "ambiguous_matches": [{"id": item.id, "name": getattr(item, "name", item.id), "source": source} for item in unique[:5]],
    }


def _active_session_kb_ids(knowledge_store: Any, session_id: str) -> list[str]:
    ids: list[str] = []
    if not session_id:
        return ids
    for binding in knowledge_store.list_session_bindings(session_id):
        if not getattr(binding, "enabled", False):
            continue
        kb = getattr(binding, "knowledge_base", None)
        if kb is None:
            try:
                kb = knowledge_store.get_knowledge_base(binding.knowledge_base_id)
            except KeyError:
                continue
        if getattr(kb, "enabled", False):
            ids.append(kb.id)
    return ids


def _detect_kb_hint(knowledge_store: Any, normalized_text: str) -> dict[str, str] | None:
    for candidate in _kb_candidates(knowledge_store):
        name = str(candidate.get("name") or "")
        name_norm = _normalize_text(name)
        if name_norm and name_norm in normalized_text:
            return {"hint": name, "source": "name"}
        for alias in candidate.get("aliases") or []:
            alias_norm = _normalize_text(alias)
            if alias_norm and alias_norm in normalized_text:
                return {"hint": str(alias), "source": "alias", "alias": str(alias)}
    return None


def _match_agent_hints(agent_registry: Any, agent_config_store: Any, normalized_text: str) -> dict[str, str] | None:
    best: dict[str, str] | None = None
    best_score = 0.0
    for candidate in _agent_candidates(agent_registry, agent_config_store):
        name = str(candidate.get("name") or "")
        agent_id = str(candidate.get("id") or "")
        for source, value in [("name", name), ("name", agent_id)]:
            norm = _normalize_text(value)
            if norm and norm in normalized_text and len(norm) >= 3:
                score = 0.7 + min(len(norm), 20) / 100
                if score > best_score:
                    best_score = score
                    best = {"id": agent_id, "source": source, "hint": value}
        for alias in candidate.get("aliases") or []:
            norm = _normalize_text(alias)
            if norm and norm in normalized_text:
                score = 0.82 + min(len(norm), 12) / 100
                if score > best_score:
                    best_score = score
                    best = {"id": agent_id, "source": "alias", "hint": str(alias), "alias": str(alias)}
        for example in candidate.get("examples") or []:
            norm = _normalize_text(example)
            overlap = _jaccard_score(normalized_text, norm)
            if norm and (norm in normalized_text or overlap >= 0.45):
                score = 0.76 if norm in normalized_text else 0.45 + overlap
                if score > best_score:
                    best_score = score
                    best = {"id": agent_id, "source": "examples", "hint": agent_id, "example": str(example)}
    return best


def _compact_slots(slots: dict[str, Any]) -> dict[str, str]:
    compact: dict[str, str] = {}
    for key in ("target_agent_hint", "kb_hint", "query", "command_hint"):
        value = slots.get(key)
        if isinstance(value, str) and value.strip():
            compact[key] = _short_text(value.strip())
    return compact


def _short_text(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    keep = (limit - 3) // 2
    return f"{value[:keep]}...{value[-keep:]}"


async def _maybe_apply_utility_extractor(
    *,
    text: str,
    prediction: dict[str, Any],
    settings: Any,
    utility_llm_service: Any = None,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    knowledge_store: Any = None,
) -> dict[str, Any]:
    if utility_llm_service is None or settings is None:
        return prediction
    if not getattr(settings, "intent_routing_utility_llm_model_path", ""):
        return prediction
    predicted_intent = str(prediction.get("predicted_intent") or "chat")
    confidence = float(prediction.get("confidence") or 0.0)
    high_threshold = float(getattr(settings, "intent_routing_high_confidence_threshold", 0.78) or 0.78)
    should_extract = confidence < high_threshold or predicted_intent in {"knowledge_query", "agent_route"}
    if not should_extract:
        return prediction
    try:
        context = compact_utility_context(
            settings=settings,
            agent_registry=agent_registry,
            agent_config_store=agent_config_store,
            knowledge_store=knowledge_store,
        )
        try:
            extracted = await utility_llm_service.extract_intent_json(text, settings, context=context)
        except TypeError:
            extracted = await utility_llm_service.extract_intent_json(text, settings)
    except Exception:
        return {**prediction, "warnings": [*list(prediction.get("warnings") or []), "utility_extractor_failed"]}
    intent_id = extracted.get("intent") or "unknown"
    definition = intent_definition(intent_id)
    slots = {
        key: value
        for key, value in {
            "target_agent_hint": extracted.get("target_agent_hint"),
            "kb_hint": extracted.get("kb_hint"),
            "query": extracted.get("query"),
            "command_hint": extracted.get("command_hint"),
        }.items()
        if value
    }
    target_agent_id = extracted.get("target_agent_id") or prediction.get("target_agent_id")
    agent_match_source = prediction.get("agent_match_source")
    matched_alias = prediction.get("matched_alias")
    if not target_agent_id and slots.get("target_agent_hint"):
        agent_match = _match_agent_hints(agent_registry, agent_config_store, _normalize_text(slots["target_agent_hint"]))
        if agent_match:
            target_agent_id = agent_match.get("id")
            agent_match_source = agent_match.get("source") or agent_match_source
            if agent_match.get("alias"):
                matched_alias = _short_text(str(agent_match["alias"]), 80)
    kb_id = extracted.get("kb_id")
    match_source = extracted.get("match_source")
    kb_match_source = prediction.get("kb_match_source")
    if intent_id == "knowledge_query" and match_source:
        kb_match_source = match_source
    elif intent_id == "agent_route" and match_source:
        agent_match_source = match_source
    final_target_agent_id = target_agent_id
    if definition is not None and definition.target_agent_id:
        final_target_agent_id = definition.target_agent_id
    merged = {
        **prediction,
        "source": "rule_based_shadow+utility_llm",
        "predicted_intent": intent_id,
        "confidence": extracted.get("confidence", prediction.get("confidence", 0.0)),
        "target_agent_id": final_target_agent_id,
        "kb_id": kb_id,
        "kb_match_source": kb_match_source,
        "agent_match_source": agent_match_source,
        "slots": slots,
        "warnings": list(prediction.get("warnings") or []),
    }
    if matched_alias:
        merged["matched_alias"] = matched_alias
    return merged


async def _maybe_apply_utility_slots(
    *,
    text: str,
    prediction: dict[str, Any],
    settings: Any,
    utility_llm_service: Any = None,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    knowledge_store: Any = None,
) -> dict[str, Any]:
    if utility_llm_service is None or settings is None:
        return prediction
    if not getattr(settings, "intent_routing_utility_llm_model_path", ""):
        return prediction
    predicted_intent = str(prediction.get("predicted_intent") or "chat")
    confidence = float(prediction.get("confidence") or 0.0)
    high_threshold = float(getattr(settings, "intent_routing_high_confidence_threshold", 0.78) or 0.78)
    if predicted_intent != "knowledge_query" and confidence >= high_threshold:
        return prediction
    try:
        context = compact_utility_context(
            settings=settings,
            agent_registry=agent_registry,
            agent_config_store=agent_config_store,
            knowledge_store=knowledge_store,
        )
        try:
            extracted = await utility_llm_service.extract_intent_json(text, settings, context=context)
        except TypeError:
            extracted = await utility_llm_service.extract_intent_json(text, settings)
    except Exception:
        return {**prediction, "warnings": [*list(prediction.get("warnings") or []), "utility_extractor_failed"]}
    slots = dict(prediction.get("slots") or {}) if isinstance(prediction.get("slots"), dict) else {}
    if predicted_intent == "knowledge_query":
        if extracted.get("kb_hint"):
            slots["kb_hint"] = extracted.get("kb_hint")
            prediction = {**prediction, "matched_alias": extracted.get("kb_hint")}
        if extracted.get("query"):
            slots["query"] = extracted.get("query")
        if extracted.get("kb_id"):
            prediction = {**prediction, "kb_id": extracted.get("kb_id")}
    elif extracted.get("query") and confidence < high_threshold:
        slots.setdefault("query", extracted.get("query"))
    return {
        **prediction,
        "source": "embedding_semantic_router+utility_llm",
        "slots": slots,
        "warnings": list(prediction.get("warnings") or []),
    }


def _bypass_reason(session: Any, route: RouteTarget) -> str | None:
    if route.kind == RouteKind.COMMAND:
        return "explicit_command"
    if route.kind == RouteKind.RESUME:
        return "waiting_run"
    if route.kind != RouteKind.AGENT:
        return "not_agent_route"
    raw = route.raw_input or ""
    if raw.startswith("@"):
        return "explicit_agent"
    if raw.startswith(":"):
        return "explicit_action"
    if (route.action_id or "default") != "default":
        return "non_default_action"
    if route.target_id != getattr(session, "default_agent_id", None):
        return "not_default_agent"
    if (getattr(session, "context_mode", "single_assistant") or "single_assistant") != "single_assistant":
        return "group_transcript"
    return None
