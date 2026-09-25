import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession

from ai_workbench.api.main import create_app
from ai_workbench.core.personas import PersonaStore
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID, USER_PERSONA_ID
from ai_workbench.core.settings import AppSettings
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import AppMetadataRecord, KnowledgeBaseRecord, MessageRecord, RunRecord, RuntimeInstallationRecord, WorldbookRecord
from ai_workbench.db.stores import SqlAppSettingsStore
from tests.model_fixtures import MockOpenAI, configure_model


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def client_pair(tmp_path, request, monkeypatch):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    upstream = MockOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param, database_url=f"sqlite:///{tmp_path / 'personas.db'}",
                     adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_collections_are_isolated_and_protected_records_stay_editable(client_pair):
    client, _ = client_pair
    assert [(p["name"], p["collection"], p["is_protected"]) for p in ok(client.get("/api/personas"))] == [
        ("Cogita", "agent", True), ("User", "user", True),
    ]
    for collection in ("roleplay_user", "character"):
        assert ok(client.get("/api/personas", params={"collection": collection})) == []
    for collection in ("agent", "roleplay_user", "character"):
        persona = ok(client.post("/api/personas", json={"name": "Same name", "collection": collection}))
        assert persona["collection"] == collection and persona["is_protected"] is False
        assert persona in ok(client.get("/api/personas", params={"collection": collection}))
        assert client.patch(f"/api/personas/{persona['id']}", json={"collection": "agent"}).status_code == 422
        assert client.patch(f"/api/personas/{persona['id']}", json={"is_protected": True}).status_code == 422
        ok(client.delete(f"/api/personas/{persona['id']}"))
    for body in ({"name": "Missing collection"}, {"name": "Extra user", "collection": "user"},
                 {"name": "Unknown", "collection": "unknown"}):
        assert client.post("/api/personas", json=body).status_code == 422
    assert client.get("/api/personas", params={"collection": "unknown"}).status_code == 422
    for persona_id in (USER_PERSONA_ID, COGITA_PERSONA_ID):
        renamed = ok(client.patch(f"/api/personas/{persona_id}", json={"name": "Changed", "system_prompt": "Edited"}))
        assert renamed["name"] == "Changed" and renamed["is_protected"]
        assert client.delete(f"/api/personas/{persona_id}").status_code == 409
    assert len(ok(client.get("/api/personas", params={"collection": "user"}))) == 1
    assert ok(client.post("/api/sessions", json={}))["persona_id"] == COGITA_PERSONA_ID


def test_resource_permissions_and_dormant_roleplay_collections(client_pair):
    client, upstream = client_pair
    configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embed")
    base = ok(client.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": embedding["id"]}))
    book = ok(client.post("/api/worldbooks", json={"name": "World"}))
    ok(client.post(f"/api/worldbooks/{book['id']}/entries", json={"name": "Always", "content": "ROLEPLAY_ONLY_LORE", "activation_mode": "always"}))
    session = ok(client.post("/api/sessions", json={}))
    path = f"/api/sessions/{session['session_id']}"
    for persona_id in (USER_PERSONA_ID, COGITA_PERSONA_ID):
        ok(client.patch(f"/api/personas/{persona_id}/knowledge-bases", json={"knowledge_base_ids": [base["id"]]}))
        assert client.get(f"/api/personas/{persona_id}/worldbooks").status_code == 422
        assert client.patch(f"/api/personas/{persona_id}/worldbooks", json={"worldbook_ids": [book["id"]]}).status_code == 422
    for collection in ("roleplay_user", "character"):
        persona = ok(client.post("/api/personas", json={"collection": collection, "name": "Roleplay", "system_prompt": "ROLEPLAY_ONLY_PROMPT"}))
        ok(client.patch(f"/api/personas/{persona['id']}/worldbooks", json={"worldbook_ids": [book["id"]]}))
        assert client.get(f"/api/personas/{persona['id']}/knowledge-bases").status_code == 422
        assert client.patch(f"/api/personas/{persona['id']}/knowledge-bases", json={"knowledge_base_ids": [base["id"]]}).status_code == 422
        assert client.post("/api/sessions", json={"persona_id": persona["id"]}).status_code == 422
        assert client.patch(path, json={"persona_id": persona["id"]}).status_code == 422
    assert client.patch(path, json={"persona_id": USER_PERSONA_ID}).status_code == 422
    for suffix in ("personas", "worldbooks"):
        assert client.get(path + "/" + suffix).status_code == 404
        assert client.patch(path + "/" + suffix, json={}).status_code == 404
    assert client.post("/api/worldbooks/match-test", json={"session_id": session["session_id"]}).status_code == 422
    assert ok(client.post("/api/worldbooks/match-test", json={"worldbook_ids": [book["id"]]}))["matched_count"] == 1
    result = ok(client.post(path + "/messages", json={"content": "hello"}))
    assert result["success"]
    assert "ROLEPLAY_ONLY" not in json.dumps(upstream.calls)
    assert "worldbook_ids" not in result["session"]["effective"]
    assert client.delete(f"/api/worldbooks/{book['id']}").status_code == 409
    general = ok(client.get("/api/settings/general"))
    for key, value in (("core_memory_content", "Old"), ("core_memory_enabled", False), ("group_transcript_system_instruction", "Old")):
        assert key not in general
        assert client.patch("/api/settings/general", json={key: value}).status_code == 422


def test_session_temperature_only_overrides_the_model_when_set(client_pair):
    client, upstream = client_pair
    profile = configure_model(client, parameters={"temperature": 0.4, "top_p": 0.8, "max_tokens": 77, "seed": 5})
    session = ok(client.post("/api/sessions", json={"model_profile_id": profile["id"]}))
    path = f"/api/sessions/{session['session_id']}"
    for value in ({"top_p": 0.2}, {"max_tokens": 5}, {"presence_penalty": 0}, {"frequency_penalty": 0}, {"seed": 0}, {"stop": "end"}):
        assert client.patch(path, json={"generation": value}).status_code == 422
        assert client.post("/api/sessions", json={"generation": value}).status_code == 422
    for generation, expected in (({"temperature": 0}, 0), ({"temperature": None}, 0.4), ({"temperature": 2}, 2), ({}, 0.4)):
        updated = ok(client.patch(path, json={"generation": generation}))
        assert updated["generation"] == {key: value for key, value in generation.items() if value is not None}
        assert ok(client.patch(path, json={"harness_enabled": False}))["generation"] == updated["generation"]
        ok(client.post(path + "/messages", json={"content": "hello"}))
        assert {key: upstream.calls[-1][key] for key in ("temperature", "top_p", "max_tokens", "seed")} == {
            "temperature": expected, "top_p": 0.8, "max_tokens": 77, "seed": 5,
        }


def test_user_identity_is_live_and_does_not_retain_old_avatar_snapshots(client_pair):
    client, _ = client_pair
    configure_model(client)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=")
    avatars = [ok(client.post("/api/attachments", files={"file": ("avatar.png", png, "image/png")}))["uri"].removeprefix("local://attachments/") for _ in range(2)]
    user_path = f"/api/personas/{USER_PERSONA_ID}"
    ok(client.patch(user_path, json={"name": "Before", "avatar_attachment_id": avatars[0], "system_prompt": "PRIVATE_USER_CONTEXT"}))
    keeper = ok(client.post("/api/personas", json={"name": "Shared", "collection": "character", "avatar_attachment_id": avatars[0]}))
    sessions = [ok(client.post("/api/sessions", json={})) for _ in range(2)]
    path = f"/api/sessions/{sessions[0]['session_id']}"
    result = ok(client.post(path + "/messages", json={"content": "hello"}))
    assert "PRIVATE_USER_CONTEXT" not in json.dumps(result)
    run_id = result["run"]["run_id"]
    snapshot = client.app.state.runtime_state.runs.get_config_snapshot(run_id)
    assert snapshot["user_persona_prompt"] == "PRIVATE_USER_CONTEXT"
    history = ok(client.get(path + "/messages"))
    assert history[0]["speaker_id"] == USER_PERSONA_ID
    assert "speaker_avatar_attachment_id" not in history[0]["metadata"]
    ok(client.patch(user_path, json={"name": "After", "avatar_attachment_id": avatars[1]}))
    for session in ok(client.get("/api/sessions")):
        assert session["user_persona"] == {"id": USER_PERSONA_ID, "name": "After", "avatar_attachment_id": avatars[1]}
    assert ok(client.get(path + "/messages")) == history
    for session in sessions:
        assert ok(client.get(f"/api/sessions/{session['session_id']}"))["user_persona"]["name"] == "After"
    assert client.get(f"/api/attachments/{avatars[0]}").status_code == 200
    ok(client.delete(f"/api/personas/{keeper['id']}"))
    assert client.get(f"/api/attachments/{avatars[0]}").status_code == 404
    ok(client.patch(user_path, json={"avatar_attachment_id": None}))
    assert client.get(f"/api/attachments/{avatars[1]}").status_code == 404


def test_deleted_historical_agent_blocks_retry_before_pruning(client_pair):
    client, _ = client_pair
    configure_model(client)
    agent = ok(client.post("/api/personas", json={"name": "Old", "collection": "agent"}))
    session = ok(client.post("/api/sessions", json={"persona_id": agent["id"]}))
    path = f"/api/sessions/{session['session_id']}"
    first = ok(client.post(path + "/messages", json={"content": "first"}))
    ok(client.patch(path, json={"persona_id": COGITA_PERSONA_ID}))
    ok(client.post(path + "/messages", json={"content": "second"}))
    ok(client.delete(f"/api/personas/{agent['id']}"))
    history = ok(client.get(path + "/messages"))
    assert client.post(f"/api/runs/{first['run']['run_id']}/retry").status_code == 404
    assert ok(client.get(path + "/messages")) == history


def test_persona_revision_resets_only_affected_state_and_keeps_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    migrations.upgrade(engine, migrations.DIRECTORY_MODELS_REVISION)
    profile = ModelProfileStore(engine).create(ModelProfile(name="Keep model", alias="keep", kind="embedding", model_ref="manual"))
    old_persona = "00000000-0000-4000-8000-000000000001"
    with engine.begin() as db:
        db.execute(text("""INSERT INTO sessionrecord
            (session_id, title, context_mode, current_persona_id, context_policy_json, generation_json,
             harness_enabled, tools_allowed_json, title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('old', 'Old', 'group_transcript', :persona, '{}', :generation, 0, '[]', 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"persona": old_persona, "generation": '{"seed":5}'})
        db.execute(text("INSERT INTO session_personas VALUES ('old', :persona, 0, 1)"), {"persona": old_persona})
    with DbSession(engine) as db:
        db.add(AppMetadataRecord(key="app_settings", value='{"core_memory_content":"Discard","core_memory_enabled":false}'))
        db.add(AppMetadataRecord(key="sentinel", value="preserved"))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id=profile.id))
        db.add(WorldbookRecord(id="book", name="Keep"))
        db.add(RuntimeInstallationRecord(id="local", version="1.0.0", state="installed", manifest_sha256="a" * 64))
        db.add(MessageRecord(message_id="message", session_id="old", role="user"))
        db.add(RunRecord(run_id="run", session_id="old", persona_id=old_persona, kind="chat", status="WAITING_FOR_USER",
                         config_snapshot_json='{"old":true}', harness_state_json='{"old":true}'))
        db.commit()
    affected = {"personas", "sessionrecord", "session_personas", "session_worldbook_bindings", "persona_knowledge_bindings",
                "persona_worldbook_bindings", "session_knowledge_bindings", "messagerecord", "runrecord", "runsteprecord", "runeventrecord", "appmetadatarecord", "alembic_version"}
    def preserved_rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
                    for name in migrations.inspect_schema(engine).tables if name not in affected}
    before = preserved_rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "attachments", "runtimes", "knowledge", "logs", "pet")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"owned file")
    before_files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    migrations.upgrade(engine, migrations.PERSONA_COLLECTIONS_REVISION)
    schema = migrations.inspect_schema(engine)
    assert not {"session_personas", "session_worldbook_bindings"}.intersection(schema.tables)
    assert not {"context_mode", "current_persona_id"}.intersection(schema.columns["sessionrecord"])
    assert "persona_id" in schema.columns["sessionrecord"]
    assert preserved_rows() == before
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == before_files
    assert SqlAppSettingsStore(engine).get() == AppSettings()
    personas = PersonaStore(engine)
    assert [(p.name, p.collection) for p in personas.list()] == [("Cogita", "agent"), ("User", "user")]
    assert personas.get(USER_PERSONA_ID).system_prompt == ""
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert db.exec_driver_sql("SELECT value FROM appmetadatarecord WHERE key='sentinel'").scalar() == "preserved"
        for table in ("sessionrecord", "messagerecord", "runrecord"):
            assert db.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0
    with pytest.raises(IntegrityError), engine.begin() as db:
        db.execute(text("""INSERT INTO personas VALUES ('extra', 'user', 'Extra', NULL, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
    personas.update(COGITA_PERSONA_ID, {"name": "Edited"})
    migrations.upgrade(engine, migrations.PERSONA_COLLECTIONS_REVISION)
    assert migrations.inspect_schema(engine) == schema
    assert personas.get(COGITA_PERSONA_ID).name == "Edited"
    engine.dispose()
