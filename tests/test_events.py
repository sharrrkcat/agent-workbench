from ai_workbench.core.events import EventBus


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
