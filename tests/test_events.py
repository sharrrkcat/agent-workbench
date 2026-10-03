import asyncio
import json

from ai_workbench.core.events import EventBus
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.core.stores import RunEventStore


def test_eventbus_close_wakes_subscribers_and_is_idempotent() -> None:
    events = EventBus()
    first = events.subscribe("session-1")
    second = events.subscribe("session-1")

    events.close()
    events.close()

    assert first.closed.is_set() and first.pending_bytes == 0
    assert second.closed.is_set()
    assert events._subscribers == []


def test_eventbus_unsubscribe_is_idempotent() -> None:
    events = EventBus()
    queue = events.subscribe("session-1")

    assert events.subscriber_count() == 1
    events.unsubscribe(queue)
    events.unsubscribe(queue)

    assert events.subscriber_count() == 0
    assert events._subscribers == []


def test_eventbus_emit_after_close_is_stored_but_not_published() -> None:
    events = EventBus()
    queue = events.subscribe("session-1")
    events.close()

    event = events.emit("run_started", session_id="session-1", run_id="run-1")

    assert not hasattr(events, "_events")
    assert queue.closed.is_set() and queue.queue.empty()


def test_message_delta_is_broadcast_but_not_persisted_by_default() -> None:
    run_events = RunEventStore()
    settings = AppSettingsStore()
    events = EventBus(run_event_store=run_events, app_settings_store=settings)
    queue = events.subscribe("session-1")

    event = events.emit(
        "message_delta",
        session_id="session-1",
        run_id="run-1",
        message_id="message-1",
        payload={"seq": 1, "delta": "he", "reasoning_delta": None},
    )

    assert not hasattr(events, "_events")
    assert json.loads(asyncio.run(queue.get())) == event.model_dump(mode="json")
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


def test_subscriptions_filter_before_queueing_and_release_consumed_bytes():
    events = EventBus()
    session = events.subscribe("a")
    models = events.subscribe("")
    for _ in range(1000):
        events.emit("message_delta", "b", payload={"delta": "unused"})
    assert session.queue.empty() and models.queue.empty()
    events.emit("message_delta", "a", payload={"delta": "中文"})
    events.emit("model_status", "")
    assert session.queue.qsize() == 2 and models.queue.qsize() == 1
    asyncio.run(session.get())
    asyncio.run(session.get())
    assert session.pending_bytes == 0
    events.unsubscribe(models)
    assert models.closed.is_set() and models.pending_bytes == 0


def test_subscription_overflow_closes_without_waiting_for_next_event():
    events = EventBus()
    subscription = events.subscribe("s")
    for _ in range(257):
        events.emit("message_delta", "s", payload={"delta": "x"})
    assert subscription.close_code == 1013 and subscription.closed.is_set()
    assert subscription.queue.empty() and subscription.pending_bytes == 0
    assert events.subscriber_count() == 0


def test_subscription_byte_budget_handles_large_single_event_and_unicode():
    from ai_workbench.core.events import MAX_PENDING_BYTES
    events = EventBus()
    subscription = events.subscribe("s")
    events.emit("message_completed", "s", payload={"text": "中" * (MAX_PENDING_BYTES // 3)})
    assert subscription.close_code == 1013 and subscription.pending_bytes == 0
    subscription = events.subscribe("s")
    for _ in range(5):
        events.emit("message_delta", "s", payload={"delta": "x" * (1024 * 1024)})
    assert subscription.close_code == 1013 and subscription.queue.empty()


def test_relay_overflow_and_blocked_send_release_subscription(monkeypatch):
    from types import SimpleNamespace
    from ai_workbench.api import ws

    async def scenario(request_event):
        events = EventBus()
        state = SimpleNamespace(events=events, active_websockets=0)
        accepted, sending = asyncio.Event(), asyncio.Event()
        closed = []

        async def accept():
            accepted.set()

        async def receive():
            if request_event and not sending.is_set():
                sending.set()
                return {"type": "next_event"}
            await asyncio.Future()

        async def send(_):
            await asyncio.Future()

        async def close(code):
            closed.append(code)

        socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime_state=state)),
                                 accept=accept, receive_json=receive, send_text=send, close=close)
        task = asyncio.create_task(ws.relay_events(socket, "s"))
        await accepted.wait()
        for _ in range(1 if request_event else 257):
            events.emit("message_delta", "s", payload={"delta": "x"})
        await asyncio.wait_for(task, 1)
        assert closed == [1013]
        assert events.subscriber_count() == state.active_websockets == 0

    monkeypatch.setattr(ws, "SEND_TIMEOUT_SECONDS", 0.01)
    asyncio.run(scenario(False))
    asyncio.run(scenario(True))
