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
    def __init__(self) -> None:
        self._events: List[Event] = []
        self._subscribers: List[asyncio.Queue] = []

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
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    def list_events(self) -> List[Event]:
        return list(self._events)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)
