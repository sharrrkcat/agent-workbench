from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.retrieval import RetrievalCandidate, rrf_merge
from tests.test_prompt_agent_execution import FakeLLMRuntime


class MockKnowledgeBackend:
    def __init__(self) -> None:
        self.embedding_calls: list[dict] = []
        self.rerank_calls: list[dict] = []
        self.fail_rerank = False

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.embedding_calls.append({"model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        return [_vector_for_text(text, model_path) for text in texts]

    def rerank(self, model_path: str, query: str, documents: list[dict[str, str]], device: str) -> list[dict]:
        self.rerank_calls.append({"model_path": model_path, "query": query, "documents": documents, "device": device})
        if self.fail_rerank:
            raise RuntimeError("mock reranker failed")
        return [
            {"id": document["id"], "score": 10.0 if "beta" in document["text"].lower() else 1.0}
            for document in documents
        ]


def _vector_for_text(text: str, model_path: str) -> list[float]:
    lowered = f"{model_path} {text}".lower()
    if "beta" in lowered:
        return [0.0, 1.0, 0.0]
    if "gamma" in lowered or "other-model" in lowered:
        return [0.0, 0.0, 1.0]
    return [1.0, 0.0, 0.0]


def make_client(tmp_path: Path) -> tuple[TestClient, MockKnowledgeBackend]:
    backend = MockKnowledgeBackend()
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, database_url=f"sqlite:///{tmp_path / 'knowledge.db'}"))
    client.app.state.runtime_state.knowledge_model_backend = backend
    return client, backend


def create_profile(client: TestClient, alias: str, model_folder: str) -> dict:
    response = client.post(
        "/api/knowledge/embedding-models",
        json={
            "name": alias,
            "alias": alias,
            "model_path": f"embeddings/{model_folder}",
            "dimension": 3,
            "normalize": False,
            "document_instruction": "",
            "query_instruction": "",
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_kb(client: TestClient, profile_id: str, name: str) -> dict:
    response = client.post(
        "/api/knowledge/bases",
        json={
            "name": name,
            "embedding_model_profile_id": profile_id,
            "chunk_size_override": 100,
            "chunk_overlap_override": 0,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_source(client: TestClient, kb_id: str, title: str, text: str) -> dict:
    response = client.post(
        f"/api/knowledge/bases/{kb_id}/sources",
        json={"source_type": "pasted_text", "title": title, "text": text},
    )
    assert response.status_code == 200, response.text
    return response.json()


def setup_indexed_kbs(client: TestClient) -> tuple[dict, dict]:
    profile = create_profile(client, "mock_a", "mock-a")
    kb = create_kb(client, profile["id"], "Docs")
    add_source(client, kb["id"], "Alpha", "alpha " * 24)
    add_source(client, kb["id"], "Beta", "beta " * 24)
    return profile, kb


def test_vector_search_returns_top_candidates_from_indexed_embeddings(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    backend.embedding_calls.clear()

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"][0]["title"] == "Alpha"
    assert payload["results"][0]["vector_rank"] == 1
    assert payload["results"][0]["vector_score"] == 1.0
    assert backend.embedding_calls == [{"model_path": "embeddings/mock-a", "texts": ["alpha"], "normalize": False, "device": "auto"}]


def test_get_knowledge_chunk_returns_content_without_vector_blob(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    search_response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]]})
    chunk_id = search_response.json()["results"][0]["chunk_id"]

    response = client.get(f"/api/knowledge/chunks/{chunk_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["chunk_id"] == chunk_id
    assert payload["knowledge_base_name"] == "Docs"
    assert payload["source_title"] == "Alpha"
    assert "alpha" in payload["content"]
    assert "vector_blob" not in payload


def test_vector_search_groups_by_embedding_model_profile_and_embeds_each_group_once(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    profile_a, kb_a = setup_indexed_kbs(client)
    profile_b = create_profile(client, "mock_b", "other-model")
    kb_b = create_kb(client, profile_b["id"], "Other")
    add_source(client, kb_b["id"], "Gamma", "gamma " * 24)
    backend.embedding_calls.clear()

    response = client.post(
        "/api/knowledge/search",
        json={"query": "alpha", "knowledge_base_ids": [kb_a["id"], kb_b["id"]], "debug": True},
    )

    assert response.status_code == 200, response.text
    model_paths = [call["model_path"] for call in backend.embedding_calls]
    assert model_paths == ["embeddings/mock-a", "embeddings/other-model"]
    groups = response.json()["debug"]["embedding_groups"]
    assert {group["embedding_model_profile_id"] for group in groups} == {profile_a["id"], profile_b["id"]}


def test_bm25_search_returns_candidates_and_filters_selected_kbs(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    profile_a, kb_a = setup_indexed_kbs(client)
    kb_b = create_kb(client, profile_a["id"], "Unselected")
    add_source(client, kb_b["id"], "Needle Other", "needle " * 24)

    response = client.post("/api/knowledge/search", json={"query": "needle", "knowledge_base_ids": [kb_a["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["keyword_candidate_count"] == 0
    assert all(result["knowledge_base_id"] == kb_a["id"] for result in payload["results"])


def test_rrf_merge_dedupes_same_chunk_and_keeps_branch_scores() -> None:
    merged = rrf_merge(
        [
            RetrievalCandidate(chunk_id="same", knowledge_base_id="kb", source_id="src", title="A", heading_path="", content="a", vector_score=0.7, vector_rank=2),
        ],
        [
            RetrievalCandidate(chunk_id="same", knowledge_base_id="kb", source_id="src", title="A", heading_path="", content="a", keyword_score=-3.1, keyword_rank=1),
            RetrievalCandidate(chunk_id="other", knowledge_base_id="kb", source_id="src", title="B", heading_path="", content="b", keyword_score=-2.0, keyword_rank=2),
        ],
        rrf_k=60,
    )

    assert [candidate.chunk_id for candidate in merged] == ["same", "other"]
    assert merged[0].vector_rank == 2
    assert merged[0].keyword_rank == 1
    assert round(merged[0].rrf_score, 6) == round((1 / 62) + (1 / 61), 6)


def test_reranker_disabled_uses_rrf_order(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    assert response.json()["debug"]["reranker_used"] is False
    assert backend.rerank_calls == []


def test_reranker_enabled_reranks_merged_candidates_once(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    client.patch("/api/knowledge/settings", json={"reranker_enabled": True, "reranker_model_path": "rerankers/mock-reranker"})

    response = client.post("/api/knowledge/search", json={"query": "alpha beta", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["reranker_used"] is True
    assert len(backend.rerank_calls) == 1
    assert len(backend.rerank_calls[0]["documents"]) == payload["debug"]["merged_candidate_count"]
    assert payload["results"][0]["title"] == "Beta"
    assert payload["results"][0]["rerank_score"] == 10.0


def test_reranker_failure_falls_back_to_rrf_and_records_warning(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    backend.fail_rerank = True
    client.patch("/api/knowledge/settings", json={"reranker_enabled": True, "reranker_model_path": "rerankers/mock-reranker"})

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["reranker_failed"] is True
    assert any("Reranker failed" in warning for warning in payload["debug"]["warnings"])
    assert payload["results"][0]["rerank_score"] is None


def test_search_api_supports_session_bindings(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    session = client.app.state.runtime_state.sessions.create_session(title="Search", default_agent_id="chat")
    client.patch(f"/api/sessions/{session.session_id}/knowledge-bases", json={"knowledge_base_ids": [kb["id"]]})

    response = client.post("/api/knowledge/search", json={"query": "alpha", "session_id": session.session_id})

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["knowledge_base_id"] == kb["id"]


def test_search_api_context_budget_and_top_k_are_applied(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    profile = create_profile(client, "budget_model", "budget-model")
    kb = create_kb(client, profile["id"], "Budget")
    client.patch(f"/api/knowledge/bases/{kb['id']}", json={"chunk_size_override": 150})
    add_source(client, kb["id"], "Alpha Long", "alpha " * 40)

    response = client.post(
        "/api/knowledge/search",
        json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "top_k": 2, "max_context_chars": 100},
    )

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 1
    assert len(results[0]["content"]) <= 100
    assert results[0]["truncated"] is True


def test_search_api_requires_target_and_returns_structured_error(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)

    response = client.post("/api/knowledge/search", json={"query": "alpha"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "KNOWLEDGE_SEARCH_TARGET_REQUIRED"
