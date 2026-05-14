from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.test_knowledge_indexing import create_kb, make_client, table_count


def test_create_origin_validates_slug_and_managed_root(tmp_path: Path) -> None:
    client, db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)

    rejected = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Bad", "slug": "../bad"})
    created = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Manual Docs", "slug": "manual_docs"})

    assert rejected.status_code == 422
    assert created.status_code == 200, created.text
    origin = created.json()
    assert origin["root_path"] == "data/knowledge/origins/manual_docs"
    assert (tmp_path / origin["root_path"]).is_dir()
    with sqlite3.connect(db_path) as connection:
        root_path = connection.execute("SELECT root_path FROM kb_origins WHERE id = ?", (origin["id"],)).fetchone()[0]
    assert root_path == "data/knowledge/origins/manual_docs"


def test_origin_scan_finds_new_file_without_indexing(tmp_path: Path) -> None:
    client, db_path, backend = make_client(tmp_path)
    kb = create_kb(client)
    origin = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Docs", "slug": "docs"}).json()
    (tmp_path / origin["root_path"] / "characters").mkdir(parents=True)
    (tmp_path / origin["root_path"] / "characters" / "cal.md").write_text("# Cal\nJedi survivor.", encoding="utf-8")

    response = client.post(f"/api/knowledge/origins/{origin['id']}/scan")

    assert response.status_code == 200, response.text
    assert response.json()["new_count"] == 1
    assert backend.calls == []
    assert table_count(db_path, "kb_chunks") == 0
    assert table_count(db_path, "kb_embeddings") == 0
    assert table_count(db_path, "kb_chunk_fts") == 0
    sources = client.get(f"/api/knowledge/bases/{kb['id']}/sources").json()
    assert sources[0]["source_type"] == "origin_file"
    assert sources[0]["relative_path"] == "characters/cal.md"
    assert sources[0]["folder_path"] == "characters"
    assert sources[0]["file_status"] == "new"


def test_origin_import_indexes_new_file_with_markdown_metadata(tmp_path: Path) -> None:
    client, db_path, backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    origin = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Docs", "slug": "docs"}).json()
    source_path = tmp_path / origin["root_path"] / "characters" / "cal.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("# Cal Kestis\n\n## Summary\nJedi survivor.", encoding="utf-8")
    client.post(f"/api/knowledge/origins/{origin['id']}/scan")

    response = client.post(f"/api/knowledge/origins/{origin['id']}/import", json={})

    assert response.status_code == 200, response.text
    assert response.json()["imported_count"] == 1
    assert table_count(db_path, "kb_chunks") == 2
    assert table_count(db_path, "kb_embeddings") == 2
    assert table_count(db_path, "kb_chunk_fts") == 2
    source = client.get(f"/api/knowledge/bases/{kb['id']}/sources").json()[0]
    assert source["status"] == "indexed"
    assert source["file_status"] == "ready"
    chunks = client.get(f"/api/knowledge/sources/{source['id']}/chunks").json()["chunks"]
    assert chunks[0]["metadata"]["chunk_title"] == "Cal Kestis"
    assert chunks[0]["metadata"]["path"] == "characters/cal.md"
    assert "Path: characters/cal.md" in backend.calls[-1]["texts"][0]


def test_origin_scan_changed_then_import_reindexes_and_preserves_old_index(tmp_path: Path) -> None:
    client, db_path, _backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    origin = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Docs", "slug": "docs"}).json()
    source_path = tmp_path / origin["root_path"] / "note.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("# Note\nold", encoding="utf-8")
    client.post(f"/api/knowledge/origins/{origin['id']}/scan")
    client.post(f"/api/knowledge/origins/{origin['id']}/import", json={})
    source = client.get(f"/api/knowledge/bases/{kb['id']}/sources").json()[0]
    old_chunk_count = table_count(db_path, "kb_chunks", "source_id = ?", (source["id"],))

    source_path.write_text("# Note\nnew content", encoding="utf-8")
    scanned = client.post(f"/api/knowledge/origins/{origin['id']}/scan")

    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["changed_count"] == 1
    changed = client.get(f"/api/knowledge/sources/{source['id']}").json()
    assert changed["status"] == "indexed"
    assert changed["file_status"] == "changed"
    assert table_count(db_path, "kb_chunks", "source_id = ?", (source["id"],)) == old_chunk_count

    imported = client.post(f"/api/knowledge/origins/{origin['id']}/import", json={})

    assert imported.status_code == 200, imported.text
    ready = client.get(f"/api/knowledge/sources/{source['id']}").json()
    assert ready["status"] == "indexed"
    assert ready["file_status"] == "ready"


def test_origin_scan_missing_keeps_old_index(tmp_path: Path) -> None:
    client, db_path, _backend = make_client(tmp_path)
    kb = create_kb(client, chunk_size=500, chunk_overlap=0)
    origin = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Docs", "slug": "docs"}).json()
    source_path = tmp_path / origin["root_path"] / "note.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("# Note\nold", encoding="utf-8")
    client.post(f"/api/knowledge/origins/{origin['id']}/scan")
    client.post(f"/api/knowledge/origins/{origin['id']}/import", json={})
    source = client.get(f"/api/knowledge/bases/{kb['id']}/sources").json()[0]
    source_path.unlink()

    scanned = client.post(f"/api/knowledge/origins/{origin['id']}/scan")

    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["missing_count"] == 1
    missing = client.get(f"/api/knowledge/sources/{source['id']}").json()
    assert missing["status"] == "indexed"
    assert missing["file_status"] == "missing"
    assert table_count(db_path, "kb_chunks", "source_id = ?", (source["id"],)) == 1
    assert table_count(db_path, "kb_embeddings", "source_id = ?", (source["id"],)) == 1


def test_origin_scan_skips_unsupported_oversize_and_traversal_slug(tmp_path: Path) -> None:
    client, db_path, _backend = make_client(tmp_path)
    kb = create_kb(client)
    client.patch("/api/knowledge/settings", json={"max_source_size_bytes": 1024})
    origin = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Docs", "slug": "docs"}).json()
    root = tmp_path / origin["root_path"]
    root.mkdir(parents=True, exist_ok=True)
    (root / "image.bin").write_bytes(b"\x00\x01")
    (root / "large.txt").write_text("x" * 2048, encoding="utf-8")
    bad_slug = client.post(f"/api/knowledge/bases/{kb['id']}/origins", json={"name": "Abs", "slug": "/tmp"})

    scanned = client.post(f"/api/knowledge/origins/{origin['id']}/scan")

    assert bad_slug.status_code == 422
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["new_count"] == 0
    assert len(scanned.json()["warnings"]) >= 2
    assert table_count(db_path, "kb_sources") == 0
