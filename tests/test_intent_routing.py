from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run


class ContextAwareUtilityIntentService:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.contexts: list[dict] = []

    async def extract_intent_json(self, text: str, settings, context=None) -> dict:
        self.contexts.append(context or {})
        return self.payload


class RouteTestPetRuntime:
    def get_settings(self, context=None) -> dict:
        return {"settings": {"default_pet_id": "jedi_cal"}}

    def list_pets(self, context=None) -> dict:
        return {
            "pets": [
                {"id": "jedi_cal", "display_name": "Jedi Cal", "valid": True},
                {"id": "bd_1", "display_name": "BD-1", "valid": True},
            ]
        }

    def command(self, args: str = "", context=None) -> str:
        raise AssertionError("Route Test must not execute /pet")


class FakeEmbeddingBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.calls.append({"model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        return [_fake_vector(text) for text in texts]


def _fake_vector(text: str) -> list[float]:
    value = text.casefold()
    if "web_query:" in value and "market pulse" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    if "image_generation:" in value:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if "knowledge_query:" in value:
        return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    if "agent_route:" in value:
        return [0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    if "pet_command:tuck:" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    if "pet_command:" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    if "web_query:" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    if "command_like:" in value:
        return [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    if "action_route:" in value:
        return [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    if "compound:" in value:
        return [0.1, 0.1, 0.1, 0.1, 0.0, 0.0]
    if "chat:" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    if "knowledge_base:" in value:
        value = value.split("knowledge_base:", 1)[1]
    if any(token in value for token in ["image", "picture", "draw", "concept art"]):
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if "market pulse" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    if any(token in value for token in ["latest", "recent news", "current exchange rate", "联网", "搜索网页", "搜一下", "查一下", "最新", "今天日元"]):
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    if any(token in value for token in ["knowledge", "documentation", "docs", "lore", "kb", "project", "stormtrooper", "say about", "star wars", "sw"]):
        return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    if any(token in value for token in ["translator", "translate agent"]):
        return [0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    if any(token in value for token in ["command", "free memory", "/free-memory"]):
        return [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    if any(token in value for token in ["action", "formal"]):
        return [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    if "tuck" in value:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    if any(token in value for token in ["pet", "jedi cal", "bd-1", "bd1"]):
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def enable_semantic_router(fixture: PromptRuntimeFixture) -> EmbeddingModelProfile:
    profile = fixture.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Semantic Embeddings", alias="semantic", model_path="embeddings/test"))
    fixture.app_settings.patch({"intent_routing_embedding_model_profile_id": profile.id})
    fixture.agent_runner.knowledge_model_backend = FakeEmbeddingBackend()
    return profile


def test_intent_routing_shadow_records_prediction_without_changing_route() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    profile = enable_semantic_router(fixture)
    fixture.app_settings.patch({"intent_routing_enabled": True})
    fixture.agent_configs.set_config("chat", runtime={"intent_routing_mode": "enabled"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "please draw an image"))

    assert result.success is True
    run_metadata = fixture.runs.get_run(result.run_id).metadata
    intent = run_metadata["intent_routing"]
    assert intent["eligible"] is True
    assert intent["bypassed"] is False
    assert intent["mode"] == "shadow"
    assert intent["predicted_intent"] == "image_generation"
    assert intent["source"] == "embedding_semantic_router"
    assert intent["route_action"] == "metadata_only"
    assert fixture.runs.get_run(result.run_id).target_id == "chat"
    assistant = fixture.messages.list_messages(session.session_id)[-1]
    assert assistant.agent_id == "chat"
    assert assistant.metadata["intent_routing"] == intent
    assert "image_generation" not in str(fixture.llm.calls[-1]["messages"])


def test_custom_route_examples_affect_prediction() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    profile = enable_semantic_router(fixture)
    fixture.app_settings.patch(
        {
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_image_generation_examples": "please make concept art",
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "please make concept art for the city"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert intent["predicted_intent"] == "image_generation"
    assert any(candidate.get("source") == "custom" for candidate in intent["top_candidates"])


def test_utility_extractor_receives_compact_candidates() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    profile = enable_semantic_router(fixture)
    fixture.app_settings.patch(
        {
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_utility_llm_model_path": "utility_llms/test-router",
            "intent_routing_knowledge_query_examples": "ask the lore binder",
            "intent_routing_web_query_examples": "check official release notes",
        }
    )
    fixture.knowledge.create_knowledge_base(KnowledgeBase(name="Lore KB", aliases_text="lore, codex", embedding_model_profile_id=profile.id))
    fixture.agent_configs.set_config("translate", runtime={"intent_routing_aliases_text": "translator", "intent_routing_examples_text": "send this to translator"})
    utility = ContextAwareUtilityIntentService({"intent": "knowledge_query", "confidence": 0.84, "kb_hint": "lore", "query": "rank notes"})
    fixture.agent_runner.utility_llm_service = utility
    session = fixture.sessions.create_session(default_agent_id="chat")

    run(fixture.runtime.handle_input(session, "ask the lore binder about rank notes"))

    context = utility.contexts[0]
    assert context["top_route_specs"][0]["id"] == "knowledge_query"
    assert context["top_route_specs"][0]["slot_schema_id"] == "knowledge_query_slots"
    assert "slot_schema" in context["top_route_specs"][0]
    assert "examples" not in context["top_route_specs"][0]
    assert any(intent["id"] == "knowledge_query" and "ask the lore binder" in intent["examples"] for intent in context["intents"])
    assert any(intent["id"] == "web_query" and "check official release notes" in intent["examples"] for intent in context["intents"])
    assert any(agent["id"] == "translate" and "translator" in agent["aliases"] for agent in context["agents"])
    assert any(kb["name"] == "Lore KB" and "lore" in kb["aliases"] for kb in context["knowledge_bases"])
    assert context["safety"]["command_like_auto_execute"] is False
    assert context["safety"]["generic_agent_route_auto_execute"] is False


def test_route_test_api_predicts_without_creating_messages_or_runs(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test.db'}"))
    state = client.app.state.runtime_state
    profile = state.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test"))
    state.app_settings.patch({"intent_routing_embedding_model_profile_id": profile.id})
    state.knowledge_model_backend = FakeEmbeddingBackend()
    client.patch(
        "/api/settings/general",
        json={
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": True,
            "intent_routing_image_generation_examples": "make concept art",
        },
    )

    response = client.post("/api/intent/test-route", json={"text": "make concept art of a station", "include_utility": False})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["eligibility_scope"] == "no_session"
    assert decision["predicted_intent"] == "image_generation"
    assert decision["source"] == "embedding_semantic_router"
    assert decision["semantic_score"] > 0
    assert decision["semantic_thresholds_used"]["intent_min_score"] == 0.5
    assert decision["intent_group_scores"]
    assert decision["not_executed_reason"] == "image_generation_action_routing_not_ready"
    assert decision["auto_executable"] is False
    assert decision["would_execute"] is False
    assert decision["diagnostic_reason"] == "image_generation_action_routing_not_ready"
    assert decision["top_candidates"]
    assert state.runs.list_all_runs() == []


def test_route_test_uses_custom_web_query_examples_without_execution(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test-web.db'}"))
    state = client.app.state.runtime_state
    profile = state.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test"))
    state.app_settings.patch({"intent_routing_embedding_model_profile_id": profile.id})
    state.knowledge_model_backend = FakeEmbeddingBackend()
    client.patch(
        "/api/settings/general",
        json={
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": True,
            "intent_routing_web_query_examples": "market pulse brief",
        },
    )

    response = client.post("/api/intent/test-route", json={"text": "market pulse brief for AI chips", "include_utility": False})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["predicted_intent"] == "web_query"
    assert any(candidate.get("intent") == "web_query" and candidate.get("source") == "custom" for candidate in decision["top_candidates"])
    assert decision["would_execute"] is False
    assert decision["executed"] is False
    assert state.runs.list_all_runs() == []
    assert state.messages.list_all_messages() == []


def test_route_test_api_reports_pet_command_without_executing(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test-pet.db'}"))
    state = client.app.state.runtime_state
    profile = state.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test"))
    state.app_settings.patch({"intent_routing_embedding_model_profile_id": profile.id})
    state.knowledge_model_backend = FakeEmbeddingBackend()
    state.runtimes.replace("pet", RouteTestPetRuntime())
    client.patch(
        "/api/settings/general",
        json={
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": True,
        },
    )

    response = client.post("/api/intent/test-route", json={"text": "鎶婂疇鐗╂崲鎴?BD-1", "include_utility": False})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["predicted_intent"] == "pet_command"
    assert decision["route_spec_id"] == "pet_command"
    assert decision["slot_schema_id"] == "pet_command_slots"
    assert decision["validator_id"] == "pet_command"
    assert decision["executor_id"] == "pet_command"
    assert decision["utility_required"] is True
    assert decision["utility_used"] is False
    assert decision["not_executed_reason"] in {"utility_llm_required", "utility_llm_unavailable"}
    assert decision["would_execute"] is False
    assert decision["executed"] is False
    assert state.runs.list_all_runs() == []
    assert state.messages.list_all_messages() == []


def test_route_test_api_reports_web_query_diagnostic_only_without_search(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test-web.db'}"))
    state = client.app.state.runtime_state
    profile = state.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test"))
    state.app_settings.patch({"intent_routing_embedding_model_profile_id": profile.id})
    state.knowledge_model_backend = FakeEmbeddingBackend()
    state.utility_llm = ContextAwareUtilityIntentService(
        {
            "intent": "web_query",
            "confidence": 0.91,
            "query": "OpenAI API latest changes",
            "freshness": "recent",
            "domain_hints": ["openai.com"],
            "language_hint": "en",
        }
    )
    client.patch(
        "/api/settings/general",
        json={
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": True,
            "intent_routing_utility_llm_model_path": "utility_llms/test-router",
        },
    )

    response = client.post("/api/intent/test-route", json={"text": "search the latest OpenAI API changes", "include_utility": True})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["predicted_intent"] == "web_query"
    assert decision["route_spec_id"] == "web_query"
    assert decision["slot_schema_id"] == "web_query_slots"
    assert decision["validator_id"] == "web_query"
    assert decision["executor_id"] == "web_query_diagnostic"
    assert decision["validation_ok"] is True
    assert decision["would_execute"] is False
    assert decision["executed"] is False
    assert decision["not_executed_reason"] == "web_query_diagnostic_only"
    assert decision["executor_plan"]["route_action"] == "metadata_only"
    assert decision["slots"]["query"] == "OpenAI API latest changes"
    assert decision["slots"]["freshness"] == "recent"
    assert decision["slots"]["domain_hints"] == ["openai.com"]
    assert state.runs.list_all_runs() == []
    assert state.messages.list_all_messages() == []


def test_route_test_web_query_missing_query_reports_validator_reason(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test-web-missing.db'}"))
    state = client.app.state.runtime_state
    profile = state.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test"))
    state.app_settings.patch({"intent_routing_embedding_model_profile_id": profile.id})
    state.knowledge_model_backend = FakeEmbeddingBackend()
    state.utility_llm = ContextAwareUtilityIntentService({"intent": "web_query", "confidence": 0.91, "query": "", "use_original_query": False})
    client.patch(
        "/api/settings/general",
        json={
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": True,
            "intent_routing_utility_llm_model_path": "utility_llms/test-router",
        },
    )

    response = client.post("/api/intent/test-route", json={"text": "search the latest OpenAI API changes", "include_utility": True})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["predicted_intent"] == "web_query"
    assert decision["validation_ok"] is False
    assert decision["would_execute"] is False
    assert decision["not_executed_reason"] == "web_query_missing_query"
    assert state.runs.list_all_runs() == []
    assert state.messages.list_all_messages() == []


def test_route_test_without_embedding_profile_warns_without_creating_messages_or_runs(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test-missing-profile.db'}"))
    state = client.app.state.runtime_state

    response = client.post("/api/intent/test-route", json={"text": "make concept art of a station", "include_utility": False})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["predicted_intent"] == "chat"
    assert decision["source"] == "semantic_router_unavailable"
    assert decision["would_execute"] is False
    assert "debug_fallback" not in decision
    assert "semantic_router_profile_missing" in decision["warnings"]
    assert state.runs.list_all_runs() == []
    assert state.messages.list_all_messages() == []


def test_intent_routing_general_master_off_bypasses_even_with_agent_override() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.agent_configs.set_config("chat", runtime={"intent_routing_mode": "enabled"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "make an image"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert intent["eligible"] is False
    assert intent["bypassed"] is True
    assert intent["bypass_reason"] == "general_disabled"


def test_intent_routing_default_off_with_use_default_bypasses() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.app_settings.patch({"intent_routing_enabled": True, "intent_routing_default_for_prompt_agents": False})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "what does the documentation say"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert intent["eligible"] is False
    assert intent["bypass_reason"] == "default_disabled"


def test_intent_routing_explicit_syntax_bypasses() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.app_settings.patch({"intent_routing_enabled": True, "intent_routing_default_for_prompt_agents": True})
    session = fixture.sessions.create_session(default_agent_id="chat")

    command = run(fixture.runtime.handle_input(session, "/encode base64 hello"))
    explicit_agent = run(fixture.runtime.handle_input(session, "@translate hello"))
    explicit_action = run(fixture.runtime.handle_input(session, "@translate:formal hello"))
    shortcut = run(fixture.runtime.handle_input(session, ":default hello"))

    assert fixture.runs.get_run(command.run_id).metadata["intent_routing"]["bypass_reason"] == "explicit_command"
    assert fixture.runs.get_run(explicit_agent.run_id).metadata["intent_routing"]["bypass_reason"] == "explicit_agent"
    assert fixture.runs.get_run(explicit_action.run_id).metadata["intent_routing"]["bypass_reason"] == "explicit_agent"
    assert fixture.runs.get_run(shortcut.run_id).metadata["intent_routing"]["bypass_reason"] == "explicit_action"


def test_intent_routing_script_default_and_group_transcript_bypass() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.app_settings.patch({"intent_routing_enabled": True, "intent_routing_default_for_prompt_agents": True})
    script_session = fixture.sessions.create_session(default_agent_id="script_lifecycle_lab")
    group_session = fixture.sessions.create_session(default_agent_id="chat", context_mode="group_transcript")

    script_result = run(fixture.runtime.handle_input(script_session, "make an image"))
    group_result = run(fixture.runtime.handle_input(group_session, "make an image"))

    assert fixture.runs.get_run(script_result.run_id).metadata["intent_routing"]["bypass_reason"] == "default_agent_not_prompt"
    assert fixture.runs.get_run(group_result.run_id).metadata["intent_routing"]["bypass_reason"] == "group_transcript_not_supported"
