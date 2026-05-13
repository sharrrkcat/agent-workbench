from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, bind_test_kb, run
from tests.test_intent_routing import enable_semantic_router


class LowSemanticKnowledgeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.calls.append({"model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        if len(texts) == 1 and "Project KB" in texts[0]:
            return [[0.0, 0.57, 0.0, 0.0, 0.0, 0.2, 0.797]]
        from tests.test_intent_routing import _fake_vector

        return [_fake_vector(text) for text in texts]


class FakeUtilityIntentService:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def extract_intent_json(self, text: str, settings) -> dict:
        self.calls.append(text)
        return self.payload


def enable_auto(fixture: PromptRuntimeFixture) -> None:
    enable_semantic_router(fixture)
    fixture.app_settings.patch(
        {
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": True,
        }
    )


def test_auto_mode_without_safe_auto_route_keeps_shadow_style_route() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.app_settings.patch(
        {
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_auto_route_safe_intents": False,
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "generate an image of a castle"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.target_id == "chat"
    assert intent["mode"] == "auto"
    assert intent["route_action"] == "metadata_only"
    assert "safe_auto_route_disabled" in intent["warnings"]


def test_auto_chat_keeps_current_prompt_agent_without_knowledge_override() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "please help me write a concise update"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "chat"
    assert intent["route_action"] == "current_prompt_agent"
    assert intent["auto_executable"] is True
    assert intent["executed"] is True
    assert intent["target_agent_id"] == "chat"
    assert "temporary_knowledge_base_ids" not in intent
    assert "knowledge_query_override" not in intent


def test_auto_image_generation_is_metadata_only_without_changing_session_default() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "generate an image of a castle"))

    assert result.success is True
    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.target_id == "chat"
    assert intent["route_action"] == "metadata_only"
    assert intent["auto_executable"] is False
    assert intent["executed"] is False
    assert "image_generation_auto_route_deferred_until_action_routing" in intent["warnings"]
    assert intent["session_default_agent_id"] == "chat"
    assert intent["session_default_changed"] is False
    assert fixture.sessions.get_session(session.session_id).default_agent_id == "chat"


def test_auto_image_generation_does_not_check_comfyui_agent_for_execution() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    fixture.agent_configs.set_config("comfyui_agent", enabled=False)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "generate an image of a castle"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.target_id == "chat"
    assert intent["route_action"] == "metadata_only"
    assert "image_generation_auto_route_deferred_until_action_routing" in intent["warnings"]


def test_auto_knowledge_query_uses_temporary_retrieval_override(monkeypatch) -> None:
    llm = FakeLLMRuntime(response="chat reply")
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto(fixture)
    fixture.app_settings.patch({"intent_routing_utility_llm_model_path": "utility_llms/test-router"})
    session = fixture.sessions.create_session(default_agent_id="chat")
    kb = bind_test_kb(fixture, session.session_id)
    fixture.agent_runner.utility_llm_service = FakeUtilityIntentService(
        {
            "intent": "knowledge_query",
            "confidence": 0.91,
            "kb_hint": "Project KB",
            "query": "stormtrooper ranks",
        }
    )
    search_calls = []

    def fake_search(**kwargs):
        search_calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "results": [
                {
                    "rank": 1,
                    "chunk_id": "chunk-1",
                    "knowledge_base_id": kb.id,
                    "source_id": "source-1",
                    "title": "Spec",
                    "heading_path": "",
                    "content": "Stormtrooper knowledge.",
                    "truncated": False,
                    "rrf_score": 1.0,
                }
            ],
            "debug": {"warnings": []},
        }

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fake_search)

    result = run(fixture.runtime.handle_input(session, "What does my Project KB say about stormtrooper ranks?"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.target_id == "chat"
    assert intent["route_action"] == "knowledge_override"
    assert intent["auto_executable"] is True
    assert intent["executed"] is True
    assert intent["temporary_knowledge_base_ids"] == [kb.id]
    assert intent["knowledge_query_override"] == "stormtrooper ranks"
    assert intent["slots"]["query"] == "stormtrooper ranks"
    assert search_calls[0]["query"] == "stormtrooper ranks"
    assert search_calls[0]["knowledge_base_ids"] == [kb.id]
    assert search_calls[0]["session_id"] is None
    assert prompt_run.metadata["knowledge_context"]["temporary_override"] is True
    assert llm.calls[0]["messages"][-1] == {"role": "user", "content": "What does my Project KB say about stormtrooper ranks?"}
    assert fixture.knowledge.list_session_bindings(session.session_id)[0].knowledge_base_id == kb.id


def test_auto_knowledge_query_uses_semantic_threshold_not_legacy_high_threshold(monkeypatch) -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    fixture.app_settings.patch({"intent_routing_high_confidence_threshold": 0.99})
    fixture.agent_runner.knowledge_model_backend = LowSemanticKnowledgeBackend()
    session = fixture.sessions.create_session(default_agent_id="chat")
    kb = bind_test_kb(fixture, session.session_id)
    search_calls = []

    def fake_search(**kwargs):
        search_calls.append(kwargs)
        return {"query": kwargs["query"], "results": [], "debug": {"warnings": []}}

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fake_search)

    result = run(fixture.runtime.handle_input(session, "What does Project KB say about stormtrooper ranks?"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    intent_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Intent semantic routing")
    assert intent["semantic_score"] == 0.57
    assert intent["semantic_thresholds_used"]["intent_min_score"] == 0.5
    assert intent["route_action"] == "knowledge_override"
    assert intent["temporary_knowledge_base_ids"] == [kb.id]
    assert intent_step.message == "knowledge_query · score 0.57 · executed"
    assert search_calls[0]["knowledge_base_ids"] == [kb.id]


def test_auto_knowledge_query_matches_kb_alias_without_persisting_binding(monkeypatch) -> None:
    llm = FakeLLMRuntime(response="chat reply")
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto(fixture)
    fixture.app_settings.patch({"intent_routing_utility_llm_model_path": "utility_llms/test-router"})
    session = fixture.sessions.create_session(default_agent_id="chat")
    profile = fixture.knowledge.create_embedding_profile(
        EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test")
    )
    kb = fixture.knowledge.create_knowledge_base(
        KnowledgeBase(
            name="Star Wars KB",
            aliases_text="星战, Star Wars, SW",
            embedding_model_profile_id=profile.id,
        )
    )
    fixture.agent_runner.utility_llm_service = FakeUtilityIntentService(
        {
            "intent": "knowledge_query",
            "confidence": 0.91,
            "kb_hint": "SW",
            "query": "stormtrooper ranks",
        }
    )
    search_calls = []

    def fake_search(**kwargs):
        search_calls.append(kwargs)
        return {"query": kwargs["query"], "results": [], "debug": {"warnings": []}}

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fake_search)

    result = run(fixture.runtime.handle_input(session, "What does SW say about stormtrooper ranks?"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert intent["route_action"] == "knowledge_override"
    assert intent["kb_id"] == kb.id
    assert intent["kb_match_source"] == "alias"
    assert intent["matched_alias"] == "SW"
    assert intent["temporary_knowledge_base_ids"] == [kb.id]
    assert search_calls[0]["knowledge_base_ids"] == [kb.id]
    assert fixture.knowledge.list_session_bindings(session.session_id) == []


def test_auto_knowledge_query_without_kb_candidate_or_active_kbs_falls_back() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    fixture.app_settings.patch({"intent_routing_utility_llm_model_path": "utility_llms/test-router"})
    fixture.agent_runner.utility_llm_service = FakeUtilityIntentService(
        {
            "intent": "knowledge_query",
            "confidence": 0.91,
            "query": "stormtrooper ranks",
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "What do the docs say about stormtrooper ranks?"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.target_id == "chat"
    assert intent["route_action"] == "fallback_current_agent"
    assert intent["auto_executable"] is False
    assert intent["executed"] is False
    assert "temporary_knowledge_base_ids" not in intent
    assert "no_kb_candidate_or_active_kbs" in intent["warnings"]


def test_auto_agent_route_hint_records_target_without_executing_agent() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    fixture.agent_configs.set_config("translate", runtime={"intent_routing_aliases_text": "translator"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "send this to translator please"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "agent_route"
    assert intent["target_agent_id"] == "translate"
    assert intent["agent_match_source"] == "alias"
    assert intent["matched_alias"] == "translator"
    assert intent["route_action"] == "metadata_only"
    assert "agent_route_auto_route_disabled" in intent["warnings"]


def test_auto_command_like_intent_is_not_executed() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "please free memory now"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "command_like"
    assert intent["route_action"] == "metadata_only"
    assert "command_like_auto_route_disabled" in intent["warnings"]
