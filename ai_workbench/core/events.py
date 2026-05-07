from datetime import datetime
import asyncio
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    session_id: str
    run_id: Optional[str] = None
    message_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EventBus:
    def __init__(self, run_event_store=None) -> None:
        self._events: List[Event] = []
        self._subscribers: List[asyncio.Queue] = []
        self.run_event_store = run_event_store
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
        self._events.append(event)
        if self.run_event_store is not None and event.run_id:
            self.run_event_store.add_event(
                run_id=event.run_id,
                session_id=event.session_id,
                type=event.type,
                message=_event_message(event),
                payload=event.payload,
            )
        if not self._closed:
            for queue in list(self._subscribers):
                queue.put_nowait(event)
        return event

    def list_events(self) -> List[Event]:
        return list(self._events)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        if self._closed:
            queue.put_nowait(None)
            return queue
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def close(self) -> None:
        self._closed = True
        for queue in list(self._subscribers):
            queue.put_nowait(None)
        self._subscribers.clear()


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
        "run_step": "Run step.",
        "action_invoked": "Action invoked.",
        "message_done": "Message completed.",
        "run_done": "Run completed.",
        "run_failed": "Run failed.",
        "run_cancelled": "Run cancelled.",
    }
    return labels.get(event.type, "")
