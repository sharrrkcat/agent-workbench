import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ai_workbench.api.main import create_app
import ai_workbench.core.knowledge_models as knowledge_models
from ai_workbench.core.knowledge_models import LocalKnowledgeModelBackend
from ai_workbench.db.database import get_engine, init_db
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'knowledge.db'}"))


def create_embedding_profile(client: TestClient, alias: str = "bge_m3") -> dict:
    root = client.app.state.runtime_state.repo_root
    model_dir = root / "data" / "models" / "embeddings" / "bge-m3"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": f"Embedding provider {alias}", "provider": "internal_transformers", "enabled": True},
    )
    assert provider.status_code == 200, provider.text
    response = client.post(
        "/api/knowledge/embedding-models",
        json={
            "name": "BGE M3",
            "alias": alias,
            "provider_profile_id": provider.json()["id"],
            "provider_model_id": "embedding/bge-m3",
            "dimension": 3,
            "normalize": True,
            "document_instruction": "Document:",
            "query_instruction": "Query:",
            "enabled": True,
            "notes": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_knowledge_settings_defaults_patch_validation_and_persist(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    defaults = client.get("/api/knowledge/settings")
    assert defaults.status_code == 200
    assert defaults.json()["models_root"] == "data/models"
    assert defaults.json()["reranker_enabled"] is False
    assert defaults.json()["unload_embedding_model_after_use"] is False
    assert defaults.json()["unload_reranker_model_after_use"] is False
    assert "{content}" in defaults.json()["knowledge_context_snippet_template"]

    patched = client.patch(
        "/api/knowledge/settings",
        json={
            "local_model_device": "cpu",
            "embedding_batch_size": 2,
            "unload_embedding_model_after_use": True,
            "reranker_model_path": "rerankers/bge-reranker",
            "unload_reranker_model_after_use": True,
            "knowledge_context_instruction": "Use KB snippets.",
            "knowledge_context_snippet_template": "{content}",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["local_model_device"] == "cpu"
    assert patched.json()["embedding_batch_size"] == 2
    assert patched.json()["unload_embedding_model_after_use"] is True
    assert patched.json()["reranker_model_path"] == "rerankers/bge-reranker"
    assert patched.json()["unload_reranker_model_after_use"] is True

    assert client.patch("/api/knowledge/settings", json={"unknown": 1}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"local_model_device": "metal"}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"reranker_model_path": "embeddings/foo"}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"reranker_model_path": "../x"}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"knowledge_context_instruction": " "}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"knowledge_context_snippet_template": "no content"}).status_code == 422

    restarted = make_client(tmp_path)
    assert restarted.get("/api/knowledge/settings").json()["embedding_batch_size"] == 2
    assert restarted.get("/api/knowledge/settings").json()["unload_embedding_model_after_use"] is True


def test_knowledge_tables_exist_and_existing_db_upgrades(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.db"
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "knowledge_settings",
        "embedding_model_profiles",
        "knowledge_bases",
        "session_knowledge_bindings",
        "kb_sources",
        "kb_chunks",
        "kb_embeddings",
    }.issubset(tables)
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{db_path}"))
    assert client.get("/api/knowledge/settings").status_code == 200


def test_model_scan_creates_directories_and_lists_direct_child_dirs(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, use_memory=True))
    (tmp_path / "data" / "models" / "embeddings" / "bge-m3").mkdir(parents=True)
    (tmp_path / "data" / "models" / "embeddings" / "file.txt").write_text("x", encoding="utf-8")
    (tmp_path / "data" / "models" / "rerankers" / "bge-reranker").mkdir(parents=True)

    response = client.get("/api/knowledge/models/scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["models_root"] == "data/models"
    assert payload["embedding_models"] == [{"model_path": "embeddings/bge-m3", "name": "bge-m3", "exists": True}]
    assert payload["reranker_models"] == [{"model_path": "rerankers/bge-reranker", "name": "bge-reranker", "exists": True}]
    assert "sentence_transformers_available" in payload["backend"]


def test_local_model_unload_collects_and_empties_cuda_cache(monkeypatch, tmp_path: Path) -> None:
    backend = LocalKnowledgeModelBackend(tmp_path)
    backend._embedding_cache[("model-a", "cuda")] = object()
    calls: list[str] = []
    original_find_spec = knowledge_models.importlib.util.find_spec

    monkeypatch.setattr(knowledge_models.gc, "collect", lambda: calls.append("gc"))
    monkeypatch.setattr(
        knowledge_models.importlib.util,
        "find_spec",
        lambda name: object() if name == "torch" else original_find_spec(name),
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, empty_cache=lambda: calls.append("empty_cache"))),
    )

    removed = backend.unload_all_embedding_models()

    assert removed == 1
    assert backend._embedding_cache == {}
    assert calls == ["gc", "empty_cache"]


def test_embedding_model_profile_crud_and_kb_in_use_delete_rejection(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    profile = create_embedding_profile(client)
    assert client.post("/api/knowledge/embedding-models", json={**profile, "id": "ignored"}).status_code == 422
    assert client.post("/api/knowledge/embedding-models", json={**{k: profile[k] for k in ["name", "provider_profile_id", "provider_model_id"]}, "alias": "Bad Alias"}).status_code == 422
    assert client.post("/api/knowledge/embedding-models", json={**{k: profile[k] for k in ["name", "alias"]}, "model_path": "embeddings/legacy"}).status_code == 422
    assert client.post("/api/knowledge/embedding-models", json={**{k: profile[k] for k in ["name", "provider_profile_id", "provider_model_id"]}, "alias": profile["alias"]}).status_code == 409
    assert client.get("/api/knowledge/embedding-models").json()[0]["alias"] == "bge_m3"

    patched = client.patch(f"/api/knowledge/embedding-models/{profile['id']}", json={"name": "BGE M3 local", "dimension": 4})
    assert patched.status_code == 200
    assert patched.json()["dimension"] == 4

    kb = client.post(
        "/api/knowledge/bases",
        json={"name": "Docs", "description": "Project docs", "embedding_model_profile_id": profile["id"], "enabled": True},
    )
    assert kb.status_code == 200
    rejected = client.delete(f"/api/knowledge/embedding-models/{profile['id']}")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "KNOWLEDGE_EMBEDDING_MODEL_IN_USE"


def test_knowledge_base_crud_and_session_bindings(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    profile = create_embedding_profile(client)
    missing = client.post("/api/knowledge/bases", json={"name": "Bad", "embedding_model_profile_id": "missing"})
    assert missing.status_code == 400
    kb = client.post("/api/knowledge/bases", json={"name": "Docs", "embedding_model_profile_id": profile["id"], "aliases_text": "docs, project docs"}).json()
    assert kb["index_status"] == "empty"
    assert kb["aliases_text"] == "docs, project docs"
    assert kb["default_chunk_profile"] == "markdown_auto"
    assert client.get("/api/knowledge/bases").json()[0]["name"] == "Docs"
    patched = client.patch(f"/api/knowledge/bases/{kb['id']}", json={"enabled": False, "final_top_k_override": 5, "aliases_text": "docs, Docs, 星战"})
    assert patched.status_code == 200
    assert patched.json()["final_top_k_override"] == 5
    assert patched.json()["aliases_text"] == "docs, 星战"
    assert client.patch(f"/api/knowledge/bases/{kb['id']}", json={"final_top_k_override": 0}).status_code == 422

    session = client.post("/api/sessions", json={"title": "", "default_agent_id": "chat"}).json()
    assert client.get(f"/api/sessions/{session['session_id']}/knowledge-bases").json() == []
    saved = client.patch(
        f"/api/sessions/{session['session_id']}/knowledge-bases",
        json={"knowledge_base_ids": [kb["id"]]},
    )
    assert saved.status_code == 200
    assert saved.json()[0]["knowledge_base_id"] == kb["id"]
    kb2 = client.post("/api/knowledge/bases", json={"name": "More Docs", "embedding_model_profile_id": profile["id"]}).json()
    ordered = client.patch(
        f"/api/sessions/{session['session_id']}/knowledge-bases",
        json={"knowledge_base_ids": [kb2["id"], kb["id"]]},
    )
    assert [item["knowledge_base_id"] for item in ordered.json()] == [kb2["id"], kb["id"]]
    assert [item["sort_order"] for item in ordered.json()] == [10, 20]
    assert client.patch(f"/api/sessions/{session['session_id']}/knowledge-bases", json={"knowledge_base_ids": ["missing"]}).status_code == 404
    assert client.delete(f"/api/knowledge/bases/{kb['id']}").status_code == 200
    assert [item["knowledge_base_id"] for item in client.get(f"/api/sessions/{session['session_id']}/knowledge-bases").json()] == [kb2["id"]]
    assert client.delete(f"/api/knowledge/bases/{kb2['id']}").status_code == 200
    assert client.get(f"/api/sessions/{session['session_id']}/knowledge-bases").json() == []
