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


def enable_inference(client: TestClient, *, require_api_key: bool = True, api_key: str | None = "test-inference-key", max_request_mb: int = 10) -> None:
    payload = {
        "inference_service_enabled": True,
        "inference_service_require_api_key": require_api_key,
        "inference_service_max_request_mb": max_request_mb,
    }
    if api_key is not None:
        payload["inference_service_api_key"] = api_key
    response = client.patch("/api/settings/general", json=payload)
    assert response.status_code == 200


def auth_headers(api_key: str = "test-inference-key") -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


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
    enable_inference(client, api_key=None)

    missing_auth = client.get("/v1/models")
    configured_key = client.patch("/api/settings/general", json={"inference_service_api_key": "test-inference-key"})
    invalid_auth = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    model_list = client.get("/v1/models", headers=auth_headers())
    not_implemented = client.post("/v1/chat/completions", json={"model": "local"}, headers=auth_headers())

    assert missing_auth.status_code == 500
    assert missing_auth.json()["error"]["code"] == "inference_service_misconfigured"
    assert configured_key.status_code == 200
    assert invalid_auth.status_code == 403
    assert invalid_auth.json()["error"]["code"] == "inference_auth_invalid"
    assert model_list.status_code == 200
    assert model_list.json() == {"object": "list", "data": []}
    assert not_implemented.status_code == 501
    assert not_implemented.json()["error"]["code"] == "inference_not_implemented"


def test_enabled_workbench_skeleton_requires_auth_then_returns_not_implemented(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, api_key=None)

    missing_auth = client.get("/api/inference/status")
    configured_key = client.patch("/api/settings/general", json={"inference_service_api_key": "test-inference-key"})
    invalid_auth = client.get("/api/inference/status", headers={"Authorization": "Bearer wrong"})
    status = client.get("/api/inference/status", headers=auth_headers())
    not_implemented = client.post("/api/inference/unload", json={"target": "all"}, headers=auth_headers())

    assert missing_auth.status_code == 500
    assert missing_auth.json()["error"]["code"] == "INFERENCE_SERVICE_MISCONFIGURED"
    assert configured_key.status_code == 200
    assert invalid_auth.status_code == 403
    assert invalid_auth.json()["error"]["code"] == "INFERENCE_AUTH_INVALID"
    assert status.status_code == 200
    assert status.json()["enabled"] is True
    assert status.json()["auth_required"] is True
    assert status.json()["api_key_configured"] is True
    assert status.json()["implementation"] == {"real_inference": False, "version": "a1.2"}
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


@pytest.mark.parametrize(
    ("path", "expected_code"),
    [
        ("/v1/chat/completions", "inference_auth_required"),
        ("/v1/embeddings", "inference_auth_required"),
        ("/api/inference/embeddings/multimodal", "INFERENCE_AUTH_REQUIRED"),
        ("/api/inference/vision", "INFERENCE_AUTH_REQUIRED"),
    ],
)
def test_enabled_auth_failure_rejects_malformed_json_before_body_parsing(
    path: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client)
    before = capture_stateless_persistence_snapshot(client.app.state.runtime_state)

    response = client.post(path, content=b'{"malformed"', headers={"content-type": "application/json"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == expected_code
    after = capture_stateless_persistence_snapshot(client.app.state.runtime_state)
    assert_snapshot_unchanged(before, after)


@pytest.mark.parametrize(
    ("path", "expected_code"),
    [
        ("/v1/chat/completions", "inference_request_too_large"),
        ("/v1/embeddings", "inference_request_too_large"),
        ("/api/inference/embeddings/multimodal", "INFERENCE_REQUEST_TOO_LARGE"),
        ("/api/inference/vision", "INFERENCE_REQUEST_TOO_LARGE"),
    ],
)
def test_enabled_request_size_rejects_before_body_parsing_and_persistence(
    path: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, max_request_mb=1)
    before = capture_stateless_persistence_snapshot(client.app.state.runtime_state)

    response = client.post(
        path,
        content=b'{"malformed"',
        headers={
            "content-type": "application/json",
            "content-length": str(2 * 1024 * 1024),
            **auth_headers(),
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == expected_code
    after = capture_stateless_persistence_snapshot(client.app.state.runtime_state)
    assert_snapshot_unchanged(before, after)


def test_disabled_route_rejects_before_size_and_auth_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/inference/vision",
        content=b'{"malformed"',
        headers={
            "content-type": "application/json",
            "content-length": str(200 * 1024 * 1024),
            "Authorization": "Bearer wrong",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INFERENCE_SERVICE_DISABLED"


def test_enabled_auth_header_contract_and_query_key_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client)

    no_key = client.get("/api/inference/models")
    invalid_bearer = client.get("/api/inference/models", headers={"Authorization": "Bearer wrong"})
    invalid_x_api_key = client.get("/api/inference/models", headers={"x-api-key": "wrong"})
    valid_bearer = client.get("/api/inference/models", headers=auth_headers())
    valid_x_api_key = client.get("/api/inference/models", headers={"x-api-key": "test-inference-key"})
    conflict = client.get(
        "/api/inference/models",
        headers={"Authorization": "Bearer test-inference-key", "x-api-key": "other"},
    )
    query_key = client.get("/api/inference/models?api_key=test-inference-key")

    assert no_key.status_code == 401
    assert no_key.json()["error"]["code"] == "INFERENCE_AUTH_REQUIRED"
    assert invalid_bearer.status_code == 403
    assert invalid_bearer.json()["error"]["code"] == "INFERENCE_AUTH_INVALID"
    assert invalid_x_api_key.status_code == 403
    assert invalid_x_api_key.json()["error"]["code"] == "INFERENCE_AUTH_INVALID"
    assert valid_bearer.status_code == 200
    assert valid_x_api_key.status_code == 200
    assert conflict.status_code == 403
    assert conflict.json()["error"]["code"] == "INFERENCE_AUTH_INVALID"
    assert query_key.status_code == 401
    assert query_key.json()["error"]["code"] == "INFERENCE_AUTH_REQUIRED"


def test_enabled_status_and_model_lists_are_no_load_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client)
    state = client.app.state.runtime_state

    def fail(*args, **kwargs):
        raise AssertionError("model listing must not call runtime/provider helpers")

    monkeypatch.setattr(state.runtimes.get_runtime("llm"), "list_models", fail, raising=False)
    monkeypatch.setattr(state.runtimes.get_runtime("llm"), "chat", fail)
    monkeypatch.setattr("ai_workbench.core.provider_status.refresh_provider_statuses", fail, raising=False)

    status = client.get("/api/inference/status", headers=auth_headers())
    workbench_models = client.get("/api/inference/models", headers=auth_headers())
    openai_models = client.get("/v1/models", headers=auth_headers())

    assert status.status_code == 200
    assert status.json()["routes"] == {"openai_compatible": True, "workbench_native": True}
    assert status.json()["capabilities"]["vision_tasks"] == "planned"
    assert "test-inference-key" not in str(status.json())
    assert workbench_models.status_code == 200
    assert workbench_models.json()["object"] == "list"
    assert workbench_models.json()["data"] == []
    assert workbench_models.json()["summary"]["reason"] == "external_model_allowlist_not_implemented"
    assert openai_models.status_code == 200
    assert openai_models.json() == {"object": "list", "data": []}


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
