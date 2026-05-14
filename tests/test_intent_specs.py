from types import SimpleNamespace

from ai_workbench.core.intent_pipeline import IntentPipelineContext, build_executor_plan, validate_intent
from ai_workbench.core.intent_specs import get_builtin_action_specs, get_builtin_route_specs, get_route_spec
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase, MemoryKnowledgeStore


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


def test_knowledge_pipeline_uses_active_session_kbs_when_no_candidate() -> None:
    store = MemoryKnowledgeStore()
    profile = store.create_embedding_profile(EmbeddingModelProfile(name="Test", alias="test", model_path="embeddings/test"))
    kb = store.create_knowledge_base(KnowledgeBase(name="Project KB", embedding_model_profile_id=profile.id))
    store.replace_session_bindings("s1", [kb.id])
    context = IntentPipelineContext(
        mode="auto",
        session=SimpleNamespace(session_id="s1"),
        route=SimpleNamespace(args="What do the docs say?"),
        agent=SimpleNamespace(id="chat"),
        knowledge_store=store,
        auto_mode=True,
    )
    decision = _base_decision("knowledge_query")
    slots = {"intent": "knowledge_query", "query": "rank notes"}

    validation = validate_intent(decision, slots, context)

    assert validation.ok is True
    assert validation.normalized_slots["selected_knowledge_base_ids"] == [kb.id]
    assert validation.normalized_slots["kb_match_source"] == "active_session"
    assert validation.executor_plan.temporary_knowledge_base_ids == [kb.id]


def test_knowledge_pipeline_rejects_query_missing_without_original_query_permission() -> None:
    context = IntentPipelineContext(mode="auto", route=SimpleNamespace(args="Original text"), agent=SimpleNamespace(id="chat"), knowledge_store=MemoryKnowledgeStore(), auto_mode=True)

    validation = validate_intent(_base_decision("knowledge_query"), {"intent": "knowledge_query"}, context)

    assert validation.ok is False
    assert validation.not_executed_reason == "knowledge_query_missing_query"


def test_knowledge_pipeline_rejects_kb_hint_semantic_conflict() -> None:
    store = MemoryKnowledgeStore()
    profile = store.create_embedding_profile(EmbeddingModelProfile(name="Test", alias="test", model_path="embeddings/test"))
    semantic_kb = store.create_knowledge_base(KnowledgeBase(name="Project KB", aliases_text="project", embedding_model_profile_id=profile.id))
    store.create_knowledge_base(KnowledgeBase(name="Lore KB", aliases_text="lore", embedding_model_profile_id=profile.id))
    decision = {**_base_decision("knowledge_query"), "kb_candidate": {"kb_id": semantic_kb.id, "field": "name"}}
    context = IntentPipelineContext(mode="auto", session=SimpleNamespace(session_id="s1"), route=SimpleNamespace(args="Ask lore"), agent=SimpleNamespace(id="chat"), knowledge_store=store, auto_mode=True)

    validation = validate_intent(decision, {"intent": "knowledge_query", "query": "rank notes", "kb_hint": "lore"}, context)

    assert validation.ok is False
    assert validation.not_executed_reason == "kb_hint_semantic_conflict"


def test_pet_pipeline_select_builds_generated_command() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    slots = {"intent": "pet_command", "domain": "workbench_pet", "action": "select", "target_pet_hint": "BD-1"}

    validation = validate_intent(_base_decision("pet_command"), slots, context)

    assert validation.ok is True
    assert validation.normalized_slots["target_pet_id"] == "bd_1"
    assert validation.executor_plan.generated_command == "/pet select bd_1"


def test_pet_pipeline_wake_target_selects_single_pet() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    slots = {"intent": "pet_command", "domain": "workbench_pet", "action": "wake", "target_pet_hint": "BD-1"}

    validation = validate_intent(_base_decision("pet_command"), slots, context)

    assert validation.ok is True
    assert validation.normalized_slots["target_pet_id"] == "bd_1"
    assert validation.executor_plan.generated_command == "/pet select bd_1"


def test_pet_pipeline_tuck_ignores_target_hint() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    slots = {"intent": "pet_command", "domain": "workbench_pet", "action": "tuck", "target_pet_hint": "BD-1"}

    validation = validate_intent(_base_decision("pet_command"), slots, context)

    assert validation.ok is True
    assert validation.normalized_slots["generated_command"] == "/pet tuck"
    assert validation.normalized_slots["target_ignored_for_action"] is True
    assert "pet_target_ignored_for_action" in validation.warnings


def test_pet_pipeline_source_hint_never_blocks_select() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    slots = {"intent": "pet_command", "domain": "workbench_pet", "action": "select", "source_pet_hint": "Unknown", "target_pet_hint": "BD-1"}

    validation = validate_intent(_base_decision("pet_command"), slots, context)

    assert validation.ok is True
    assert validation.executor_plan.generated_command == "/pet select bd_1"


def test_pet_pipeline_low_semantic_margin_warns_without_blocking() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    decision = {**_base_decision("pet_command"), "semantic_margin": 0.0}
    slots = {"intent": "pet_command", "domain": "workbench_pet", "action": "select", "target_pet_hint": "BD-1"}

    validation = validate_intent(decision, slots, context)

    assert validation.ok is True
    assert validation.executor_plan.generated_command == "/pet select bd_1"


def test_pet_pipeline_rejects_non_workbench_domain() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    slots = {"intent": "pet_command", "domain": "real_pet", "action": "status"}

    validation = validate_intent(_base_decision("pet_command"), slots, context)

    assert validation.ok is False
    assert validation.not_executed_reason == "not_workbench_pet_context"


def test_pet_pipeline_uses_utility_action_over_semantic_action_candidate() -> None:
    context = IntentPipelineContext(mode="auto", runtime_registry=_PetRuntimeRegistry(), auto_mode=True)
    decision = {**_base_decision("pet_command"), "action_candidate": {"action_spec_id": "pet.wake", "explicit": True}}
    slots = {"intent": "pet_command", "domain": "workbench_pet", "action": "tuck"}

    validation = validate_intent(decision, slots, context)

    assert validation.ok is True
    assert validation.normalized_slots["generated_command"] == "/pet tuck"
    assert validation.normalized_slots["action_match_source"] == "utility_slots"


def _base_decision(intent: str) -> dict:
    return {
        "predicted_intent": intent,
        "route_spec_id": intent,
        "utility_ok": intent != "chat",
        "semantic_score": 0.9,
        "semantic_margin": 0.2,
        "semantic_thresholds_used": {"intent_min_score": 0.5, "intent_min_margin": 0.03},
        "warnings": [],
    }


class _PetRuntimeRegistry:
    def __init__(self) -> None:
        self.runtime = _PetRuntime()

    def get_method(self, capability_id: str, method_name: str):
        assert capability_id == "pet"
        return getattr(self.runtime, method_name)


class _PetRuntime:
    def get_settings(self, context=None) -> dict:
        return {"settings": {"default_pet_id": "jedi_cal"}}

    def list_pets(self, context=None) -> dict:
        return {
            "pets": [
                {"id": "jedi_cal", "display_name": "Jedi Cal", "valid": True},
                {"id": "bd_1", "display_name": "BD-1", "valid": True},
            ]
        }
