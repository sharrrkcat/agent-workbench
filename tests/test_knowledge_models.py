from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.knowledge_models import KnowledgeModelError, normalize_model_path, resolve_device
from tests.test_knowledge_settings import create_embedding_profile
from tests.test_prompt_agent_execution import FakeLLMRuntime


class FakeKnowledgeBackend:
    def __init__(self, fail_code: str | None = None) -> None:
        self.fail_code = fail_code
        self.calls = []

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.calls.append({"kind": "embed", "model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        if self.fail_code:
            raise KnowledgeModelError(self.fail_code, "backend unavailable")
        return [[3.0, 4.0, 0.0] for _ in texts]

    def rerank(self, model_path: str, query: str, documents: list[dict[str, str]], device: str) -> list[dict]:
        self.calls.append({"kind": "rerank", "model_path": model_path, "query": query, "documents": documents, "device": device})
        if self.fail_code:
            raise KnowledgeModelError(self.fail_code, "backend unavailable")
        scores = {"doc1": 0.9, "doc2": 0.1}
        return sorted([{"id": doc["id"], "score": scores.get(doc["id"], 0.0)} for doc in documents], key=lambda item: item["score"], reverse=True)


def make_client_with_backend(tmp_path: Path, backend: FakeKnowledgeBackend) -> TestClient:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'models.db'}"))
    client.app.state.runtime_state.knowledge_model_backend = backend
    return client


def test_model_path_validators_reject_escape_and_wrong_kind() -> None:
    assert normalize_model_path("embeddings/bge-m3", "embeddings") == "embeddings/bge-m3"
    assert normalize_model_path("embeddings\\bge-m3", "embeddings") == "embeddings/bge-m3"
    for value in ["/abs/model", "../model", "embeddings/../x", "rerankers/foo"]:
        with pytest.raises(ValueError):
            normalize_model_path(value, "embeddings")
    with pytest.raises(ValueError):
        normalize_model_path("embeddings/foo", "rerankers")


def test_optional_dependency_missing_returns_structured_error_and_startup_works(tmp_path: Path) -> None:
    client = make_client_with_backend(tmp_path, FakeKnowledgeBackend("KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE"))
    profile = create_embedding_profile(client)
    response = client.post(
        "/api/knowledge/embeddings",
        json={"model_profile_id": profile["id"], "purpose": "query", "inputs": ["hello"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE"
    assert client.post("/api/sessions", json={"title": "", "default_agent_id": "chat"}).status_code == 200


def test_embedding_api_uses_instructions_normalizes_and_checks_batch_and_dimension(tmp_path: Path) -> None:
    backend = FakeKnowledgeBackend()
    client = make_client_with_backend(tmp_path, backend)
    profile = create_embedding_profile(client)

    empty = client.post("/api/knowledge/embeddings", json={"model_profile_id": profile["id"], "purpose": "query", "inputs": []})
    assert empty.status_code == 422
    invalid = client.post("/api/knowledge/embeddings", json={"model_profile_id": profile["id"], "purpose": "bad", "inputs": ["x"]})
    assert invalid.status_code == 422
    client.patch("/api/knowledge/settings", json={"embedding_batch_size": 1})
    too_many = client.post("/api/knowledge/embeddings", json={"model_profile_id": profile["id"], "purpose": "query", "inputs": ["a", "b"]})
    assert too_many.status_code == 422

    response = client.post("/api/knowledge/embeddings", json={"model_profile_id": profile["id"], "purpose": "query", "inputs": ["hello"]})
    assert response.status_code == 200
    assert response.json()["dimension"] == 3
    assert response.json()["vectors"][0] == [0.6, 0.8, 0.0]
    assert backend.calls[-1]["texts"] == ["Query:\nhello"]

    document = client.post("/api/knowledge/embeddings", json={"model_profile_id": profile["id"], "purpose": "document", "inputs": ["hello"]})
    assert document.status_code == 200
    assert backend.calls[-1]["texts"] == ["Document:\nhello"]

    client.patch(f"/api/knowledge/embedding-models/{profile['id']}", json={"dimension": 4})
    mismatch = client.post("/api/knowledge/embeddings", json={"model_profile_id": profile["id"], "purpose": "query", "inputs": ["hello"]})
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "KNOWLEDGE_EMBEDDING_DIMENSION_MISMATCH"


def test_embedding_test_endpoint_returns_truncated_sample(tmp_path: Path) -> None:
    client = make_client_with_backend(tmp_path, FakeKnowledgeBackend())
    profile = create_embedding_profile(client)
    response = client.post(f"/api/knowledge/embedding-models/{profile['id']}/test", json={"text": "hello", "purpose": "query"})
    assert response.status_code == 200
    assert response.json()["sample"] == [0.6, 0.8, 0.0]


def test_reranker_api_disabled_configured_limit_and_mock_sorted_scores(tmp_path: Path) -> None:
    client = make_client_with_backend(tmp_path, FakeKnowledgeBackend())
    disabled = client.post("/api/knowledge/rerank", json={"query": "q", "documents": [{"id": "doc1", "text": "a"}]})
    assert disabled.status_code == 400
    assert disabled.json()["error"]["code"] == "KNOWLEDGE_RERANKER_DISABLED"

    client.patch("/api/knowledge/settings", json={"reranker_enabled": True})
    missing_path = client.post("/api/knowledge/rerank", json={"query": "q", "documents": [{"id": "doc1", "text": "a"}]})
    assert missing_path.status_code == 400
    assert missing_path.json()["error"]["code"] == "KNOWLEDGE_RERANKER_MODEL_NOT_CONFIGURED"

    assert client.patch("/api/knowledge/settings", json={"reranker_model_path": "embeddings/foo"}).status_code == 422
    client.patch("/api/knowledge/settings", json={"reranker_model_path": "rerankers/bge-reranker", "reranker_candidate_limit": 1})
    too_many = client.post("/api/knowledge/rerank", json={"query": "q", "documents": [{"id": "doc1", "text": "a"}, {"id": "doc2", "text": "b"}]})
    assert too_many.status_code == 422
    client.patch("/api/knowledge/settings", json={"reranker_candidate_limit": 2})
    response = client.post("/api/knowledge/rerank", json={"query": "q", "documents": [{"id": "doc2", "text": "b"}, {"id": "doc1", "text": "a"}]})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == ["doc1", "doc2"]


def test_resolve_device_auto_cpu_and_cuda_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("ai_workbench.core.knowledge_models.backend_availability", lambda: {"torch_available": True, "cuda_available": False})
    assert resolve_device("auto") == "cpu"
    with pytest.raises(KnowledgeModelError) as exc:
        resolve_device("cuda")
    assert exc.value.code == "KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE"
