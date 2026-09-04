from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


def test_session_store_keeps_context_and_model_overrides() -> None:
    store = SessionStore()

    session = store.create_session(title="Test", context_mode="group_transcript")
    updated = store.set_llm_profile(session.session_id, "profile-1")

    assert session.session_id
    assert updated.context_mode == "group_transcript"
    assert updated.llm_profile_id == "profile-1"
    assert store.get_session(session.session_id).llm_profile_id == "profile-1"


def test_run_store_uses_generic_chat_contract() -> None:
    store = RunStore()

    run = store.create_run(kind="chat", target="chat", session_id="session-1")
    running = store.update_status(run.run_id, RunStatus.RUNNING, current_step="context")
    done = store.update_status(run.run_id, RunStatus.DONE, current_step="done")

    assert run.kind == "chat"
    assert run.target == "chat"
    assert running.status is RunStatus.RUNNING
    assert done.status is RunStatus.DONE
    assert store.get_run(run.run_id).status is RunStatus.DONE


def test_message_store_persists_generic_speaker_parts_and_parent() -> None:
    sessions = SessionStore()
    store = MessageStore(session_store=sessions)
    session = sessions.create_session()
    session_id = session.session_id

    first = store.add_message(session_id=session_id, role="user", content="hello")
    second = store.add_message(
        session_id=session_id,
        role="assistant",
        content="reply",
        run_id="run-1",
        parent_message_id=first.message_id,
        metadata={"target": "chat"},
    )

    messages = store.list_messages(session_id)

    assert [message.message_id for message in messages] == [first.message_id, second.message_id]
    assert messages[0].parts[0]["text"] == "hello"
    assert messages[1].speaker_id == "chat"
    assert messages[1].parent_message_id == first.message_id
    assert messages[1].metadata == {"target": "chat"}
