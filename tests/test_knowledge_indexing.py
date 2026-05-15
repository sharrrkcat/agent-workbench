from __future__ import annotations

import sqlite3
from array import array
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ai_workbench.api.main import create_app
from ai_workbench.core.knowledge_indexing import chunk_source_text
from ai_workbench.core.attachments import save_attachment_from_upload
from ai_workbench.core.knowledge_models import KnowledgeModelError
from ai_workbench.core.knowledge_settings import KnowledgeSettings
from ai_workbench.core.knowledge_store import KnowledgeBase
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


def create_kb_with_profile(client: TestClient, *, default_chunk_profile: str | None, chunk_size: int = 500, chunk_overlap: int = 0, alias: str = "bge_m3") -> dict:
    profile = create_embedding_profile(client, alias=alias)
    payload = {
        "name": "Docs",
        "embedding_model_profile_id": profile["id"],
        "chunk_size_override": chunk_size,
        "chunk_overlap_override": chunk_overlap,
    }
    if default_chunk_profile is not None:
        payload["default_chunk_profile"] = default_chunk_profile
    response = client.post("/api/knowledge/bases", json=payload)
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


def test_markdown_collection_auto_chunks_entity_headings_and_metadata(tmp_path: Path) -> None:
    client, _db_path, backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    markdown = """# Jedi Fallen Order

## Characters

### Cal Kestis
Cal is a Jedi survivor.

### Cere Junda
Cere is a mentor.

## Locations

### Bracca
Bracca is a scrapyard world.
"""

    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "jedi-fallen-order.md", "text": markdown},
    )

    assert created.status_code == 200, created.text
    chunks = client.get(f"/api/knowledge/sources/{created.json()['source_id']}/chunks").json()["chunks"]
    metadata = [chunk["metadata"] for chunk in chunks]
    assert [item["chunk_title"] for item in metadata] == ["Cal Kestis", "Cere Junda", "Bracca"]
    assert [item["entity_type"] for item in metadata] == ["Character", "Character", "Location"]
    assert all(item["document_title"] == "Jedi Fallen Order" for item in metadata)
    assert all(item["chunk_profile_effective"] == "markdown_collection" for item in metadata)
    assert metadata[0]["heading_path"] == "Jedi Fallen Order > Characters > Cal Kestis"
    assert metadata[0]["line_start"] == 5
    assert "Title: Cal Kestis" in backend.calls[-1]["texts"][0]
    assert "Document: Jedi Fallen Order" in backend.calls[-1]["texts"][0]
    assert "Type: Character" in backend.calls[-1]["texts"][0]
    assert "Section: Jedi Fallen Order > Characters > Cal Kestis" in backend.calls[-1]["texts"][0]
    assert "jedi-fallen-order.md" in backend.calls[-1]["texts"][0]


def test_markdown_document_auto_uses_document_title_for_all_chunks(tmp_path: Path) -> None:
    client, _db_path, backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    markdown = """# Cal Kestis

## Summary
Jedi survivor.

## Role in Fallen Order
Main protagonist.

## Relationships
Cere and BD-1.
"""

    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "characters/cal-kestis.md", "text": markdown},
    )

    assert created.status_code == 200, created.text
    chunks = client.get(f"/api/knowledge/sources/{created.json()['source_id']}/chunks").json()["chunks"]
    metadata = [chunk["metadata"] for chunk in chunks]
    assert {item["chunk_profile_effective"] for item in metadata} == {"markdown_document"}
    assert {item["chunk_title"] for item in metadata} == {"Cal Kestis"}
    assert {item["entity_type"] for item in metadata} == {"Character"}
    assert any(item["heading_path"] == "Cal Kestis > Role in Fallen Order" for item in metadata)
    assert any("Title: Cal Kestis" in text for text in backend.calls[-1]["texts"])
    assert not any("Title: cal-kestis.md" in text or "Title: characters/cal-kestis.md" in text for text in backend.calls[-1]["texts"])


def test_markdown_fenced_code_hash_is_not_heading(tmp_path: Path) -> None:
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    markdown = """# Real Title

```python
# Not A Heading
print("ok")
```

## Real Section
Content.
"""

    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "real-title.md", "text": markdown},
    )

    assert created.status_code == 200, created.text
    chunks = client.get(f"/api/knowledge/sources/{created.json()['source_id']}/chunks").json()["chunks"]
    heading_paths = [chunk["metadata"]["heading_path"] for chunk in chunks]
    assert "Real Title > Not A Heading" not in heading_paths
    assert "Real Title > Real Section" in heading_paths


def test_frontmatter_chunk_profile_overrides_auto_detector(tmp_path: Path) -> None:
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    markdown = """---
title: Jedi Fallen Order
chunk_profile: markdown_document
type: Document
---
# Jedi Fallen Order

## Characters

### Cal Kestis
Cal is a Jedi survivor.

### Cere Junda
Cere is a mentor.
"""

    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "jedi-fallen-order.md", "text": markdown},
    )

    assert created.status_code == 200, created.text
    chunks = client.get(f"/api/knowledge/sources/{created.json()['source_id']}/chunks").json()["chunks"]
    metadata = [chunk["metadata"] for chunk in chunks]
    assert {item["chunk_profile_requested"] for item in metadata} == {"markdown_document"}
    assert {item["chunk_profile_effective"] for item in metadata} == {"markdown_document"}
    assert {item["chunk_title"] for item in metadata} == {"Jedi Fallen Order"}
    assert {item["entity_type"] for item in metadata} == {"Document"}
    assert {item["profile_source"] for item in metadata} == {"frontmatter"}


def test_chunk_profile_precedence_frontmatter_origin_kb_auto_fallback(tmp_path: Path) -> None:
    client, _db_path, _backend = make_client(tmp_path)
    kb = create_kb_with_profile(client, default_chunk_profile="markdown_document")
    markdown = "# Codex Docs\n\n## Characters\n\n### Ada\nAda writes notes.\n\n### Ben\nBen reads notes."

    settings_default = client.patch("/api/knowledge/settings", json={"default_chunk_profile": "plain_text"})
    assert settings_default.status_code == 200, settings_default.text

    kb_default = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "collection.md", "text": markdown},
    )
    assert kb_default.status_code == 200, kb_default.text
    kb_meta = client.get(f"/api/knowledge/sources/{kb_default.json()['source_id']}/chunks").json()["chunks"][0]["metadata"]
    assert kb_meta["chunk_profile_effective"] == "markdown_document"
    assert kb_meta["profile_source"] == "kb_default"

    source_override = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "source-override.md", "text": markdown, "chunk_profile": "markdown_collection"},
    )
    assert source_override.status_code == 200, source_override.text
    source_override_meta = client.get(f"/api/knowledge/sources/{source_override.json()['source_id']}/chunks").json()["chunks"][0]["metadata"]
    assert source_override_meta["chunk_profile_effective"] == "markdown_collection"
    assert source_override_meta["profile_source"] == "source_override"

    origin = client.post(
        f"/api/knowledge/bases/{kb['id']}/origins",
        json={"name": "Origin", "slug": "origin_docs", "default_chunk_profile": "markdown_collection"},
    ).json()
    source_path = tmp_path / origin["root_path"] / "collection.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(markdown, encoding="utf-8")
    client.post(f"/api/knowledge/origins/{origin['id']}/scan")
    imported = client.post(f"/api/knowledge/origins/{origin['id']}/import", json={})
    assert imported.status_code == 200, imported.text
    origin_source = client.get(f"/api/knowledge/bases/{kb['id']}/sources").json()[-1]
    origin_meta = client.get(f"/api/knowledge/sources/{origin_source['id']}/chunks").json()["chunks"][0]["metadata"]
    assert origin_meta["chunk_profile_effective"] == "markdown_collection"
    assert origin_meta["profile_source"] == "origin_default"
    assert origin_meta["entity_level"] == 3

    source_path.write_text("---\nchunk_profile: markdown_document\n---\n" + markdown, encoding="utf-8")
    client.post(f"/api/knowledge/origins/{origin['id']}/scan")
    client.post(f"/api/knowledge/origins/{origin['id']}/import", json={})
    frontmatter_meta = client.get(f"/api/knowledge/sources/{origin_source['id']}/chunks").json()["chunks"][0]["metadata"]
    assert frontmatter_meta["chunk_profile_effective"] == "markdown_document"
    assert frontmatter_meta["profile_source"] == "frontmatter"

    auto_kb = create_kb_with_profile(client, default_chunk_profile=None, alias="bge_m3_auto")
    assert auto_kb["default_chunk_profile"] == "markdown_auto"
    auto_source = client.post(
        f"/api/knowledge/bases/{auto_kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "auto.md", "text": markdown},
    )
    auto_meta = client.get(f"/api/knowledge/sources/{auto_source.json()['source_id']}/chunks").json()["chunks"][0]["metadata"]
    assert auto_meta["chunk_profile_requested"] == "markdown_auto"
    assert auto_meta["profile_source"] == "kb_default"

    fallback_source = client.post(
        f"/api/knowledge/bases/{auto_kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "plain.txt", "text": "no markdown here"},
    )
    fallback_meta = client.get(f"/api/knowledge/sources/{fallback_source.json()['source_id']}/chunks").json()["chunks"][0]["metadata"]
    assert fallback_meta["chunk_profile_effective"] == "markdown_document"
    assert fallback_meta["chunk_profile_requested"] == "markdown_auto"
    assert fallback_meta["profile_source"] == "kb_default"


def test_api_compact_profile_fields_and_old_metadata_fallback(tmp_path: Path) -> None:
    client, db_path, _backend = make_client(tmp_path)
    kb = create_kb_with_profile(client, default_chunk_profile=None, alias="bge_m3_compact")
    created = client.post(
        f"/api/knowledge/bases/{kb['id']}/sources",
        json={"source_type": "pasted_text", "title": "compact.md", "text": "# Title\n\n## Summary\nBody"},
    ).json()
    source = client.get(f"/api/knowledge/sources/{created['source_id']}").json()
    assert source["chunk_profile_effective"] == "markdown_document"
    assert source["profile_source"] == "kb_default"
    assert source["title_source"] in {"h1", "filename"}

    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE kb_sources SET metadata_json = '{}' WHERE id = ?", (created["source_id"],))
        connection.commit()
    old_source = client.get(f"/api/knowledge/sources/{created['source_id']}")
    assert old_source.status_code == 200, old_source.text
    assert old_source.json()["chunk_profile_effective"] is None


def test_legacy_empty_kb_profile_ignores_knowledge_defaults_profile() -> None:
    settings = KnowledgeSettings(default_chunk_profile="plain_text", default_chunk_size=500, default_chunk_overlap=0)
    legacy_kb = KnowledgeBase.model_construct(
        id="legacy",
        name="Legacy",
        description="",
        aliases_text="",
        embedding_model_profile_id="profile",
        enabled=True,
        index_status="empty",
        index_error=None,
        chunk_size_override=500,
        chunk_overlap_override=0,
        vector_candidate_k_override=None,
        keyword_candidate_k_override=None,
        final_top_k_override=None,
        max_context_chars_override=None,
        default_chunk_profile=None,
    )

    markdown_chunks = chunk_source_text("# Title\n\nBody", settings=settings, knowledge_base=legacy_kb, source_title="note.md")
    plain_chunks = chunk_source_text("plain text only", settings=settings, knowledge_base=legacy_kb, source_title="note.txt")

    assert markdown_chunks[0].metadata["chunk_profile_requested"] == "markdown_auto"
    assert markdown_chunks[0].metadata["profile_source"] == "auto_detector"
    assert plain_chunks[0].metadata["chunk_profile_effective"] == "markdown_document"
    assert plain_chunks[0].metadata["profile_source"] == "fallback"
