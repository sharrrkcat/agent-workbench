from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from ai_workbench.core import keyword_search
from ai_workbench.core.keyword_search import build_safe_fts_query
from ai_workbench.api.main import create_app
from ai_workbench.core.retrieval import RetrievalCandidate, rrf_merge
from tests.test_prompt_agent_execution import FakeLLMRuntime


class MockKnowledgeBackend:
    def __init__(self) -> None:
        self.embedding_calls: list[dict] = []
        self.rerank_calls: list[dict] = []
        self.unloaded_embeddings: list[dict] = []
        self.unloaded_rerankers: list[dict] = []
        self.fail_rerank = False
        self.fail_unload_embedding = False
        self.fail_unload_reranker = False

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

    def unload_embedding_model(self, model_path: str, device: str) -> bool:
        if self.fail_unload_embedding:
            raise RuntimeError("mock embedding unload failed")
        self.unloaded_embeddings.append({"model_path": model_path, "device": device})
        return True

    def unload_reranker_model(self, model_path: str, device: str) -> bool:
        if self.fail_unload_reranker:
            raise RuntimeError("mock reranker unload failed")
        self.unloaded_rerankers.append({"model_path": model_path, "device": device})
        return True


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


def assert_warning_hygiene(warnings: list[str]) -> None:
    warning_text = "\n".join(warnings).lower()
    assert "select" not in warning_text
    assert " match " not in warning_text
    assert "sqlalchemy" not in warning_text
    assert "parameters" not in warning_text
    assert "https://sqlalche.me" not in warning_text


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


def test_embedding_unload_after_use_releases_each_retrieval_profile(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile_a, kb_a = setup_indexed_kbs(client)
    profile_b = create_profile(client, "mock_b", "other-model")
    kb_b = create_kb(client, profile_b["id"], "Other")
    add_source(client, kb_b["id"], "Gamma", "gamma " * 24)
    backend.embedding_calls.clear()
    client.patch("/api/knowledge/settings", json={"unload_embedding_model_after_use": True})

    response = client.post(
        "/api/knowledge/search",
        json={"query": "alpha", "knowledge_base_ids": [kb_a["id"], kb_b["id"]], "debug": True},
    )

    assert response.status_code == 200, response.text
    assert backend.unloaded_embeddings == [
        {"model_path": "embeddings/mock-a", "device": "auto"},
        {"model_path": "embeddings/other-model", "device": "auto"},
    ]
    assert response.json()["debug"]["warnings"].count("Embedding unloaded after use.") == 2


def test_embedding_test_unload_after_use_releases_profile(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    profile = create_profile(client, "test_model", "test-model")
    client.patch("/api/knowledge/settings", json={"unload_embedding_model_after_use": True})

    response = client.post(f"/api/knowledge/embedding-models/{profile['id']}/test", json={"text": "alpha", "purpose": "query"})

    assert response.status_code == 200, response.text
    assert backend.unloaded_embeddings == [{"model_path": "embeddings/test-model", "device": "auto"}]


def test_embedding_unload_failure_does_not_fail_search(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    backend.embedding_calls.clear()
    backend.fail_unload_embedding = True
    client.patch("/api/knowledge/settings", json={"unload_embedding_model_after_use": True})

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    assert any("Embedding unload after use failed" in warning for warning in response.json()["debug"]["warnings"])


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


def test_fts_query_builder_quotes_punctuation_and_hyphenated_queries() -> None:
    queries = [
        "他们俩和r5-d4又是什么关系",
        "R5-D4",
        "Qwen3.5-9B",
        "C++",
        "foo:bar",
        '"quoted"',
        "(abc)",
        "path/to/file",
        "relationship with rebellion",
        "他们是什么关系",
    ]

    for query in queries:
        built = build_safe_fts_query(query)
        assert built
        assert "-" not in built
        assert ":" not in built
        assert "(" not in built
        assert ")" not in built

    assert build_safe_fts_query("--- ::: ()") is None


def test_keyword_search_handles_hyphen_cjk_and_punctuation_without_sql_warnings(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    profile = create_profile(client, "punctuation", "punctuation-model")
    kb = create_kb(client, profile["id"], "Punctuation")
    add_source(
        client,
        kb["id"],
        "Mixed Tokens",
        '他们俩和R5-D4又是什么关系。Qwen3.5-9B, C++, foo:bar, "quoted", (abc), path/to/file, relationship with rebellion, 他们是什么关系。 ' * 4,
    )

    queries = [
        "他们俩和r5-d4又是什么关系",
        "R5-D4",
        "Qwen3.5-9B",
        "C++",
        "foo:bar",
        '"quoted"',
        "(abc)",
        "path/to/file",
        "relationship with rebellion",
        "他们是什么关系",
    ]

    for query in queries:
        response = client.post("/api/knowledge/search", json={"query": query, "knowledge_base_ids": [kb["id"]], "debug": True})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["results"]
        assert_warning_hygiene(payload["debug"]["warnings"])


def test_keyword_search_skips_all_punctuation_query_with_short_warning(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)

    response = client.post("/api/knowledge/search", json={"query": "--- ::: ()", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    warnings = response.json()["debug"]["warnings"]
    assert "KEYWORD_QUERY_UNSAFE: Keyword search skipped: query could not be converted to a safe FTS query." in warnings
    assert_warning_hygiene(warnings)


def test_keyword_operational_error_records_compact_warning_and_keeps_vector_results(tmp_path: Path, monkeypatch) -> None:
    client, _backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)

    def fail_keyword_search(**_kwargs):
        raise OperationalError(
            "SELECT * FROM kb_chunk_fts WHERE kb_chunk_fts MATCH :query",
            {"query": "R5-D4"},
            Exception("no such column: d4; see https://sqlalche.me/e/20/e3q8"),
        )

    monkeypatch.setattr(keyword_search, "_execute_keyword_search", fail_keyword_search)

    response = client.post("/api/knowledge/search", json={"query": "R5-D4", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"]
    assert payload["debug"]["warnings"] == ["KEYWORD_SEARCH_FAILED: Keyword search skipped: FTS query failed after sanitization."]
    assert_warning_hygiene(payload["debug"]["warnings"])


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


def test_reranker_profile_reranks_merged_candidates(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    model_dir = tmp_path / "data" / "models" / "rerankers" / "mock-reranker"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    provider = client.post("/api/llm-provider-profiles", json={"name": "Internal", "provider": "internal_transformers"}).json()
    reranker = client.post(
        "/api/knowledge/reranker-models",
        json={"name": "Mock Reranker", "alias": "mock-reranker", "provider_profile_id": provider["id"], "provider_model_id": "reranker/mock-reranker"},
    ).json()
    client.patch("/api/knowledge/settings", json={"reranker_enabled": True, "reranker_profile_id": reranker["id"]})

    response = client.post("/api/knowledge/search", json={"query": "alpha beta", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["reranker_used"] is True
    assert backend.rerank_calls[-1]["model_path"] == "rerankers/mock-reranker"
    assert payload["results"][0]["title"] == "Beta"


def test_reranker_unload_after_use_runs_after_successful_rerank(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    client.patch(
        "/api/knowledge/settings",
        json={
            "reranker_enabled": True,
            "reranker_model_path": "rerankers/mock-reranker",
            "unload_reranker_model_after_use": True,
        },
    )

    response = client.post("/api/knowledge/search", json={"query": "alpha beta", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    assert backend.unloaded_rerankers == [{"model_path": "rerankers/mock-reranker", "device": "auto"}]
    assert "Reranker unloaded after use." in response.json()["debug"]["warnings"]


def test_reranker_test_unload_after_use_releases_model(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    client.patch(
        "/api/knowledge/settings",
        json={
            "reranker_enabled": True,
            "reranker_model_path": "rerankers/mock-reranker",
            "unload_reranker_model_after_use": True,
        },
    )

    response = client.post(
        "/api/knowledge/rerank",
        json={"query": "alpha", "documents": [{"id": "doc1", "text": "alpha text"}]},
    )

    assert response.status_code == 200, response.text
    assert backend.unloaded_rerankers == [{"model_path": "rerankers/mock-reranker", "device": "auto"}]


def test_reranker_unload_failure_does_not_fail_search(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    backend.fail_unload_reranker = True
    client.patch(
        "/api/knowledge/settings",
        json={
            "reranker_enabled": True,
            "reranker_model_path": "rerankers/mock-reranker",
            "unload_reranker_model_after_use": True,
        },
    )

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    assert any("Reranker unload after use failed" in warning for warning in response.json()["debug"]["warnings"])


def test_reranker_failure_falls_back_to_rrf_and_records_warning(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    backend.fail_rerank = True
    client.patch(
        "/api/knowledge/settings",
        json={"reranker_enabled": True, "reranker_model_path": "rerankers/mock-reranker", "unload_reranker_model_after_use": True},
    )

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["reranker_failed"] is True
    assert any("Reranker failed" in warning for warning in payload["debug"]["warnings"])
    assert backend.unloaded_rerankers == [{"model_path": "rerankers/mock-reranker", "device": "auto"}]
    assert payload["results"][0]["rerank_score"] is None


def test_min_score_threshold_filters_final_candidates(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    client.patch("/api/knowledge/settings", json={"min_score_threshold": 0.99})

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"] == []
    assert payload["debug"]["before_filter_count"] > 0
    assert payload["debug"]["min_score_filtered_count"] > 0
    assert payload["debug"]["final_result_count"] == 0


def test_retrieval_limits_chunks_per_source_before_top_k(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    profile = create_profile(client, "source_limit", "source-limit")
    kb = create_kb(client, profile["id"], "Source Limit")
    add_source(client, kb["id"], "Alpha Long", "alpha " * 60)
    client.patch("/api/knowledge/settings", json={"retrieval_max_chunks_per_source": 1})

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "top_k": 10, "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["results"]) == 1
    assert payload["debug"]["per_source_filtered_count"] > 0


def test_retrieval_limits_chunks_per_knowledge_base_before_top_k(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    profile = create_profile(client, "kb_limit", "kb-limit")
    kb = create_kb(client, profile["id"], "KB Limit")
    add_source(client, kb["id"], "Alpha One", "alpha " * 24)
    add_source(client, kb["id"], "Alpha Two", "alpha " * 24)
    client.patch("/api/knowledge/settings", json={"retrieval_max_chunks_per_knowledge_base": 1})

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "top_k": 10, "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["results"]) == 1
    assert payload["debug"]["per_kb_filtered_count"] > 0


def test_query_expansion_is_disabled_by_default(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    backend.embedding_calls.clear()

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]], "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["query_expansion_enabled"] is False
    assert payload["debug"]["query_expansion_used"] is False
    assert backend.embedding_calls[0]["texts"] == ["alpha"]


def test_query_expansion_variants_participate_in_retrieval(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    session = client.app.state.runtime_state.sessions.create_session(title="Expansion", default_agent_id="chat")
    client.patch(f"/api/sessions/{session.session_id}/knowledge-bases", json={"knowledge_base_ids": [kb["id"]]})
    client.app.state.runtime_state.runtimes.replace("llm", FakeLLMRuntime(response='["beta"]'))
    client.patch("/api/knowledge/settings", json={"query_expansion_enabled": True})
    backend.embedding_calls.clear()

    response = client.post("/api/knowledge/search", json={"query": "delta", "session_id": session.session_id, "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["query_expansion_used"] is True
    assert payload["debug"]["expanded_query_count"] == 2
    assert payload["debug"]["expanded_queries"] == ["beta"]
    assert backend.embedding_calls[0]["texts"] == ["delta", "beta"]
    assert any(result["title"] == "Beta" for result in payload["results"])


def test_query_expansion_failure_falls_back_to_original_query(tmp_path: Path) -> None:
    client, backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    session = client.app.state.runtime_state.sessions.create_session(title="Expansion", default_agent_id="chat")
    client.patch(f"/api/sessions/{session.session_id}/knowledge-bases", json={"knowledge_base_ids": [kb["id"]]})
    client.app.state.runtime_state.runtimes.replace("llm", FakeLLMRuntime(response="not json"))
    client.patch("/api/knowledge/settings", json={"query_expansion_enabled": True})
    backend.embedding_calls.clear()

    response = client.post("/api/knowledge/search", json={"query": "alpha", "session_id": session.session_id, "debug": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["debug"]["expansion_failed"] is True
    assert any("Query expansion failed" in warning for warning in payload["debug"]["warnings"])
    assert backend.embedding_calls[0]["texts"] == ["alpha"]


def test_search_response_includes_context_preview_using_current_templates(tmp_path: Path) -> None:
    client, _backend = make_client(tmp_path)
    _profile, kb = setup_indexed_kbs(client)
    client.patch(
        "/api/knowledge/settings",
        json={
            "knowledge_context_instruction": "Use this preview.",
            "knowledge_context_snippet_template": "({index}) {source_title}: {content}",
        },
    )

    response = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]]})

    assert response.status_code == 200, response.text
    preview = response.json()["context_preview"]
    assert "# Retrieved Knowledge" in preview
    assert "Use this preview." in preview
    assert "(K1) Alpha:" in preview


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
