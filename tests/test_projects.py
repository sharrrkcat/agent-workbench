import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session as DbSession

from ai_workbench.api.main import create_app
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID, USER_PERSONA_ID
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import AppMetadataRecord, KnowledgeBaseRecord, RuntimeInstallationRecord, WorldbookRecord
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, ok, tool_call


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def client_pair(tmp_path, request):
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param,
                     database_url=f"sqlite:///{tmp_path / 'app.db'}", adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream, tmp_path


def workspace(client, **values):
    return ok(client.post("/api/projects", json={
        "kind": "workspace", "name": "Workspace", "agent_persona_id": COGITA_PERSONA_ID,
        "cogita_persona_id": USER_PERSONA_ID, "context_policy": {"mode": "session"},
        "harness_enabled": False, "tools_allowed": ["base64_encode", "read_file", "knowledge_search"], **values,
    }))


def child(client, project, **values):
    return ok(client.post(f"/api/projects/{project['id']}/sessions", json=values))


def test_types_required_fields_and_timeline_creation_only(client_pair):
    client, upstream, _ = client_pair
    project = workspace(client)
    standard = ok(client.post("/api/sessions", json={}))
    session = child(client, project)
    assert (standard["kind"], standard["project_id"]) == ("ordinary", None)
    assert (session["kind"], session["project_id"], session["overrides"]) == ("workspace", project["id"], {})
    assert "persona_id" not in session and "model_profile_id" not in session
    assert [s["session_id"] for s in ok(client.get("/api/sessions"))] == [standard["session_id"]]
    assert ok(client.get(f"/api/projects/{project['id']}/sessions")) == [session]
    for name in ("agent_persona_id", "cogita_persona_id", "context_policy", "harness_enabled", "tools_allowed"):
        values = {key: value for key, value in project.items() if key not in {"id", "created_at", "updated_at", name}}
        assert client.post("/api/projects", json=values).status_code == 422
    for patch in ({"kind": "timeline"}, {"worldbook_ids": []}, {"cogita_persona_id": COGITA_PERSONA_ID}, {"name": "  "}):
        assert client.patch(f"/api/projects/{project['id']}", json=patch).status_code == 422
    for patch in ({"project_id": project["id"]}, {"kind": "ordinary"}, {"model_profile_id": None}, {"user_persona_id": USER_PERSONA_ID}):
        assert client.patch(f"/api/sessions/{session['session_id']}", json=patch).status_code == 422
    assert client.post("/api/sessions", json={"project_id": project["id"]}).status_code == 422
    assert client.get(f"/api/projects/{project['id']}/worldbooks").status_code == 422

    personas = [ok(client.post("/api/personas", json={"name": collection, "collection": collection, "system_prompt": "ROLEPLAY_ONLY"}))
                for collection in ("character", "roleplay_user")]
    book = ok(client.post("/api/worldbooks", json={"name": "Timeline book"}))
    timeline = ok(client.post("/api/projects", json={"kind": "timeline", "name": "Timeline",
        "character_persona_id": personas[0]["id"], "user_persona_id": personas[1]["id"],
        "context_policy": {"mode": "session"}, "worldbook_ids": [book["id"]]}))
    path = f"/api/projects/{timeline['id']}"
    assert "harness_enabled" not in timeline and "tools_allowed" not in timeline
    assert ok(client.get(path + "/worldbooks"))["worldbook_ids"] == [book["id"]]
    assert client.get(path + "/knowledge-bases").status_code == 422
    for patch in ({"harness_enabled": False}, {"knowledge_base_ids": []}, {"user_persona_id": USER_PERSONA_ID}, {"character_persona_id": COGITA_PERSONA_ID}):
        assert client.patch(path, json=patch).status_code == 422
    assert client.post(path + "/sessions", json={}).json()["error"]["code"] == "PROJECT_CHAT_UNAVAILABLE"
    assert client.get(path + "/sessions").status_code == 409
    assert client.delete(f"/api/personas/{personas[0]['id']}").status_code == 409
    assert client.delete(f"/api/worldbooks/{book['id']}").status_code == 409
    assert len(ok(client.get("/api/projects"))) == 2 and upstream.calls == []
    ok(client.delete(path))
    assert ok(client.get(f"/api/worldbooks/{book['id']}"))["id"] == book["id"]
    assert ok(client.get(f"/api/personas/{personas[0]['id']}"))["id"] == personas[0]["id"]


def test_live_inheritance_overrides_reset_and_model_sources(client_pair):
    client, upstream, _ = client_pair
    first = configure_model(client, alias="first", parameters={"temperature": 0.25, "top_p": 0.8})
    project = workspace(client, temperature=0.7)
    session = child(client, project)
    path = f"/api/sessions/{session['session_id']}"
    assert session["effective"]["model_source"] == "global"
    ordinary = ok(client.post("/api/sessions", json={}))
    second = configure_model(client, alias="second", parameters={"temperature": 0.4})
    assert ok(client.get(path))["effective"]["model_profile_id"] == second["id"]
    assert ok(client.get(f"/api/sessions/{ordinary['session_id']}"))["model_profile_id"] == first["id"]
    persona = ok(client.post("/api/personas", json={"collection": "agent", "name": "Project Agent"}))
    ok(client.patch(f"/api/projects/{project['id']}", json={"agent_persona_id": persona["id"],
        "model_profile_id": first["id"], "harness_enabled": True, "context_policy": {"mode": "none"}}))
    resolved = ok(client.get(path))["effective"]
    assert resolved["persona_id"] == persona["id"] and resolved["context_policy"]["mode"] == "none"
    assert resolved["model_source"] == "project" and resolved["harness_enabled"]
    assert resolved["generation"]["temperature"] == 0.7 and resolved["generation"]["top_p"] == 0.8
    overrides = {"persona_id": COGITA_PERSONA_ID, "model_profile_id": second["id"], "context_policy": {"mode": "current_message"},
                 "temperature": 0, "harness_enabled": False, "tools_allowed": []}
    overridden = ok(client.patch(path, json={"overrides": overrides}))
    assert overridden["overrides"]["temperature"] == 0
    assert overridden["effective"]["model_source"] == "session"
    assert overridden["effective"]["generation"]["temperature"] == 0
    assert overridden["effective"]["tools_allowed"] == [] and not overridden["effective"]["harness_enabled"]
    ok(client.patch(f"/api/projects/{project['id']}", json={"temperature": 1.2, "context_policy": {"mode": "session"}}))
    unchanged = ok(client.patch(path, json={"title": "Title only"}))
    assert unchanged["overrides"] == overridden["overrides"]
    reset = ok(client.patch(path, json={"overrides": {key: None for key in overrides}}))
    assert reset["overrides"] == {} and reset["effective"]["generation"]["temperature"] == 1.2
    assert reset["effective"]["sources"]["context"] == "project"
    ok(client.patch(f"/api/projects/{project['id']}", json={"model_profile_id": None, "temperature": None}))
    resolved = ok(client.get(path))["effective"]
    assert resolved["model_profile_id"] == second["id"] and resolved["generation"]["temperature"] == 0.4
    assert resolved["sources"]["temperature"] == "model"
    assert any(e.type == "session_updated" and e.session_id == session["session_id"]
               for e in client.app.state.runtime_state.events.list_events())
    assert upstream.calls == []


def test_empty_global_model_and_project_tool_ceiling(client_pair):
    client, upstream, _ = client_pair
    project = workspace(client, tools_allowed=["base64_encode"])
    session = child(client, project)
    path = f"/api/sessions/{session['session_id']}"
    assert session["effective"]["model_profile_id"] is None
    denied = client.patch(path, json={"overrides": {"tools_allowed": ["read_file"]}})
    assert denied.status_code == 422 and denied.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert ok(client.get(path))["overrides"] == {}
    ok(client.patch(path, json={"overrides": {"harness_enabled": True, "tools_allowed": ["base64_encode"]}}))
    direct = ok(client.post("/api/tools/base64_encode/call", json={"session_id": session["session_id"], "arguments": {"value": "hello"}}))
    assert direct["run"]["status"] == "DONE" and upstream.calls == []
    ok(client.patch(f"/api/projects/{project['id']}", json={"tools_allowed": []}))
    assert ok(client.get(path))["effective"]["tools_allowed"] == []
    assert client.post("/api/tools/base64_encode/call", json={"session_id": session["session_id"], "arguments": {"value": "hello"}}).json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert client.post(path + "/messages", json={"content": "/base64_encode hi"}).json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    model = configure_model(client)
    assert ok(client.get(path))["effective"]["model_profile_id"] is not None
    ok(client.patch("/api/models/settings", json={"default_model_profile_id": None}))
    ok(client.patch(f"/api/projects/{project['id']}", json={"model_profile_id": model["id"]}))
    assert client.delete(f"/api/models/profiles/{model['id']}").json()["error"]["code"] == "MODEL_IN_USE"
    ok(client.patch(f"/api/projects/{project['id']}", json={"model_profile_id": None}))
    ok(client.delete(f"/api/models/profiles/{model['id']}"))
    assert ok(client.get(path))["effective"]["model_profile_id"] is None


def test_project_knowledge_context_order_and_session_isolation(client_pair):
    client, upstream, _ = client_pair
    configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embedding")
    ids = []
    for name in ("cogita", "agent", "project", "addition", "outside"):
        base = ok(client.post("/api/knowledge/bases", json={"name": name, "embedding_model_profile_id": embedding["id"]}))
        ok(client.post(f"/api/knowledge/bases/{base['id']}/sources", json={"title": name, "text": f"artifact {name}", "source_type": "pasted_text"}))
        ids.append(base["id"])
    ok(client.patch(f"/api/personas/{USER_PERSONA_ID}", json={"name": "Me", "system_prompt": "COGITA_BACKGROUND"}))
    ok(client.patch(f"/api/personas/{COGITA_PERSONA_ID}", json={"system_prompt": "AGENT_INSTRUCTION"}))
    ok(client.patch(f"/api/personas/{USER_PERSONA_ID}/knowledge-bases", json={"knowledge_base_ids": ids[:1]}))
    ok(client.patch(f"/api/personas/{COGITA_PERSONA_ID}/knowledge-bases", json={"knowledge_base_ids": ids[:2]}))
    project = workspace(client, knowledge_base_ids=ids[1:3], system_prompt="PROJECT_INSTRUCTION")
    session = child(client, project)
    path = f"/api/sessions/{session['session_id']}"
    bindings = ok(client.patch(path + "/knowledge-bases", json={"knowledge_base_ids": ids[2:4]}))
    assert bindings["project_knowledge_base_ids"] == ids[1:3] and bindings["effective_knowledge_base_ids"] == ids[:4]
    assert client.delete(f"/api/knowledge/bases/{ids[2]}").status_code == 409
    result = ok(client.post(path + "/messages", json={"content": "artifact"}))
    source = result["messages"][0]["message_id"]
    for mode in ("none", "current_message", "recent_messages", "session", "selected_message"):
        ok(client.patch(path, json={"overrides": {"context_policy": {"mode": mode}}}))
        result = ok(client.post(path + "/messages", json={"content": "artifact", "source_message_id": source}))
        assert result["success"]
        system = upstream.calls[-1]["messages"][0]["content"]
        assert system.index("AGENT_INSTRUCTION") < system.index("PROJECT_INSTRUCTION") < system.index("COGITA_BACKGROUND")
        assert all(system.count(value) == 1 for value in ("AGENT_INSTRUCTION", "PROJECT_INSTRUCTION", "COGITA_BACKGROUND"))
        assert "PROJECT_INSTRUCTION" not in json.dumps(result)
        assert result["session"]["user_persona"]["name"] == "Me"
    denied = ok(client.post("/api/tools/knowledge_search/call", json={"session_id": session["session_id"], "arguments": {"query": "artifact", "knowledge_base_ids": ids[4:]}}))
    assert denied["run"]["error_code"] == "KNOWLEDGE_SCOPE_FORBIDDEN"
    sibling = child(client, project, overrides={"context_policy": {"mode": "selected_message"}})
    isolated = ok(client.post(f"/api/sessions/{sibling['session_id']}/messages", json={"content": "artifact", "source_message_id": source}))
    assert isolated["run"]["error_code"] == "CONTEXT_MESSAGE_REQUIRED"
    other = child(client, workspace(client, name="Other"))
    assert ok(client.get(f"/api/sessions/{other['session_id']}/knowledge-bases"))["effective_knowledge_base_ids"] == ids[:2]
    cleared = ok(client.patch(path + "/knowledge-bases", json={"knowledge_base_ids": []}))
    assert cleared["effective_knowledge_base_ids"] == ids[:3]


def test_approval_uses_snapshot_but_cannot_execute_revoked_project_tools(client_pair):
    client, upstream, root = client_pair
    model = configure_model(client, capabilities={"tools": True})
    file = root / "data/knowledge/note.txt"
    file.parent.mkdir(parents=True)
    file.write_text("PRIVATE_FILE_DATA")
    project = workspace(client, harness_enabled=True, system_prompt="ORIGINAL_PROJECT_PROMPT", temperature=0.3)
    session = child(client, project)
    upstream.turns = [completion(tool_call("read_file", {"path": "data/knowledge/note.txt"})), completion(content="done")]
    pending = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "read"}))
    run_id = pending["run"]["run_id"]
    assert pending["run"]["status"] == "WAITING_FOR_USER"
    assert client.delete(f"/api/projects/{project['id']}").status_code == 409
    ok(client.patch(f"/api/projects/{project['id']}", json={"tools_allowed": ["base64_encode"], "system_prompt": "NEW_PROJECT_PROMPT", "temperature": 1.3}))
    snapshot = client.app.state.runtime_state.runs.get_config_snapshot(run_id)
    assert snapshot["project_system_prompt"] == "ORIGINAL_PROJECT_PROMPT" and snapshot["model_profile_id"] == model["id"]
    approved = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    results = [part for message in approved["messages"] for part in message["parts"] if part["type"] == "tool_result"]
    assert results[0]["error_code"] == "TOOL_NOT_ALLOWED" and approved["run"]["status"] == "DONE"
    assert upstream.calls[-1]["temperature"] == 0.3
    assert "ORIGINAL_PROJECT_PROMPT" in json.dumps(upstream.calls[-1]) and "NEW_PROJECT_PROMPT" not in json.dumps(upstream.calls[-1])
    assert "PRIVATE_FILE_DATA" not in json.dumps(upstream.calls)
    assert [tool["function"]["name"] for tool in upstream.calls[-1]["tools"]] == ["base64_encode"]
    other = child(client, workspace(client, name="Keep"))
    deleted = ok(client.delete(f"/api/projects/{project['id']}"))
    assert deleted["deleted_session_ids"] == [session["session_id"]]
    assert client.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert ok(client.get(f"/api/sessions/{other['session_id']}"))["session_id"] == other["session_id"]


def test_project_migration_preserves_resources_and_files_and_is_repeatable(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    migrations.upgrade(engine, migrations.PERSONA_COLLECTIONS_REVISION)
    profile = ModelProfileStore(engine).create(ModelProfile(name="Keep", alias="keep", kind="embedding", model_ref="manual"))
    with DbSession(engine) as db:
        db.add(AppMetadataRecord(key="sentinel", value="preserved"))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id=profile.id))
        db.add(WorldbookRecord(id="book", name="Keep"))
        db.add(RuntimeInstallationRecord(id="local", version="1.0.0", state="installed"))
        db.commit()
    with engine.begin() as db:
        db.execute(text("""INSERT INTO sessionrecord (session_id, title, persona_id, context_policy_json, generation_json,
            harness_enabled, tools_allowed_json, title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('old', 'Old', :persona, '{"mode":"session"}', '{}', 0, '[]', 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
            {"persona": COGITA_PERSONA_ID})
    tables = ("personas", "model_profiles", "provider_profiles", "knowledge_bases", "worldbooks", "runtime_installations", "appmetadatarecord")
    def rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall() for name in tables}
    before = rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "attachments", "runtimes", "knowledge", "logs")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"owned file")
    migrations.upgrade(engine)
    assert rows() == before and all(path.read_bytes() == b"owned file" for path in files)
    schema = migrations.inspect_schema(engine)
    assert {"projects", "project_knowledge_bindings", "project_worldbook_bindings"} <= set(schema.tables)
    with engine.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM sessionrecord").scalar() == 0
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    migrations.upgrade(engine)
    assert migrations.inspect_schema(engine) == schema and rows() == before
    engine.dispose()
