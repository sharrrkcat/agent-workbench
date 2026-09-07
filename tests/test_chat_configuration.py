import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session as DbSession

from ai_workbench.api.main import create_app
from ai_workbench.core.harness.schema import ToolSpec
from ai_workbench.core.schema.persona import CHAT_PERSONA_ID
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import (
    AppMetadataRecord, KnowledgeBaseRecord, MessageRecord, ModelProfileRecord,
    RunEventRecord, RunRecord, RunStepRecord, WorldbookRecord,
)
from tests.model_fixtures import MockOpenAI, configure_model


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def client_pair(tmp_path, request):
    upstream = MockOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param,
                     database_url=f"sqlite:///{tmp_path / 'app.db'}", adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_strict_persona_and_session_configuration(client_pair):
    client, _ = client_pair
    persona = ok(client.post("/api/personas", json={"name": "Minimal", "system_prompt": "Prompt"}))
    assert set(persona) == {"id", "name", "avatar_attachment_id", "system_prompt", "created_at", "updated_at"}
    for field, value in {"model_profile_id": None, "generation": {}, "context_policy": {"mode": "none"},
                         "harness_enabled": True, "tools_allowed": []}.items():
        assert client.post("/api/personas", json={"name": "Invalid", field: value}).status_code == 422
        assert client.patch(f"/api/personas/{persona['id']}", json={field: value}).status_code == 422
    session = ok(client.post("/api/sessions", json={}))
    path = f"/api/sessions/{session['session_id']}"
    assert session["generation"] == {} and session["context_policy"]["mode"] == "session"
    assert session["harness_enabled"] is False
    for field in ("generation", "context_policy", "harness_enabled", "tools_allowed"):
        assert client.post("/api/sessions", json={field: None}).status_code == 422
        assert client.patch(path, json={field: None}).status_code == 422
    for field in ("knowledge_binding_mode", "worldbook_binding_mode"):
        assert client.post("/api/sessions", json={field: "inherit"}).status_code == 422
        assert client.patch(path, json={field: "override"}).status_code == 422
    assert client.patch(path, json={"context_policy": {"mode": "none", "include_system_prompt": False}}).status_code == 422
    for suffix in ("knowledge-bases", "worldbooks"):
        assert client.patch(path + "/" + suffix, json={"mode": "inherit"}).status_code == 422
        assert client.patch(path + "/" + suffix, json={}).status_code == 422
    assert ok(client.get(path)) == session


def test_catalog_defaults_and_session_tool_switches(client_pair):
    client, upstream = client_pair
    configure_model(client, capabilities={"tools": True})
    catalog = ok(client.get("/api/tools"))
    names = [tool["name"] for tool in catalog]
    session = ok(client.post("/api/sessions", json={}))
    path = f"/api/sessions/{session['session_id']}"
    assert session["tools_allowed"] == names == session["effective"]["tools_allowed"]
    assert not session["harness_enabled"]
    ok(client.post(path + "/messages", json={"content": "hello"}))
    assert "tools" not in upstream.calls[-1]
    direct = ok(client.post("/api/tools/base64_encode/call", json={"session_id": session["session_id"], "arguments": {"value": "hi"}}))
    assert direct["run"]["status"] == "DONE"
    enabled = ok(client.patch(path, json={"harness_enabled": True}))
    assert enabled["tools_allowed"] == names
    ok(client.post(path + "/messages", json={"content": "tools"}))
    assert [tool["function"]["name"] for tool in upstream.calls[-1]["tools"]] == names
    subset = [name for name in names if name != "base64_encode"]
    ok(client.patch(path, json={"tools_allowed": subset}))
    for enabled in (False, True):
        assert ok(client.patch(path, json={"harness_enabled": enabled}))["tools_allowed"] == subset
        rejected = client.post("/api/tools/base64_encode/call", json={"session_id": session["session_id"], "arguments": {"value": "x"}})
        assert rejected.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    ok(client.patch(path, json={"tools_allowed": []}))
    ok(client.post(path + "/messages", json={"content": "no tools"}))
    assert "tools" not in upstream.calls[-1]
    assert ok(client.post("/api/sessions", json={"tools_allowed": []}))["tools_allowed"] == []

    async def later_tool(_arguments, _context):
        return {}

    client.app.state.runtime_state.tool_registry.register(ToolSpec("later_tool", "Later", {"type": "object"}, later_tool))
    assert ok(client.get(path))["tools_allowed"] == []
    assert "later_tool" in ok(client.post("/api/sessions", json={}))["tools_allowed"]


def test_new_sessions_store_the_default_or_explicit_model(client_pair):
    client, upstream = client_pair
    first = configure_model(client, alias="first", name="A first")
    preferred = configure_model(client, alias="preferred", name="B preferred", model_ref="other")
    session = ok(client.post("/api/sessions", json={}))
    path = f"/api/sessions/{session['session_id']}"
    assert session["model_profile_id"] == preferred["id"] == session["effective"]["model_profile_id"]
    assert session["effective"]["model_source"] == "session"
    health = ok(client.get("/api/health/details"))["llm"]
    assert health["status"] == "ok" and health["model_profile_id"] == preferred["id"]
    assert client.app.state.runtime_state.sessions.get_session(session["session_id"]).model_profile_id == preferred["id"]
    assert ok(client.post("/api/sessions", json={"model_profile_id": first["id"]}))["model_profile_id"] == first["id"]
    assert ok(client.post("/api/sessions", json={"model_profile_id": None}))["model_profile_id"] == preferred["id"]
    assert upstream.calls == []

    for default_id in (first["id"], None):
        ok(client.patch("/api/models/settings", json={"default_model_profile_id": default_id}))
        saved = ok(client.get(path))
        assert saved["model_profile_id"] == preferred["id"] == saved["effective"]["model_profile_id"]
        assert ok(client.post("/api/sessions", json={}))["model_profile_id"] == first["id"]
    assert ok(client.post(path + "/messages", json={"content": "use the saved model"}))["success"]
    assert upstream.calls[-1]["model"] == "other"


def test_new_session_model_fallback_skips_disabled_and_other_kinds(client_pair):
    client, upstream = client_pair
    embedding = configure_model(client, kind="embedding", alias="embedding", name="A embedding")
    disabled = configure_model(client, alias="disabled", name="B disabled")
    later = configure_model(client, alias="later", name="D later")
    first = configure_model(client, alias="first", name="C first")
    ok(client.patch(f"/api/models/profiles/{disabled['id']}", json={"enabled": False}))
    listed = ok(client.get("/api/models/profiles", params={"kind": "llm"}))
    assert [profile["id"] for profile in listed] == [disabled["id"], first["id"], later["id"]]
    for default_id in (None, "missing", disabled["id"], embedding["id"]):
        # A saved default may become unavailable after its profile changes.
        client.app.state.runtime_state.model_settings.patch({"default_model_profile_id": default_id})
        session = ok(client.post("/api/sessions", json={}))
        assert session["model_profile_id"] == first["id"] == session["effective"]["model_profile_id"]
        assert ok(client.get("/api/models/settings"))["default_model_profile_id"] == default_id
        health = ok(client.get("/api/health/details"))["llm"]
        assert health["status"] == "ok" and health["model_profile_id"] == first["id"]
    count = len(ok(client.get("/api/sessions")))
    for profile_id, error in (("missing", "MODEL_NOT_FOUND"), ("", "MODEL_NOT_FOUND"),
                              (disabled["id"], "MODEL_UNAVAILABLE"), (embedding["id"], "MODEL_KIND_MISMATCH")):
        response = client.post("/api/sessions", json={"model_profile_id": profile_id})
        assert response.status_code >= 400 and response.json()["error"]["code"] == error
    assert len(ok(client.get("/api/sessions"))) == count
    assert upstream.calls == []


def test_sessions_without_models_remain_unselected_until_an_explicit_choice(client_pair):
    client, upstream = client_pair
    empty = ok(client.post("/api/sessions", json={}))
    assert empty["model_profile_id"] is None and empty["effective"]["model_profile_id"] is None
    assert ok(client.get("/api/health/details"))["llm"] == {
        "status": "degraded", "error": "No enabled chat model is configured."}
    configure_model(client, kind="embedding", alias="embedding")
    model = configure_model(client)
    ok(client.patch(f"/api/models/profiles/{model['id']}", json={"enabled": False}))
    session = ok(client.post("/api/sessions", json={}))
    path = f"/api/sessions/{session['session_id']}"
    assert session["model_profile_id"] is None and session["effective"]["model_profile_id"] is None
    assert ok(client.get("/api/health/details"))["llm"]["status"] == "degraded"
    ok(client.patch(f"/api/models/profiles/{model['id']}", json={"enabled": True}))
    assert ok(client.get(path))["effective"]["model_profile_id"] is None
    assert ok(client.post("/api/sessions", json={}))["model_profile_id"] == model["id"]
    failed = ok(client.post(path + "/messages", json={"content": "no model selected"}))
    assert failed["run"]["error_code"] == "MODEL_NOT_CONFIGURED" and upstream.calls == []
    chosen = ok(client.patch(path, json={"model_profile_id": model["id"]}))
    assert chosen["effective"]["model_profile_id"] == model["id"]
    cleared = ok(client.patch(path, json={"model_profile_id": None}))
    assert cleared["model_profile_id"] is None and cleared["effective"]["model_profile_id"] is None


@pytest.mark.parametrize("context_mode", ["single_assistant", "group_transcript"])
def test_prompt_is_always_included_once_in_every_history_mode(client_pair, context_mode):
    client, upstream = client_pair
    configure_model(client)
    persona = ok(client.post("/api/personas", json={"name": "Speaker", "system_prompt": "FIXED_PERSONA_PROMPT"}))
    session = ok(client.post("/api/sessions", json={"current_persona_id": persona["id"],
        "personas": [{"persona_id": persona["id"]}], "context_mode": context_mode}))
    path = f"/api/sessions/{session['session_id']}"
    history = ok(client.post(path + "/messages", json={"content": "history"}))["messages"][0]
    for mode in ("none", "current_message", "recent_messages", "session", "selected_message"):
        ok(client.patch(path, json={"context_policy": {"mode": mode}}))
        result = ok(client.post(path + "/messages", json={"content": "current", "source_message_id": history["message_id"]}))
        assert result["success"]
        assert sum(message["content"].count("FIXED_PERSONA_PROMPT") for message in upstream.calls[-1]["messages"]) == 1
        assert upstream.calls[-1]["messages"][0] == {"role": "system", "content": "FIXED_PERSONA_PROMPT"}
    ok(client.patch(f"/api/personas/{persona['id']}", json={"system_prompt": ""}))
    ok(client.post(path + "/messages", json={"content": "empty prompt", "source_message_id": history["message_id"]}))
    assert "FIXED_PERSONA_PROMPT" not in json.dumps(upstream.calls[-1])


def test_ordered_additions_deduplicate_and_follow_only_the_current_speaker(client_pair):
    client, upstream = client_pair
    configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embedding")
    bases, books = [], []
    for name in ("first", "second", "extra", "outside"):
        base = ok(client.post("/api/knowledge/bases", json={"name": name, "embedding_model_profile_id": embedding["id"]}))
        ok(client.post(f"/api/knowledge/bases/{base['id']}/sources", json={"title": name, "text": f"artifact {name}", "source_type": "pasted_text"}))
        book = ok(client.post("/api/worldbooks", json={"name": name}))
        ok(client.post(f"/api/worldbooks/{book['id']}/entries", json={"name": name, "content": f"WORLD_{name}", "activation_mode": "always"}))
        bases.append(base["id"])
        books.append(book["id"])
    role = ok(client.post("/api/personas", json={"name": "First"}))
    session = ok(client.post("/api/sessions", json={"current_persona_id": role["id"],
        "personas": [{"persona_id": role["id"]}, {"persona_id": CHAT_PERSONA_ID}], "context_mode": "group_transcript"}))
    path = f"/api/sessions/{session['session_id']}"
    for suffix, field, ids in (("knowledge-bases", "knowledge_base_ids", bases), ("worldbooks", "worldbook_ids", books)):
        ok(client.patch(f"/api/personas/{role['id']}/{suffix}", json={field: ids[:2]}))
        ok(client.patch(f"/api/personas/{CHAT_PERSONA_ID}/{suffix}", json={field: [ids[2]]}))
        response = ok(client.patch(path + "/" + suffix, json={field: ids[1:3]}))
        assert response == {"session_id": session["session_id"], field: ids[1:3],
                            "persona_" + field: ids[:2], "effective_" + field: ids[:3]}
    ok(client.post(path + "/messages", json={"content": "artifact"}))
    prompt = json.dumps(upstream.calls[-1])
    assert all(f"WORLD_{name}" in prompt for name in ("first", "second", "extra"))
    assert "WORLD_outside" not in prompt
    search = ok(client.post("/api/knowledge/search", json={"query": "artifact", "session_id": session["session_id"]}))
    assert {item["knowledge_base_id"] for item in search["results"]} == set(bases[:3])
    direct = ok(client.post("/api/tools/knowledge_search/call", json={"session_id": session["session_id"], "arguments": {"query": "artifact"}}))
    part = next(part for message in direct["messages"] for part in message["parts"] if part["type"] == "tool_result")
    assert {item["knowledge_base_id"] for item in part["data"]["results"]} == set(bases[:3])
    forbidden = ok(client.post("/api/tools/knowledge_search/call", json={"session_id": session["session_id"],
        "arguments": {"query": "artifact", "knowledge_base_ids": [bases[3]]}}))
    assert forbidden["run"]["error_code"] == "KNOWLEDGE_SCOPE_FORBIDDEN"
    for suffix, ids in (("knowledge/bases", bases), ("worldbooks", books)):
        ok(client.patch(f"/api/{suffix}/{ids[1]}", json={"enabled": False}))
    search = ok(client.post("/api/knowledge/search", json={"query": "artifact", "session_id": session["session_id"]}))
    assert {item["knowledge_base_id"] for item in search["results"]} == {bases[0], bases[2]}
    matches = ok(client.post("/api/worldbooks/match-test", json={"session_id": session["session_id"]}))
    assert {item["worldbook_id"] for item in matches["results"]} == {books[0], books[2]}
    switched = ok(client.patch(path, json={"current_persona_id": CHAT_PERSONA_ID}))
    assert switched["effective"]["knowledge_base_ids"] == [bases[2], bases[1]]
    assert switched["effective"]["worldbook_ids"] == [books[2], books[1]]
    ok(client.patch(path, json={"current_persona_id": role["id"]}))
    for suffix, field, ids in (("knowledge-bases", "knowledge_base_ids", bases), ("worldbooks", "worldbook_ids", books)):
        assert ok(client.get(path + "/" + suffix))[field] == ids[1:3]
        cleared = ok(client.patch(path + "/" + suffix, json={field: []}))
        assert cleared[field] == [] and cleared["effective_" + field] == ids[:2]


def test_configuration_revision_discards_chat_only_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.PHASE5_REVISION)
    with engine.begin() as db:
        db.execute(text("""INSERT INTO sessionrecord
            (session_id, title, context_mode, current_persona_id, knowledge_binding_mode,
             worldbook_binding_mode, title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('old', '', 'single_assistant', :persona, 'inherit', 'override', 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
            {"persona": CHAT_PERSONA_ID})
        db.execute(text("INSERT INTO session_personas VALUES ('old', :persona, 0, 1)"), {"persona": CHAT_PERSONA_ID})
    with DbSession(engine) as db:
        db.add(AppMetadataRecord(key="app_settings", value='{"core_memory_content":"Keep"}'))
        db.add(ModelProfileRecord(id="model", alias="model", name="Model", kind="embedding", model_ref="manual"))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id="model"))
        db.add(WorldbookRecord(id="book", name="Keep"))
        db.add(RunRecord(run_id="run", session_id="old", persona_id=CHAT_PERSONA_ID, kind="chat", status="WAITING_FOR_USER",
                         config_snapshot_json='{"model_source":"persona"}', harness_state_json='{"old":true}'))
        db.add(MessageRecord(message_id="message", session_id="old", role="user"))
        db.add(RunStepRecord(step_id="step", run_id="run", kind="approval", status="running"))
        db.add(RunEventRecord(event_id="event", run_id="run", session_id="old", type="approval_requested"))
        db.commit()
    affected = {"personas", "sessionrecord", "session_personas", "persona_knowledge_bindings", "persona_worldbook_bindings",
                "session_knowledge_bindings", "session_worldbook_bindings", "messagerecord", "runrecord", "runsteprecord", "runeventrecord"}
    def unrelated_rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
                    for name in inspect(engine).get_table_names() if name not in affected | {"alembic_version"}}
    before_rows = unrelated_rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "runtimes", "attachments", "knowledge", "pet", "logs")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"owned file")
    before_files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    migrations.upgrade(engine, migrations.CHAT_CONFIGURATION_REVISION)
    assert unrelated_rows() == before_rows
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == before_files
    schema = migrations.inspect_schema(engine)
    assert set(schema.columns["personas"]) == {"id", "name", "avatar_attachment_id", "system_prompt", "created_at", "updated_at"}
    assert not {"knowledge_binding_mode", "worldbook_binding_mode"}.intersection(schema.columns["sessionrecord"])
    with engine.connect() as db:
        assert db.exec_driver_sql("SELECT name FROM personas ORDER BY name").scalars().all() == ["Chat", "Translate"]
        assert all(db.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar() == 0 for name in affected - {"personas"})
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    migrations.upgrade(engine, migrations.CHAT_CONFIGURATION_REVISION)
    assert migrations.inspect_schema(engine) == schema and unrelated_rows() == before_rows
    engine.dispose()
