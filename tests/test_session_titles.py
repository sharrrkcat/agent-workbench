from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.session_titles import normalize_generated_title, truncate_title_input
from tests.test_api import make_client
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run
from tests.test_script_agent import ScriptRuntimeFixture, write_script_agent


class SequenceLLMRuntime(FakeLLMRuntime):
    def __init__(self, responses: list[str], fail_from_call: int | None = None) -> None:
        super().__init__(response="")
        self.responses = responses
        self.fail_from_call = fail_from_call

    def chat(self, messages, model_config=None, stream=False):
        self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": stream})
        if self.fail_from_call is not None and len(self.calls) >= self.fail_from_call:
            raise RuntimeError("title LLM failed")
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


class FailFirstTitleRuntime(SequenceLLMRuntime):
    def chat(self, messages, model_config=None, stream=False):
        self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": stream})
        if len(self.calls) == 1:
            raise RuntimeError("title LLM failed")
        index = min(len(self.calls) - 2, len(self.responses) - 1)
        return self.responses[index]


def enable_auto_titles(fixture) -> None:
    fixture.agent_runner.app_settings_store.patch({"auto_generate_session_titles": True})


def add_title_profile(fixture, profile_id: str = "title-profile", model_id: str = "title-model") -> LLMProfileSchema:
    provider = fixture.provider_profiles.create(
        ProviderProfileSchema(id=f"provider-{profile_id}", name=f"Provider {profile_id}", provider="lm_studio", base_url="http://studio/v1")
    )
    profile = fixture.llm_profiles.create(
        LLMProfileSchema(
            id=profile_id,
            alias=profile_id.replace("-", "_"),
            name=f"Title {profile_id}",
            provider_profile_id=provider.id,
            model_id=model_id,
            supports_streaming=False,
        )
    )
    return profile


def set_chat_title_profile(fixture, profile_id: str = "title-profile", model_id: str = "title-model") -> LLMProfileSchema:
    profile = add_title_profile(fixture, profile_id, model_id)
    fixture.agent_configs.set_config("chat", runtime={"llm_profile_id": profile.id})
    return profile


def test_patch_session_updates_title_and_touches_updated_at() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "  Renamed chat  "})

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Renamed chat"
    assert payload["updated_at"] > session["updated_at"]


def test_patch_session_rejects_empty_title() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "   "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_TITLE_EMPTY"


def test_patch_session_rejects_overlong_title() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "x" * 121})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_TITLE_TOO_LONG"


def test_default_title_generates_before_first_prompt_llm_call() -> None:
    llm = SequenceLLMRuntime(['"Generated Title."', "assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto_titles(fixture)
    set_chat_title_profile(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Generated Title"
    assert fixture.sessions.get_session(session.session_id).title_generation_state == "done"
    assert len(llm.calls) == 2
    assert "hello" in llm.calls[0]["messages"][0]["content"]
    assert "assistant reply" not in llm.calls[0]["messages"][0]["content"]
    messages = fixture.messages.list_messages(session.session_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert not [event for event in fixture.events.list_events() if event.type == "message_delta"]


def test_title_generation_failure_does_not_fail_main_conversation() -> None:
    llm = FailFirstTitleRuntime(["assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto_titles(fixture)
    set_chat_title_profile(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Session 1"
    assert fixture.sessions.get_session(session.session_id).title_generation_state == "failed"
    assert "Session title generation skipped: title LLM failed" in prompt_run.metadata["warnings"]


def test_prompt_agent_title_generation_reuses_resolved_model_config() -> None:
    llm = SequenceLLMRuntime(["Short title", "assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto_titles(fixture)
    profile = add_title_profile(fixture, model_id="title-model")
    fixture.agent_runner.app_settings_store.patch(
        {
            "session_title_backend": "specified_model_profile",
            "session_title_model_profile_id": profile.id,
        }
    )
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    run(fixture.runtime.handle_input(session, "hello"))

    assert llm.calls[0]["model_config"]["model"] == profile.model_id
    assert llm.calls[1]["model_config"]["model"] == "qwen2.5-3b-instruct"
    assert fixture.sessions.get_session(session.session_id).llm_profile_id is None


def test_script_agent_without_llm_does_not_generate_title() -> None:
    llm = SequenceLLMRuntime(["Script title"])
    fixture = ScriptRuntimeFixture(llm=llm)
    enable_auto_titles(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "@script_lifecycle_lab:steps hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Session 1"
    assert fixture.sessions.get_session(session.session_id).title_generation_state == "pending"
    assert llm.calls == []


def test_script_agent_title_generation_runs_before_first_ctx_llm_text(tmp_path) -> None:
    llm = SequenceLLMRuntime(["Script title", "script llm reply"])
    agents = write_script_agent(
        tmp_path,
        "title_llm_script",
        "async def run(ctx):\n"
        "    text = await ctx.llm.text(system='Say hi.', user=ctx.input.text)\n"
        "    await ctx.reply_text(text)\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=agents, llm=llm)
    enable_auto_titles(fixture)
    profile = add_title_profile(fixture)
    session = fixture.sessions.create_session(default_agent_id="title_llm_script", title="Session 1")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello from script"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Script title"
    assert "hello from script" in llm.calls[0]["messages"][0]["content"]
    assert llm.calls[1]["messages"][-1]["content"] == "hello from script"


def test_script_agent_title_generation_runs_once_before_ctx_llm_json(tmp_path) -> None:
    llm = SequenceLLMRuntime(["JSON title", '{"ok": true}', '{"ok": true}'])
    agents = write_script_agent(
        tmp_path,
        "title_json_script",
        "async def run(ctx):\n"
        "    first = await ctx.llm.json(system='Return JSON.', user=ctx.input.text)\n"
        "    second = await ctx.llm.json(system='Return JSON again.', user=ctx.input.text)\n"
        "    await ctx.reply_json({'first': first, 'second': second})\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=agents, llm=llm)
    enable_auto_titles(fixture)
    profile = add_title_profile(fixture)
    session = fixture.sessions.create_session(default_agent_id="title_json_script", title="Session 1")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "json please"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "JSON title"
    assert len(llm.calls) == 3
    assert "json please" in llm.calls[0]["messages"][0]["content"]


def test_no_available_llm_skips_title_generation_without_failing_command(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    app = create_app(llm_runtime=FakeLLMRuntime(response="unused"), use_memory=True)
    client = TestClient(app)
    state = app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(update={"model": None, "llm": None})
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/encode base64 hello"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["session"]["title"] == "Session 1"


def test_title_prompt_uses_only_current_user_message_and_truncates_input() -> None:
    long_input = "head-" + ("x" * 1500) + "-tail"
    llm = SequenceLLMRuntime(["Current turn", "assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto_titles(fixture)
    set_chat_title_profile(fixture)
    fixture.agent_runner.app_settings_store.patch({"session_title_max_input_chars": 100})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")
    fixture.messages.add_message(session_id=session.session_id, role="user", content="old secret history")
    fixture.messages.add_message(session_id=session.session_id, role="assistant", content="old assistant history", agent_id="chat")

    result = run(fixture.runtime.handle_input(session, long_input))
    title_prompt = llm.calls[0]["messages"][0]["content"]
    main_user_content = llm.calls[1]["messages"][-1]["content"]

    assert "head-" in title_prompt
    assert "-tail" in title_prompt
    assert "\n...\n" in title_prompt
    assert "assistant reply" not in title_prompt
    assert "old secret history" not in title_prompt
    assert "old assistant history" not in title_prompt
    assert long_input in main_user_content
    assert fixture.runs.get_run(result.run_id).metadata["title_generation"]["input_truncated"] is True


def test_non_default_session_title_is_not_overwritten() -> None:
    llm = SequenceLLMRuntime(["assistant reply"])
    fixture = PromptRuntimeFixture(llm=llm)
    enable_auto_titles(fixture)
    set_chat_title_profile(fixture)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Manual title")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Manual title"
    assert fixture.sessions.get_session(session.session_id).title_generation_state == "manual"
    assert len(llm.calls) == 1


def test_disabled_title_generation_marks_session_skipped_and_does_not_retry() -> None:
    llm = SequenceLLMRuntime(["assistant one", "Generated later"])
    fixture = PromptRuntimeFixture(llm=llm)
    fixture.agent_runner.app_settings_store.patch({"auto_generate_session_titles": False})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    first = run(fixture.runtime.handle_input(session, "first"))
    fixture.agent_runner.app_settings_store.patch({"auto_generate_session_titles": True})
    second = run(fixture.runtime.handle_input(fixture.sessions.get_session(session.session_id), "second"))

    assert first.success is True
    assert second.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Session 1"
    assert fixture.sessions.get_session(session.session_id).title_generation_state == "skipped"
    assert len(llm.calls) == 2


def test_manual_rename_sets_title_generation_state_manual() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "Manual"})

    assert response.status_code == 200
    assert response.json()["title_generation_state"] == "manual"


def test_command_does_not_trigger_title_generation_and_next_llm_uses_next_message() -> None:
    llm = SequenceLLMRuntime(["普通问�?, "assistant reply"])
    app = create_app(llm_runtime=llm, use_memory=True)
    client = TestClient(app)
    state = app.state.runtime_state
    provider = state.provider_profiles.create(
        ProviderProfileSchema(id="title-provider", name="Title Provider", provider="lm_studio", base_url="http://studio/v1")
    )
    profile = state.llm_profiles.create(
        LLMProfileSchema(id="title-profile", alias="title_profile", name="Title Profile", provider_profile_id=provider.id, model_id="title-model")
    )
    state.agent_configs.set_config("chat", runtime={"llm_profile_id": profile.id})
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    command = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/encode base64 secret"})
    reply = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "普通问�?})

    assert command.status_code == 200
    assert reply.status_code == 200
    assert reply.json()["session"]["title"] == "普通问�?
    assert len(llm.calls) == 2
    assert "/encode base64 secret" not in llm.calls[0]["messages"][0]["content"]
    assert "普通问�? in llm.calls[0]["messages"][0]["content"]


def test_title_truncation_and_cleanup_helpers() -> None:
    short, short_truncated = truncate_title_input("short", 100)
    long, long_truncated = truncate_title_input("a" * 80 + "b" * 80, 100)

    assert short == "short"
    assert short_truncated is False
    assert "\n...\n" in long
    assert long_truncated is True
    assert len(long) <= 100
    assert normalize_generated_title('"Title: Hello world."') == "Hello world"
    assert normalize_generated_title("标题：测试标题�?) == "测试标题"
    assert normalize_generated_title("```text\nFenced title\n```") == "Fenced title"
