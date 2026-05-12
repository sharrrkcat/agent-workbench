from dataclasses import dataclass, field
from typing import Any

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

    def classify(self, text: str) -> dict[str, Any]:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return self._prediction("chat", 0.0, warnings=["empty_input"])
        best_intent = "chat"
        best_score = 0.35
        for intent in INTENT_DEFINITIONS:
            score = self._score_intent(normalized, intent)
            if score > best_score:
                best_intent = intent.id
                best_score = score
        return self._prediction(best_intent, min(best_score, 0.95))

    def _score_intent(self, text: str, intent: IntentDefinition) -> float:
        score = 0.0
        for keyword in intent.keywords:
            lowered = keyword.lower()
            if lowered and lowered in text:
                score = max(score, 0.62 + min(len(lowered), 18) / 100)
        for example in intent.examples:
            lowered = example.lower()
            if lowered and lowered in text:
                score = max(score, 0.82)
        return score

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
    prediction = (classifier or RuleBasedIntentClassifier()).classify(route.args)
    prediction = await _maybe_apply_utility_extractor(
        text=route.args,
        prediction=prediction,
        settings=settings,
        utility_llm_service=utility_llm_service,
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
    if kb_hint:
        match_result = _match_knowledge_bases(knowledge_store, kb_hint)
        selected_ids = match_result["ids"]
        warnings.extend(match_result["warnings"])
        if not selected_ids:
            active_ids = _active_session_kb_ids(knowledge_store, getattr(session, "session_id", ""))
            selected_ids = active_ids
            if not active_ids:
                return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": warnings}
    else:
        selected_ids = _active_session_kb_ids(knowledge_store, getattr(session, "session_id", ""))
        if not selected_ids:
            return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": [*warnings, "no_kb_hint_no_active_kbs"]}
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
    normalized = hint.lower()
    enabled_bases = [kb for kb in knowledge_store.list_knowledge_bases() if getattr(kb, "enabled", False)]
    exact = [kb for kb in enabled_bases if getattr(kb, "name", "") == hint]
    if exact:
        return {"ids": [exact[0].id], "warnings": []}
    ci_exact = [kb for kb in enabled_bases if getattr(kb, "name", "").lower() == normalized]
    if ci_exact:
        return {"ids": [ci_exact[0].id], "warnings": []}
    substring = [kb for kb in enabled_bases if normalized in getattr(kb, "name", "").lower() or normalized in getattr(kb, "description", "").lower()]
    if len(substring) == 1:
        return {"ids": [substring[0].id], "warnings": []}
    if len(substring) > 1:
        return {"ids": [], "warnings": ["ambiguous_knowledge_base"]}
    return {"ids": [], "warnings": ["no_matching_knowledge_base"]}


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
    return {
        **prediction,
        "source": "rule_based_shadow+utility_llm",
        "predicted_intent": intent_id,
        "confidence": extracted.get("confidence", prediction.get("confidence", 0.0)),
        "target_agent_id": definition.target_agent_id if definition is not None else prediction.get("target_agent_id"),
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
