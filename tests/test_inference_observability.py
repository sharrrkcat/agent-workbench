import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.inference.stateless_guard import assert_snapshot_unchanged, capture_stateless_persistence_snapshot
from ai_workbench.core.inference.vision_runtime import (
    VisionRuntimeResult,
    clear_vision_runtime_cache,
    clear_vision_runtime_factories,
    register_vision_runtime_factory,
)
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True, root=tmp_path))


def enable_inference(
    client: TestClient,
    *,
    require_api_key: bool = True,
    api_key: str | None = "test-inference-key",
    max_request_mb: int = 10,
) -> None:
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


def log_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "logs" / "inference" / "inference.jsonl"


def read_log_events(tmp_path: Path) -> list[dict]:
    path = log_path(tmp_path)
    assert path.is_file()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def log_text(tmp_path: Path) -> str:
    return log_path(tmp_path).read_text(encoding="utf-8")


def create_vision_profile(client: TestClient, *, alias: str = "obs-vision") -> dict:
    response = client.post(
        "/api/inference/vision-models",
        json={
            "name": "Observable Vision",
            "alias": alias,
            "provider_model_id": "vision/observable",
            "architecture": "florence2",
            "backend": "transformers",
            "supported_tasks": ["caption", "detailed_caption", "ocr", "object_detection"],
            "external_inference_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def teardown_function() -> None:
    clear_vision_runtime_factories()
    clear_vision_runtime_cache()


def test_generated_request_id_is_shared_by_header_body_and_log(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/api/inference/status")

    assert response.status_code == 503
    request_id = response.headers["x-request-id"]
    UUID(request_id)
    assert response.json()["error"]["request_id"] == request_id
    access = read_log_events(tmp_path)[-1]
    assert access["event"] == "access"
    assert access["request_id"] == request_id
    assert access["route_family"] == "workbench_native"
    assert access["method"] == "GET"
    assert access["path"] == "/api/inference/status"
    assert access["status_code"] == 503
    assert access["error_code"] == "INFERENCE_SERVICE_DISABLED"


def test_safe_incoming_request_id_is_preserved_for_openai_routes(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    request_id = "client.req-123:abc"

    response = client.get("/v1/models", headers={"X-Request-ID": request_id})

    assert response.status_code == 503
    assert response.headers["x-request-id"] == request_id
    assert "request_id" not in response.json()["error"]
    access = read_log_events(tmp_path)[-1]
    assert access["request_id"] == request_id
    assert access["route_family"] == "openai_compatible"
    assert access["error_code"] == "inference_service_disabled"


def test_unsafe_incoming_request_id_is_replaced(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    unsafe_request_id = "../bad request id with fake-secret"

    response = client.get("/api/inference/status", headers={"X-Request-ID": unsafe_request_id})

    request_id = response.headers["x-request-id"]
    assert request_id != unsafe_request_id
    UUID(request_id)
    assert response.json()["error"]["request_id"] == request_id
    assert read_log_events(tmp_path)[-1]["request_id"] == request_id


def test_auth_and_size_failures_log_compact_events_without_body_or_secret_leaks(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, max_request_mb=1)
    sensitive_body = b'{"model":"vision:missing","input":{"type":"image","image_base64":"AAAA"},"note":"fake-secret"}'

    auth_failure = client.post(
        "/api/inference/vision",
        content=sensitive_body,
        headers={"content-type": "application/json", "Authorization": "Bearer fake-secret-token"},
    )
    size_failure = client.post(
        "/api/inference/vision",
        content=sensitive_body,
        headers={
            "content-type": "application/json",
            "content-length": str(2 * 1024 * 1024),
            **auth_headers(),
        },
    )

    assert auth_failure.status_code == 403
    assert size_failure.status_code == 413
    events = read_log_events(tmp_path)
    assert any(event["event"] == "access" and event["status_code"] == 403 and event["error_code"] == "INFERENCE_AUTH_INVALID" for event in events)
    assert any(event["event"] == "access" and event["status_code"] == 413 and event["error_code"] == "INFERENCE_REQUEST_TOO_LARGE" for event in events)
    rendered = log_text(tmp_path)
    assert "fake-secret" not in rendered
    assert "fake-secret-token" not in rendered
    assert "AAAA" not in rendered
    assert "image_base64" not in rendered


def test_vision_provider_error_logs_sanitized_root_cause_and_keeps_response_safe(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_vision_profile(client)

    class ExplodingVisionRuntime:
        def __init__(self, profile) -> None:
            self.profile = profile

        def run(self, *, profile, task: str, input, options: dict) -> VisionRuntimeResult:
            raise RuntimeError(f"fake-secret in {tmp_path} with AAAA and generated text that must not leak")

    register_vision_runtime_factory("florence2", ExplodingVisionRuntime)
    state = client.app.state.runtime_state
    before = capture_stateless_persistence_snapshot(state)

    response = client.post(
        "/api/inference/vision",
        json={
            "model": f"vision:{profile['alias']}",
            "task": "caption",
            "input": {"type": "image", "image_base64": "AAAA"},
            "options": {"max_new_tokens": 64},
        },
    )

    assert response.status_code == 502
    request_id = response.headers["x-request-id"]
    assert response.json()["error"] == {
        "code": "PROVIDER_ERROR",
        "message": "Vision runtime failed.",
        "request_id": request_id,
    }
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(state))
    events = read_log_events(tmp_path)
    failure = next(event for event in events if event["event"] == "inference_failure" and event["request_id"] == request_id)
    assert failure["endpoint"] == "/api/inference/vision"
    assert failure["status_code"] == 502
    assert failure["error_code"] == "PROVIDER_ERROR"
    assert failure["context"]["model"] == f"vision:{profile['alias']}"
    assert failure["context"]["task"] == "caption"
    assert any(item["type"] == "RuntimeError" for item in failure["exception"])
    rendered_response = str(response.json()).lower()
    rendered_log = log_text(tmp_path)
    for forbidden in ("fake-secret", "AAAA", "generated text", str(tmp_path)):
        assert forbidden.lower() not in rendered_response
        assert forbidden not in rendered_log
    assert "RuntimeError" in rendered_log
