from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run

from ai_workbench.core.schema.run import RunStatus


def make_translated_message(fixture: PromptRuntimeFixture, session):
    result = run(fixture.runtime.handle_input(session, "@translate bonjour"))
    assert result.success is True
    return fixture.messages.list_messages(session.session_id)[-1]


def test_prompt_agent_default_output_contains_available_actions() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    message = make_translated_message(fixture, session)

    assert message.available_actions


def test_available_actions_exclude_default_action() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    message = make_translated_message(fixture, session)

    assert "default" not in {action["action_id"] for action in message.available_actions}


def test_available_actions_include_translate_actions() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    message = make_translated_message(fixture, session)

    assert {action["action_id"] for action in message.available_actions} == {"formal", "casual", "retry"}
    assert all(action["source_message_id"] == message.message_id for action in message.available_actions)


def test_agent_output_parent_message_points_to_user_input() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    message = make_translated_message(fixture, session)
    user_message = fixture.messages.list_messages(session.session_id)[0]

    assert user_message.role == "user"
    assert message.parent_message_id == user_message.message_id


def test_text_agent_action_invocation_uses_latest_source_message() -> None:
    llm = FakeLLMRuntime(response="formal hello")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)

    result = run(fixture.runtime.handle_input(session, "@translate:formal"))
    action_message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert action_message.action_id == "formal"
    assert action_message.parent_message_id == source.message_id


def test_runtime_invoke_action_uses_same_formal_action() -> None:
    llm = FakeLLMRuntime(response="formal hello")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)

    result = run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id=source.message_id,
        )
    )
    action_message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert action_message.action_id == "formal"
    assert action_message.parent_message_id == source.message_id


def test_user_text_cannot_directly_invoke_internal_action() -> None:
    fixture = PromptRuntimeFixture()
    session = fixture.sessions.create_session(default_agent_id="comfyui_agent")

    result = run(fixture.runtime.handle_input(session, ":save_recipe_from_form"))

    assert result.success is False
    assert result.error_code == "ACTION_NOT_CALLABLE"
    assert "not user-callable" in result.error


def test_runtime_invoke_action_rejects_internal_action() -> None:
    fixture = PromptRuntimeFixture()
    session = fixture.sessions.create_session(default_agent_id="comfyui_agent")

    result = run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="comfyui_agent",
            action_id="save_recipe_from_form",
        )
    )

    assert result.success is False
    assert result.error_code == "ACTION_NOT_CALLABLE"


def test_selected_message_context_includes_source_agent_message() -> None:
    llm = FakeLLMRuntime(response="formal hello")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)

    run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id=source.message_id,
        )
    )
    sent = llm.calls[-1]["messages"]

    assert {"role": "assistant", "content": source.content} in sent


def test_selected_message_context_includes_original_user_message() -> None:
    llm = FakeLLMRuntime(response="formal hello")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)
    original = fixture.messages.get_message(source.parent_message_id)

    run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id=source.message_id,
        )
    )
    sent = llm.calls[-1]["messages"]

    assert {"role": "user", "content": original.content} in sent


def test_action_output_parent_message_points_to_source_message() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="formal hello"))
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)

    run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id=source.message_id,
        )
    )
    action_message = fixture.messages.list_messages(session.session_id)[-1]

    assert action_message.parent_message_id == source.message_id


def test_action_run_records_action_id() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="formal hello"))
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)

    result = run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id=source.message_id,
        )
    )
    action_run = fixture.runs.get_run(result.run_id)

    assert action_run.kind == "action"
    assert action_run.action_id == "formal"


def test_action_invoked_event_is_recorded() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="formal hello"))
    session = fixture.sessions.create_session()
    source = make_translated_message(fixture, session)

    run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id=source.message_id,
        )
    )

    assert "action_invoked" in [event.type for event in fixture.events.list_events()]


def test_message_done_event_includes_available_actions() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    make_translated_message(fixture, session)
    message_done = [event for event in fixture.events.list_events() if event.type == "message_done"][-1]

    assert {action["action_id"] for action in message_done.payload["available_actions"]} == {
        "formal",
        "casual",
        "retry",
    }


def test_missing_source_message_returns_structured_failed_run() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="formal hello"))
    session = fixture.sessions.create_session()

    result = run(
        fixture.runtime.invoke_action(
            session_id=session.session_id,
            agent_id="translate",
            action_id="formal",
            source_message_id="missing-message",
        )
    )
    action_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert "missing-message" in result.error
    assert action_run.status == RunStatus.FAILED
