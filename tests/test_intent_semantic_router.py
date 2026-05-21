from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.intent_specs import build_semantic_candidate_specs, get_route_spec
from ai_workbench.core.intent_semantic_router import SemanticRouter
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase, MemoryKnowledgeStore
from ai_workbench.core.settings import AppSettings
from tests.test_intent_routing import FakeEmbeddingBackend


def test_semantic_router_uses_profile_and_query_document_purposes() -> None:
    knowledge = MemoryKnowledgeStore()
    profile = knowledge.create_embedding_profile(
        EmbeddingModelProfile(
            name="Semantic",
            alias="semantic",
            model_path="embeddings/test",
            document_instruction="Document:",
            query_instruction="Query:",
        )
    )
    knowledge.create_knowledge_base(KnowledgeBase(name="Project KB", aliases_text="project", embedding_model_profile_id=profile.id))
    settings = AppSettings(intent_routing_embedding_model_profile_id=profile.id, intent_routing_knowledge_query_examples="ask project docs")
    backend = FakeEmbeddingBackend()
    agents = AgentRegistry()
    agents.load_from_directory("agents")
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory("capabilities")
    commands = CommandRegistry.from_capability_registry(capabilities)

    decision = SemanticRouter().decide(
        "What does Project KB say about stormtrooper ranks?",
        settings=settings,
        knowledge_store=knowledge,
        model_backend=backend,
        agent_registry=agents,
        capability_registry=capabilities,
        command_registry=commands,
    )

    assert decision["source"] == "embedding_semantic_router"
    assert decision["predicted_intent"] == "knowledge_query"
    assert decision["embedding_model_profile_id"] == profile.id
    assert decision["semantic_index_version"]
    assert decision["intent_group_scores"][0]["intent"] == "knowledge_query"
    assert decision["second_intent"] != "knowledge_query"
    assert decision["semantic_margin"] >= 0.5
    assert "ambiguous_intent" not in decision["warnings"]
    assert decision["semantic_thresholds_used"]["intent_min_score"] == 0.5
    assert decision["kb_candidate"]["kb_id"]
    assert decision["candidate_summary"]["intent_examples"] > 0
    assert decision["candidate_summary"]["knowledge_bases"] > 0
    assert decision["candidate_summary"]["actions"] > 0
    assert decision["candidate_summary"]["commands"] > 0
    assert len(backend.calls) == 2
    assert any(text.startswith("Document:") for text in backend.calls[0]["texts"])
    assert backend.calls[1]["texts"] == ["Query:\nWhat does Project KB say about stormtrooper ranks?"]


def test_semantic_router_missing_profile_returns_warning_without_embedding() -> None:
    backend = FakeEmbeddingBackend()

    decision = SemanticRouter().decide(
        "make an image",
        settings=AppSettings(),
        knowledge_store=MemoryKnowledgeStore(),
        model_backend=backend,
    )

    assert decision["predicted_intent"] == "chat"
    assert "semantic_router_profile_missing" in decision["warnings"]
    assert backend.calls == []


def test_semantic_router_uses_pet_action_specs_as_candidates() -> None:
    knowledge = MemoryKnowledgeStore()
    profile = knowledge.create_embedding_profile(EmbeddingModelProfile(name="Semantic", alias="semantic", model_path="embeddings/test"))
    settings = AppSettings(intent_routing_embedding_model_profile_id=profile.id)
    backend = FakeEmbeddingBackend()

    decision = SemanticRouter().decide(
        "tuck the pet away",
        settings=settings,
        knowledge_store=knowledge,
        model_backend=backend,
    )

    assert decision["predicted_intent"] == "pet_command"
    assert any(candidate.get("action_spec_id") == "pet.tuck" for candidate in decision["top_candidates"])


def test_semantic_router_recognizes_web_query_without_stealing_writing() -> None:
    knowledge = MemoryKnowledgeStore()
    profile = knowledge.create_embedding_profile(EmbeddingModelProfile(name="Semantic", alias="semantic", model_path="embeddings/test"))
    settings = AppSettings(intent_routing_embedding_model_profile_id=profile.id)
    backend = FakeEmbeddingBackend()
    router = SemanticRouter()

    web = router.decide(
        "search the latest OpenAI API changes",
        settings=settings,
        knowledge_store=knowledge,
        model_backend=backend,
    )
    writing = router.decide(
        "write a Star Wars style short story",
        settings=settings,
        knowledge_store=knowledge,
        model_backend=backend,
    )

    assert web["predicted_intent"] == "web_query"
    assert web["intent_group_scores"][0]["intent"] == "web_query"
    assert writing["predicted_intent"] != "web_query"


def test_web_query_custom_examples_are_semantic_candidates() -> None:
    settings = AppSettings(intent_routing_web_query_examples="check official release notes\n\nwhat changed today")

    candidates = build_semantic_candidate_specs(settings=settings)

    web_custom = [
        candidate
        for candidate in candidates
        if candidate["intent"] == "web_query" and candidate["source"] == "custom"
    ]
    assert [candidate["text"] for candidate in web_custom] == ["check official release notes", "what changed today"]
    assert all(candidate["field"] == "example" for candidate in web_custom)


def test_web_query_safety_notes_describe_web_context_signal() -> None:
    spec = get_route_spec("web_query")

    assert spec is not None
    assert spec.executor_id == "web_context_signal"
    notes = " ".join(spec.safety_notes)
    stale_note = "Diagnostic" + "-" + "only in this version"
    assert stale_note not in notes
    assert "Web Context pipeline" in notes
    assert "Web Search Capability commands directly" in notes
