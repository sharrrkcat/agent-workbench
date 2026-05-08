from ai_workbench.core.events import EventBus
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.core.stores import RunEventStore


def test_eventbus_close_wakes_subscribers_and_is_idempotent() -> None:
    events = EventBus()
    first = events.subscribe()
    second = events.subscribe()

    events.close()
    events.close()

    assert first.get_nowait() is None
    assert second.get_nowait() is None
    assert events._subscribers == []


def test_eventbus_unsubscribe_is_idempotent() -> None:
    events = EventBus()
    queue = events.subscribe()

    assert events.subscriber_count() == 1
    events.unsubscribe(queue)
    events.unsubscribe(queue)

    assert events.subscriber_count() == 0
    assert events._subscribers == []


def test_eventbus_emit_after_close_is_stored_but_not_published() -> None:
    events = EventBus()
    queue = events.subscribe()
    events.close()

    event = events.emit("run_started", session_id="session-1", run_id="run-1")

    assert events.list_events() == [event]
    assert queue.get_nowait() is None


def test_message_delta_is_broadcast_but_not_persisted_by_default() -> None:
    run_events = RunEventStore()
    settings = AppSettingsStore()
    events = EventBus(run_event_store=run_events, app_settings_store=settings)
    queue = events.subscribe()

    event = events.emit(
        "message_delta",
        session_id="session-1",
        run_id="run-1",
        message_id="message-1",
        payload={"seq": 1, "delta": "he", "reasoning_delta": None},
    )

    assert events.list_events() == [event]
    assert queue.get_nowait() == event
    assert run_events.list_events("run-1") == []


def test_message_delta_persists_when_data_setting_is_enabled() -> None:
    run_events = RunEventStore()
    settings = AppSettingsStore()
    settings.patch({"persist_streaming_message_deltas": True})
    events = EventBus(run_event_store=run_events, app_settings_store=settings)

    events.emit(
        "message_delta",
        session_id="session-1",
        run_id="run-1",
        message_id="message-1",
        payload={"seq": 1, "delta": "he", "reasoning_delta": None},
    )
    events.emit(
        "message_completed",
        session_id="session-1",
        run_id="run-1",
        message_id="message-1",
        payload={"seq": 2, "message": {"content": "he"}},
    )

    persisted = run_events.list_events("run-1")
    assert [event.type for event in persisted] == ["message_delta", "message_completed"]


def test_non_delta_events_persist_with_default_settings() -> None:
    run_events = RunEventStore()
    settings = AppSettingsStore()
    events = EventBus(run_event_store=run_events, app_settings_store=settings)

    events.emit("message_completed", session_id="session-1", run_id="run-1", payload={"message": {"content": "hello"}})
    events.emit("run_step_created", session_id="session-1", run_id="run-1", payload={"step": {"label": "Calling LLM"}})
    events.emit("run_warning", session_id="session-1", run_id="run-1", payload={"warning": "careful"})
    events.emit("run_failed", session_id="session-1", run_id="run-1", payload={"error": "failed"})

    assert [event.type for event in run_events.list_events("run-1")] == [
        "message_completed",
        "run_step_created",
        "run_warning",
        "run_failed",
    ]
