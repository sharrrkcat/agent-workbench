from ai_workbench.core.intent_pipeline import IntentPipelineContext, build_executor_plan, validate_intent
from ai_workbench.core.intent_specs import get_builtin_action_specs, get_builtin_route_specs, get_route_spec


def test_builtin_route_specs_cover_v2_intents() -> None:
    specs = {spec.id: spec for spec in get_builtin_route_specs()}

    assert set(specs) >= {"chat", "knowledge_query", "pet_command", "image_generation", "command_like", "agent_route", "action_route", "compound"}
    assert specs["chat"].execution_mode == "semantic_only"
    assert specs["chat"].utility_required is False
    assert specs["knowledge_query"].execution_mode == "utility_required"
    assert specs["knowledge_query"].utility_required is True
    assert specs["pet_command"].execution_mode == "utility_required"
    assert specs["pet_command"].utility_required is True
    for intent in ("image_generation", "command_like", "agent_route", "action_route", "compound"):
        assert specs[intent].execution_mode == "diagnostic_only"
        assert specs[intent].auto_executable is False


def test_builtin_pet_action_specs_exist_and_serialize_compactly() -> None:
    actions = {spec.id: spec for spec in get_builtin_action_specs()}

    assert set(actions) >= {"pet.status", "pet.wake", "pet.tuck", "pet.select", "pet.reload"}
    compact = actions["pet.select"].compact_dict()
    assert compact["parent_intent"] == "pet_command"
    assert compact["action"] == "select"
    assert compact["required_slots"] == ["domain", "action", "target_pet_hint"]
    assert "examples_preview" in compact


def test_slot_schema_compact_export_omits_full_runtime_content() -> None:
    spec = get_route_spec("knowledge_query")

    assert spec is not None
    compact = spec.compact_dict()
    assert compact["slot_schema_id"] == "knowledge_query_slots"
    assert compact["slot_schema"]["required"] == ["intent", "query"]
    assert "examples" not in compact


def test_chat_pipeline_builds_current_prompt_agent_plan_without_utility() -> None:
    context = IntentPipelineContext(mode="auto", agent=type("Agent", (), {"id": "chat"})(), auto_mode=True)
    validation = validate_intent({"predicted_intent": "chat"}, {}, context)
    plan = build_executor_plan(validation, context, {"predicted_intent": "chat"})

    assert validation.ok is True
    assert plan.route_action == "current_prompt_agent"
    assert plan.target_agent_id == "chat"


def test_diagnostic_pipeline_builds_no_execution_plan() -> None:
    context = IntentPipelineContext(mode="auto", auto_mode=True)
    validation = validate_intent({"predicted_intent": "image_generation"}, {}, context)
    plan = build_executor_plan(validation, context, {"predicted_intent": "image_generation", "route_action": "metadata_only"})

    assert validation.ok is False
    assert validation.not_executed_reason == "diagnostic_only"
    assert plan.auto_executable is False
