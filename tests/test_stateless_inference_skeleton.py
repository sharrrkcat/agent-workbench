from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.inference.stateless_guard import (
    assert_snapshot_unchanged,
    capture_stateless_persistence_snapshot,
)
from tests.test_prompt_agent_execution import FakeLLMRuntime


OPENAI_ENDPOINTS = [
    ("get", "/v1/models", None),
    ("post", "/v1/chat/completions", {"model": "local", "messages": [{"role": "user", "content": "hello"}]}),
    ("post", "/v1/embeddings", {"model": "embed", "input": "hello"}),
]

WORKBENCH_ENDPOINTS = [
    ("get", "/api/inference/status", None),
    ("get", "/api/inference/models", None),
    ("post", "/api/inference/unload", {"target": "all"}),
    (
        "post",
        "/api/inference/embeddings/multimodal",
        {"model": "clip", "inputs": [{"type": "text", "text": "red robot"}], "normalize": True},
    ),
    ("post", "/api/inference/vision", {"model": "florence", "task": "caption", "image_base64": "AAAA", "options": {}}),
]


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))


@pytest.mark.parametrize(("method", "path", "body"), OPENAI_ENDPOINTS + WORKBENCH_ENDPOINTS)
def test_stateless_inference_routes_are_registered_and_disabled_by_default(
    method: str,
    path: str,
    body: dict | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)

    assert response.status_code == 503
    payload = response.json()
    assert "error" in payload
    if path.startswith("/v1/"):
        assert payload["error"]["type"] == "invalid_request_error"
        assert payload["error"]["code"] == "inference_service_disabled"
    else:
        assert payload["error"]["code"] == "INFERENCE_SERVICE_DISABLED"
        assert payload["error"]["request_id"]


def test_enabled_openai_skeleton_requires_auth_then_returns_not_implemented(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    client.patch("/api/settings/general", json={"inference_service_enabled": True})

    missing_auth = client.get("/v1/models")
    invalid_auth = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    disabled_auth = client.patch("/api/settings/general", json={"inference_service_require_api_key": False})
    not_implemented = client.get("/v1/models")

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error"]["code"] == "inference_auth_required"
    assert invalid_auth.status_code == 403
    assert invalid_auth.json()["error"]["code"] == "inference_auth_invalid"
    assert disabled_auth.status_code == 200
    assert not_implemented.status_code == 501
    assert not_implemented.json()["error"]["code"] == "inference_not_implemented"


def test_enabled_workbench_skeleton_requires_auth_then_returns_not_implemented(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    client.patch("/api/settings/general", json={"inference_service_enabled": True})

    missing_auth = client.get("/api/inference/status")
    invalid_auth = client.get("/api/inference/status", headers={"Authorization": "Bearer wrong"})
    client.patch("/api/settings/general", json={"inference_service_require_api_key": False})
    not_implemented = client.get("/api/inference/status")

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error"]["code"] == "INFERENCE_AUTH_REQUIRED"
    assert invalid_auth.status_code == 403
    assert invalid_auth.json()["error"]["code"] == "INFERENCE_AUTH_INVALID"
    assert not_implemented.status_code == 501
    assert not_implemented.json()["error"]["code"] == "INFERENCE_NOT_IMPLEMENTED"
    assert not_implemented.json()["error"]["request_id"]


def test_disabled_stateless_inference_calls_do_not_persist_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state
    before = capture_stateless_persistence_snapshot(state)

    for method, path, body in OPENAI_ENDPOINTS + WORKBENCH_ENDPOINTS:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 503

    after = capture_stateless_persistence_snapshot(state)
    assert_snapshot_unchanged(before, after)


def test_disabled_stateless_inference_post_routes_do_not_validate_payload_before_disabled_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/api/inference/vision", json={"unexpected": ["payload"]})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INFERENCE_SERVICE_DISABLED"


@pytest.mark.parametrize(
    "path",
    ["/v1/chat/completions", "/v1/embeddings"],
)
def test_disabled_openai_routes_reject_malformed_json_before_body_parsing(
    path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    before = capture_stateless_persistence_snapshot(client.app.state.runtime_state)

    response = client.post(path, content=b'{"malformed"', headers={"content-type": "application/json"})

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert response.json()["error"]["code"] == "inference_service_disabled"
    after = capture_stateless_persistence_snapshot(client.app.state.runtime_state)
    assert_snapshot_unchanged(before, after)


@pytest.mark.parametrize(
    "path",
    ["/api/inference/embeddings/multimodal", "/api/inference/vision"],
)
def test_disabled_workbench_routes_reject_malformed_json_before_body_parsing(
    path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    before = capture_stateless_persistence_snapshot(client.app.state.runtime_state)

    response = client.post(path, content=b'{"malformed"', headers={"content-type": "application/json"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INFERENCE_SERVICE_DISABLED"
    assert response.json()["error"]["request_id"]
    after = capture_stateless_persistence_snapshot(client.app.state.runtime_state)
    assert_snapshot_unchanged(before, after)


def test_disabled_stateless_inference_routes_do_not_call_unsafe_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = client.app.state.runtime_state

    def fail(*args, **kwargs):
        raise AssertionError("unsafe helper was called")

    monkeypatch.setattr(state.runtime, "handle_input", fail)
    monkeypatch.setattr(state.agent_runner, "run", fail, raising=False)
    monkeypatch.setattr(state.command_runner, "run", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_data_url", fail)
    monkeypatch.setattr("ai_workbench.core.attachments.save_attachment_from_upload", fail)
    monkeypatch.setattr("ai_workbench.core.knowledge_indexing.upsert_indexed_source", fail, raising=False)
    monkeypatch.setattr("ai_workbench.core.embedding.embed_texts", fail)
    monkeypatch.setattr(client.app.state.runtime_state.runtimes.get_runtime("llm"), "chat", fail)
    monkeypatch.setattr(client.app.state.runtime_state.runtimes.get_runtime("llm"), "chat_raw", fail, raising=False)

    for method, path, body in OPENAI_ENDPOINTS + WORKBENCH_ENDPOINTS:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 503

    for path in ("/v1/chat/completions", "/v1/embeddings", "/api/inference/embeddings/multimodal", "/api/inference/vision"):
        response = client.post(path, content=b'{"malformed"', headers={"content-type": "application/json"})
        assert response.status_code == 503


def test_v1_unknown_backend_path_returns_404_not_frontend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/v1/not-a-route")

    assert response.status_code == 404
