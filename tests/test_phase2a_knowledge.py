import asyncio

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import RerankResult
from tests.model_fixtures import MockOpenAI, configure_model


@pytest.mark.parametrize("memory", [False, True])
def test_index_search_invalidation_reindex_and_shared_embeddings(tmp_path, memory):
    upstream = MockOpenAI()
    with TestClient(create_app(use_memory=memory, database_url=f"sqlite:///{tmp_path / 'knowledge.db'}",
                              root=tmp_path, adapter_factory=upstream.factory)) as client:
        profile = configure_model(client, kind="embedding", alias="embed", parameters={"dimensions": 2, "query_instruction": "query: ", "document_instruction": "doc: "})
        base = client.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": profile["id"]}).json()
        response = client.post(f"/api/knowledge/bases/{base['id']}/sources", json={"title": "Fact", "text": "alpha fact"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "indexed"
        assert upstream.calls[-1]["input"] == ["doc: alpha fact"]
        result = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [base["id"]], "debug": True})
        assert result.status_code == 200, result.text
        assert result.json()["results"][0]["content"] == "alpha fact"
        assert upstream.calls[-1]["input"] == ["query: alpha"]
        filtered = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [base["id"]], "min_score_threshold": 1})
        assert filtered.json()["results"] == [], filtered.text
        assert client.patch(f"/api/models/profiles/{profile['id']}", json={"parameters": {"dimensions": 2, "normalize": False}}).status_code == 200
        assert client.get(f"/api/knowledge/bases/{base['id']}").json()["index_status"] == "needs_reindex"
        assert client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [base["id"]]}).json()["results"] == []
        reindex = client.post(f"/api/knowledge/bases/{base['id']}/reindex")
        assert reindex.status_code == 200, reindex.text
        assert reindex.json()["sources"][0]["status"] == "indexed"
        result = client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [base["id"]]})
        assert result.json()["results"], result.text
        provider_path = '/api/models/providers/' + profile['source']['provider_profile_id']
        assert client.patch(provider_path, json={'connection': {'api_key': 'replacement-key'}}).status_code == 200
        assert client.get(f"/api/knowledge/bases/{base['id']}").json()['index_status'] != 'needs_reindex'
        other = client.post('/api/models/providers', json={'name': 'Other', 'connection': {'base_url': 'https://other.test/v1'}}).json()
        for path, patch in (
            (provider_path, {'connection': {'base_url': 'https://replacement.test/v1'}}),
            (f"/api/models/profiles/{profile['id']}", {'source': {'type': 'provider', 'provider_profile_id': other['id']}}),
        ):
            assert client.patch(path, json=patch).status_code == 200
            assert client.get(f"/api/knowledge/bases/{base['id']}").json()['index_status'] == 'needs_reindex'
            assert client.post(f"/api/knowledge/bases/{base['id']}/reindex").status_code == 200


def test_rag_rerank_contract_uses_manager_and_rrf_on_failure(tmp_path, monkeypatch):
    upstream = MockOpenAI()
    with TestClient(create_app(use_memory=True, root=tmp_path, adapter_factory=upstream.factory)) as client:
        embed = configure_model(client, kind="embedding", alias="embed")
        rerank = configure_model(client, kind="reranker", alias="rerank", source=None)
        manager = client.app.state.runtime_state.model_manager
        original = manager.rerank

        async def rerank_result(profile_id, query, documents):
            assert profile_id == rerank['id']
            return RerankResult(scores=list(range(len(documents))))
        monkeypatch.setattr(manager, 'rerank', rerank_result)
        base = client.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": embed["id"]}).json()
        for value in ("alpha first", "alpha second"):
            assert client.post(f"/api/knowledge/bases/{base['id']}/sources", json={"title": value, "text": value}).status_code == 200
        client.patch("/api/knowledge/settings", json={"reranker_enabled": True, "reranker_model_profile_id": rerank["id"]})
        search = lambda: client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [base["id"]], "debug": True}).json()
        ranked = search()
        assert ranked["metadata"]["reranker_used"] is True
        assert ranked["results"][0]["content"] == "alpha second"
        monkeypatch.setattr(manager, 'rerank', original)
        fallback = search()
        assert fallback["metadata"]["rerank_fallback"] is True
        assert fallback["metadata"]["reranker_used"] is False
        assert fallback["results"][0]["content"] == "alpha first"


def test_titles_only_use_explicit_auxiliary_after_main_lease_releases(tmp_path):
    upstream = MockOpenAI()
    with TestClient(create_app(use_memory=True, root=tmp_path, adapter_factory=upstream.factory)) as client:
        main = configure_model(client, alias="chat", parameters={"temperature": 0.7})
        auxiliary = configure_model(client, alias="titles", model_ref="other")
        client.patch("/api/models/settings", json={"default_model_profile_id": main["id"], "utility_model_profile_id": auxiliary["id"]})
        session = client.post("/api/sessions", json={}).json()
        response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})
        assert response.json()["success"], response.text
        assert [c["model"] for c in upstream.calls] == ["fake", "other"]
        assert upstream.calls[-1]["max_tokens"] == 64
        assert client.get(f"/api/sessions/{session['session_id']}").json()["title"] == "reply"
        client.patch("/api/models/settings", json={"utility_model_profile_id": None})
        session = client.post("/api/sessions", json={}).json()
        client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "another"})
        assert len(upstream.calls) == 3
        assert client.get(f"/api/sessions/{session['session_id']}").json()["title"] == ""
