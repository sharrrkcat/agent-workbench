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


async def build_intent_routing_metadata(
    *,
    session: Any,
    route: RouteTarget,
    agent_registry: Any,
    agent_config_store: Any = None,
    app_settings_store: Any = None,
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
    if mode != "shadow":
        return {**base, "bypass_reason": "unsupported_mode"}
    prediction = (classifier or RuleBasedIntentClassifier()).classify(route.args)
    prediction = await _maybe_apply_utility_extractor(
        text=route.args,
        prediction=prediction,
        settings=settings,
        utility_llm_service=utility_llm_service,
    )
    return {
        "enabled": True,
        "mode": "shadow",
        "eligible": True,
        "bypassed": False,
        **prediction,
    }


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
