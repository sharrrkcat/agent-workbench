import asyncio

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import ModelStatus, RerankResult
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


def test_rag_rerank_contract_uses_manager_and_rrf_on_failure(tmp_path):
    upstream = MockOpenAI()
    fail = False

    class Adapter(OpenAIAdapter):
        async def health(self, profile):
            return ModelStatus(state="ready") if profile.kind == "reranker" else await super().health(profile)

        async def rerank(self, profile, query, documents):
            if fail:
                raise ModelError("MODEL_UNAVAILABLE", "reranker unavailable", 503)
            return RerankResult(scores=list(range(len(documents))))

    with TestClient(create_app(use_memory=True, root=tmp_path, adapter_factory=lambda p: Adapter(p, __import__("httpx").MockTransport(upstream.handle)))) as client:
        embed = configure_model(client, kind="embedding", alias="embed")
        rerank = configure_model(client, kind="reranker", alias="rerank")
        base = client.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": embed["id"]}).json()
        for value in ("alpha first", "alpha second"):
            assert client.post(f"/api/knowledge/bases/{base['id']}/sources", json={"title": value, "text": value}).status_code == 200
        client.patch("/api/knowledge/settings", json={"reranker_enabled": True, "reranker_model_profile_id": rerank["id"]})
        search = lambda: client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [base["id"]], "debug": True}).json()
        ranked = search()
        assert ranked["metadata"]["reranker_used"] is True
        assert ranked["results"][0]["content"] == "alpha second"
        fail = True
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
