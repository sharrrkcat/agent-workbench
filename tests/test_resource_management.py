import base64

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.message_parts import make_image_part
from ai_workbench.core.schema.run import RunStatus
from tests.model_fixtures import MockOpenAI, configure_model


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def resources(request, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "data/attachments"))
    upstream = MockOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param, database_url=f"sqlite:///{tmp_path / 'resources.db'}",
                     adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream


def base(client):
    model = configure_model(client, kind="embedding", alias="resource-embedding", parameters={"dimensions": 2})
    return ok(client.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": model["id"]})), model


def test_worldbook_edit_validation_order_and_match(resources):
    client, _ = resources
    book = ok(client.post("/api/worldbooks", json={"name": "World"}))
    path = f"/api/worldbooks/{book['id']}"
    first = ok(client.post(path + "/entries", json={"name": "One", "content": "beta", "keywords_text": "alpha"}))
    second = ok(client.post(path + "/entries", json={"name": "Two", "content": "end", "keywords_text": "beta"}))
    for patch in [{"keywords_text": "["}, {"name": " "}, {"content": ""}, {"enabled": None}]:
        response = client.patch(f"/api/worldbook-entries/{first['id']}", json=patch)
        assert response.status_code == 422, response.text
        assert ok(client.get(f"/api/worldbook-entries/{first['id']}")) == first
    assert client.patch(path, json={"name": " "}).status_code == 422
    assert ok(client.get(path))["name"] == "World"
    ids = [second["id"], first["id"]]
    assert [item["id"] for item in ok(client.patch(path + "/entries/reorder", json={"entry_ids": ids}))["entries"]] == ids
    assert client.patch(path + "/entries/reorder", json={"entry_ids": ids + ids[:1]}).status_code == 422
    ok(client.patch("/api/worldbook/settings", json={"worldbook_recursion_depth": 1, "worldbook_case_sensitive": True}))
    match = ok(client.post("/api/worldbooks/match-test", json={"text": "alpha", "worldbook_ids": [book["id"]]}))
    assert [item["entry_id"] for item in match["results"]] == ids
    assert match["results"][0]["matched_by_recursion"] is True
    ok(client.delete(f"/api/worldbook-entries/{first['id']}"))
    assert ok(client.get(path))["entry_count"] == 1


def test_attachment_source_preview_reindex_and_reference_protection(resources):
    client, _ = resources
    kb, _ = base(client)
    attachment = ok(client.post("/api/attachments", files={"file": ("facts.md", b"# Facts\nalpha fact", "text/markdown")}))
    source = ok(client.post(f"/api/knowledge/bases/{kb['id']}/sources", json={"source_type": "attachment_text", "attachment_id": attachment["uri"], "title": "Facts"}))
    source_path = f"/api/knowledge/sources/{source['source_id']}"
    assert "id" not in source and source["chunks"] == 1
    assert ok(client.get(source_path + "/preview"))["content"] == "# Facts\nalpha fact"
    chunk = ok(client.get(source_path + "/chunks"))["chunks"][0]
    assert chunk["content"] == "# Facts\nalpha fact" and chunk["char_start"] == 0
    assert ok(client.post(source_path + "/reindex"))["source_id"] == source["source_id"]
    attachment_id = attachment["uri"].rsplit("/", 1)[-1]
    assert client.delete(f"/api/attachments/{attachment_id}").status_code == 409
    assert ok(client.post("/api/data/attachments/scan-orphans"))["orphan_count"] == 0
    assert ok(client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True}))["deleted_count"] == 0
    ok(client.delete(source_path))
    assert ok(client.get(f"/api/knowledge/bases/{kb['id']}"))["index_status"] == "empty"
    assert client.get(f"/api/attachments/{attachment_id}").status_code == 200
    assert ok(client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True}))["deleted_count"] == 1


def test_index_invalidation_stays_until_all_sources_are_rebuilt(resources):
    client, upstream = resources
    kb, model = base(client)
    path = f"/api/knowledge/bases/{kb['id']}"
    sources = [ok(client.post(path + "/sources", json={"title": title, "text": title}))["source_id"] for title in ["alpha", "beta"]]
    ok(client.patch(f"/api/models/profiles/{model['id']}", json={"parameters": {"dimensions": 2, "normalize": False}}))
    ok(client.post(f"/api/knowledge/sources/{sources[0]}/reindex"))
    assert ok(client.get(path))["index_status"] == "needs_reindex"
    assert ok(client.post("/api/knowledge/search", json={"query": "alpha", "knowledge_base_ids": [kb["id"]]}))["results"] == []
    upstream.failure = 500
    results = ok(client.post(path + "/reindex"))["sources"]
    assert all(item["status"] == "failed" for item in results)
    assert ok(client.get(path))["index_status"] == "needs_reindex"
    upstream.failure = None
    ok(client.post(f"/api/knowledge/sources/{sources[1]}/reindex"))
    assert ok(client.get(path))["index_status"] == "ready"
    ok(client.delete(f"/api/knowledge/sources/{sources[0]}"))
    ok(client.delete(f"/api/knowledge/sources/{sources[1]}"))
    assert ok(client.get(path))["index_status"] == "empty"


def test_full_attachment_indexing_obeys_knowledge_limits(resources):
    client, _ = resources
    kb, _ = base(client)
    ok(client.patch("/api/knowledge/settings", json={"default_chunk_size": 10000, "default_chunk_overlap": 0, "max_total_index_chars_per_source": 2000000}))
    content = b"a" * (1024 * 1024 + 100) + b"TAIL"
    upload = ok(client.post("/api/attachments", files={"file": ("large.txt", content, "text/plain")}))
    payload = {"source_type": "attachment_text", "attachment_id": upload["uri"]}
    source = ok(client.post(f"/api/knowledge/bases/{kb['id']}/sources", json=payload))
    chunks = ok(client.get(f"/api/knowledge/sources/{source['source_id']}/chunks"))["chunks"]
    assert "".join(chunk["content"] for chunk in chunks) == content.decode()
    assert ok(client.get(f"/api/knowledge/sources/{source['source_id']}/preview"))["truncated"]
    ok(client.patch("/api/knowledge/settings", json={"max_source_size_bytes": 1024}))
    assert client.post(f"/api/knowledge/bases/{kb['id']}/sources", json=payload).status_code == 422
    for data in [b"", b"  \n", b"\xff\xfe"]:
        upload = ok(client.post("/api/attachments", files={"file": ("bad.txt", data, "text/plain")}))
        assert client.post(f"/api/knowledge/bases/{kb['id']}/sources", json={"source_type": "attachment_text", "attachment_id": upload["uri"]}).status_code == 422
    assert client.patch("/api/knowledge/settings", json={"default_chunk_overlap": 10000}).status_code == 422


def test_orphan_cleanup_preserves_message_persona_and_running_snapshot_references(resources):
    client, _ = resources
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=")
    ids = [ok(client.post("/api/attachments", files={"file": ("avatar.png", png, "image/png")}))["uri"].rsplit("/", 1)[-1] for _ in range(4)]
    ok(client.post("/api/personas", json={"name": "Avatar owner", "avatar_attachment_id": ids[0]}))
    session = ok(client.post("/api/sessions", json={}))
    state = client.app.state.runtime_state
    state.messages.add_message(session["session_id"], role="user", parts=[make_image_part(attachment_id=ids[1])])
    run = state.runs.create_run(kind="chat", persona_id=session["current_persona_id"], session_id=session["session_id"], config_snapshot={"avatar_attachment_id": ids[2]})
    state.runs.update_status(run.run_id, RunStatus.RUNNING)
    orphans = ok(client.post("/api/data/attachments/scan-orphans"))["orphans"]
    assert [item["id"] for item in orphans] == [ids[3]]
    assert ok(client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True}))["deleted_count"] == 1
    for attachment_id in ids[:3]:
        assert client.get(f"/api/attachments/{attachment_id}").content == png
        assert client.delete(f"/api/attachments/{attachment_id}").status_code == 409
    state.runs.update_status(run.run_id, RunStatus.DONE)
    assert ok(client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True}))["deleted_count"] == 1
