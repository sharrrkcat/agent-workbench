from tests.test_intent_auto_routing import FakeUtilityIntentService, bind_test_kb, enable_auto
from tests.test_prompt_agent_execution import PromptRuntimeFixture, run
from tests.test_session_titles import SequenceLLMRuntime, add_title_profile, set_chat_title_profile


class TitleUtilityLLM:
    def __init__(self, title: str = "Utility Title") -> None:
        self.title = title
        self.title_calls: list[str] = []
        self.unload_calls = 0

    async def generate_title(self, user_input, settings):
        self.title_calls.append(user_input)
        return {"title": self.title, "backend": "utility_llm", "model_path": settings.intent_routing_utility_llm_model_path}

    def unload(self):
        self.unload_calls += 1
        return {"ok": True}


def test_follow_agent_backend_prefers_input_override_profile() -> None:
    llm = SequenceLLMRuntime(["Input Override Title", "translated reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    input_profile = add_title_profile(fixture, "input-profile", "input-model")
    session_profile = add_title_profile(fixture, "session-profile", "session-model")
    invoked_profile = add_title_profile(fixture, "invoked-profile", "invoked-model")
    fixture.agent_configs.set_config("chat", runtime={"llm_profile_id": session_profile.id})
    fixture.agent_configs.set_config("translate", runtime={"llm_profile_id": invoked_profile.id})
    fixture.app_settings.patch({"auto_generate_session_titles": True, "session_title_backend": "follow_agent_model_profile"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")
    fixture.sessions.set_llm_profile(session.session_id, input_profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@translate hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["backend"] == "model_profile"
    assert metadata["requested_backend"] == "follow_agent_model_profile"
    assert metadata["model_profile_resolution"] == "input_override"
    assert metadata["model_profile_id"] == input_profile.id
    assert llm.calls[0]["model_config"]["model"] == "input-model"


def test_follow_agent_backend_prefers_session_agent_before_invoked_agent() -> None:
    llm = SequenceLLMRuntime(["Session Agent Title", "translated reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    session_profile = add_title_profile(fixture, "session-agent-profile", "session-agent-model")
    invoked_profile = add_title_profile(fixture, "invoked-agent-profile", "invoked-agent-model")
    fixture.agent_configs.set_config("chat", runtime={"llm_profile_id": session_profile.id})
    fixture.agent_configs.set_config("translate", runtime={"llm_profile_id": invoked_profile.id})
    fixture.app_settings.patch({"auto_generate_session_titles": True, "session_title_backend": "follow_agent_model_profile"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "@translate hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["model_profile_resolution"] == "session_agent"
    assert metadata["model_profile_id"] == session_profile.id
    assert llm.calls[0]["model_config"]["model"] == "session-agent-model"
    assert llm.calls[1]["model_config"]["model"] == "invoked-agent-model"


def test_specific_model_profile_backend_uses_configured_profile() -> None:
    llm = SequenceLLMRuntime(["Specific Title", "assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    chat_profile = set_chat_title_profile(fixture, "chat-profile", "chat-model")
    title_profile = add_title_profile(fixture, "specific-title-profile", "specific-title-model")
    fixture.app_settings.patch(
        {
            "auto_generate_session_titles": True,
            "session_title_backend": "specified_model_profile",
            "session_title_model_profile_id": title_profile.id,
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["requested_backend"] == "specified_model_profile"
    assert metadata["model_profile_resolution"] == "specified"
    assert metadata["model_profile_id"] == title_profile.id
    assert llm.calls[0]["model_config"]["model"] == "specific-title-model"
    assert llm.calls[1]["model_config"]["model"] == chat_profile.model_id


def test_specific_model_profile_missing_skips_title_without_failing_reply() -> None:
    llm = SequenceLLMRuntime(["assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    fixture.app_settings.patch({"auto_generate_session_titles": True, "session_title_backend": "specified_model_profile"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Session 1"
    assert metadata["state"] == "skipped"
    assert metadata["reason"] == "specified_model_profile_missing"
    assert "session_title_model_profile_missing" in metadata["warnings"]
    assert len(llm.calls) == 1


def test_specific_model_profile_disabled_skips_title_without_failing_reply() -> None:
    llm = SequenceLLMRuntime(["assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_title_profile(fixture, "disabled-title-profile", "disabled-model")
    fixture.llm_profiles.update(profile.id, {"enabled": False})
    fixture.app_settings.patch(
        {
            "auto_generate_session_titles": True,
            "session_title_backend": "specified_model_profile",
            "session_title_model_profile_id": profile.id,
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["state"] == "skipped"
    assert metadata["reason"] == "llm_profile_disabled"
    assert "llm_profile_disabled" in metadata["warnings"]
    assert len(llm.calls) == 1


def test_utility_backend_unload_after_generation_releases_utility_model() -> None:
    llm = SequenceLLMRuntime(["assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    utility = TitleUtilityLLM("Utility Title")
    fixture.agent_runner.utility_llm_service = utility
    fixture.app_settings.patch(
        {
            "auto_generate_session_titles": True,
            "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B",
            "session_title_unload_after_generation": True,
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["backend"] == "utility_llm"
    assert metadata["unload_state"] == "released"
    assert utility.unload_calls == 1


def test_model_profile_unload_defers_when_title_model_matches_current_response(monkeypatch) -> None:
    llm = SequenceLLMRuntime(["Shared Title", "assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    profile = set_chat_title_profile(fixture, "shared-profile", "shared-model")
    fixture.app_settings.patch(
        {
            "auto_generate_session_titles": True,
            "session_title_backend": "follow_agent_model_profile",
            "session_title_unload_after_generation": True,
        }
    )
    unload_calls = []
    monkeypatch.setattr(
        "ai_workbench.core.runner.unload_model_for_profile",
        lambda **kwargs: unload_calls.append(kwargs)
        or {"ok": True, "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [], "errors": []},
    )
    monkeypatch.setattr(
        "ai_workbench.core.runner.refresh_provider_status_for_profile",
        lambda provider_profile_store, llm_profile_store, provider_profile_id: {"provider_profile_id": provider_profile_id, "status": "READY"},
    )
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["unload_state"] == "released"
    assert fixture.sessions.get_session(session.session_id).title_generation_metadata["unload_state"] == "released"
    assert unload_calls == [
        {
            "provider_profile_store": fixture.provider_profiles,
            "llm_profile_store": fixture.llm_profiles,
            "provider_profile_id": profile.provider_profile_id,
            "model_profile_id": profile.id,
            "model_id": "shared-model",
            "reason": "session_title_generation",
        }
    ]


def test_model_profile_unload_unsupported_records_no_supported_release(monkeypatch) -> None:
    llm = SequenceLLMRuntime(["Specific Title", "assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    title_profile = add_title_profile(fixture, "unsupported-title-profile", "title-model")
    fixture.app_settings.patch(
        {
            "auto_generate_session_titles": True,
            "session_title_backend": "specified_model_profile",
            "session_title_model_profile_id": title_profile.id,
            "session_title_unload_after_generation": True,
        }
    )
    monkeypatch.setattr(
        "ai_workbench.core.runner.unload_model_for_profile",
        lambda **kwargs: {
            "ok": False,
            "code": "MODEL_UNLOAD_UNSUPPORTED",
            "provider_profile_id": kwargs["provider_profile_id"],
            "model_id": kwargs["model_id"],
            "unloaded": [],
            "errors": [{"code": "MODEL_UNLOAD_UNSUPPORTED", "message": "unsupported"}],
        },
    )
    monkeypatch.setattr(
        "ai_workbench.core.runner.refresh_provider_status_for_profile",
        lambda provider_profile_store, llm_profile_store, provider_profile_id: {"provider_profile_id": provider_profile_id, "status": "READY"},
    )
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert result.success is True
    assert metadata["unload_state"] == "no_supported_release"


def test_intent_auto_knowledge_query_title_uses_original_user_input(monkeypatch) -> None:
    llm = SequenceLLMRuntime(["Knowledge Title", "chat reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    title_profile = set_chat_title_profile(fixture, "knowledge-title-profile", "knowledge-title-model")
    fixture.app_settings.patch({"auto_generate_session_titles": True, "session_title_backend": "follow_agent_model_profile"})
    enable_auto(fixture)
    fixture.app_settings.patch({"intent_routing_utility_llm_model_path": "utility_llms/test-router"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")
    kb = bind_test_kb(fixture, session.session_id)
    fixture.agent_runner.utility_llm_service = FakeUtilityIntentService(
        {
            "intent": "knowledge_query",
            "confidence": 0.91,
            "kb_hint": "Project KB",
            "query": "rewritten retrieval query",
        }
    )
    monkeypatch.setattr(
        "ai_workbench.core.knowledge_context.search_knowledge",
        lambda **kwargs: {
            "query": kwargs["query"],
            "results": [
                {
                    "rank": 1,
                    "chunk_id": "chunk-1",
                    "knowledge_base_id": kb.id,
                    "source_id": "source-1",
                    "title": "Spec",
                    "heading_path": "",
                    "content": "Knowledge snippet.",
                    "truncated": False,
                    "rrf_score": 1.0,
                }
            ],
            "debug": {"warnings": []},
        },
    )
    user_input = "What does my Project KB say about title generation?"

    result = run(fixture.runtime.handle_input(session, user_input))

    prompt_run = fixture.runs.get_run(result.run_id)
    metadata = prompt_run.metadata["title_generation"]
    assert result.success is True
    assert prompt_run.metadata["intent_routing"]["route_action"] == "knowledge_override"
    assert metadata["trigger"] == "first_llm_capable_user_message"
    assert metadata["model_profile_id"] == title_profile.id
    assert llm.calls[0]["model_config"]["model"] == "knowledge-title-model"
    assert user_input in llm.calls[0]["messages"][0]["content"]
    assert "rewritten retrieval query" not in llm.calls[0]["messages"][0]["content"]
