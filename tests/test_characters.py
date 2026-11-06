"""Character ownership, user identities and deliberately inactive resource mounts."""

import json

import pytest
from fastapi.testclient import TestClient

from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
from ai_workbench.core.schema.chat_config import ResolvedChatConfig
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from tests.history_helpers import history_messages
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, create_tool_app, ok, completion, tool_call, register_approval_tool


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def client_pair(tmp_path, request):
    upstream = ToolOpenAI()
    app = create_tool_app(root=tmp_path, use_memory=request.param,
        database_url=f"sqlite:///{tmp_path / 'app.db'}", adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream, app.state.runtime_state


def character(client, **values):
    return ok(client.post("/api/characters", json={"kind": "normal", "name": "Assistant", **values}))


def child(client, owner, **overrides):
    return ok(client.post(f"/api/characters/{owner['id']}/sessions", json={"overrides": overrides}))


def test_seed_identities_and_strict_ownership(client_pair):
    client, upstream, _ = client_pair
    user, = ok(client.get("/api/personas"))
    cogita, = ok(client.get("/api/characters"))
    assert (user["id"], user["name"], user["background"], user["is_protected"]) == (USER_PERSONA_ID, "User", "", True)
    assert (cogita["id"], cogita["name"], cogita["kind"], cogita["system_prompt"], cogita["is_protected"]) == (COGITA_CHARACTER_ID, "Cogita", "normal", "", True)
    for path in (f"/api/personas/{user['id']}", f"/api/characters/{cogita['id']}"):
        assert client.delete(path).status_code == 409
    assert client.post("/api/characters", json={"name": "Missing kind"}).status_code == 422
    assert client.post("/api/personas", json={"name": "Old", "collection": "user"}).status_code == 422
    assert client.post("/api/personas", json={"name": "Old", "system_prompt": "old"}).status_code == 422
    assert client.get("/api/projects").status_code == 404
    assert client.post("/api/sessions", json={}).status_code == 404
    assert client.get("/api/sessions").status_code == 404
    other = character(client)
    session = child(client, other)
    assert (session["kind"], session["character_id"], session["overrides"]) == ("normal", other["id"], {})
    assert session["persona"]["id"] == USER_PERSONA_ID
    assert ok(client.get(f"/api/characters/{cogita['id']}/sessions")) == []
    for values in ({"character_id": cogita["id"]}, {"kind": "qqbot"}, {"persona_id": USER_PERSONA_ID}, {"model_profile_id": None}):
        assert client.patch(f"/api/sessions/{session['session_id']}", json=values).status_code == 422
    assert client.patch(f"/api/characters/{other['id']}", json={"kind": "qqbot"}).status_code == 422
    for path in (f"/api/personas/{user['id']}/knowledge-bases", f"/api/characters/{other['id']}/worldbooks",
                 f"/api/sessions/{session['session_id']}/knowledge-bases"):
        assert client.patch(path, json={}).status_code in (404, 405)
    assert upstream.calls == []


def test_model_selection_is_saved_once_and_overrides_replace_defaults(client_pair):
    client, _, _ = client_pair
    first = configure_model(client, alias="first", parameters={"temperature": 0.2, "top_p": 0.8})
    owner = character(client, temperature=0.7, tools_allowed=["test_echo"])
    assert owner["model_profile_id"] == first["id"]
    second = configure_model(client, alias="second")
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}"
    assert session["effective"]["model_profile_id"] == first["id"]
    assert session["effective"]["model_source"] == "character"
    assert ok(client.get(f"/api/characters/{COGITA_CHARACTER_ID}"))["model_profile_id"] is None
    assert character(client)["model_profile_id"] == second["id"]
    assert character(client, model_profile_id=None)["model_profile_id"] is None
    updates = {"model_profile_id": second["id"], "temperature": 0, "reasoning": False,
        "harness_enabled": False, "tools_allowed": ["test_other"], "context_policy": {"history_enabled": False}}
    saved = ok(client.patch(path, json={"overrides": updates}))
    assert saved["effective"]["generation"]["temperature"] == 0
    assert saved["effective"]["reasoning"] is False
    assert saved["effective"]["tools_allowed"] == ["test_other"]
    ok(client.patch(f"/api/characters/{owner['id']}", json={"temperature": 1.1, "reasoning": True, "tools_allowed": []}))
    assert ok(client.get(path))["overrides"] == saved["overrides"]
    reset = ok(client.patch(path, json={"overrides": {key: None for key in updates}}))
    assert reset["overrides"] == {}
    assert reset["effective"]["generation"]["temperature"] == 1.1
    assert reset["effective"]["generation"]["top_p"] == 0.8
    assert reset["effective"]["sources"]["reasoning"] == "character"
    assert reset["effective"]["tools_allowed"] == []
    assert client.patch(path, json={"overrides": {"reasoning": "false"}}).status_code == 422


def test_bound_persona_ignores_parent_changes_and_preserves_retry_identity(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    a = ok(client.post("/api/personas", json={"name": "A", "background": "A_BACKGROUND"}))
    b = ok(client.post("/api/personas", json={"name": "B", "background": "B_BACKGROUND"}))
    owner = character(client, system_prompt="AI_PROMPT", persona_id=a["id"])
    session = child(client, owner)
    path = f"/api/sessions/{session['session_id']}"
    first = ok(client.post(path + "/messages", json={"content": "first"}))
    assert first["success"]
    run = first["run"]
    assert (run["character_id"], run["persona_id"]) == (owner["id"], a["id"])
    user, assistant = history_messages(ok(client.get(path + "/history")))
    assert (user["speaker_id"], assistant["speaker_id"]) == (a["id"], owner["id"])
    assert client.patch(path, json={"overrides": {"persona_id": b["id"]}}).status_code == 409
    assert client.patch(path, json={"overrides": {"persona_id": None}}).status_code == 409
    ok(client.patch(f"/api/characters/{owner['id']}", json={"persona_id": b["id"]}))
    ok(client.post(path + "/messages", json={"content": "second"}))
    request = json.dumps(upstream.calls[-1])
    assert a["id"] not in request and b["id"] not in request
    assert "A_BACKGROUND" in request and "B_BACKGROUND" not in request
    ok(client.patch(f"/api/personas/{a['id']}", json={"name": "A renamed", "background": "A_CURRENT"}))
    retried = ok(client.post(f"/api/runs/{run['run_id']}/retry"))
    assert retried["success"] and retried["run"]["persona_id"] == a["id"]
    assert ok(client.get(path))["persona"]["id"] == a["id"]
    assert child(client, owner)["persona"]["id"] == b["id"]
    assert "A_CURRENT" in json.dumps(upstream.calls[-1])
    assert history_messages(ok(client.get(path + "/history")))[0]["speaker_id"] == a["id"]
    edited = ok(client.post(f"/api/messages/{user['message_id']}/edit", json={"content": "revised", "attachment_ids": []}))
    assert edited["success"] and edited["run"]["persona_id"] == a["id"]
    assert state.runs.get_config_snapshot(edited["run"]["run_id"])["persona_background"] == "A_CURRENT"
    assert "A_CURRENT" not in json.dumps(edited)


def test_bound_persona_survives_cleared_history_and_blocks_deletion(client_pair):
    client, _, _ = client_pair
    configure_model(client)
    a = ok(client.post("/api/personas", json={"name": "Temporary"}))
    owner = character(client)
    session = child(client, owner, persona_id=a["id"])
    path = f"/api/sessions/{session['session_id']}"
    ok(client.post(path + "/messages", json={"content": "first"}))
    user = history_messages(ok(client.get(path + "/history")))[0]
    assert client.delete(f"/api/personas/{a['id']}").status_code == 409
    ok(client.delete(f"/api/messages/{user['message_id']}"))
    assert history_messages(ok(client.get(path + "/history"))) == []
    assert client.patch(path, json={"overrides": {"persona_id": None}}).status_code == 409
    assert ok(client.get(path))["bound_persona_id"] == a["id"]
    assert client.delete(f"/api/personas/{a['id']}").status_code == 409
    ok(client.delete(path))
    ok(client.delete(f"/api/personas/{a['id']}"))


def test_resource_mounts_replace_and_never_enter_chat(client_pair, monkeypatch):
    client, upstream, state = client_pair
    configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embedding")
    bases = [ok(client.post("/api/knowledge/bases", json={"name": name, "embedding_model_profile_id": embedding["id"]})) for name in ("A", "B")]
    book = ok(client.post("/api/worldbooks", json={"name": "Lore"}))
    owner = character(client, knowledge_base_ids=[bases[0]["id"]], worldbook_ids=[book["id"]])
    session = child(client, owner, knowledge_base_ids=[bases[1]["id"]], worldbook_ids=[])
    path = f"/api/sessions/{session['session_id']}"
    assert session["effective"]["knowledge_base_ids"] == [bases[1]["id"]]
    assert session["effective"]["worldbook_ids"] == []
    async def forbidden(**_):
        pytest.fail("Chat must not search mounted Knowledge")
    monkeypatch.setattr(state.knowledge_service, "search", forbidden)
    for harness in (False, True):
        ok(client.patch(path, json={"overrides": {"harness_enabled": harness, "tools_allowed": []}}))
        result = ok(client.post(path + "/messages", json={"content": "hello"}))
        assert result["success"]
        assert ok(client.post(f"/api/runs/{result['run']['run_id']}/retry"))["success"]
    assert "Retrieved Knowledge" not in json.dumps(upstream.calls)
    for base in bases:
        assert client.delete(f"/api/knowledge/bases/{base['id']}").status_code == 409
    assert client.delete(f"/api/worldbooks/{book['id']}").status_code == 409
    reset = ok(client.patch(path, json={"overrides": {"knowledge_base_ids": None, "worldbook_ids": None}}))
    assert reset["effective"]["knowledge_base_ids"] == [bases[0]["id"]]
    assert reset["effective"]["worldbook_ids"] == [book["id"]]


def test_active_run_snapshot_and_tool_defaults_are_not_a_ceiling(client_pair):
    client, upstream, state = client_pair
    configure_model(client)
    register_approval_tool(state.tool_registry)
    owner = character(client, system_prompt="BEFORE", tools_allowed=[])
    session = child(client, owner, harness_enabled=True, tools_allowed=["test_approval"])
    upstream.turns = [completion(tool_call("test_approval")), completion(content="done")]
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "approve"}))
    assert result["run"]["status"] == "WAITING_FOR_USER"
    snapshot = state.runs.get_config_snapshot(result["run"]["run_id"])
    ok(client.patch(f"/api/characters/{owner['id']}", json={"system_prompt": "AFTER", "tools_allowed": []}))
    assert state.runs.get_config_snapshot(result["run"]["run_id"]) == snapshot
    assert state.chat_service.tools_for_run(ResolvedChatConfig.model_validate(snapshot)) == ["test_approval"]
    assert client.delete(f"/api/characters/{owner['id']}").status_code == 409
    resumed = ok(client.post(f"/api/tools/approvals/{result['run']['run_id']}", json={"decision": "approve"}))
    assert resumed["run"]["status"] == "DONE"
    assert "BEFORE" in json.dumps(upstream.calls[-1]) and "AFTER" not in json.dumps(upstream.calls[-1])


def test_character_delete_cascades_conversations_only(client_pair):
    client, _, _ = client_pair
    configure_model(client)
    book = ok(client.post("/api/worldbooks", json={"name": "Shared"}))
    owner = character(client, worldbook_ids=[book["id"]])
    session = child(client, owner)
    ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"}))
    removed = ok(client.delete(f"/api/characters/{owner['id']}"))
    assert removed["deleted_session_ids"] == [session["session_id"]]
    assert client.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert ok(client.get(f"/api/worldbooks/{book['id']}"))["id"] == book["id"]


def test_avatar_references_follow_both_live_identities_and_refresh_history(client_pair, monkeypatch, tmp_path):
    import base64
    client, _, state = client_pair
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    configure_model(client)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=")
    upload = ok(client.post("/api/attachments", files={"file": ("avatar.png", png, "image/png")}))
    avatar = upload["uri"].rsplit("/", 1)[-1]
    user = ok(client.post("/api/personas", json={"name": "User A", "avatar_attachment_id": avatar}))
    owner = character(client, avatar_attachment_id=avatar)
    session = child(client, owner, persona_id=user["id"])
    path = f"/api/sessions/{session['session_id']}"
    reply = ok(client.post(path + "/messages", json={"content": "hello"}))
    old = history_messages(ok(client.get(path + "/history")))
    assert [m["speaker_id"] for m in old] == [user["id"], owner["id"]]
    assert all("speaker_avatar_attachment_id" not in m["metadata"] for m in old)
    assert client.delete(f"/api/attachments/{avatar}").status_code == 409
    ok(client.patch(f"/api/personas/{user['id']}", json={"name": "Renamed", "avatar_attachment_id": None}))
    assert ok(client.get(path))["persona"]["name"] == "Renamed"
    assert client.get(f"/api/attachments/{avatar}").status_code == 200
    if hasattr(state.messages, "engine"):
        from scripts.cleanup_attachments import main
        orphan = ok(client.post("/api/attachments", files={"file": ("orphan.png", png, "image/png")}))
        orphan_id = orphan["uri"].rsplit("/", 1)[-1]
        args = ["--database-url", state.database_url]
        assert main(args) == 0
        assert client.get(f"/api/attachments/{orphan_id}").status_code == 200
        assert main([*args, "--apply"]) == 0
        assert client.get(f"/api/attachments/{avatar}").status_code == 200
        assert client.get(f"/api/attachments/{orphan_id}").status_code == 404
    ok(client.patch(f"/api/characters/{owner['id']}", json={"avatar_attachment_id": None}))
    assert client.get(f"/api/attachments/{avatar}").status_code == 404
    assert history_messages(ok(client.get(path + "/history"))) == old
    assert state.runs.get_config_snapshot(reply["run"]["run_id"])["character_avatar_attachment_id"] == avatar


def test_model_validation_and_disabled_saved_selection(client_pair):
    client, upstream, _ = client_pair
    model = configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embedding")
    bad = client.post("/api/characters", json={"kind": "normal", "name": "Invalid", "model_profile_id": embedding["id"]})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "MODEL_KIND_MISMATCH"
    owner = character(client)
    session = child(client, owner)
    ok(client.patch(f"/api/models/profiles/{model['id']}", json={"enabled": False}))
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"}))
    assert not result["success"] and result["run"]["error_code"] == "MODEL_UNAVAILABLE"
    assert upstream.calls == []


def test_sql_restart_keeps_defaults_overrides_authors_and_private_snapshot(tmp_path):
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    upstream = ToolOpenAI()
    with TestClient(create_tool_app(root=tmp_path, database_url=url, adapter_factory=upstream.factory)) as client:
        configure_model(client)
        user = ok(client.post("/api/personas", json={"name": "Persistent user", "background": "PRIVATE_BACKGROUND"}))
        owner = character(client, system_prompt="PRIVATE_PROMPT")
        session = child(client, owner, persona_id=user["id"], temperature=0.6)
        run = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"}))["run"]
        ok(client.patch(f"/api/characters/{COGITA_CHARACTER_ID}", json={"name": "Edited default"}))
    with TestClient(create_tool_app(root=tmp_path, database_url=url, adapter_factory=upstream.factory)) as client:
        loaded = ok(client.get(f"/api/sessions/{session['session_id']}"))
        assert loaded["character_id"] == owner["id"]
        assert loaded["overrides"] == {"persona_id": user["id"], "temperature": 0.6}
        assert ok(client.get(f"/api/characters/{COGITA_CHARACTER_ID}"))["name"] == "Edited default"
        snapshot = client.app.state.runtime_state.runs.get_config_snapshot(run["run_id"])
        assert snapshot["system_prompt"] == "PRIVATE_PROMPT" and snapshot["persona_background"] == "PRIVATE_BACKGROUND"
        assert [m["speaker_id"] for m in history_messages(ok(client.get(f"/api/sessions/{session['session_id']}/history")))] == [user["id"], owner["id"]]
