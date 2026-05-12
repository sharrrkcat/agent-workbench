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


SAFE_AUTO_ROUTE_INTENTS = {"chat", "image_generation", "knowledge_query"}
COMMAND_LIKE_WARNING = "command_like_auto_route_disabled"
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
    classifier: RuleBasedIntentClassifier | None = None,
    utility_llm_service: Any = None,
) -> dict[str, Any] | None:
    settings = app_settings_store.get() if app_settings_store is not None else None
    mode = getattr(settings, "intent_routing_mode", "shadow")
    base = {
        "enabled": bool(getattr(settings, "intent_routing_enabled", False)),
        "mode": mode,
        "eligible": False,
        "bypassed": True,
    }
    bypass_reason = _bypass_reason(session, route)
    if bypass_reason:
        return {**base, "bypass_reason": bypass_reason}
    try:
        agent = agent_registry.get(route.target_id or "")
    except KeyError:
        return {**base, "bypass_reason": "agent_not_found"}
    config = agent_config_store.get_config(agent.id) if agent_config_store is not None else {}
    effective = resolved_intent_routing_mode(agent, config, settings=settings)
    if agent.type != "prompt":
        return {**base, "bypass_reason": "default_agent_not_prompt"}
    if not bool(effective["enabled"]):
        return {**base, "bypass_reason": str(effective.get("reason") or "disabled")}
    if mode not in {"shadow", "auto"}:
        return {**base, "bypass_reason": "unsupported_mode"}
    prediction = (classifier or RuleBasedIntentClassifier()).classify(
        route.args,
        settings=settings,
        agent_registry=agent_registry,
        agent_config_store=agent_config_store,
        knowledge_store=knowledge_store,
    )
    prediction = await _maybe_apply_utility_extractor(
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
    high_threshold = float(getattr(settings, "intent_routing_high_confidence_threshold", 0.78) or 0.78)
    low_threshold = float(getattr(settings, "intent_routing_low_confidence_threshold", 0.55) or 0.55)
    intent_id = str(prediction.get("predicted_intent") or "chat")
    confidence = float(prediction.get("confidence") or 0.0)
    slots = _compact_slots(prediction.get("slots") if isinstance(prediction.get("slots"), dict) else {})
    warnings = list(prediction.get("warnings") or [])
    metadata = {
        **prediction,
        "predicted_intent": intent_id,
        "confidence": round(confidence, 2),
        "slots": slots,
        "warnings": warnings,
        "route_action": "none",
        "target_agent_id": prediction.get("target_agent_id") or route.target_id,
        "target_action_id": route.action_id or "default",
        "session_default_agent_id": getattr(session, "default_agent_id", None),
        "session_default_changed": False,
        "session_bindings_changed": False,
        "kb_match_source": prediction.get("kb_match_source") or "none",
        "agent_match_source": prediction.get("agent_match_source") or "none",
    }
    if mode != "auto":
        return metadata
    if not bool(getattr(settings, "intent_routing_auto_route_safe_intents", False)):
        metadata["route_action"] = "none"
        metadata["warnings"] = [*warnings, "safe_auto_route_disabled"]
        return metadata
    if intent_id in {"command_like", "agent_route"}:
        metadata["route_action"] = "confirmation_needed_future"
        warning = COMMAND_LIKE_WARNING if intent_id == "command_like" else "agent_route_auto_route_disabled"
        metadata["warnings"] = [*warnings, warning]
        return metadata
    if confidence < high_threshold:
        reason = "confidence_below_high_threshold" if confidence >= low_threshold else "confidence_below_low_threshold"
        metadata["route_action"] = "fallback_current_agent"
        metadata["warnings"] = [*warnings, reason]
        return metadata
    if intent_id not in SAFE_AUTO_ROUTE_INTENTS:
        metadata["route_action"] = "confirmation_needed_future" if intent_id in {"command_like", "agent_route"} else "fallback_current_agent"
        warning = COMMAND_LIKE_WARNING if intent_id == "command_like" else "auto_route_not_supported"
        metadata["warnings"] = [*warnings, warning]
        return metadata
    if intent_id == "chat":
        metadata["route_action"] = "none"
        metadata["target_agent_id"] = agent.id
        metadata["target_action_id"] = "default"
        return metadata
    if intent_id == "image_generation":
        return _image_generation_decision(metadata, agent_registry, agent_config_store)
    if intent_id == "knowledge_query":
        return _knowledge_query_decision(metadata, session, agent, knowledge_store)
    return metadata


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


def _knowledge_query_decision(metadata: dict[str, Any], session: Any, agent: Any, knowledge_store: Any) -> dict[str, Any]:
    warnings = list(metadata.get("warnings") or [])
    slots = metadata.get("slots") if isinstance(metadata.get("slots"), dict) else {}
    query_override = str(slots.get("query") or "").strip()
    if knowledge_store is None:
        return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": [*warnings, "knowledge_store_unavailable"]}
    kb_hint = str(slots.get("kb_hint") or "").strip()
    selected_ids: list[str] = []
    explicit_kb_id = str(metadata.get("kb_id") or "").strip()
    if explicit_kb_id:
        try:
            kb = knowledge_store.get_knowledge_base(explicit_kb_id)
            if getattr(kb, "enabled", False):
                selected_ids = [kb.id]
                metadata["kb_match_source"] = metadata.get("kb_match_source") or "name"
        except KeyError:
            warnings.append("no_matching_knowledge_base")
    if not selected_ids:
        if kb_hint:
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
                    return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": warnings}
        else:
            selected_ids = _active_session_kb_ids(knowledge_store, getattr(session, "session_id", ""))
            if not selected_ids:
                return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": [*warnings, "no_kb_hint_no_active_kbs"]}
            metadata["kb_match_source"] = "active_session"
    return {
        **metadata,
        "route_action": "knowledge_override",
        "target_agent_id": agent.id,
        "target_action_id": "default",
        "temporary_knowledge_base_ids": selected_ids,
        "knowledge_query_override": query_override or None,
        "warnings": warnings,
    }


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
