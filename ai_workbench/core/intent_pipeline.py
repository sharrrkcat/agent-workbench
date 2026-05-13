from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_workbench.core.intent_specs import ExecutorPlan, ValidatorResult, get_route_spec


@dataclass(frozen=True)
class IntentPipelineContext:
    mode: str
    session: Any = None
    route: Any = None
    agent: Any = None
    settings: Any = None
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
    # TODO Round 4: migrate knowledge_query and pet_command validators here fully.
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

