from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase
from ai_workbench.core.utility_llm import UtilityLLMService
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, bind_test_kb, run
from tests.test_intent_routing import enable_semantic_router
from tests.test_session_titles import set_chat_title_profile


class LowSemanticKnowledgeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.calls.append({"model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        if len(texts) == 1 and "Project KB" in texts[0]:
            return [[0.0, 0.57, 0.0, 0.0, 0.0, 0.2, 0.0, 0.797]]
        from tests.test_intent_routing import _fake_vector

        return [_fake_vector(text) for text in texts]


class FakeUtilityIntentService:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def extract_intent_json(self, text: str, settings) -> dict:
        self.calls.append(text)
        return self.payload


class FakePetRuntime:
    def __init__(self, default_pet_id: str = "jedi_cal") -> None:
        self.default_pet_id = default_pet_id
        self.command_calls: list[str] = []
        self.pets = [
            {"id": "jedi_cal", "display_name": "Jedi Cal", "valid": True},
            {"id": "bd_1", "display_name": "BD-1", "valid": True},
        ]

    def get_settings(self, context=None) -> dict:
        return {"settings": {"default_pet_id": self.default_pet_id}}

    def list_pets(self, context=None) -> dict:
        return {"pets": list(self.pets)}

    def command(self, args: str = "", context=None) -> str:
        self.command_calls.append(args)
        return f"pet command: {args or 'status'}"


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


def enable_utility(fixture: PromptRuntimeFixture, payload: dict) -> FakeUtilityIntentService:
    fixture.app_settings.patch({"intent_routing_utility_llm_model_path": "utility_llms/test-router"})
    service = FakeUtilityIntentService(payload)
    fixture.agent_runner.utility_llm_service = service
    return service


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


def test_auto_chat_does_not_call_utility_llm_model_profile() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto(fixture)
    profile = set_chat_title_profile(fixture, "utility-profile", "utility-model")
    fixture.app_settings.patch({
        "intent_routing_utility_llm_backend": "model_profile",
        "intent_routing_utility_llm_model_profile_id": profile.id,
    })
    fixture.agent_runner.utility_llm_service = UtilityLLMService(
        llm_runtime=llm,
        llm_profile_store=fixture.llm_profiles,
        provider_profile_store=fixture.provider_profiles,
        capability_registry=fixture.agent_runner.capability_registry,
        capability_config_store=fixture.agent_runner.capability_config_store,
    )
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "please help me write a concise update"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert result.success is True
    assert intent["predicted_intent"] == "chat"
    assert intent["utility_used"] is False
    assert len(llm.calls) == 1


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
    assert "image_generation_action_routing_not_ready" in intent["warnings"]
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
    assert "image_generation_action_routing_not_ready" in intent["warnings"]


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


def test_auto_knowledge_query_uses_utility_llm_model_profile_slots(monkeypatch) -> None:
    llm = FakeLLMRuntime(response='{"intent":"knowledge_query","confidence":0.91,"kb_hint":"Project KB","query":"stormtrooper ranks"}')
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto(fixture)
    profile = set_chat_title_profile(fixture, "utility-profile", "utility-model")
    fixture.app_settings.patch({
        "intent_routing_utility_llm_backend": "model_profile",
        "intent_routing_utility_llm_model_profile_id": profile.id,
    })
    fixture.agent_runner.utility_llm_service = UtilityLLMService(
        llm_runtime=llm,
        llm_profile_store=fixture.llm_profiles,
        provider_profile_store=fixture.provider_profiles,
        capability_registry=fixture.agent_runner.capability_registry,
        capability_config_store=fixture.agent_runner.capability_config_store,
    )
    session = fixture.sessions.create_session(default_agent_id="chat")
    kb = bind_test_kb(fixture, session.session_id)
    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", lambda **kwargs: {"query": kwargs["query"], "results": [], "debug": {"warnings": []}})

    result = run(fixture.runtime.handle_input(session, "What does my Project KB say about stormtrooper ranks?"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert intent["route_action"] == "knowledge_override"
    assert intent["executed"] is True
    assert intent["temporary_knowledge_base_ids"] == [kb.id]
    assert intent["slots"]["query"] == "stormtrooper ranks"
    assert llm.calls[0]["model_config"]["model"] == "utility-model"


def test_auto_knowledge_query_uses_semantic_threshold_not_legacy_high_threshold(monkeypatch) -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    # Legacy high-confidence settings are no longer accepted by the settings patch API.
    enable_utility(fixture, {"intent": "knowledge_query", "confidence": 0.9, "query": "stormtrooper ranks"})
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
    assert intent_step.message == "knowledge_query - executed"
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


def test_blocked_knowledge_query_candidate_skips_web_context(monkeypatch) -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    fixture.app_settings.patch({"web_context_enabled": True})
    enable_utility(fixture, {"intent": "knowledge_query", "confidence": 0.9, "query": "Cal Kestis 的经历", "kb_hint": "Star Wars"})
    fixture.agent_runner.semantic_router = type(
        "LowScoreKnowledgeRouter",
        (),
        {
            "decide": lambda self, *args, **kwargs: {
                "predicted_intent": "knowledge_query",
                "confidence": 0.42,
                "semantic_score": 0.42,
                "semantic_margin": 0.2,
                "semantic_thresholds_used": {"intent_min_score": 0.5, "intent_min_margin": 0.03},
                "route_action": "metadata_only",
                "auto_executable": True,
                "warnings": [],
            }
        },
    )()
    session = fixture.sessions.create_session(default_agent_id="chat")

    def fail_web_search(runtime_registry):
        raise AssertionError("blocked knowledge query candidates must not call Web Search")

    monkeypatch.setattr("ai_workbench.core.web_context._search_from_runtime", fail_web_search)

    result = run(fixture.runtime.handle_input(session, "根据现有的 Star Wars 知识库回答 Cal Kestis 的经历"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    web = prompt_run.metadata["web_context"]
    web_plan_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Web context plan")
    assert result.success is True
    assert intent["predicted_intent"] == "knowledge_query"
    assert intent["not_executed_reason"] == "semantic_confidence_too_low"
    assert web["attempted"] is False
    assert web["skipped_reason"] == "knowledge_query_candidate_blocked"
    assert web["intent_influence"] == "knowledge_query:semantic_confidence_too_low"
    assert web["warnings"] == ["knowledge_query_below_threshold"]
    assert web_plan_step.message == "skipped: knowledge_query_candidate_blocked"


def test_auto_knowledge_query_requires_utility_slots(monkeypatch) -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")
    kb = bind_test_kb(fixture, session.session_id)
    search_calls = []

    def fake_search(**kwargs):
        search_calls.append(kwargs)
        return {"query": kwargs["query"], "results": [], "debug": {"warnings": []}}

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fake_search)

    result = run(fixture.runtime.handle_input(session, "What does Project KB say about stormtrooper ranks?"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert intent["predicted_intent"] == "knowledge_query"
    assert intent["route_action"] == "fallback_current_agent"
    assert intent["not_executed_reason"] in {"utility_llm_required", "utility_llm_unavailable"}
    assert "temporary_knowledge_base_ids" not in intent
    assert search_calls[0]["knowledge_base_ids"] is None
    assert search_calls[0]["session_id"] == session.session_id
    assert fixture.knowledge.list_session_bindings(session.session_id)[0].knowledge_base_id == kb.id


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


def test_auto_web_query_is_diagnostic_only_and_can_feed_web_context(monkeypatch) -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_auto(fixture)
    fixture.app_settings.patch({"web_context_enabled": True})
    service = enable_utility(
        fixture,
        {
            "intent": "web_query",
            "confidence": 0.9,
            "query": "Qwen recent releases",
            "freshness": "recent",
            "domain_hints": ["qwenlm.github.io"],
            "language_hint": "en",
        },
    )
    session = fixture.sessions.create_session(default_agent_id="chat")
    search_calls = []

    def fake_search_from_runtime(runtime_registry):
        def search(query, context=None):
            search_calls.append((query, context))
            return {
                "provider": "searxng",
                "results": [
                    {
                        "rank": 1,
                        "title": "Qwen release",
                        "url": "https://example.com/qwen",
                        "domain": "example.com",
                        "snippet": "Qwen release news.",
                    }
                ],
            }

        return search

    monkeypatch.setattr("ai_workbench.core.web_context._search_from_runtime", fake_search_from_runtime)

    result = run(fixture.runtime.handle_input(session, "find recent news about Qwen"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    web_context = prompt_run.metadata["web_context"]
    intent_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Intent semantic routing")
    web_plan_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Web context plan")
    assert result.success is True
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "web_query"
    assert intent["route_action"] == "metadata_only"
    assert intent["auto_executable"] is False
    assert intent["would_execute"] is False
    assert intent["executed"] is False
    assert intent["not_executed_reason"] == "web_query_diagnostic_only"
    assert intent["web_context_usage"] == "used_for_web_context"
    assert intent["slots"]["query"] == "Qwen recent releases"
    assert intent["slots"]["domain_hints"] == ["qwenlm.github.io"]
    assert web_context["query_source"] == "intent_web_query_slots"
    assert web_context["attempted"] is True
    assert web_context["injected"] is True
    assert search_calls[0][0] == "Qwen recent releases"
    assert intent_step.message == "web_query - used for Web context"
    assert "web_query_diagnostic_only" not in intent_step.message
    assert web_plan_step.metadata["web_context_plan"]["query_source"] == "intent_web_query_slots"
    assert "web_context" not in web_plan_step.metadata
    assert service.calls == ["find recent news about Qwen"]


def test_auto_pet_command_requires_utility_slots() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "show pet status"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["route_action"] == "fallback_current_agent"
    assert intent["not_executed_reason"] in {"utility_llm_required", "utility_llm_unavailable"}
    assert pet_runtime.command_calls == []


def test_utility_semantic_conflict_does_not_execute_pet_command() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "knowledge_query", "query": "pet status"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "show pet status"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["not_executed_reason"] == "utility_semantic_action_conflict"
    assert pet_runtime.command_calls == []


def test_auto_pet_command_routes_only_to_pet_command() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "wake", "target_pet_hint": "Jedi Cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "bring out Jedi Cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert command_run.target_id == "/pet"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["pet_action"] == "wake"
    assert intent["target_pet_id"] == "jedi_cal"
    assert intent["generated_command"] == "/pet select jedi_cal"
    assert intent["route_action"] == "pet_command"
    assert intent["auto_executable"] is True
    assert intent["executed"] is True
    assert pet_runtime.command_calls == ["select jedi_cal"]


def test_auto_pet_command_uses_utility_llm_model_profile_slots() -> None:
    llm = FakeLLMRuntime(response='{"intent":"pet_command","domain":"workbench_pet","action":"wake","target_pet_hint":"Jedi Cal"}')
    fixture = PromptRuntimeFixture(llm=llm)
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    profile = set_chat_title_profile(fixture, "utility-profile", "utility-model")
    fixture.app_settings.patch({
        "intent_routing_utility_llm_backend": "model_profile",
        "intent_routing_utility_llm_model_profile_id": profile.id,
    })
    fixture.agent_runner.utility_llm_service = UtilityLLMService(
        llm_runtime=llm,
        llm_profile_store=fixture.llm_profiles,
        provider_profile_store=fixture.provider_profiles,
        capability_registry=fixture.agent_runner.capability_registry,
        capability_config_store=fixture.agent_runner.capability_config_store,
    )
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "wake up Jedi Cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["route_action"] == "pet_command"
    assert intent["generated_command"] == "/pet select jedi_cal"
    assert pet_runtime.command_calls == ["select jedi_cal"]
    assert llm.calls[0]["model_config"]["model"] == "utility-model"


def test_auto_pet_command_persists_original_user_message_before_result() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "status"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "show pet status"))

    assert result.success is True
    messages = fixture.messages.list_messages(session.session_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].parts[0]["text"] == "show pet status"
    assert messages[0].metadata["intent_routing"]["predicted_intent"] == "pet_command"
    assert messages[0].metadata["intent_routing"]["generated_command"] == "/pet status"
    assert "original_user_text" not in messages[0].metadata["intent_routing"]
    assert messages[1].parent_message_id == messages[0].message_id
    command_run = fixture.runs.get_run(result.run_id)
    assert command_run.kind == "command"
    assert command_run.target_id == "/pet"
    assert command_run.metadata["input_message_id"] == messages[0].message_id
    assert command_run.metadata["intent_routing"]["executed"] is True
    assert command_run.metadata["intent_routing"]["generated_command"] == "/pet status"
    assert pet_runtime.command_calls == ["status"]


def test_auto_pet_command_show_pet_status_stays_status() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "status"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "show pet status"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["pet_action"] == "status"
    assert intent["generated_command"] == "/pet status"
    assert pet_runtime.command_calls == ["status"]


def test_auto_pet_command_wake_accepts_summon_phrasing() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "wake", "target_pet_hint": "cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "summon pet cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["pet_action"] == "wake"
    assert intent["target_pet_id"] == "jedi_cal"
    assert intent["generated_command"] == "/pet select jedi_cal"
    assert pet_runtime.command_calls == ["select jedi_cal"]


def test_auto_pet_command_wake_accepts_bring_out_phrasing() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "wake", "target_pet_hint": "cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "bring out pet cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["pet_action"] == "wake"
    assert intent["target_pet_id"] == "jedi_cal"
    assert intent["generated_command"] == "/pet select jedi_cal"
    assert pet_runtime.command_calls == ["select jedi_cal"]


def test_shadow_pet_command_records_metadata_without_executing() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_semantic_router(fixture)
    fixture.app_settings.patch({"intent_routing_enabled": True, "intent_routing_default_for_prompt_agents": True, "intent_routing_mode": "shadow"})
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "tuck", "target_pet_hint": "Jedi Cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "隐藏 Jedi Cal"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["pet_action"] == "tuck"
    assert intent["target_pet_id"] is None
    assert intent["target_ignored_for_action"] is True
    assert "pet_target_ignored_for_action" in intent["warnings"]
    assert intent["executed"] is False
    assert pet_runtime.command_calls == []


def test_pet_command_ambiguous_pet_does_not_execute() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    pet_runtime.pets.append({"id": "jedi_cal_alt", "display_name": "Jedi Cal", "valid": True})
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "wake", "target_pet_hint": "Jedi Cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "唤醒 Jedi Cal"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["not_executed_reason"] == "ambiguous_pet_candidate"
    assert intent["auto_executable"] is False
    assert pet_runtime.command_calls == []


def test_reality_pet_question_stays_chat() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.agent_runner.runtime_registry.replace("pet", FakePetRuntime())
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "my real cat will not eat today"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "chat"


def test_reality_pet_status_question_stays_chat() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.agent_runner.runtime_registry.replace("pet", FakePetRuntime())
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "how is my real cat doing"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["predicted_intent"] == "chat"


def test_pet_names_without_pet_operation_do_not_execute() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.agent_runner.runtime_registry.replace("pet", FakePetRuntime())
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "what is the relationship between Cal and Yoda?"))

    prompt_run = fixture.runs.get_run(result.run_id)
    intent = prompt_run.metadata["intent_routing"]
    assert prompt_run.kind == "agent"
    assert prompt_run.target_id == "chat"
    assert intent["route_action"] != "pet_command"


def test_pet_wake_target_not_current_selects_target_pet() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime(default_pet_id="bd_1")
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "wake", "target_pet_hint": "Cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "wake pet Cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["predicted_intent"] == "pet_command"
    assert intent["target_pet_id"] == "jedi_cal"
    assert intent["generated_command"] == "/pet select jedi_cal"
    assert pet_runtime.command_calls == ["select jedi_cal"]


def test_pet_select_low_semantic_margin_executes_with_warning() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime(default_pet_id="bd_1")
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    fixture.agent_runner.semantic_router = type(
        "LowMarginPetRouter",
        (),
        {
            "decide": lambda self, *args, **kwargs: {
                "predicted_intent": "pet_command",
                "confidence": 0.9,
                "semantic_score": 0.9,
                "semantic_margin": 0.0,
                "semantic_thresholds_used": {"intent_min_score": 0.5, "intent_min_margin": 0.03},
                "route_action": "metadata_only",
                "auto_executable": True,
                "warnings": [],
            }
        },
    )()
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "select", "target_pet_hint": "Cal", "source_pet_hint": "Old Pet"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "select pet Cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["generated_command"] == "/pet select jedi_cal"
    assert intent["would_execute"] is True
    assert "semantic_margin_too_low" in intent["warnings"]
    assert pet_runtime.command_calls == ["select jedi_cal"]


def test_pet_reload_ignores_target_hint_and_executes_current_command() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    enable_utility(fixture, {"intent": "pet_command", "domain": "workbench_pet", "action": "reload", "target_pet_hint": "Cal"})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "reload pet Cal"))

    command_run = fixture.runs.get_run(result.run_id)
    intent = command_run.metadata["intent_routing"]
    assert command_run.kind == "command"
    assert intent["generated_command"] == "/pet reload"
    assert intent["target_ignored_for_action"] is True
    assert "pet_target_ignored_for_action" in intent["warnings"]
    assert pet_runtime.command_calls == ["reload"]


def test_explicit_pet_command_bypasses_intent_routing() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    pet_runtime = FakePetRuntime()
    fixture.agent_runner.runtime_registry.replace("pet", pet_runtime)
    enable_auto(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "/pet wake"))

    command_run = fixture.runs.get_run(result.run_id)
    assert command_run.kind == "command"
    assert command_run.target_id == "/pet"
    assert "intent_routing" not in command_run.metadata or command_run.metadata["intent_routing"].get("skip_reason") == "explicit_command"
    assert pet_runtime.command_calls == ["wake"]
