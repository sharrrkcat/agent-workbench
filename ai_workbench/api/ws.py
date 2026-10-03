import asyncio
from anyio import CancelScope

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter(tags=["ws"])
SEND_TIMEOUT_SECONDS = 5


@router.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await relay_events(websocket, session_id)


@router.websocket("/api/models/events")
async def model_events(websocket: WebSocket) -> None:
    await relay_events(websocket, "")


async def relay_events(websocket: WebSocket, session_id: str) -> None:
    state = websocket.app.state.runtime_state
    await websocket.accept()
    state.active_websockets = getattr(state, "active_websockets", 0) + 1
    subscription = state.events.subscribe(session_id)
    close_task = asyncio.create_task(subscription.closed.wait())
    receive_task: asyncio.Task | None = None
    event_task: asyncio.Task | None = None
    wants_event = False
    try:
        receive_task = asyncio.create_task(websocket.receive_json())
        while True:
            if wants_event and event_task is None:
                event_task = asyncio.create_task(subscription.get())

            wait_tasks = [receive_task, close_task]
            if event_task is not None:
                wait_tasks.append(event_task)
            done, _pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

            if close_task in done:
                await asyncio.wait_for(websocket.close(code=subscription.close_code), SEND_TIMEOUT_SECONDS)
                return

            if receive_task in done:
                message = receive_task.result()
                receive_task = asyncio.create_task(websocket.receive_json())
                if message.get("type") == "ping":
                    await _send(websocket, '{"type":"pong"}', close_task)
                elif message.get("type") == "next_event":
                    wants_event = True

            if event_task is not None and event_task in done:
                data = event_task.result()
                event_task = None
                await _send(websocket, data, close_task)
                wants_event = False
    except (TimeoutError, asyncio.TimeoutError):
        subscription.close(1013)
        try:
            await asyncio.wait_for(websocket.close(code=1013), SEND_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.TimeoutError, WebSocketDisconnect):
            pass
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        state.events.unsubscribe(subscription)
        state.active_websockets = max(0, getattr(state, "active_websockets", 0) - 1)
        pending_tasks = [task for task in (receive_task, event_task, close_task) if task is not None and not task.done()]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            with CancelScope(shield=True):
                await asyncio.gather(*pending_tasks, return_exceptions=True)


async def _send(websocket: WebSocket, data: str, close_task: asyncio.Task) -> None:
    sending = asyncio.create_task(websocket.send_text(data))
    try:
        done, _ = await asyncio.wait((sending, close_task), timeout=SEND_TIMEOUT_SECONDS,
                                     return_when=asyncio.FIRST_COMPLETED)
        if sending in done:
            sending.result()
        elif close_task not in done:
            raise TimeoutError
    finally:
        if not sending.done():
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
