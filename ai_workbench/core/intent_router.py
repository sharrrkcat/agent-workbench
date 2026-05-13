from dataclasses import dataclass
from typing import Any
import inspect
import re

from ai_workbench.core.agent_settings import resolved_intent_routing_mode
from ai_workbench.core.intent_pipeline import IntentPipelineContext, build_executor_plan, validate_intent
from ai_workbench.core.intent_specs import compact_specs_for_utility, get_action_spec, get_action_spec_for_intent_action, get_builtin_route_specs, get_route_spec
from ai_workbench.core.schema.route import RouteKind, RouteTarget


@dataclass(frozen=True)
class IntentDefinition:
    id: str
    label: str
    description: str
    examples: list[str]
    safe_auto_route: bool = False
    target_agent_id: str | None = None


INTENT_DEFINITIONS: tuple[IntentDefinition, ...] = (
    IntentDefinition(
        id="chat",
        label="Chat",
        description="General conversation, writing, translation, and follow-up help.",
        examples=["继续", "解释一下", "还有什么方法", "translate this", "help me write"],
        safe_auto_route=True,
    ),
    IntentDefinition(
        id="image_generation",
        label="Image generation",
        description="Requests to create or draw an image.",
        examples=["帮我生成一张图片", "画一张图", "make an image", "generate a picture", "生成角色立绘"],
        target_agent_id="comfyui_agent",
    ),
    IntentDefinition(
        id="knowledge_query",
        label="Knowledge query",
        description="Questions that ask for project, document, or knowledge base grounded answers.",
        examples=["知识库里说了什么", "根据项目文档回答", "星球大战知识库里的内容", "what does the documentation say"],
    ),
    IntentDefinition(
        id="agent_route",
        label="Agent route",
        description="Requests that appear to ask for another agent or specialized route.",
        examples=["找翻译 agent", "交给图片助手", "route this to the image agent"],
    ),
    IntentDefinition(
        id="pet_command",
        label="Pet command",
        description="Narrow Workbench Pet status, wake, tuck, select, and reload commands.",
        examples=[
            "我想看看宠物状态",
            "看看 Jedi Cal 状态",
            "Jedi Cal 目前怎么样",
            "唤醒宠物",
            "召唤宠物 Cal",
            "把宠物叫出来",
            "隐藏 Jedi Cal",
            "把宠物换成 BD-1",
            "切换到 Jedi Cal",
            "重新加载宠物",
            "刷新宠物",
            "show pet status",
            "wake the pet",
            "switch pet to BD-1",
        ],
    ),
    IntentDefinition(
        id="command_like",
        label="Command-like",
        description="Requests that resemble operational commands or cleanup actions.",
        examples=["释放显存", "清理内存", "删除这个", "运行命令"],
    ),
)


SAFE_AUTO_ROUTE_INTENTS = {"chat", "knowledge_query", "pet_command"}
PIPELINE_VERSION = "semantic_utility_validator_v1"
UTILITY_REQUIRED_INTENTS = {"knowledge_query", "pet_command"}
PET_ACTIONS = {"status", "wake", "tuck", "select", "reload"}
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
    "pet_candidate_not_found",
    "ambiguous_pet_candidate",
    "target_pet_not_current",
    "select_target_missing",
    "source_pet_mismatch",
    "source_pet_not_found",
    "ambiguous_source_pet_candidate",
    "pet_command_context_missing",
    "pet_action_unrecognized",
    "pet_command_runtime_unavailable",
    "utility_llm_required",
    "utility_llm_unavailable",
    "utility_llm_slots_failed",
    "utility_semantic_action_conflict",
    "validation_failed",
    "pet_domain_not_workbench_pet",
    "not_workbench_pet_context",
    "knowledge_query_missing_query",
    "kb_hint_semantic_conflict",
    "ambiguous_kb_candidate",
    "no_kb_candidate_or_active_kbs",
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

# RouteSpec is the source of built-in route examples for Intent Routing v2.
# The legacy IntentDefinition block above remains temporarily for import
# compatibility and will be removed when Round 4 migrates the old adapters.
INTENT_DEFINITIONS = get_builtin_route_specs()


def compact_utility_context(
    *,
    settings: Any = None,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    knowledge_store: Any = None,
    pet_candidates: list[dict[str, Any]] | None = None,
    prediction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec_context = compact_specs_for_utility(prediction)
    payload = {
        **spec_context,
        "intents": [
            {
                "id": intent.id,
                "execution_mode": getattr(intent, "execution_mode", "diagnostic_only"),
                "utility_required": bool(getattr(intent, "utility_required", False)),
                "slot_schema_id": getattr(getattr(intent, "slot_schema", None), "schema_id", None),
                "examples": [*list(intent.examples)[:3], *_line_values(getattr(settings, CUSTOM_EXAMPLE_FIELDS.get(intent.id, ""), ""), 3, MAX_ROUTE_EXAMPLE_CHARS)][:4],
                "examples_preview": [*list(intent.examples)[:3], *_line_values(getattr(settings, CUSTOM_EXAMPLE_FIELDS.get(intent.id, ""), ""), 3, MAX_ROUTE_EXAMPLE_CHARS)][:4],
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
            "non_chat_auto_requires_utility_slots": True,
        },
    }
    if pet_candidates:
        payload["pets"] = pet_candidates[:20]
    return payload


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
    capability_config_store: Any = None,
    runtime_registry: Any = None,
    command_registry: Any = None,
    semantic_router: Any = None,
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
    )
    prediction = await _maybe_apply_utility_slots(
        text=route.args,
        prediction=prediction,
        settings=settings,
        utility_llm_service=utility_llm_service,
        agent_registry=agent_registry,
        agent_config_store=agent_config_store,
        knowledge_store=knowledge_store,
        runtime_registry=runtime_registry,
        capability_config_store=capability_config_store,
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
        capability_config_store=capability_config_store,
        runtime_registry=runtime_registry,
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
    capability_config_store: Any = None,
    runtime_registry: Any = None,
) -> dict[str, Any]:
    intent_id = str(prediction.get("predicted_intent") or "chat")
    confidence = float(prediction.get("confidence") or 0.0)
    thresholds = _semantic_thresholds_used(settings, prediction)
    slots = _compact_slots(prediction.get("slots") if isinstance(prediction.get("slots"), dict) else {})
    warnings = list(prediction.get("warnings") or [])
    metadata = {
        **prediction,
        "pipeline_version": PIPELINE_VERSION,
        "semantic_evaluated": True,
        "predicted_intent": intent_id,
        "confidence": round(confidence, 2),
        "intent_score": _rounded_optional(prediction.get("semantic_score")),
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
        "utility_required": bool(prediction.get("utility_required", intent_id in UTILITY_REQUIRED_INTENTS)),
        "utility_available": bool(prediction.get("utility_available", False)),
        "utility_used": bool(prediction.get("utility_used", False)),
        "utility_ok": bool(prediction.get("utility_ok", False)),
        "utility_error_code": prediction.get("utility_error_code"),
        "validation_ok": False,
        "executor_plan": prediction.get("executor_plan") if isinstance(prediction.get("executor_plan"), dict) else {},
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
    route_spec = get_route_spec(intent_id)
    action_spec = None
    action_candidate = prediction.get("action_candidate")
    if isinstance(action_candidate, dict):
        action_spec = get_action_spec(action_candidate.get("action_spec_id"))
    slot_action = slots.get("action") if isinstance(slots, dict) else None
    if action_spec is None and slot_action:
        action_spec = get_action_spec_for_intent_action(intent_id, slot_action)
    metadata.update(
        {
            "route_spec_id": route_spec.id if route_spec else intent_id,
            "action_spec_id": action_spec.id if action_spec else None,
            "slot_schema_id": route_spec.slot_schema.schema_id if route_spec and route_spec.slot_schema else None,
            "validator_id": route_spec.validator_id if route_spec else None,
            "executor_id": route_spec.executor_id if route_spec else None,
            "executor_plan_type": route_spec.executor_id if route_spec and route_spec.executor_id else "none",
        }
    )
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
        if intent_id in UTILITY_REQUIRED_INTENTS and metadata.get("utility_ok"):
            return _with_pipeline_result(
                metadata,
                session=session,
                route=route,
                agent=agent,
                settings=settings,
                knowledge_store=knowledge_store,
                runtime_registry=runtime_registry,
                capability_config_store=capability_config_store,
                auto_mode=False,
            )
        if intent_id in UTILITY_REQUIRED_INTENTS and not metadata.get("utility_ok"):
            reason = str(metadata.get("utility_error_code") or "utility_llm_required")
            metadata["not_executed_reason"] = reason if reason in {"utility_llm_required", "utility_llm_unavailable", "utility_llm_slots_failed", "utility_semantic_action_conflict"} else "utility_llm_unavailable"
            metadata["warnings"] = _ensure_warning(warnings, metadata["not_executed_reason"])
            metadata["executor_plan"] = {"route_action": "metadata_only", "auto_executable": False}
        return metadata
    if not bool(getattr(settings, "intent_routing_auto_route_safe_intents", False)):
        metadata["route_action"] = "metadata_only"
        metadata["auto_executable"] = False
        metadata["not_executed_reason"] = "safe_auto_route_disabled"
        metadata["warnings"] = [*warnings, "safe_auto_route_disabled"]
        metadata["executor_plan"] = {"route_action": "metadata_only", "auto_executable": False, "would_execute": False}
        return metadata
    if intent_id in DIAGNOSTIC_ONLY_WARNINGS:
        metadata["route_action"] = "metadata_only"
        metadata["auto_executable"] = False
        warning = DIAGNOSTIC_ONLY_WARNINGS.get(intent_id, "auto_route_not_supported")
        metadata["diagnostic_reason"] = warning
        metadata["not_executed_reason"] = warning
        metadata["warnings"] = [*warnings, warning]
        metadata["executor_plan"] = {"route_action": "metadata_only", "auto_executable": False, "would_execute": False}
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
    if intent_id in UTILITY_REQUIRED_INTENTS and not metadata.get("utility_ok"):
        reason = str(metadata.get("utility_error_code") or "utility_llm_required")
        if reason not in {"utility_llm_required", "utility_llm_unavailable", "utility_llm_slots_failed", "utility_semantic_action_conflict"}:
            reason = "utility_llm_unavailable"
        metadata["route_action"] = "fallback_current_agent"
        metadata["auto_executable"] = False
        metadata["executed"] = False
        metadata["would_execute"] = False
        metadata["not_executed_reason"] = reason
        metadata["validation_ok"] = False
        metadata["executor_plan"] = {"route_action": "fallback_current_agent", "auto_executable": False}
        metadata["warnings"] = _ensure_warning(warnings, reason)
        return metadata
    if intent_id == "chat":
        metadata["route_action"] = "current_prompt_agent"
        metadata["auto_executable"] = True
        metadata["executed"] = True
        metadata["would_execute"] = True
        metadata["not_executed_reason"] = None
        metadata["utility_required"] = False
        metadata["utility_available"] = bool(prediction.get("utility_available", False))
        metadata["utility_used"] = False
        metadata["utility_ok"] = False
        metadata["validation_ok"] = True
        metadata["target_agent_id"] = agent.id
        metadata["target_action_id"] = "default"
        metadata["executor_plan"] = {"route_action": "current_prompt_agent", "auto_executable": True}
        return metadata
    if intent_id == "knowledge_query":
        return _with_pipeline_result(
            metadata,
            session=session,
            route=route,
            agent=agent,
            settings=settings,
            knowledge_store=knowledge_store,
            runtime_registry=runtime_registry,
            capability_config_store=capability_config_store,
            auto_mode=True,
        )
    if intent_id == "pet_command":
        return _with_pipeline_result(
            metadata,
            session=session,
            route=route,
            agent=agent,
            settings=settings,
            knowledge_store=knowledge_store,
            runtime_registry=runtime_registry,
            capability_config_store=capability_config_store,
            auto_mode=True,
        )
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
    semantic_unavailable = bool(prediction.get("warnings") and any(str(item).startswith("semantic_router_") for item in prediction.get("warnings") or []))
    if semantic_unavailable:
        prediction = {**prediction, "source": "semantic_router_unavailable", "predicted_intent": "chat", "confidence": 0.0, "route_action": "fallback_current_agent", "auto_executable": False}
    return prediction


def _with_pipeline_result(
    metadata: dict[str, Any],
    *,
    session: Any,
    route: RouteTarget,
    agent: Any,
    settings: Any,
    knowledge_store: Any = None,
    runtime_registry: Any = None,
    capability_config_store: Any = None,
    auto_mode: bool,
) -> dict[str, Any]:
    slots = metadata.get("slots") if isinstance(metadata.get("slots"), dict) else {}
    context = IntentPipelineContext(
        mode=str(metadata.get("mode") or getattr(settings, "intent_routing_mode", "shadow")),
        session=session,
        route=route,
        agent=agent,
        settings=settings,
        knowledge_store=knowledge_store,
        runtime_registry=runtime_registry,
        capability_config_store=capability_config_store,
        auto_mode=auto_mode,
    )
    validation = validate_intent(metadata, slots, context)
    plan = build_executor_plan(validation, context, metadata)
    normalized = validation.normalized_slots or slots
    result = {
        **metadata,
        "validation_ok": validation.ok,
        "not_executed_reason": None if validation.ok else validation.not_executed_reason,
        "warnings": validation.warnings,
        "executor_plan": plan.compact_dict(),
        "route_action": plan.route_action if validation.ok and auto_mode else ("metadata_only" if validation.ok else "fallback_current_agent"),
        "auto_executable": bool(validation.ok and plan.auto_executable),
        "would_execute": bool(validation.ok and plan.would_execute),
        "executed": bool(validation.ok and plan.would_execute),
    }
    if metadata.get("predicted_intent") == "knowledge_query":
        result["target_agent_id"] = plan.target_agent_id or getattr(agent, "id", None)
        result["target_action_id"] = plan.target_action_id or "default"
        result["kb_match_source"] = normalized.get("kb_match_source") or result.get("kb_match_source") or "none"
        if normalized.get("selected_knowledge_base_ids"):
            result["temporary_knowledge_base_ids"] = list(normalized["selected_knowledge_base_ids"])
        if normalized.get("query"):
            result["knowledge_query_override"] = _short_text(str(normalized["query"]))
        if normalized.get("kb_hint"):
            result["matched_alias"] = _short_text(str(normalized["kb_hint"]), 80)
        result["session_bindings_changed"] = False
        result["session_default_changed"] = False
    if metadata.get("predicted_intent") == "pet_command":
        result["pet_action"] = normalized.get("action")
        result["target_pet_hint"] = normalized.get("target_pet_hint")
        result["target_pet_id"] = normalized.get("target_pet_id")
        result["source_pet_hint"] = normalized.get("source_pet_hint")
        result["source_pet_id"] = normalized.get("source_pet_id")
        result["generated_command"] = normalized.get("generated_command") or plan.generated_command
        result["target_command"] = "/pet"
        result["action_match_source"] = normalized.get("action_match_source") or result.get("action_match_source")
    return result


PET_CONTEXT_TERMS = ("宠物", "电子宠物", "虚拟宠物", "桌宠", "pet", "小助手", "小人")
PET_OPERATION_TERMS = (
    "状态",
    "目前怎么样",
    "唤醒",
    "召唤",
    "唤出",
    "叫出来",
    "叫醒",
    "出来",
    "出来一下",
    "隐藏",
    "藏起来",
    "换成",
    "切换",
    "重新加载",
    "刷新",
    "重载",
    "status",
    "wake",
    "summon",
    "bring out",
    "show pet",
    "hide",
    "tuck",
    "switch",
    "reload",
    "refresh",
)


def _parse_pet_command_text(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw or raw.startswith(("/", "@", ":")):
        return None
    compact = _normalize_text(raw)
    has_context = any(term.casefold() in compact for term in PET_CONTEXT_TERMS)
    has_operation = any(term.casefold() in compact for term in PET_OPERATION_TERMS)
    if not has_context and not has_operation:
        return None

    patterns: list[tuple[str, str, tuple[str, ...]]] = [
        ("select_swap", "select", (r"^把\s*(?P<source>.+?)\s*换成\s*(?P<target>.+?)\s*$",)),
        ("select", "select", (r"^把宠物换成\s*(?P<target>.+?)\s*$", r"^切换到\s*(?P<target>.+?)\s*$", r"^switch\s+(?:pet\s+)?to\s+(?P<target>.+?)\s*$")),
        (
            "wake",
            "wake",
            (
                r"^唤醒\s*(?P<target>.+?)?\s*$",
                r"^召唤\s*(?P<target>.+?)?\s*$",
                r"^唤出\s*(?P<target>.+?)?\s*$",
                r"^叫醒\s*(?P<target>.+?)?\s*$",
                r"^把\s*(?P<target>.+?)\s*(?:叫出来|唤出|叫醒)\s*$",
                r"^(?P<target>.+?)\s*(?:出来|出来一下)\s*$",
                r"^(?:wake|summon|bring\s+out)\s+(?:the\s+)?(?P<target>.+?)?\s*$",
                r"^show\s+(?:the\s+)?pet(?:\s+(?!(?:status)\s*$)(?P<target>.+?))?\s*$",
            ),
        ),
        ("tuck", "tuck", (r"^隐藏\s*(?P<target>.+?)?\s*$", r"^把\s*(?P<target>.+?)\s*藏起来\s*$", r"^把\s*(?P<target>.+?)\s*隐藏\s*$", r"^(?:hide|tuck)\s+(?:the\s+)?(?P<target>.+?)?\s*$")),
        ("reload", "reload", (r"^重新加载\s*(?P<target>.+?)?\s*$", r"^刷新\s*(?P<target>.+?)?\s*$", r"^重载\s*(?P<target>.+?)?\s*$", r"^(?:reload|refresh)\s+(?:the\s+)?(?P<target>.+?)?\s*$")),
        ("status", "status", (r"^我想看看宠物状态\s*$", r"^看看\s*(?P<target>.+?)?\s*状态\s*$", r"^(?P<target>.+?)\s*目前怎么样\s*$", r"^(?:show\s+)?(?:the\s+)?(?P<target>.+?)?\s*status\s*$")),
    ]
    for _, action, regexes in patterns:
        for regex in regexes:
            match = re.match(regex, raw, flags=re.IGNORECASE)
            if not match:
                continue
            target = _clean_pet_hint(match.groupdict().get("target"))
            source = _clean_pet_hint(match.groupdict().get("source"))
            if target in {"宠物", "桌宠", "电子宠物", "虚拟宠物", "pet", "the pet"}:
                target = None
            if source in {"宠物", "桌宠", "电子宠物", "虚拟宠物", "pet", "the pet"}:
                source = None
            if not has_context and not target and action != "status":
                return None
            return {"pet_action": action, "target_pet_hint": target, "source_pet_hint": source, "has_pet_context": has_context}
    return None


def _clean_pet_hint(value: Any) -> str | None:
    text = str(value or "").strip()
    text = re.sub(r"^(?:宠物|桌宠|电子宠物|虚拟宠物)\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^(?:the\s+)?pet\s+", "", text, flags=re.IGNORECASE).strip()
    return _short_text(text, 120) if text else None


def _pet_command_decision(
    metadata: dict[str, Any],
    *,
    text: str,
    mode: str,
    runtime_registry: Any = None,
    capability_config_store: Any = None,
    auto_mode: bool,
) -> dict[str, Any]:
    warnings = list(metadata.get("warnings") or [])
    slots = metadata.get("slots") if isinstance(metadata.get("slots"), dict) else {}
    action = str(slots.get("action") or "").strip()
    domain = str(slots.get("domain") or "").strip()
    target_hint = slots.get("target_pet_hint")
    source_hint = slots.get("source_pet_hint")
    if not action or action not in PET_ACTIONS:
        reason = "pet_action_unrecognized"
        return {**metadata, "route_action": "fallback_current_agent", "auto_executable": False, "executed": False, "would_execute": False, "not_executed_reason": reason, "validation_ok": False, "warnings": _ensure_warning(warnings, reason)}
    if domain != "workbench_pet":
        reason = "pet_domain_not_workbench_pet"
        return {**metadata, "pet_action": action, "route_action": "fallback_current_agent", "auto_executable": False, "executed": False, "would_execute": False, "not_executed_reason": reason, "validation_ok": False, "warnings": _ensure_warning(warnings, reason)}
    pets_state = _load_pet_candidates(runtime_registry, capability_config_store)
    if pets_state.get("warning"):
        reason = str(pets_state["warning"])
        return {**metadata, "pet_action": action, "route_action": "fallback_current_agent", "auto_executable": False, "executed": False, "would_execute": False, "not_executed_reason": reason, "validation_ok": False, "warnings": _ensure_warning(warnings, reason)}

    target = _resolve_pet_hint(target_hint, pets_state) if target_hint else pets_state.get("default_pet")
    source = _resolve_pet_hint(source_hint, pets_state) if source_hint else None
    reason = None
    if target_hint and target.get("reason"):
        reason = str(target["reason"])
    elif action == "select" and not target_hint:
        reason = "pet_candidate_not_found"
    elif source_hint and source.get("reason"):
        reason = str(source["reason"])
    elif source and source.get("pet") and pets_state.get("default_pet", {}).get("pet") and source["pet"]["id"] != pets_state["default_pet"]["pet"]["id"]:
        reason = "source_pet_mismatch"
    elif (
        action in {"wake", "tuck", "reload"}
        and target_hint
        and target.get("pet")
        and pets_state.get("default_pet", {}).get("pet")
        and target["pet"]["id"] != pets_state["default_pet"]["pet"]["id"]
    ):
        reason = "target_pet_not_current"
    if reason is None and not target.get("pet") and action != "status":
        reason = "pet_candidate_not_found"

    target_pet = target.get("pet") if isinstance(target, dict) else None
    source_pet = source.get("pet") if isinstance(source, dict) else None
    generated_command = _generated_pet_command(action, target_pet.get("id") if action == "select" and isinstance(target_pet, dict) else None)
    decision = {
        **metadata,
        "predicted_intent": "pet_command",
        "pet_action": action,
        "target_pet_hint": target_hint,
        "target_pet_id": target_pet.get("id") if isinstance(target_pet, dict) else None,
        "target_pet_name": target_pet.get("display_name") if isinstance(target_pet, dict) else None,
        "source_pet_hint": source_hint,
        "source_pet_id": source_pet.get("id") if isinstance(source_pet, dict) else None,
        "source_pet_name": source_pet.get("display_name") if isinstance(source_pet, dict) else None,
        "generated_command": generated_command,
        "target_command": "/pet",
        "route_action": "pet_command" if reason is None else "fallback_current_agent",
        "auto_executable": reason is None and auto_mode,
        "executed": reason is None and auto_mode,
        "would_execute": reason is None and auto_mode,
        "not_executed_reason": reason,
        "validation_ok": reason is None,
        "executor_plan": {
            "route_action": "pet_command" if reason is None else "fallback_current_agent",
            "auto_executable": reason is None and auto_mode,
            "generated_command": generated_command if reason is None else None,
            "target_pet_id": target_pet.get("id") if isinstance(target_pet, dict) else None,
        },
        "warnings": warnings if reason is None else _ensure_warning(warnings, reason),
    }
    if not auto_mode and reason is None:
        decision["auto_executable"] = True
        decision["would_execute"] = mode == "auto"
        decision["executed"] = False
    return decision


def _generated_pet_command(action: str, target_pet_id: str | None) -> str:
    if action == "select" and target_pet_id:
        return f"/pet select {target_pet_id}"
    if action == "status":
        return "/pet status"
    return f"/pet {action}"


def _load_pet_candidates(runtime_registry: Any, capability_config_store: Any) -> dict[str, Any]:
    if runtime_registry is None:
        return {"pets": [], "default_pet": {}, "warning": "pet_command_runtime_unavailable"}
    context = {"capability_config_store": capability_config_store, "capability_id": "pet"}
    try:
        settings_method = runtime_registry.get_method("pet", "get_settings")
        list_method = runtime_registry.get_method("pet", "list_pets")
        settings = _call_pet_runtime_method(settings_method, context).get("settings", {})
        pets = [pet for pet in _call_pet_runtime_method(list_method, context).get("pets", []) if pet.get("valid")]
    except Exception:
        return {"pets": [], "default_pet": {}, "warning": "pet_command_runtime_unavailable"}
    default_id = str(settings.get("default_pet_id") or "").strip()
    default_pet = next((pet for pet in pets if pet.get("id") == default_id), None) or (pets[0] if pets else None)
    return {"pets": pets, "default_pet": {"pet": default_pet} if default_pet else {}, "settings": settings}


def _call_pet_runtime_method(method: Any, context: dict[str, Any]) -> dict[str, Any]:
    parameters = inspect.signature(method).parameters
    if len(parameters) == 0:
        result = method()
    elif "context" in parameters:
        result = method(context=context)
    else:
        result = method(context)
    return result if isinstance(result, dict) else {}


def _resolve_pet_hint(hint: Any, pets_state: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_pet_name(hint)
    if not normalized:
        return pets_state.get("default_pet") or {}
    matches = []
    for pet in pets_state.get("pets") or []:
        fields = [
            str(pet.get("id") or ""),
            str(pet.get("display_name") or ""),
            str(pet.get("name") or ""),
        ]
        folder = str(pet.get("folder") or pet.get("source") or "")
        if folder and folder != "data":
            fields.append(folder)
        normalized_fields = {_normalize_pet_name(field) for field in fields if field}
        if normalized in normalized_fields:
            matches.append(pet)
    if not matches:
        for pet in pets_state.get("pets") or []:
            fields = [str(pet.get("id") or ""), str(pet.get("display_name") or ""), str(pet.get("name") or "")]
            if any(normalized and (normalized in _normalize_pet_name(field) or _normalize_pet_name(field) in normalized) for field in fields if field):
                matches.append(pet)
    unique = []
    seen: set[str] = set()
    for pet in matches:
        pet_id = str(pet.get("id") or "")
        if pet_id and pet_id not in seen:
            seen.add(pet_id)
            unique.append(pet)
    if len(unique) == 1:
        return {"pet": unique[0]}
    if len(unique) > 1:
        return {"reason": "ambiguous_pet_candidate", "matches": [{"id": pet.get("id"), "display_name": pet.get("display_name")} for pet in unique[:5]]}
    return {"reason": "pet_candidate_not_found"}


def _normalize_pet_name(value: Any) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[\s_-]+", "", text)
    return text


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
    if "utility_llm_slots_failed" in warnings:
        return "utility_llm_slots_failed"
    if "kb_hint_semantic_conflict" in warnings:
        return "utility_semantic_action_conflict"
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


def _knowledge_query_decision(metadata: dict[str, Any], session: Any, agent: Any, knowledge_store: Any) -> dict[str, Any]:
    warnings = list(metadata.get("warnings") or [])
    slots = metadata.get("slots") if isinstance(metadata.get("slots"), dict) else {}
    query_override = str(slots.get("query") or "").strip()
    if not query_override:
        return {**metadata, "route_action": "fallback_current_agent", "target_agent_id": agent.id, "warnings": _ensure_warning(warnings, "utility_llm_slots_failed")}
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


def _compact_slots(slots: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("intent", "target_agent_hint", "kb_hint", "query", "command_hint", "domain", "action", "target_pet_hint", "source_pet_hint"):
        value = slots.get(key)
        if isinstance(value, str) and value.strip():
            compact[key] = _short_text(value.strip())
    if slots.get("use_original_query") is not None:
        compact["use_original_query"] = bool(slots.get("use_original_query"))
    return compact


def _short_text(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    keep = (limit - 3) // 2
    return f"{value[:keep]}...{value[-keep:]}"


async def _maybe_apply_utility_slots(
    *,
    text: str,
    prediction: dict[str, Any],
    settings: Any,
    utility_llm_service: Any = None,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    knowledge_store: Any = None,
    runtime_registry: Any = None,
    capability_config_store: Any = None,
) -> dict[str, Any]:
    predicted_intent = str(prediction.get("predicted_intent") or "chat")
    utility_required = predicted_intent in UTILITY_REQUIRED_INTENTS
    if predicted_intent == "chat":
        return {
            **prediction,
            "utility_required": False,
            "utility_available": _utility_available(utility_llm_service, settings)[0],
            "utility_used": False,
            "utility_ok": False,
            "utility_error_code": None,
        }
    available, unavailable_reason = _utility_available(utility_llm_service, settings)
    base = {
        **prediction,
        "utility_required": utility_required,
        "utility_available": available,
        "utility_used": False,
        "utility_ok": False,
        "utility_error_code": None if available else unavailable_reason,
    }
    if not utility_required:
        return base
    if not available:
        return {**base, "warnings": _ensure_warning(list(prediction.get("warnings") or []), unavailable_reason or "utility_llm_unavailable")}
    try:
        pet_candidates = None
        if predicted_intent == "pet_command":
            pets_state = _load_pet_candidates(runtime_registry, capability_config_store)
            pet_candidates = _compact_pet_candidates(pets_state)
        context = compact_utility_context(
            settings=settings,
            agent_registry=agent_registry,
            agent_config_store=agent_config_store,
            knowledge_store=knowledge_store,
            pet_candidates=pet_candidates,
            prediction=prediction,
        )
        try:
            extracted = await utility_llm_service.extract_intent_json(text, settings, context=context)
        except TypeError:
            extracted = await utility_llm_service.extract_intent_json(text, settings)
    except Exception:
        return {**base, "utility_used": True, "utility_error_code": "utility_llm_slots_failed", "warnings": _ensure_warning(list(prediction.get("warnings") or []), "utility_llm_slots_failed")}
    extracted_intent = str(extracted.get("intent") or "unknown")
    if extracted_intent not in {"unknown", predicted_intent}:
        return {
            **base,
            "utility_used": True,
            "utility_available": True,
            "utility_error_code": "utility_semantic_action_conflict",
            "warnings": _ensure_warning(list(prediction.get("warnings") or []), "utility_semantic_action_conflict"),
        }
    slots = dict(prediction.get("slots") or {}) if isinstance(prediction.get("slots"), dict) else {}
    slots["intent"] = extracted_intent
    if predicted_intent == "knowledge_query":
        if extracted.get("kb_hint"):
            slots["kb_hint"] = extracted.get("kb_hint")
            prediction = {**prediction, "matched_alias": extracted.get("kb_hint")}
        if extracted.get("query"):
            slots["query"] = extracted.get("query")
        if extracted.get("use_original_query") is not None:
            slots["use_original_query"] = bool(extracted.get("use_original_query"))
        if extracted.get("kb_id"):
            prediction = {**prediction, "kb_id": extracted.get("kb_id")}
    elif predicted_intent == "pet_command":
        for key in ("domain", "action", "target_pet_hint", "source_pet_hint"):
            if extracted.get(key):
                slots[key] = extracted.get(key)
    return {
        **prediction,
        "utility_required": utility_required,
        "utility_available": True,
        "utility_used": True,
        "utility_ok": True,
        "utility_error_code": None,
        "source": "embedding_semantic_router+utility_llm",
        "slots": slots,
        "warnings": list(prediction.get("warnings") or []),
    }


def _utility_available(utility_llm_service: Any, settings: Any) -> tuple[bool, str | None]:
    if utility_llm_service is None or settings is None:
        return False, "utility_llm_unavailable"
    backend = str(getattr(settings, "intent_routing_utility_llm_backend", "transformers") or "transformers")
    configured = bool(getattr(settings, "intent_routing_utility_llm_model_profile_id", None)) if backend == "model_profile" else bool(getattr(settings, "intent_routing_utility_llm_model_path", ""))
    if not configured:
        return False, "utility_llm_required"
    status = getattr(utility_llm_service, "status", None)
    if callable(status):
        try:
            result = status(settings)
        except Exception:
            return False, "utility_llm_unavailable"
        if not bool(result.get("available")):
            reason = str(result.get("reason") or "utility_llm_unavailable")
            if reason in {"model_path_not_configured", "model_profile_not_configured"}:
                return False, "utility_llm_required"
            return False, "utility_llm_unavailable"
    return True, None


def _compact_pet_candidates(pets_state: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    default_id = ((pets_state.get("default_pet") or {}).get("pet") or {}).get("id")
    for pet in pets_state.get("pets") or []:
        candidates.append(
            {
                "id": pet.get("id"),
                "display_name": pet.get("display_name"),
                "name": pet.get("name"),
                "folder": pet.get("folder") or pet.get("source"),
                "is_current": bool(default_id and pet.get("id") == default_id),
            }
        )
    return candidates


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
