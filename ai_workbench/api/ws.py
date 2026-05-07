import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter(tags=["ws"])


@router.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    state = websocket.app.state.runtime_state
    await websocket.accept()
    state.active_websockets = getattr(state, "active_websockets", 0) + 1
    queue = state.events.subscribe()
    receive_task: asyncio.Task | None = None
    event_task: asyncio.Task | None = None
    wants_event = False
    try:
        receive_task = asyncio.create_task(websocket.receive_json())
        while True:
            if wants_event and event_task is None:
                event_task = asyncio.create_task(queue.get())

            wait_tasks = [receive_task]
            if event_task is not None:
                wait_tasks.append(event_task)
            done, _pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

            if receive_task in done:
                message = receive_task.result()
                receive_task = asyncio.create_task(websocket.receive_json())
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "next_event":
                    wants_event = True

            if event_task is not None and event_task in done:
                event = event_task.result()
                event_task = None
                if event is None:
                    return
                if event.session_id == session_id:
                    await websocket.send_json(event.model_dump(mode="json"))
                    wants_event = False
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        pending_tasks = [task for task in (receive_task, event_task) if task is not None and not task.done()]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        state.events.unsubscribe(queue)
        state.active_websockets = max(0, getattr(state, "active_websockets", 0) - 1)
