from __future__ import annotations

import sqlite3
from array import array
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import save_attachment_from_upload
from ai_workbench.core.knowledge_models import KnowledgeModelError
from ai_workbench.db.database import get_engine, init_db
from tests.test_knowledge_settings import create_embedding_profile
from tests.test_prompt_agent_execution import FakeLLMRuntime


class MockEmbeddingBackend:
    def __init__(self, dimension: int = 3, fail_code: str | None = None) -> None:
        self.dimension = dimension
        self.fail_code = fail_code
        self.calls: list[dict] = []
        self.unloaded_embeddings: list[dict] = []

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self.calls.append({"model_path": model_path, "texts": texts, "normalize": normalize, "device": device})
        if self.fail_code:
            raise KnowledgeModelError(self.fail_code, "mock embedding failed")
        base = [3.0, 4.0, 0.0]
        return [base[: self.dimension] for _ in texts]

    def unload_embedding_model(self, model_path: str, device: str) -> bool:
        self.unloaded_embeddings.append({"model_path": model_path, "device": device})
        return True


def make_client(tmp_path: Path, backend: MockEmbeddingBackend | None = None) -> tuple[TestClient, Path, MockEmbeddingBackend]:
    backend = backend or MockEmbeddingBackend()
    db_path = tmp_path / "knowledge.db"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), root=tmp_path, database_url=f"sqlite:///{db_path}"))
    client.app.state.runtime_state.knowledge_model_backend = backend
    return client, db_path, backend


def create_kb(client: TestClient, *, chunk_size: int = 100, chunk_overlap: int = 20) -> dict:
    profile = create_embedding_profile(client)
    response = client.post(
        "/api/knowledge/bases",
        json={
            "name": "Docs",
            "embedding_model_profile_id": profile["id"],
            "chunk_size_override": chunk_size,
            "chunk_overlap_override": chunk_overlap,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def table_count(db_path: Path, table: str, where: str = "", params: tuple = ()) -> int:
    with sqlite3.connect(db_path) as connection:
        suffix = f" WHERE {where}" if where else ""
        return int(connection.execute(f"SELECT count(*) FROM {table}{suffix}", params).fetchone()[0])


def test_knowledge_index_tables_exist_and_upgrade_is_idempotent(tmp_path: Path) -> None:
    engine = get_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    init_db(engine)
    init_db(engine)

    tables = set(inspect(engine).get_table_names())
    assert {"kb_sources", "kb_chunks", "kb_embeddings"}.issubset(tables)
    with sqlite3.connect(tmp_path / "existing.db") as connection:
        fts = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kb_chunk_fts'").fetchone()
    assert fts == ("kb_chunk_fts",)


def test_pasted_text_source_indexes_chunks_vectors_fts_and_raw_file(tmp_path: Path) -> None:
    client, db_path, backend = make_client(tmp_path)
    kb = create_kb(client)

    response = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Notes", "text": "a" * 250},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "indexed"
    assert payload["chunks"] == 3
    assert payload["embedding_model_profile_id"] == kb["embedding_model_profile_id"]
    assert payload["embedding_dimension"] == 3
    assert backend.calls[-1]["texts"][0].startswith("Document:\n")
    assert len(backend.calls[-1]["texts"]) == 3

    source = client.get(f"/api/knowledge/sources/{payload['source_id']}").json()
    assert source["title"] == "Notes"
    assert source["chunks"] == 3
    assert source["uri"] == f"data/knowledge/sources/{payload['source_id']}.txt"
    assert (tmp_path / source["uri"]).read_text(encoding="utf-8") == "a" * 250
    assert "text" not in source

    with sqlite3.connect(db_path) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(kb_sources)").fetchall()]
        assert "text" not in columns
        chunks = connection.execute("SELECT chunk_index, char_start, char_end FROM kb_chunks ORDER BY chunk_index").fetchall()
        blob = connection.execute("SELECT vector_blob FROM kb_embeddings LIMIT 1").fetchone()[0]
        fts_content = connection.execute("SELECT search_text FROM kb_chunk_fts LIMIT 1").fetchone()[0]
    assert chunks == [(0, 0, 100), (1, 80, 180), (2, 160, 250)]
    vector = array("f")
    vector.frombytes(blob)
    assert [round(value, 3) for value in vector.tolist()] == [0.6, 0.8, 0.0]
    assert "Notes" in fts_content
    assert table_count(db_path, "kb_chunk_fts", "source_id = ?", (payload["source_id"],)) == 3
    assert client.get(f"/api/knowledge/bases/{kb['id']}").json()["index_status"] == "ready"


def test_embedding_unload_after_use_runs_after_single_source_index(tmp_path: Path) -> None:
    client, _db_path, backend = make_client(tmp_path)
    kb = create_kb(client)
    client.patch("/api/knowledge/settings", json={"unload_embedding_model_after_use": True})

    response = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Notes", "text": "a" * 120},
    )

    assert response.status_code == 200, response.text
    assert backend.unloaded_embeddings == [{"model_path": "embeddings/bge-m3", "device": "auto"}]


def test_source_preview_and_chunk_list_hide_vectors(tmp_path: Path) -> None:
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)
    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Preview", "text": "alpha " * 60},
    ).json()
    source_id = created["source_id"]

    preview = client.get(f"/api/knowledge/sources/{source_id}/preview")
    chunks = client.get(f"/api/knowledge/sources/{source_id}/chunks")

    assert preview.status_code == 200, preview.text
    assert preview.json()["source_id"] == source_id
    assert preview.json()["preview"].startswith("alpha alpha")
    assert preview.json()["size_bytes"] == len(("alpha " * 60).encode("utf-8"))
    assert "vector_blob" not in preview.text
    assert chunks.status_code == 200, chunks.text
    payload = chunks.json()
    assert [item["chunk_index"] for item in payload["chunks"]] == [0, 1, 2, 3, 4]
    assert payload["chunks"][0]["content_preview"].startswith("alpha")
    assert payload["chunks"][0]["embedding_dimension"] == 3
    assert "vector_blob" not in chunks.text


def test_source_limit_and_dimension_errors_are_structured(tmp_path: Path) -> None:
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)
    client.patch("/api/knowledge/settings", json={"max_source_size_bytes": 1024, "max_total_index_chars_per_source": 2000})

    too_large = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Large", "text": "x" * 1025},
    )
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "KNOWLEDGE_SOURCE_TOO_LARGE"

    client.patch("/api/knowledge/settings", json={"max_chunks_per_source": 1})
    too_many = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Chunks", "text": "y" * 250},
    )
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "KNOWLEDGE_TOO_MANY_CHUNKS"

    client.patch("/api/knowledge/settings", json={"max_chunks_per_source": 500})
    client.patch(f"/api/knowledge/embedding-models/{kb['embedding_model_profile_id']}", json={"dimension": 4})
    mismatch = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Mismatch", "text": "z" * 120},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "KNOWLEDGE_EMBEDDING_DIMENSION_MISMATCH"


def test_delete_source_removes_chunks_embeddings_and_fts(tmp_path: Path) -> None:
    client, db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)
    source = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Delete", "text": "a" * 180},
    ).json()

    response = client.delete(f"/api/knowledge/sources/{source['source_id']}")

    assert response.status_code == 200
    assert table_count(db_path, "kb_chunks", "source_id = ?", (source["source_id"],)) == 0
    assert table_count(db_path, "kb_embeddings", "source_id = ?", (source["source_id"],)) == 0
    assert table_count(db_path, "kb_chunk_fts", "source_id = ?", (source["source_id"],)) == 0
    assert client.get(f"/api/knowledge/bases/{kb['id']}").json()["index_status"] == "empty"


def test_reindex_replaces_chunks_and_embedding_failure_preserves_old_index(tmp_path: Path) -> None:
    client, db_path, backend = make_client(tmp_path)
    kb = create_kb(client)
    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Reindex", "text": "a" * 180},
    ).json()
    source_id = created["source_id"]
    source_path = tmp_path / "data" / "knowledge" / "sources" / f"{source_id}.txt"
    source_path.write_text("b" * 250, encoding="utf-8")

    reindexed = client.post(f"/api/knowledge/sources/{source_id}/reindex")

    assert reindexed.status_code == 200, reindexed.text
    assert reindexed.json()["chunks"] == 3
    assert table_count(db_path, "kb_chunks", "source_id = ?", (source_id,)) == 3

    backend.fail_code = "KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE"
    source_path.write_text("c" * 120, encoding="utf-8")
    failed = client.post(f"/api/knowledge/sources/{source_id}/reindex")

    assert failed.status_code == 422
    assert table_count(db_path, "kb_chunks", "source_id = ?", (source_id,)) == 3
    source = client.get(f"/api/knowledge/sources/{source_id}").json()
    assert source["status"] == "indexed"
    assert source["error"] == "mock embedding failed"
    assert source["chunks"] == 3
    assert client.get(f"/api/knowledge/bases/{kb['id']}").json()["index_status"] == "ready"


def test_attachment_text_source_indexes_and_binary_attachment_is_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    text_attachment = save_attachment_from_upload("note.txt", "text/plain", b"hello knowledge")
    image_attachment = save_attachment_from_upload("image.svg", "image/svg+xml", b"<svg></svg>")
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)

    indexed = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "attachment_text", "attachment_id": text_attachment["uri"], "title": "Readable note"},
    )
    rejected = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "attachment_text", "attachment_id": image_attachment["uri"]},
    )

    assert indexed.status_code == 200, indexed.text
    source = client.get(f"/api/knowledge/sources/{indexed.json()['source_id']}").json()
    assert source["source_type"] == "attachment_text"
    assert source["title"] == "Readable note"
    assert source["uri"] == text_attachment["uri"]
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "KNOWLEDGE_ATTACHMENT_NOT_TEXT"


def test_kb_reindex_reindexes_all_sources(tmp_path: Path) -> None:
    client, _db_path, backend = make_client(tmp_path)
    kb = create_kb(client)
    first = client.post(f"/api/knowledge/bases/{kb['id']}/sources", json={"source_type": "pasted_text", "title": "One", "text": "a" * 120}).json()
    second = client.post(f"/api/knowledge/bases/{kb['id']}/sources", json={"source_type": "pasted_text", "title": "Two", "text": "b" * 120}).json()
    backend.calls.clear()

    response = client.post(f"/api/knowledge/bases/{kb['id']}/reindex")

    assert response.status_code == 200
    assert {item["source_id"] for item in response.json()["sources"]} == {first["source_id"], second["source_id"]}
    assert len(backend.calls) == 2


def test_kb_reindex_unloads_embedding_once_after_all_sources(tmp_path: Path) -> None:
    client, _db_path, backend = make_client(tmp_path)
    kb = create_kb(client)
    client.post(f"/api/knowledge/bases/{kb['id']}/sources", json={"source_type": "pasted_text", "title": "One", "text": "a" * 120})
    client.post(f"/api/knowledge/bases/{kb['id']}/sources", json={"source_type": "pasted_text", "title": "Two", "text": "b" * 120})
    backend.calls.clear()
    backend.unloaded_embeddings.clear()
    client.patch("/api/knowledge/settings", json={"unload_embedding_model_after_use": True})

    response = client.post(f"/api/knowledge/bases/{kb['id']}/reindex")

    assert response.status_code == 200, response.text
    assert len(backend.calls) == 2
    assert backend.unloaded_embeddings == [{"model_path": "embeddings/bge-m3", "device": "auto"}]


def test_kb_and_embedding_profile_changes_mark_existing_index_needs_reindex(tmp_path: Path) -> None:
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)
    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "Stale", "text": "a" * 180},
    ).json()
    source_id = created["source_id"]

    changed_kb = client.patch(f"/api/knowledge/bases/{kb['id']}", json={"chunk_size_override": 120})

    assert changed_kb.status_code == 200, changed_kb.text
    assert changed_kb.json()["index_status"] == "needs_reindex"
    assert client.get(f"/api/knowledge/sources/{source_id}").json()["status"] == "needs_reindex"

    reindexed = client.post(f"/api/knowledge/bases/{kb['id']}/reindex")

    assert reindexed.status_code == 200, reindexed.text
    assert client.get(f"/api/knowledge/bases/{kb['id']}").json()["index_status"] == "ready"
    assert client.get(f"/api/knowledge/sources/{source_id}").json()["status"] == "indexed"

    changed_profile = client.patch(
        f"/api/knowledge/embedding-models/{kb['embedding_model_profile_id']}",
        json={"normalize": False, "document_instruction": "Doc:"},
    )

    assert changed_profile.status_code == 200, changed_profile.text
    assert client.get(f"/api/knowledge/bases/{kb['id']}").json()["index_status"] == "needs_reindex"
    assert client.get(f"/api/knowledge/sources/{source_id}").json()["status"] == "needs_reindex"
