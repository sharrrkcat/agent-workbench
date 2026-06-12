from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, MemoryKnowledgeStore
from ai_workbench.core.knowledge_models import KnowledgeModelError
from ai_workbench.core.inference.stateless_guard import (
    assert_snapshot_unchanged,
    capture_stateless_persistence_snapshot,
)
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.stores import SqlKnowledgeStore
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
    ("post", "/api/inference/vision", {"model": "vision:florence", "task": "caption", "input": {"type": "image", "image_base64": "AAAA"}, "options": {}}),
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


class FakeKnowledgeBackend:
    def __init__(self, fail_code: str | None = None) -> None:
        self.fail_code = fail_code
        self.calls = []

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.calls.append({"model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        if self.fail_code:
            raise KnowledgeModelError(self.fail_code, "backend unavailable")
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


def create_provider(client: TestClient, *, enabled: bool = True) -> dict:
    response = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Provider", "provider": "lm_studio", "base_url": "http://provider/v1", "api_key": "provider-secret", "enabled": enabled},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_llm_profile(client: TestClient, *, external: bool = False, enabled: bool = True, provider_enabled: bool = True) -> dict:
    provider = create_provider(client, enabled=provider_enabled)
    alias = f"chatmodel-{uuid4().hex[:8]}"
    response = client.post(
        "/api/llm-profiles",
        json={
            "alias": alias,
            "name": "Chat Model",
            "provider_profile_id": provider["id"],
            "model_id": "provider-chat-model",
            "enabled": enabled,
            "external_inference_enabled": external,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_embedding_profile(client: TestClient, *, external: bool = False, enabled: bool = True, provider_enabled: bool = True) -> dict:
    alias = f"a2-embed-{uuid4().hex[:8]}"
    root = client.app.state.runtime_state.repo_root
    model_dir = root / "data" / "models" / "embeddings" / alias
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Embedding Provider", "provider": "internal_transformers", "enabled": provider_enabled},
    )
    assert provider.status_code == 200, provider.text
    response = client.post(
        "/api/knowledge/embedding-models",
        json={
            "name": "A2 Embed",
            "alias": alias,
            "provider_profile_id": provider.json()["id"],
            "provider_model_id": f"embedding/{alias}",
            "enabled": enabled,
            "normalize": False,
            "external_inference_enabled": external,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_embedding_profile_lookup_by_id_or_alias_works_for_memory_and_sql(tmp_path: Path) -> None:
    memory = MemoryKnowledgeStore()
    memory_profile = memory.create_embedding_profile(
        EmbeddingModelProfile(name="Semantic", alias="semantic", provider_model_id="embedding/semantic")
    )
    engine = get_engine(f"sqlite:///{tmp_path / 'knowledge-lookup.db'}")
    init_db(engine)
    sql = SqlKnowledgeStore(engine)
    sql_profile = sql.create_embedding_profile(
        EmbeddingModelProfile(name="Semantic SQL", alias="semantic-sql", provider_model_id="embedding/semantic-sql")
    )

    assert memory.find_embedding_profile_by_alias("semantic") == memory_profile
    assert memory.get_embedding_profile_by_id_or_alias(memory_profile.id) == memory_profile
    assert memory.get_embedding_profile_by_id_or_alias("semantic") == memory_profile
    assert sql.find_embedding_profile_by_alias("semantic-sql") == sql_profile
    assert sql.get_embedding_profile_by_id_or_alias(sql_profile.id) == sql_profile
    assert sql.get_embedding_profile_by_id_or_alias("semantic-sql") == sql_profile


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
    invalid_request = client.post("/v1/chat/completions", json={"model": "local"}, headers=auth_headers())

    assert missing_auth.status_code == 500
    assert missing_auth.json()["error"]["code"] == "inference_service_misconfigured"
    assert configured_key.status_code == 200
    assert invalid_auth.status_code == 403
    assert invalid_auth.json()["error"]["code"] == "inference_auth_invalid"
    assert model_list.status_code == 200
    assert model_list.json() == {"object": "list", "data": []}
    assert invalid_request.status_code == 400
    assert invalid_request.json()["error"]["code"] == "inference_invalid_request"


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
    assert status.json()["implementation"] == {
        "real_inference": True,
        "real_multimodal_inference": True,
        "real_vision_inference": True,
        "version": "a5.2",
    }
    assert status.json()["capabilities"]["llm_chat"] == "available"
    assert status.json()["capabilities"]["text_embeddings"] == "available"
    assert status.json()["capabilities"]["vision_tasks"] == "configured"
    assert status.json()["runtime"]["multimodal_embedding_cache"] == {"runtime_count": 0, "profile_count": 0, "architecture_counts": {}}
    assert status.json()["runtime"]["vision_cache"] == {"runtime_count": 0, "profile_count": 0, "architecture_counts": {}}
    assert status.json()["models"] == {
        "llm_external_enabled_count": 0,
        "embedding_external_enabled_count": 0,
        "multimodal_external_enabled_count": 0,
        "vision_external_enabled_count": 0,
    }
    assert not_implemented.status_code == 200
    assert not_implemented.json()["ok"] is True
    assert not_implemented.json()["results"][0]["target"] == "multimodal_embedding"


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


def test_enabled_multimodal_route_rejects_oversized_streamed_body_without_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, max_request_mb=1)

    def chunks():
        yield b'{"model":"multimodal:missing","inputs":['
        yield b'{"type":"image_base64","data":"'
        yield b"A" * (2 * 1024 * 1024)
        yield b'"}]}'

    response = client.post(
        "/api/inference/embeddings/multimodal",
        content=chunks(),
        headers={"content-type": "application/json", **auth_headers()},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "INFERENCE_REQUEST_TOO_LARGE"


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
    assert status.json()["capabilities"]["vision_tasks"] == "configured"
    assert status.json()["runtime"]["multimodal_embedding_cache"] == {"runtime_count": 0, "profile_count": 0, "architecture_counts": {}}
    assert "test-inference-key" not in str(status.json())
    assert workbench_models.status_code == 200
    assert workbench_models.json()["object"] == "list"
    assert workbench_models.json()["data"] == []
    assert workbench_models.json()["summary"]["llm_profiles_available"] == 0
    assert workbench_models.json()["summary"]["embedding_profiles_available"] == 0
    assert openai_models.status_code == 200
    assert openai_models.json() == {"object": "list", "data": []}


def test_external_allowlist_defaults_false_and_lists_only_enabled_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)

    llm = create_llm_profile(client)
    embed = create_embedding_profile(client)
    assert llm["external_inference_enabled"] is False
    assert embed["external_inference_enabled"] is False
    assert client.get("/v1/models").json() == {"object": "list", "data": []}

    llm = client.patch(f"/api/llm-profiles/{llm['id']}", json={"external_inference_enabled": True}).json()
    embed = client.patch(f"/api/knowledge/embedding-models/{embed['id']}", json={"external_inference_enabled": True}).json()
    disabled_llm = create_llm_profile(client, external=True, enabled=False)
    disabled_embed = create_embedding_profile(client, external=True, enabled=False)

    openai_models = client.get("/v1/models").json()["data"]
    workbench = client.get("/api/inference/models").json()
    ids = {item["id"] for item in openai_models}
    assert ids == {f"llm:{llm['alias']}", f"embedding:{embed['alias']}"}
    assert f"llm:{llm['id']}" not in ids
    assert f"embedding:{embed['id']}" not in ids
    assert f"llm:{disabled_llm['alias']}" not in ids
    assert f"embedding:{disabled_embed['alias']}" not in ids
    assert "provider-secret" not in str(openai_models)
    assert str(tmp_path) not in str(openai_models)
    assert {item["id"] for item in workbench["data"]} == ids
    workbench_by_id = {item["id"]: item for item in workbench["data"]}
    assert workbench_by_id[f"llm:{llm['alias']}"]["profile_id"] == llm["id"]
    assert workbench_by_id[f"llm:{llm['alias']}"]["profile_alias"] == llm["alias"]
    assert workbench_by_id[f"llm:{llm['alias']}"]["legacy_model_id"] == f"llm:{llm['id']}"
    assert workbench_by_id[f"embedding:{embed['alias']}"]["profile_id"] == embed["id"]
    assert workbench_by_id[f"embedding:{embed['alias']}"]["profile_alias"] == embed["alias"]
    assert workbench_by_id[f"embedding:{embed['alias']}"]["legacy_model_id"] == f"embedding:{embed['id']}"
    assert workbench["summary"]["llm_profiles_available"] == 1
    assert workbench["summary"]["embedding_profiles_available"] == 1


def test_chat_completion_allowlisted_profile_calls_llm_runtime_once_and_is_stateless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_llm_profile(client, external=True)
    llm = client.app.state.runtime_state.runtimes.get_runtime("llm")
    before = capture_stateless_persistence_snapshot(client.app.state.runtime_state)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": f"llm:{profile['alias']}",
            "messages": [{"role": "system", "content": "brief"}, {"role": "user", "content": "hello"}],
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": 32,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == f"llm:{profile['alias']}"
    assert payload["choices"][0]["message"] == {"role": "assistant", "content": "fake response"}
    assert payload["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert len(llm.calls) == 1
    assert llm.calls[0]["messages"][-1] == {"role": "user", "content": "hello"}
    assert llm.calls[0]["model_config"]["model"] == "provider-chat-model"
    assert llm.calls[0]["model_config"]["temperature"] == 0.2
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(client.app.state.runtime_state))


def test_chat_completion_stream_unknown_and_non_allowlisted_do_not_call_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_llm_profile(client, external=False)
    llm = client.app.state.runtime_state.runtimes.get_runtime("llm")
    body = {"messages": [{"role": "user", "content": "hello"}]}

    stream = client.post("/v1/chat/completions", json={"model": f"llm:{profile['id']}", "stream": True, **body})
    unknown = client.post("/v1/chat/completions", json={"model": "missing", **body})
    not_allowed = client.post("/v1/chat/completions", json={"model": f"llm:{profile['id']}", **body})

    assert stream.status_code == 501
    assert stream.json()["error"]["code"] == "inference_not_implemented"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "model_not_found"
    assert not_allowed.status_code == 403
    assert not_allowed.json()["error"]["code"] == "model_not_allowed"
    assert llm.calls == []


def test_chat_completion_accepts_legacy_uuid_model_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    enable_inference(client, require_api_key=False)
    profile = create_llm_profile(client, external=True)
    llm = client.app.state.runtime_state.runtimes.get_runtime("llm")

    response = client.post(
        "/v1/chat/completions",
        json={"model": f"llm:{profile['id']}", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["model"] == f"llm:{profile['id']}"
    assert len(llm.calls) == 1


def test_embeddings_allowlisted_profile_returns_vectors_and_is_stateless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    backend = FakeKnowledgeBackend()
    client.app.state.runtime_state.knowledge_model_backend = backend
    enable_inference(client, require_api_key=False)
    profile = create_embedding_profile(client, external=True)
    before = capture_stateless_persistence_snapshot(client.app.state.runtime_state)

    single = client.post("/v1/embeddings", json={"model": f"embedding:{profile['alias']}", "input": "hello"})
    batch = client.post("/v1/embeddings", json={"model": f"embedding:{profile['id']}", "input": ["a", "b"], "purpose": "query"})

    assert single.status_code == 200, single.text
    assert single.json()["data"] == [{"object": "embedding", "index": 0, "embedding": [0.0, 1.0]}]
    assert single.json()["model"] == f"embedding:{profile['alias']}"
    assert batch.status_code == 200, batch.text
    assert [item["embedding"] for item in batch.json()["data"]] == [[0.0, 1.0], [1.0, 1.0]]
    assert batch.json()["model"] == f"embedding:{profile['id']}"
    assert backend.calls[0]["texts"] == ["hello"]
    assert backend.calls[1]["texts"] == ["a", "b"]
    assert_snapshot_unchanged(before, capture_stateless_persistence_snapshot(client.app.state.runtime_state))


def test_embeddings_reject_non_float_and_non_text_inputs_without_runtime_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    backend = FakeKnowledgeBackend()
    client.app.state.runtime_state.knowledge_model_backend = backend
    enable_inference(client, require_api_key=False)
    profile = create_embedding_profile(client, external=True)
    model = f"embedding:{profile['id']}"

    bad_encoding = client.post("/v1/embeddings", json={"model": model, "input": "hello", "encoding_format": "base64"})
    bad_object = client.post("/v1/embeddings", json={"model": model, "input": {"text": "hello"}})
    nested = client.post("/v1/embeddings", json={"model": model, "input": [["hello"]]})

    assert bad_encoding.status_code == 400
    assert bad_encoding.json()["error"]["code"] == "inference_invalid_request"
    assert bad_object.status_code == 400
    assert bad_object.json()["error"]["code"] == "inference_invalid_request"
    assert nested.status_code == 400
    assert nested.json()["error"]["code"] == "model_input_type_unsupported"
    assert backend.calls == []


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
