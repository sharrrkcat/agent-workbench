import asyncio
import base64
import json
import struct
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.http import read_request
from ai_workbench.core.models.schema import ChatRequest, ModelSettings
from starlette.requests import Request
from tests.model_fixtures import MockOpenAI, configure_model


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    upstream = MockOpenAI()
    with TestClient(create_app(use_memory=True, root=tmp_path, adapter_factory=upstream.factory),
                    client=("127.0.0.1", 40000)) as client:
        yield client, upstream


def enable_external(client):
    result = client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "public-key"})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer public-key"}


def sse_data(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]


def test_internal_chat_and_external_nonstream_share_transport_and_parameters(app_client):
    client, upstream = app_client
    profile = configure_model(client, parameters={"temperature": 0.4, "top_p": 0.8, "max_tokens": 123})
    headers = enable_external(client)
    session = client.post("/api/sessions", json={}).json()
    result = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})
    assert result.json()["success"] is True, result.text
    assert upstream.calls[-1]["temperature"] == 0.4
    assert upstream.calls[-1]["max_tokens"] == 123
    before = client.get("/api/sessions").json()
    message_count = len(client.app.state.runtime_state.messages.list_all_messages())
    response = client.post("/v1/chat/completions", headers=headers, json={
        "model": "local", "messages": [{"role": "user", "content": "external"}], "temperature": 0.1,
    })
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "local"
    assert response.json()["choices"][0]["message"]["content"] == "reply"
    assert upstream.calls[-1]["model"] == upstream.calls[-2]["model"] == "fake"
    assert upstream.calls[-1]["temperature"] == 0.1
    assert client.get("/api/sessions").json() == before
    assert len(client.app.state.runtime_state.messages.list_all_messages()) == message_count
    assert len(client.app.state.runtime_state.model_manager._slots) == 1
    assert client.get(f"/api/models/profiles/{profile['id']}/status").json()["residency"] == "unknown"


def test_streaming_tools_vision_schema_usage_and_ids_are_forwarded(app_client):
    client, upstream = app_client
    configure_model(client, capabilities={"streaming": True, "tools": True, "vision": True, "json_schema": True})
    headers = enable_external(client)
    upstream.stream_events = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": '{"q":'}}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}},
    ]
    payload = {
        "model": "local", "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": [{"type": "text", "text": "inspect"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"}}]}],
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}],
        "tool_choice": {"type": "function", "function": {"name": "lookup"}}, "parallel_tool_calls": False,
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": {"type": "object"}, "strict": True}},
    }
    response = client.post("/v1/chat/completions", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.endswith("data: [DONE]\n\n")
    chunks = sse_data(response)
    assert len({(c["id"], c["created"], c["model"]) for c in chunks}) == 1
    tools = [c["choices"][0]["delta"]["tool_calls"][0] for c in chunks[:2]]
    assert "".join(t["function"]["arguments"] for t in tools) == '{"q":"x"}'
    assert chunks[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"]["total_tokens"] == 10
    for key in ("messages", "tools", "tool_choice", "parallel_tool_calls", "response_format"):
        assert upstream.calls[-1][key] == payload[key]
    assert client.app.state.runtime_state.runs.list_all_runs() == []
    log = Path(client.app.state.runtime_state.repo_root, "data/logs/inference/inference.jsonl").read_text()
    assert "public-key" not in log and "base64,AAAA" not in log and "call-1" not in log
    assert response.headers["x-request-id"] in log


@pytest.mark.parametrize("patch", [
    {"n": 2}, {"unknown": 1}, {"tools": [{"type": "other"}]},
    {"response_format": {"type": "json_schema"}}, {"stream_options": {"include_usage": True}},
    {"messages": [{"role": "tool", "content": "x", "tool_call_id": "missing"}]},
    {"messages": [{"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{}"}}]}]},
])
def test_strict_protocol_rejects_invalid_requests_before_transport(app_client, patch):
    client, upstream = app_client
    configure_model(client)
    response = client.post("/v1/chat/completions", headers=enable_external(client),
                           json={"model": "local", "messages": [{"role": "user", "content": "hello"}], **patch})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert not upstream.calls


def test_unsupported_capabilities_and_alias_visibility_have_no_substitution(app_client):
    client, upstream = app_client
    profile = configure_model(client)
    headers = enable_external(client)
    payload = {"model": "local", "messages": [{"role": "user", "content": "hello"}]}
    assert client.post("/v1/chat/completions", headers=headers, json={**payload, "stream": True}).status_code == 422
    for name in (profile["id"], "llm:local", "missing"):
        assert client.post("/v1/chat/completions", headers=headers, json={**payload, "model": name}).status_code == 404
    client.patch(f"/api/models/profiles/{profile['id']}", json={"external_enabled": False})
    assert client.get("/v1/models", headers=headers).json()["data"] == []
    assert client.post("/v1/chat/completions", headers=headers, json=payload).status_code == 404
    assert not upstream.calls


def test_stream_failure_is_explicit_and_releases_occupation(app_client):
    client, upstream = app_client
    profile = configure_model(client, capabilities={"streaming": True})
    upstream.stream_events = [
        {"choices": [{"index": 0, "delta": {"content": "partial"}, "finish_reason": None}]},
        {"error": {"message": "upstream-private-secret"}},
    ]
    response = client.post("/v1/chat/completions", headers=enable_external(client), json={
        "model": "local", "stream": True, "messages": [{"role": "user", "content": "hello"}],
    })
    assert response.status_code == 200
    assert sse_data(response)[-1]["error"]["code"] == "PROVIDER_ERROR"
    assert "upstream-private-secret" not in response.text
    status = client.get(f"/api/models/profiles/{profile['id']}/status").json()
    assert status["active"] == status["queued"] == 0
    log = (client.app.state.runtime_state.repo_root / "data/logs/inference/inference.jsonl").read_text()
    assert "PROVIDER_ERROR" in log


def test_embeddings_batch_preprocessing_dimensions_and_base64(app_client):
    client, upstream = app_client
    configure_model(client, kind="embedding", alias="embed", parameters={"dimensions": 2, "normalize": True, "document_instruction": "doc: ", "batch_size": 1})
    headers = enable_external(client)
    response = client.post("/v1/embeddings", headers=headers, json={"model": "embed", "input": ["a", "b"], "encoding_format": "base64"})
    assert response.status_code == 200, response.text
    vectors = [struct.unpack("<2f", base64.b64decode(row["embedding"])) for row in response.json()["data"]]
    assert vectors[0] == pytest.approx((0.6, 0.8))
    assert [c["input"] for c in upstream.calls] == [["doc: a"], ["doc: b"]]
    assert response.json()["usage"]["prompt_tokens"] == 2
    assert client.post("/v1/embeddings", headers=headers, json={"model": "embed", "input": "a", "dimensions": 3}).status_code == 422


def test_auth_localhost_size_and_removed_routes(app_client):
    client, _ = app_client
    assert client.get("/v1/models").status_code == 503
    enable_external(client)
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer public-key", "x-api-key": "different"}).status_code == 401
    assert client.get("/v1/models", headers={"x-api-key": "public-key"}).status_code == 200
    for path in ("/api/llm-profiles", "/api/llm-provider-profiles", "/api/knowledge/embedding-models", "/api/inference/vision-models", "/v1/vision", "/v1/embeddings/multimodal", "/v1/rerank", "/api/runtime/free-memory"):
        assert client.get(path).status_code == 404
    payload = {"model": "x", "messages": [{"role": "user", "content": "x"}]}
    assert client.post("/v1/chat/completions", headers={"Authorization": "Bearer public-key", "content-length": "999999999"}, json=payload).status_code == 413
    from ai_workbench.core.models.http import guard
    request = Request({"type": "http", "client": ("192.168.1.2", 40), "headers": [(b"authorization", b"Bearer public-key")]})
    with pytest.raises(ModelError, match="localhost"):
        guard(request, ModelSettings(external_enabled=True, external_api_key="public-key"))


def test_actual_chunked_body_limit_does_not_trust_content_length():
    async def scenario():
        chunks = [b"x" * (600 * 1024), b"x" * (600 * 1024)]
        async def receive():
            data = chunks.pop(0)
            return {"type": "http.request", "body": data, "more_body": bool(chunks)}
        request = Request({"type": "http", "headers": [(b"content-length", b"1")]}, receive)
        with pytest.raises(ModelError) as error:
            await read_request(request, ModelSettings(max_request_mb=1), ChatRequest)
        assert error.value.code == "REQUEST_TOO_LARGE"
    asyncio.run(scenario())


def test_current_images_reach_provider_and_stream_events_have_stable_identity(app_client):
    client, upstream = app_client
    profile = configure_model(client, capabilities={"streaming": True, "vision": True})
    session = client.post("/api/sessions", json={"model_profile_id": profile["id"]}).json()
    image = {"id": "image1", "name": "one.png", "type": "image", "mime_type": "image/png",
             "size": 68,
             "data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII="}
    result = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "look", "attachments": [image]})
    assert result.json()["success"], result.text
    assert upstream.calls[-1]["messages"][-1]["content"][1]["type"] == "image_url"
    state = client.app.state.runtime_state
    events = [e for e in state.events.list_events() if e.type.startswith("message_")]
    started = next(e for e in events if e.type == "message_started")
    deltas = [e for e in events if e.type == "message_delta"]
    completed = next(e for e in events if e.type == "message_completed")
    assert started.message_id == completed.message_id
    assert [e.payload["seq"] for e in deltas] == [1, 2]
    assert {e.message_id for e in deltas} == {completed.message_id}
    assert "".join(e.payload["delta"] for e in deltas) == completed.payload["message"]["parts"][0]["text"]
    assert state.sessions.get_session(session["session_id"]).title == ""
    client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "again"})
    assert all(isinstance(m["content"], str) for m in upstream.calls[-1]["messages"])
