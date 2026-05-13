from __future__ import annotations

from dataclasses import dataclass
import inspect
import re
from typing import Any, Protocol

from ai_workbench.core.intent_specs import ExecutorPlan, ValidatorResult, get_action_spec, get_action_spec_for_intent_action, get_route_spec


@dataclass(frozen=True)
class IntentPipelineContext:
    mode: str
    session: Any = None
    route: Any = None
    agent: Any = None
    settings: Any = None
    knowledge_store: Any = None
    runtime_registry: Any = None
    capability_config_store: Any = None
    auto_mode: bool = False


class IntentValidator(Protocol):
    def validate_intent(self, decision: dict[str, Any], slots: dict[str, Any], context: IntentPipelineContext) -> ValidatorResult:
        ...


class IntentExecutor(Protocol):
    def build_executor_plan(self, validation: ValidatorResult, context: IntentPipelineContext) -> ExecutorPlan:
        ...

    def execute_plan(self, plan: ExecutorPlan, context: IntentPipelineContext) -> Any:
        ...


def validate_intent(decision: dict[str, Any], slots: dict[str, Any], context: IntentPipelineContext) -> ValidatorResult:
    intent = str(decision.get("predicted_intent") or "chat")
    spec = get_route_spec(intent)
    if spec is None:
        return ValidatorResult(ok=False, not_executed_reason="unknown_route_spec", warnings=["unknown_route_spec"], normalized_slots=slots)
    if spec.execution_mode == "diagnostic_only":
        return ValidatorResult(ok=False, not_executed_reason="diagnostic_only", warnings=["diagnostic_only"], normalized_slots=slots)
    if spec.execution_mode == "semantic_only":
        plan = ExecutorPlan(
            route_action=spec.executor_id or "current_prompt_agent",
            auto_executable=spec.auto_executable,
            would_execute=context.auto_mode and spec.auto_executable,
            target_agent_id=getattr(context.agent, "id", None),
            target_action_id="default",
        )
        return ValidatorResult(ok=True, normalized_slots=slots, executor_plan=plan)
    if spec.utility_required and not bool(decision.get("utility_ok")):
        reason = str(decision.get("utility_error_code") or "utility_llm_required")
        return ValidatorResult(ok=False, not_executed_reason=reason, warnings=[reason], normalized_slots=slots)
    if spec.id == "knowledge_query":
        return KnowledgeQueryValidator().validate_intent(decision, slots, context)
    if spec.id == "pet_command":
        return PetCommandValidator().validate_intent(decision, slots, context)
    return ValidatorResult(ok=True, normalized_slots=slots)


def build_executor_plan(validation: ValidatorResult, context: IntentPipelineContext, decision: dict[str, Any] | None = None) -> ExecutorPlan:
    if validation.executor_plan is not None:
        return validation.executor_plan
    decision = decision or {}
    if not validation.ok:
        return ExecutorPlan(route_action=str(decision.get("route_action") or "fallback_current_agent"), auto_executable=False, would_execute=False)
    intent = str(decision.get("predicted_intent") or "chat")
    spec = get_route_spec(intent)
    route_action = str(decision.get("route_action") or (spec.executor_id if spec else "metadata_only") or "metadata_only")
    return ExecutorPlan(
        route_action=route_action,
        auto_executable=bool(decision.get("auto_executable", spec.auto_executable if spec else False)),
        would_execute=bool(decision.get("would_execute", False)),
        target_agent_id=decision.get("target_agent_id") or getattr(context.agent, "id", None),
        target_action_id=decision.get("target_action_id"),
        target_command=decision.get("target_command"),
        generated_command=decision.get("generated_command"),
        temporary_knowledge_base_ids=list(decision.get("temporary_knowledge_base_ids") or []),
        knowledge_query_override=decision.get("knowledge_query_override"),
    )


def execute_plan(plan: ExecutorPlan, context: IntentPipelineContext) -> Any:
    del context
    # Execution remains in the existing runtime branches this round.
    return {"executed": False, "route_action": plan.route_action}


class KnowledgeQueryValidator:
    def validate_intent(self, decision: dict[str, Any], slots: dict[str, Any], context: IntentPipelineContext) -> ValidatorResult:
        warnings = list(decision.get("warnings") or [])
        route_spec_id = str(decision.get("route_spec_id") or decision.get("predicted_intent") or "")
        if decision.get("predicted_intent") != "knowledge_query" or route_spec_id != "knowledge_query":
            return _failed("utility_semantic_intent_conflict", slots, warnings)
        if not _semantic_thresholds_pass(decision):
            return _failed(str(decision.get("not_executed_reason") or "semantic_threshold_not_met"), slots, warnings)
        if slots.get("intent") != "knowledge_query":
            return _failed("utility_semantic_intent_conflict", slots, warnings)

        query = str(slots.get("query") or "").strip()
        if not query and slots.get("use_original_query") is True:
            query = str(getattr(context.route, "args", "") or "").strip()
        if not query:
            return _failed("knowledge_query_missing_query", slots, warnings)
        if context.knowledge_store is None:
            return _failed("knowledge_store_unavailable", slots, warnings)

        kb_hint = str(slots.get("kb_hint") or "").strip()
        semantic = _semantic_kb_candidate(decision)
        hint_match = _match_knowledge_bases(context.knowledge_store, kb_hint) if kb_hint else {"ids": [], "source": "none", "warnings": []}
        if hint_match["warnings"]:
            warnings.extend(hint_match["warnings"])
            if "ambiguous_kb_candidate" in hint_match["warnings"]:
                return _failed("ambiguous_kb_candidate", slots, warnings)
        if semantic.get("ambiguous"):
            return _failed("ambiguous_kb_candidate", slots, _ensure_warning(warnings, "ambiguous_kb_candidate"))

        selected_ids: list[str] = []
        match_source = "none"
        semantic_id = semantic.get("id")
        hint_ids = hint_match.get("ids") or []
        if hint_ids and semantic_id:
            if hint_ids == [semantic_id]:
                selected_ids = hint_ids
                match_source = str(hint_match.get("source") or semantic.get("source") or "alias")
            else:
                return _failed("kb_hint_semantic_conflict", slots, _ensure_warning(warnings, "kb_hint_semantic_conflict"))
        elif hint_ids:
            selected_ids = hint_ids
            match_source = str(hint_match.get("source") or "alias")
        elif semantic_id:
            selected_ids = [str(semantic_id)]
            match_source = str(semantic.get("source") or "semantic")
        else:
            selected_ids = _active_session_kb_ids(context.knowledge_store, getattr(context.session, "session_id", ""))
            if selected_ids:
                match_source = "active_session"
            else:
                return _failed("no_kb_candidate_or_active_kbs", slots, _ensure_warning(warnings, "no_kb_candidate_or_active_kbs"))

        normalized = {
            **slots,
            "query": _short_text(query),
            "kb_hint": kb_hint or None,
            "selected_knowledge_base_ids": selected_ids,
            "kb_match_source": match_source,
        }
        plan = ExecutorPlan(
            route_action="knowledge_override",
            auto_executable=True,
            would_execute=context.auto_mode,
            target_agent_id=getattr(context.agent, "id", None),
            target_action_id="default",
            temporary_knowledge_base_ids=selected_ids,
            knowledge_query_override=_short_text(query),
            metadata={
                "session_bindings_changed": False,
                "session_default_changed": False,
            },
        )
        return ValidatorResult(ok=True, warnings=warnings, normalized_slots=normalized, executor_plan=plan)


class PetCommandValidator:
    def validate_intent(self, decision: dict[str, Any], slots: dict[str, Any], context: IntentPipelineContext) -> ValidatorResult:
        warnings = list(decision.get("warnings") or [])
        route_spec_id = str(decision.get("route_spec_id") or decision.get("predicted_intent") or "")
        if decision.get("predicted_intent") != "pet_command" or route_spec_id != "pet_command":
            return _failed("utility_semantic_intent_conflict", slots, warnings)
        if not _semantic_thresholds_pass(decision):
            return _failed(str(decision.get("not_executed_reason") or "semantic_threshold_not_met"), slots, warnings)
        if slots.get("intent") != "pet_command":
            return _failed("utility_semantic_intent_conflict", slots, warnings)
        domain = str(slots.get("domain") or "").strip()
        action = str(slots.get("action") or "").strip()
        if domain != "workbench_pet":
            return _failed("not_workbench_pet_context", slots, _ensure_warning(warnings, "not_workbench_pet_context"))
        if action not in {"status", "wake", "tuck", "select", "reload"}:
            return _failed("pet_action_unrecognized", slots, _ensure_warning(warnings, "pet_action_unrecognized"))

        semantic_action = _semantic_action(decision)
        if semantic_action and semantic_action != action:
            return _failed("utility_semantic_action_conflict", slots, _ensure_warning(warnings, "utility_semantic_action_conflict"))
        action_match_source = "semantic" if semantic_action else "utility_only"
        pets_state = _load_pet_candidates(context.runtime_registry, context.capability_config_store)
        if pets_state.get("warning"):
            reason = str(pets_state["warning"])
            return _failed(reason, slots, _ensure_warning(warnings, reason))

        target_hint = str(slots.get("target_pet_hint") or "").strip()
        source_hint = str(slots.get("source_pet_hint") or "").strip()
        default_target = pets_state.get("default_pet") or {}
        target = _resolve_pet_hint(target_hint, pets_state) if target_hint else default_target
        source = _resolve_pet_hint(source_hint, pets_state) if source_hint else {}
        reason = None
        if target_hint and target.get("reason"):
            reason = str(target["reason"])
        elif action == "select" and not target_hint:
            reason = "select_target_missing"
        elif source_hint and source.get("reason"):
            source_reason = str(source["reason"])
            if source_reason == "pet_candidate_not_found":
                reason = "source_pet_not_found"
            elif source_reason == "ambiguous_pet_candidate":
                reason = "ambiguous_source_pet_candidate"
            else:
                reason = source_reason
        elif source.get("pet") and default_target.get("pet") and source["pet"]["id"] != default_target["pet"]["id"]:
            reason = "source_pet_mismatch"
        elif action in {"wake", "tuck", "reload"} and target_hint and target.get("pet") and default_target.get("pet") and target["pet"]["id"] != default_target["pet"]["id"]:
            reason = "target_pet_not_current"
        elif not target.get("pet") and action != "status":
            reason = "pet_candidate_not_found"
        if reason is not None:
            return _pet_failed(reason, action, target, source, slots, warnings, target_hint, source_hint)

        target_pet = target.get("pet") if isinstance(target, dict) else None
        source_pet = source.get("pet") if isinstance(source, dict) else None
        generated_command = _generated_pet_command(action, target_pet.get("id") if action == "select" and isinstance(target_pet, dict) else None)
        normalized = {
            **slots,
            "domain": domain,
            "action": action,
            "target_pet_hint": target_hint or None,
            "source_pet_hint": source_hint or None,
            "target_pet_id": target_pet.get("id") if isinstance(target_pet, dict) else None,
            "source_pet_id": source_pet.get("id") if isinstance(source_pet, dict) else None,
            "generated_command": generated_command,
            "action_match_source": action_match_source,
        }
        plan = ExecutorPlan(
            route_action="pet_command",
            auto_executable=True,
            would_execute=context.auto_mode,
            target_command="/pet",
            generated_command=generated_command,
            metadata={
                "target_pet_id": normalized["target_pet_id"],
                "source_pet_id": normalized["source_pet_id"],
                "pet_action": action,
            },
        )
        return ValidatorResult(ok=True, warnings=warnings, normalized_slots=normalized, executor_plan=plan)


def _failed(reason: str, slots: dict[str, Any], warnings: list[str]) -> ValidatorResult:
    return ValidatorResult(ok=False, not_executed_reason=reason, warnings=_ensure_warning(warnings, reason), normalized_slots=slots)


def _pet_failed(reason: str, action: str, target: dict[str, Any], source: dict[str, Any], slots: dict[str, Any], warnings: list[str], target_hint: str, source_hint: str) -> ValidatorResult:
    target_pet = target.get("pet") if isinstance(target, dict) else None
    source_pet = source.get("pet") if isinstance(source, dict) else None
    normalized = {
        **slots,
        "action": action,
        "target_pet_hint": target_hint or None,
        "source_pet_hint": source_hint or None,
        "target_pet_id": target_pet.get("id") if isinstance(target_pet, dict) else None,
        "source_pet_id": source_pet.get("id") if isinstance(source_pet, dict) else None,
    }
    return ValidatorResult(ok=False, not_executed_reason=reason, warnings=_ensure_warning(warnings, reason), normalized_slots=normalized)


def _semantic_thresholds_pass(decision: dict[str, Any]) -> bool:
    thresholds = decision.get("semantic_thresholds_used") if isinstance(decision.get("semantic_thresholds_used"), dict) else {}
    score = decision.get("semantic_score", decision.get("confidence"))
    margin = decision.get("semantic_margin")
    try:
        if score is not None and float(score) < float(thresholds.get("intent_min_score", 0.0)):
            return False
        if margin is not None and float(margin) < float(thresholds.get("intent_min_margin", 0.0)):
            return False
    except (TypeError, ValueError):
        return False
    return True


def _semantic_action(decision: dict[str, Any]) -> str | None:
    action_candidate = decision.get("action_candidate")
    if isinstance(action_candidate, dict) and not action_candidate.get("explicit"):
        return None
    action_spec = get_action_spec(action_candidate.get("action_spec_id")) if isinstance(action_candidate, dict) else None
    if action_spec is not None:
        return action_spec.action
    action_spec_id = decision.get("action_spec_id")
    action_spec = get_action_spec(str(action_spec_id)) if action_spec_id else None
    return action_spec.action if action_spec else None


def _semantic_kb_candidate(decision: dict[str, Any]) -> dict[str, Any]:
    candidate = decision.get("kb_candidate")
    if not isinstance(candidate, dict):
        return {"id": None, "source": "none", "ambiguous": _semantic_kb_candidate_ambiguous(decision)}
    return {
        "id": str(candidate.get("kb_id") or candidate.get("knowledge_base_id") or "") or None,
        "source": candidate.get("field") or "semantic",
        "ambiguous": _semantic_kb_candidate_ambiguous(decision),
    }


def _semantic_kb_candidate_ambiguous(decision: dict[str, Any]) -> bool:
    top = decision.get("top_candidates")
    if not isinstance(top, list):
        return False
    threshold = 0.03
    thresholds = decision.get("semantic_thresholds_used")
    if isinstance(thresholds, dict):
        try:
            threshold = float(thresholds.get("intent_min_margin", threshold))
        except (TypeError, ValueError):
            pass
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
    return any(candidate["kb_id"] != first["kb_id"] and first["score"] - candidate["score"] < threshold for candidate in kb_candidates[1:])


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
    return {"ids": [], "warnings": [], "source": "none"}


def _single_or_ambiguous(matches: list[Any], source: str, matched_alias: str | None = None) -> dict[str, Any]:
    unique = []
    seen: set[str] = set()
    for item in matches:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    if len(unique) == 1:
        payload = {"ids": [unique[0].id], "warnings": [], "source": source}
        if matched_alias:
            payload["matched_alias"] = matched_alias
        return payload
    return {
        "ids": [],
        "warnings": ["ambiguous_kb_candidate"],
        "source": source,
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


def _generated_pet_command(action: str, target_pet_id: str | None) -> str:
    if action == "select" and target_pet_id:
        return f"/pet select {target_pet_id}"
    if action == "status":
        return "/pet status"
    return f"/pet {action}"


def _normalize_pet_name(value: Any) -> str:
    text = _normalize_text(value)
    return re.sub(r"[\s_-]+", "", text)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


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


def _ensure_warning(warnings: list[str], warning: str) -> list[str]:
    return warnings if warning in warnings else [*warnings, warning]


def _short_text(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    keep = (limit - 3) // 2
    return f"{value[:keep]}...{value[-keep:]}"
