from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


def test_session_store_creates_session_and_changes_default_agent() -> None:
    store = SessionStore()

    session = store.create_session(default_agent_id="chat", title="Test")
    updated = store.set_default_agent(session.session_id, "translate")

    assert session.session_id
    assert session.title == "Test"
    assert updated.default_agent_id == "translate"
    assert store.get_session(session.session_id).default_agent_id == "translate"
    assert [item.session_id for item in store.list_sessions()] == [session.session_id]


def test_run_store_creates_and_updates_run() -> None:
    store = RunStore()

    run = store.create_run(kind="command", target_id="/base64", session_id="session-1")
    running = store.update_status(run.run_id, RunStatus.RUNNING, current_step="started")
    done = store.update_status(run.run_id, RunStatus.DONE, current_step="done")

    assert run.status == RunStatus.PENDING
    assert running.status == RunStatus.RUNNING
    assert running.current_step == "started"
    assert done.status == RunStatus.DONE
    assert done.current_step == "done"
    assert store.get_run(run.run_id).status == RunStatus.DONE
    assert [item.run_id for item in store.list_runs("session-1")] == [run.run_id]


def test_message_store_appends_and_lists_messages() -> None:
    store = MessageStore()

    first = store.add_message(session_id="session-1", role="user", content="hello")
    second = store.add_message(
        session_id="session-1",
        role="assistant",
        content="placeholder",
        agent_id="chat",
        action_id="default",
        run_id="run-1",
        parent_message_id=first.message_id,
    )

    messages = store.list_messages("session-1")

    assert [message.message_id for message in messages] == [first.message_id, second.message_id]
    assert messages[0].content == "hello"
    assert messages[1].agent_id == "chat"
    assert messages[1].parent_message_id == first.message_id

