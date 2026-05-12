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


def test_intent_routing_shadow_records_prediction_without_changing_route() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.app_settings.patch({"intent_routing_enabled": True})
    fixture.agent_configs.set_config("chat", runtime={"intent_routing_mode": "enabled"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "帮我生成一张图片"))

    assert result.success is True
    run_metadata = fixture.runs.get_run(result.run_id).metadata
    intent = run_metadata["intent_routing"]
    assert intent["eligible"] is True
    assert intent["bypassed"] is False
    assert intent["mode"] == "shadow"
    assert intent["predicted_intent"] == "image_generation"
    assert intent["target_agent_id"] == "comfyui_agent"
    assert fixture.runs.get_run(result.run_id).target_id == "chat"
    assistant = fixture.messages.list_messages(session.session_id)[-1]
    assert assistant.agent_id == "chat"
    assert assistant.metadata["intent_routing"] == intent
    assert "image_generation" not in str(fixture.llm.calls[-1]["messages"])


def test_custom_route_examples_affect_prediction() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
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
    assert intent["custom_examples_used"] is True
    assert intent["matched_route_example"] == "please make concept art"


def test_utility_extractor_receives_compact_candidates() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.app_settings.patch(
        {
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_utility_llm_model_path": "utility_llms/test-router",
            "intent_routing_knowledge_query_examples": "ask the lore binder",
        }
    )
    profile = fixture.knowledge.create_embedding_profile(EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test"))
    fixture.knowledge.create_knowledge_base(KnowledgeBase(name="Lore KB", aliases_text="lore, codex", embedding_model_profile_id=profile.id))
    fixture.agent_configs.set_config("translate", runtime={"intent_routing_aliases_text": "translator", "intent_routing_examples_text": "send this to translator"})
    utility = ContextAwareUtilityIntentService({"intent": "knowledge_query", "confidence": 0.84, "kb_hint": "lore", "query": "rank notes"})
    fixture.agent_runner.utility_llm_service = utility
    session = fixture.sessions.create_session(default_agent_id="chat")

    run(fixture.runtime.handle_input(session, "ask the lore binder about rank notes"))

    context = utility.contexts[0]
    assert any(intent["id"] == "knowledge_query" and "ask the lore binder" in intent["examples"] for intent in context["intents"])
    assert any(agent["id"] == "translate" and "translator" in agent["aliases"] for agent in context["agents"])
    assert any(kb["name"] == "Lore KB" and "lore" in kb["aliases"] for kb in context["knowledge_bases"])
    assert context["safety"]["command_like_auto_execute"] is False
    assert context["safety"]["generic_agent_route_auto_execute"] is False


def test_route_test_api_predicts_without_creating_messages_or_runs(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'route-test.db'}"))
    state = client.app.state.runtime_state
    client.patch("/api/settings/general", json={"intent_routing_image_generation_examples": "make concept art"})

    response = client.post("/api/intent/test-route", json={"text": "make concept art of a station", "include_utility": False})

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["eligibility_scope"] == "no_session"
    assert decision["predicted_intent"] == "image_generation"
    assert decision["custom_examples_used"] is True
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

    command = run(fixture.runtime.handle_input(session, "/base64 hello"))
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
    script_session = fixture.sessions.create_session(default_agent_id="echo_script")
    group_session = fixture.sessions.create_session(default_agent_id="chat", context_mode="group_transcript")

    script_result = run(fixture.runtime.handle_input(script_session, "make an image"))
    group_result = run(fixture.runtime.handle_input(group_session, "make an image"))

    assert fixture.runs.get_run(script_result.run_id).metadata["intent_routing"]["bypass_reason"] == "default_agent_not_prompt"
    assert fixture.runs.get_run(group_result.run_id).metadata["intent_routing"]["bypass_reason"] == "group_transcript"
