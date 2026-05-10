from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ai_workbench.api.main import create_app
from ai_workbench.db.database import get_engine, init_db
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'knowledge.db'}"))


def create_embedding_profile(client: TestClient, alias: str = "bge_m3") -> dict:
    response = client.post(
        "/api/knowledge/embedding-models",
        json={
            "name": "BGE M3",
            "alias": alias,
            "model_path": "embeddings/bge-m3",
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
    assert "{content}" in defaults.json()["knowledge_context_snippet_template"]

    patched = client.patch(
        "/api/knowledge/settings",
        json={
            "local_model_device": "cpu",
            "embedding_batch_size": 2,
            "reranker_model_path": "rerankers/bge-reranker",
            "knowledge_context_instruction": "Use KB snippets.",
            "knowledge_context_snippet_template": "{content}",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["local_model_device"] == "cpu"
    assert patched.json()["embedding_batch_size"] == 2
    assert patched.json()["reranker_model_path"] == "rerankers/bge-reranker"

    assert client.patch("/api/knowledge/settings", json={"unknown": 1}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"local_model_device": "metal"}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"reranker_model_path": "embeddings/foo"}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"reranker_model_path": "../x"}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"knowledge_context_instruction": " "}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"knowledge_context_snippet_template": "no content"}).status_code == 422

    restarted = make_client(tmp_path)
    assert restarted.get("/api/knowledge/settings").json()["embedding_batch_size"] == 2


def test_knowledge_tables_exist_and_existing_db_upgrades(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.db"
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"knowledge_settings", "embedding_model_profiles", "knowledge_bases", "session_knowledge_bindings"}.issubset(tables)
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


def test_embedding_model_profile_crud_and_kb_in_use_delete_rejection(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    profile = create_embedding_profile(client)
    assert client.post("/api/knowledge/embedding-models", json={**profile, "id": "ignored"}).status_code == 422
    assert client.post("/api/knowledge/embedding-models", json={**{k: profile[k] for k in ["name", "model_path"]}, "alias": "Bad Alias"}).status_code == 422
    assert client.post("/api/knowledge/embedding-models", json={**{k: profile[k] for k in ["name", "alias"]}, "model_path": "rerankers/x"}).status_code == 422
    assert client.post("/api/knowledge/embedding-models", json={**{k: profile[k] for k in ["name", "model_path"]}, "alias": profile["alias"]}).status_code == 409
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
    kb = client.post("/api/knowledge/bases", json={"name": "Docs", "embedding_model_profile_id": profile["id"]}).json()
    assert kb["index_status"] == "empty"
    assert client.get("/api/knowledge/bases").json()[0]["name"] == "Docs"
    patched = client.patch(f"/api/knowledge/bases/{kb['id']}", json={"enabled": False, "final_top_k_override": 5})
    assert patched.status_code == 200
    assert patched.json()["final_top_k_override"] == 5
    assert client.patch(f"/api/knowledge/bases/{kb['id']}", json={"final_top_k_override": 0}).status_code == 422

    session = client.post("/api/sessions", json={"title": "", "default_agent_id": "chat"}).json()
    assert client.get(f"/api/sessions/{session['session_id']}/knowledge-bases").json() == []
    saved = client.patch(
        f"/api/sessions/{session['session_id']}/knowledge-bases",
        json={"knowledge_base_ids": [kb["id"]]},
    )
    assert saved.status_code == 200
    assert saved.json()[0]["knowledge_base_id"] == kb["id"]
    assert client.patch(f"/api/sessions/{session['session_id']}/knowledge-bases", json={"knowledge_base_ids": ["missing"]}).status_code == 404
    assert client.delete(f"/api/knowledge/bases/{kb['id']}").status_code == 200
    assert client.get(f"/api/sessions/{session['session_id']}/knowledge-bases").json() == []
