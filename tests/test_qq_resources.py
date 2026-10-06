"""Global QQ gallery, manual descriptions, favorites and positional deletion."""
from datetime import timedelta
import json

import pytest
from sqlmodel import Session

from ai_workbench.core.attachments import resolve_attachment_uri
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.time import utc_now
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.qq_models import QQMedia, QQMediaAsset, QQBatch
from tests.test_qqbot import qq_client, project, child, configure_execution, ingest, freeze
from tests.test_qq_media import isolated_attachments, prepare_images, image_event, finish_pending, page, reply
from tests.test_qq_image_generation import image_provider, draw, deliveries
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import ok, completion


def gallery(client, **params):
    return ok(client.get("/api/qq/resources", params=params))


def populate(client, state, monkeypatch, **options):
    prepare_images(monkeypatch)
    p, session, _ = configure_execution(client, state, **options)
    ingest(client, state, p, image_event(), 1)
    client.portal.call(finish_pending, state)
    return p, session


def test_global_gallery_and_manual_descriptions(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session = populate(client, state, monkeypatch)
    other = project(client, bot_account="54321")
    other_session = child(client, other)
    data = image_event()
    data["self_id"] = 54321
    ingest(client, state, other, data, 1)
    client.portal.call(finish_pending, state)
    result = gallery(client)
    assert result["total"] == 2 and result["page_size"] == 30
    image = result["items"][0]
    assert image["has_references"] and not image["is_favorite"]
    assert set(image) == {"id", "attachment", "description", "is_favorite", "created_at", "has_references"}
    url = f"/api/qq/resources/{image['id']}"
    description = "A manually edited description longer than twenty characters.\n第二行描述"
    edited = ok(client.patch(url, json={"description": description}))
    assert edited["description"] == description and edited["created_at"] == image["created_at"]
    for current in (session, other_session):
        assert next(s for s in page(client, current)[0]["segments"] if s.get("asset_id") == image["id"])["description"] == description
        assert state.sessions.get_session(current["session_id"]).history_version == 1
    starred = ok(client.patch(url, json={"is_favorite": True}))
    assert starred["description"] == description and starred["created_at"] == image["created_at"]
    assert state.sessions.get_session(session["session_id"]).history_version == 1
    assert gallery(client, favorite="favorites")["total"] == gallery(client, favorite="unfavorited")["total"] == 1
    ok(client.patch(url, json={"description": "  "}))
    assert state.qq.store.update_description(image["id"], "late caption", only_if_empty=True) == set()
    saved = state.qq.store.get(QQMediaAsset, image["id"])
    assert saved.description is None and saved.description_manual
    with Session(state.qq.store.engine) as db:
        state.qq.store.confirm_generated_asset(db, saved, "later generation prompt", session["session_id"])
        db.commit()
    assert state.qq.store.get(QQMediaAsset, image["id"]).description is None


def test_sort_pagination_and_face_exclusion(qq_client, monkeypatch):
    client, state, _ = qq_client
    _, session = populate(client, state, monkeypatch)
    row = page(client, session)[0]
    original = gallery(client)["items"][0]
    created = utc_now()
    ids = []
    for number in range(33):
        attachment = {**original["attachment"], "size": 100 + number // 2}
        asset = state.qq.store.save(QQMediaAsset(sha256=f"fixture-{number}",
            attachment_json=json.dumps(attachment), created_at=created + timedelta(seconds=number // 2)))
        state.qq.store.save(QQMedia(message_id=row["id"], segment_index=100 + number,
            text_start=0, text_end=0, kind="face" if number == 32 else "image", source_json="{}", status="ready", asset_id=asset.id))
        if number != 32:
            ids.append(asset.id)
    first, second = gallery(client, page_size=30), gallery(client, page=2, page_size=30)
    assert first["total"] == 34 and len(second["items"]) == 4
    assert [r["id"] for r in first["items"]] == list(reversed(ids))[:30]
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    ascending = gallery(client, sort="size", order="asc", page_size=100)["items"]
    assert [(r["attachment"]["size"], r["id"]) for r in ascending] == sorted((r["attachment"]["size"], r["id"]) for r in ascending)
    assert gallery(client, page=100)["items"] == []
    for params in ({"page": 0}, {"page_size": 101}, {"sort": "description"}, {"order": "bad"}, {"favorite": "yes"}, {"unknown": "field"}):
        assert client.get("/api/qq/resources", params=params).status_code == 422
    for payload in ({"is_favorite": None}, {"is_favorite": 1}, {"is_favorite": "true"}, {"description": []}, {"sha256": "x"}):
        assert client.patch(f"/api/qq/resources/{original['id']}", json=payload).status_code == 422
    assert client.delete(f"/api/qq/resources/{asset.id}").status_code == 404


def test_favorites_survive_last_reference_and_require_explicit_deletion(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session = populate(client, state, monkeypatch)
    image = gallery(client)["items"][0]
    url = f"/api/qq/resources/{image['id']}"
    ok(client.patch(url, json={"is_favorite": True}))
    asset = state.qq.store.get(QQMediaAsset, image["id"])
    paths = {resolve_attachment_uri(a.uri) for a in (asset.attachment, asset.model_attachment) if a}
    ok(client.delete(f"/api/projects/{p['id']}"))
    retained = gallery(client)["items"]
    assert len(retained) == 1 and not retained[0]["has_references"]
    assert all(path.is_file() for path in paths)
    state.qq.media.cleanup({path.name for path in paths})
    assert all(path.is_file() for path in paths)
    result = client.patch(url, json={"is_favorite": False})
    assert result.status_code == 409 and result.json()["error"]["code"] == "QQ_RESOURCE_UNREFERENCED"
    assert gallery(client)["items"][0]["is_favorite"]
    ok(client.delete(url))
    assert gallery(client)["total"] == 0 and all(not path.exists() for path in paths)
    assert client.delete(url).status_code == 404


def test_shared_deletion_is_positional_and_reacquisition_is_new(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session = populate(client, state, monkeypatch)
    image = gallery(client)["items"][0]
    other = child(client, p, "9988")
    data = image_event(2)
    data["group_id"] = 9988
    ingest(client, state, p, data, 2)
    client.portal.call(finish_pending, state)
    batch = freeze(state, session, 6)
    batch.status = "running"
    state.qq.store.save(batch)
    url = f"/api/qq/resources/{image['id']}"
    assert client.delete(url).status_code == 409
    batch.status = "cancelled"
    state.qq.store.save(batch)
    ok(client.delete(url))
    for current in (session, other):
        segments = page(client, current)[0]["segments"]
        assert [s["type"] for s in segments] == ["text", "image", "text", "image", "text"]
        deleted = next(s for s in segments if s.get("status") == "deleted")
        assert deleted["label"] == "[图片]" and deleted["attachment"] is None and deleted["description"] is None
        assert state.sessions.get_session(current["session_id"]).history_version == 1
    ingest(client, state, p, image_event(3), 10)
    client.portal.call(finish_pending, state)
    assert gallery(client)["total"] == 2 and image["id"] not in {r["id"] for r in gallery(client)["items"]}
    assert any(s.get("status") == "deleted" for s in page(client, session)[1]["segments"])


def test_deletion_preserves_recorded_snapshots_but_removes_future_image_context(qq_client, monkeypatch):
    client, state, upstream = qq_client
    _, session = populate(client, state, monkeypatch, image_input_enabled=True)
    image = gallery(client)["items"][0]
    ok(client.patch(f"/api/qq/resources/{image['id']}", json={"description": "deleted-description"}))
    reply(upstream)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    assert state.qq.store.get(QQBatch, batch.id).status == "done"
    asset = state.qq.store.get(QQMediaAsset, image["id"])
    model_path = resolve_attachment_uri(asset.model_attachment.uri)
    snapshot_ids = state.runs.context_attachment_ids({batch.run_id})
    assert model_path.name in snapshot_ids
    ok(client.delete(f"/api/qq/resources/{image['id']}"))
    assert model_path.is_file() and state.runs.context_attachment_ids({batch.run_id}) == snapshot_ids
    context = build_qq_context(state.qq.store, state.messages, session['session_id'], "next", ContextPolicy(), None)
    assert "deleted-description" not in context.model_dump_json() and "[图片]" in context.model_dump_json()
    ok(client.delete(f"/api/runs/{batch.run_id}"))
    assert not model_path.exists()


def test_deleted_generated_images_do_not_inject_original_prompts(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=1,
        image_generation_model_profile_id=image_provider.profile["id"])
    upstream.turns = [completion(draw("secret drawing prompt"))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == "DONE"
    image = gallery(client)["items"][0]
    ok(client.delete(f"/api/qq/resources/{image['id']}"))
    delivery = deliveries(client, session)[0]
    assert delivery["status"] == "sent" and delivery["asset_id"] is None and delivery["attachment"] is None
    context = build_qq_context(state.qq.store, state.messages, session['session_id'], "next", ContextPolicy(), None)
    assert "secret drawing prompt" not in context.model_dump_json()
    assert any(m.get("role") == "assistant" and m.get("content") == "[图片]" for m in context.messages)


def test_resources_migration_preserves_files_and_repeated_upgrades(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'resources.db'}")
    migrations.upgrade(engine, migrations.QQ_ICEBREAKER_REVISION)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO qq_media_assets (id, sha256, attachment_json, updated_at) VALUES (99, 'deleted', '{}', CURRENT_TIMESTAMP)")
        db.exec_driver_sql("DELETE FROM qq_media_assets")
        db.exec_driver_sql("INSERT INTO qq_media_assets (id, sha256, attachment_json, description, updated_at) VALUES (12, 'retained', '{}', 'existing', CURRENT_TIMESTAMP)")
    files = [tmp_path / name for name in ("models/model.bin", "attachments/image.png", "runtimes/worker.exe")]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"retained")
    migrations.upgrade(engine)
    migrations.upgrade(engine)
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO qq_media_assets (sha256, attachment_json, updated_at) VALUES ('new', '{}', CURRENT_TIMESTAMP)")
        assert db.exec_driver_sql("SELECT description FROM qq_media_assets WHERE id = 12").scalar_one() == 'existing'
        row = db.exec_driver_sql("SELECT id, is_favorite, description_manual, created_at FROM qq_media_assets WHERE sha256 = 'new'").one()
        assert row[0] > 99 and row[1:3] == (0, 0) and row[3]
    assert all(path.read_bytes() == b"retained" for path in files)
