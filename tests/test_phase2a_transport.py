"""Real loopback HTTP/SSE/WS tests, without model files or browser automation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import socket
import threading
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import httpx
from httpx_sse import connect_sse
import pytest
import uvicorn
from websockets.sync.client import connect

from ai_workbench.api.main import create_app


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for transport state")


@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", ws="websockets-sansio")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            wait_until(lambda: server.started)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=6)
            assert not thread.is_alive(), "Transport fixture server did not shut down"


@pytest.fixture
def transport_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    upstream = FastAPI()
    proceed = threading.Event()
    closed = threading.Event()

    @upstream.get("/v1/models")
    async def models():
        return {"data": [{"id": "socket-model"}]}

    @upstream.post("/v1/chat/completions")
    async def chat():
        async def stream():
            try:
                chunk = {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "\u4f60\u597d"}, "finish_reason": None}]}
                wire = ("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode()
                for offset in range(0, len(wire), 3):
                    yield wire[offset:offset + 3]
                    await asyncio.sleep(0)
                while not proceed.is_set():
                    await asyncio.sleep(0.01)
                yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
                yield b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n'
                yield b'data: [DONE]\n\n'
            finally:
                closed.set()
        return StreamingResponse(stream(), media_type="text/event-stream")

    with serve(upstream) as provider_url:
        app = create_app(use_memory=True, root=tmp_path)
        with serve(app) as url, httpx.Client(base_url=url, timeout=5) as client:
            provider = client.post("/api/models/providers", json={"name": "Socket", "base_url": provider_url + "/v1"}).json()
            profile = client.post("/api/models/profiles", json={
                "name": "Socket", "alias": "socket", "kind": "llm", "model_ref": "socket-model",
                "provider_profile_id": provider["id"], "capabilities": {"streaming": True}, "external_enabled": True,
            }).json()
            settings = client.patch("/api/models/settings", json={
                "default_model_profile_id": profile["id"], "external_enabled": True, "external_api_key": "test-key",
            })
            assert settings.status_code == 200, settings.text
            yield client, app.state.runtime_state, profile, proceed, closed
            proceed.set()


def test_real_sse_fragments_usage_and_disconnect_release(transport_app):
    client, state, profile, proceed, closed = transport_app
    payload = {"model": "socket", "stream": True, "stream_options": {"include_usage": True},
               "messages": [{"role": "user", "content": "hello"}]}
    with connect_sse(client, "POST", "/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=payload) as source:
        events = source.iter_sse()
        first = json.loads(next(events).data)
        assert first["choices"][0]["delta"]["content"] == "\u4f60\u597d"
        assert state.model_manager.status(profile["id"]).active == 1
        proceed.set()
        rest = [event.data for event in events]
        assert rest[-1] == "[DONE]"
        assert json.loads(rest[-2])["usage"]["total_tokens"] == 3
        assert all(json.loads(event)["id"] == first["id"] for event in rest[:-1])
    wait_until(lambda: state.model_manager.status(profile["id"]).active == 0)
    proceed.clear()
    closed.clear()
    with connect_sse(client, "POST", "/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=payload) as source:
        assert next(source.iter_sse()).data
    wait_until(closed.is_set)
    wait_until(lambda: state.model_manager.status(profile["id"]).active == 0)
    assert state.model_manager.status(profile["id"]).queued == 0
    log_path = state.repo_root / "data/logs/inference/inference.jsonl"
    wait_until(lambda: "REQUEST_CANCELLED" in log_path.read_text())


def test_websocket_delivers_deltas_before_chat_request_completes(transport_app):
    client, state, profile, proceed, _ = transport_app
    session = client.post("/api/sessions", json={"model_profile_id": profile["id"]}).json()
    path = f"/api/sessions/{session['session_id']}/messages"
    ws_url = str(client.base_url).replace("http://", "ws://").rstrip("/") + f"/api/ws/{session['session_id']}"
    with connect(ws_url, open_timeout=5) as ws, ThreadPoolExecutor(max_workers=1) as executor:
        wait_until(lambda: state.events.subscriber_count() == 1)
        future = executor.submit(client.post, path, json={"content": "hello"})
        seen = []
        try:
            while not seen or seen[-1]["type"] != "message_delta":
                ws.send(json.dumps({"type": "next_event"}))
                seen.append(json.loads(ws.recv(timeout=5)))
            assert not future.done()
            assert seen[-1]["payload"]["delta"] == "\u4f60\u597d"
            proceed.set()
            while seen[-1]["type"] != "message_completed":
                ws.send(json.dumps({"type": "next_event"}))
                seen.append(json.loads(ws.recv(timeout=5)))
            completed = seen[-1]
            started = next(event for event in seen if event["type"] == "message_started")
            assert completed["message_id"] == started["message_id"]
            assert future.result(timeout=5).json()["success"]
        finally:
            proceed.set()
