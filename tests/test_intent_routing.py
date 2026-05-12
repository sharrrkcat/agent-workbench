from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run


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
