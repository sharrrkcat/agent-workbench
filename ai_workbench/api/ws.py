import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter(tags=["ws"])


@router.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    state = websocket.app.state.runtime_state
    await websocket.accept()
    queue = state.events.subscribe()
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if message.get("type") == "next_event":
                event = await queue.get()
                if event is None:
                    return
                if event.session_id == session_id:
                    await websocket.send_json(event.model_dump(mode="json"))
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        state.events.unsubscribe(queue)
