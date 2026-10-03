import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.time import isoformat_utc, utc_now


MAX_PENDING_EVENTS = 256
MAX_PENDING_BYTES = 4 * 1024 * 1024


class EventSubscription:
    """One bounded transport mailbox, with closure independent of consumption."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=MAX_PENDING_EVENTS)
        self.pending_bytes = 0
        self.closed = asyncio.Event()
        self.close_code = 1000

    def publish(self, data: str, size: int) -> bool:
        if self.queue.full() or self.pending_bytes + size > MAX_PENDING_BYTES:
            self.close(1013)
            return False
        self.queue.put_nowait((data, size))
        self.pending_bytes += size
        return True

    async def get(self) -> str:
        data, size = await self.queue.get()
        self.pending_bytes -= size
        return data

    def close(self, code: int = 1000) -> None:
        if self.closed.is_set():
            return
        self.close_code = code
        self.closed.set()
        while not self.queue.empty():
            self.queue.get_nowait()
        self.pending_bytes = 0


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    session_id: str
    run_id: Optional[str] = None
    message_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class EventBus:
    def __init__(self, run_event_store=None, app_settings_store=None) -> None:
        self._subscribers: list[EventSubscription] = []
        self.run_event_store = run_event_store
        self.app_settings_store = app_settings_store
        self._closed = False

    def emit(
        self,
        event_type: str,
        session_id: str,
        run_id: Optional[str] = None,
        message_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Event:
        event = Event(
            type=event_type,
            session_id=session_id,
            run_id=run_id,
            message_id=message_id,
            payload=payload or {},
        )
        if self.run_event_store is not None and event.run_id and self.should_persist_event(event.type):
            self.run_event_store.add_event(
                run_id=event.run_id,
                session_id=event.session_id,
                type=event.type,
                message=_event_message(event),
                payload=event.payload,
            )
        if not self._closed:
            subscribers = [s for s in self._subscribers if event.session_id in {s.session_id, ""}]
            if subscribers:
                data = event.model_dump_json()
                size = len(data.encode("utf-8"))
                for subscription in subscribers:
                    if not subscription.publish(data, size):
                        self._subscribers.remove(subscription)
        return event

    def should_persist_event(self, event_type: str) -> bool:
        if event_type != "message_delta":
            return True
        if self.app_settings_store is None:
            return False
        try:
            settings = self.app_settings_store.get()
        except Exception:
            return False
        return bool(getattr(settings, "persist_streaming_message_deltas", False))

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self, session_id: str) -> EventSubscription:
        subscription = EventSubscription(session_id)
        if self._closed:
            subscription.close()
        else:
            self._subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        if subscription in self._subscribers:
            self._subscribers.remove(subscription)
        subscription.close()

    def close(self) -> None:
        self._closed = True
        for subscription in self._subscribers:
            subscription.close()
        self._subscribers.clear()


async def flush_realtime_events() -> None:
    """Yield so websocket/event subscribers can drain queued realtime events."""
    await asyncio.sleep(0)


def _event_message(event: Event) -> str:
    if "error" in event.payload:
        return str(event.payload["error"])
    if "warning" in event.payload:
        return str(event.payload["warning"])
    if "step" in event.payload:
        return str(event.payload["step"])
    if event.message_id:
        return f"Message {event.message_id}"
    labels = {
        "run_started": "Run started.",
        "run_updated": "Run updated.",
        "run_step_created": "Run step created.",
        "run_step_updated": "Run step updated.",
        "run_cancel_requested": "Run cancellation requested.",
        "run_completed": "Run completed.",
        "run_step": "Run step.",
        "run_failed": "Run failed.",
        "run_cancelled": "Run cancelled.",
    }
    return labels.get(event.type, "")
