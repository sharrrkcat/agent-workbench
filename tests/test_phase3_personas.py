import asyncio
import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session as DbSession

from ai_workbench.api.main import create_app
from ai_workbench.core.schema.persona import CHAT_PERSONA_ID, TRANSLATE_PERSONA_ID
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import MessageRecord
from tests.model_fixtures import MockOpenAI, configure_model


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def chat_client(tmp_path, monkeypatch, request):
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    upstream = MockOpenAI()
    app = create_app(root=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}",
                     use_memory=request.param, adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def persona(client, name="Role", **values):
    return ok(client.post("/api/personas", json={"name": name, "system_prompt": "PRIVATE_PERSONA_PROMPT", **values}))


def session_for(client, *ids, **values):
    return ok(client.post("/api/sessions", json={
        "personas": [{"persona_id": value} for value in ids],
        "current_persona_id": ids[0], **values,
    }))


def send(client, session, content="hello", **values):
    return ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": content, **values}))


def test_migration_seeds_and_discards_only_chat_rows(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.PHASE2B_REVISION)
    with engine.begin() as db:
        db.execute(text("INSERT INTO sessionrecord (session_id,title,context_mode,title_generation_state,title_generation_metadata_json,created_at,updated_at) VALUES ('old','old','single_assistant','pending','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO appmetadatarecord (key,value,updated_at) VALUES ('sentinel','preserved',CURRENT_TIMESTAMP)"))
    with DbSession(engine) as db:
        db.add(MessageRecord(message_id="old-message", session_id="old", role="user"))
        db.commit()
    files = [tmp_path / f"data/{kind}/keep.bin" for kind in ("models", "attachments", "runtimes")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(path.name.encode())
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    migrations.upgrade(engine, migrations.PHASE3_REVISION)
    with engine.connect() as db:
        seeds = db.execute(text("SELECT id,name,context_policy_json FROM personas ORDER BY name")).all()
        assert [row.name for row in seeds] == ["Chat", "Translate"]
        assert [row.id for row in seeds] == [CHAT_PERSONA_ID, TRANSLATE_PERSONA_ID]
        assert json.loads(seeds[1].context_policy_json)["mode"] == "current_message"
        assert db.execute(text("SELECT count(*) FROM sessionrecord")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM messagerecord")).scalar() == 0
        assert db.execute(text("SELECT value FROM appmetadatarecord WHERE key='sentinel'")).scalar() == "preserved"
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == before
    schema = migrations.inspect_schema(engine).as_dict()
    migrations.upgrade(engine, migrations.PHASE3_REVISION)
    assert migrations.inspect_schema(engine).as_dict() == schema
    assert "target" not in schema["columns"]["runrecord"]
    assert "config_snapshot_json" in schema["columns"]["runrecord"]
    assert len(inspect(engine).get_foreign_keys("session_personas")) == 2
    source = Path("alembic/versions/0005_phase3_personas.py").read_text()
    assert "import ai_workbench" not in source and "SQLModel.metadata" not in source
    with pytest.raises(RuntimeError, match="unsupported"):
        migrations.downgrade(engine, migrations.PHASE2B_REVISION)
    engine.dispose()


def test_persona_crud_membership_and_strict_schemas(chat_client):
    client, _ = chat_client
    default = ok(client.post("/api/sessions", json={}))
    assert default["current_persona_id"] == CHAT_PERSONA_ID
    assert default["personas"][0]["name"] == "Chat"
    role = persona(client, "  Editor  ")
    assert role["name"] == "Editor"
    current = session_for(client, role["id"], CHAT_PERSONA_ID)
    path = f"/api/sessions/{current['session_id']}"
    assert client.delete(f"/api/personas/{role['id']}").status_code == 409
    for patch in (
        {"personas": []},
        {"personas": [{"persona_id": role["id"], "enabled": False}]},
        {"current_persona_id": TRANSLATE_PERSONA_ID},
        {"personas": [{"persona_id": role["id"]}, {"persona_id": role["id"]}]},
        {"context_policy": {"mode": "recent_messages", "max_messages": 0}},
        {"harness_enabled": "true"}, {"tools_allowed": ["x", "x"]},
        {"generation": {"temperature": 5}}, {"generation": {"unknown": 1}},
        {"title": "Must not save", "current_persona_id": "missing"},
    ):
        assert client.patch(path, json=patch).status_code == 422
    assert ok(client.get(path))["title"] == ""
    assert client.patch(f"/api/personas/{role['id']}", json={"name": "New", "unknown": True}).status_code == 422
    assert ok(client.get(f"/api/personas/{role['id']}"))["name"] == "Editor"
    assert client.post("/api/personas", json={"name": " "}).status_code == 422
    assert client.post("/api/personas", json={"name": "Bad", "tools_allowed": ["x", "x"]}).status_code == 422
    assert client.post("/api/personas", json={"name": "Bad", "avatar_attachment_id": "../secret"}).status_code == 400
    assert client.delete(f"/api/personas/{CHAT_PERSONA_ID}").json()["error"]["code"] == "PERSONA_DEFAULT"
    updated = ok(client.patch(path + "/personas", json={"personas": [{"persona_id": CHAT_PERSONA_ID}], "current_persona_id": CHAT_PERSONA_ID}))
    assert updated["effective"]["persona_name"] == "Chat"
    assert ok(client.delete(f"/api/personas/{role['id']}"))["deleted"]
    assert client.get("/api/knowledge/sessions/old/bindings").status_code == 404


def test_model_generation_and_context_precedence(chat_client):
    client, upstream = chat_client
    global_model = configure_model(client, alias="global", parameters={"temperature": 0.1}, capabilities={"tools": True})
    selected_model = configure_model(client, alias="selected", model_ref="other", parameters={"temperature": 0.2, "top_p": 0.7}, capabilities={"tools": True})
    override_model = configure_model(client, alias="override", model_ref="fake", parameters={"temperature": 0.3}, capabilities={"tools": True})
    ok(client.patch("/api/models/settings", json={"default_model_profile_id": global_model["id"]}))
    role = persona(client)
    session = session_for(client, role["id"], model_profile_id=selected_model["id"], generation={"temperature": 0.6},
                          context_policy={"mode": "current_message"}, harness_enabled=True, tools_allowed=["read_file"])
    response = send(client, session)
    assert response["run"]["persona_id"] == role["id"]
    assert upstream.calls[-1]["model"] == "other"
    assert upstream.calls[-1]["temperature"] == 0.6 and upstream.calls[-1]["top_p"] == 0.7
    assert [tool["function"]["name"] for tool in upstream.calls[-1]["tools"]] == ["read_file"]
    assert response["session"]["effective"]["harness_enabled"] is True
    assert response["session"]["effective"]["model_source"] == "session"
    assert response["messages"][-1]["speaker_name"] == "Role"
    assert "PRIVATE_PERSONA_PROMPT" not in json.dumps(response)
    state = client.app.state.runtime_state
    assert state.runs.get_config_snapshot(response["run"]["run_id"])["system_prompt"] == "PRIVATE_PERSONA_PROMPT"
    events = ok(client.get(f"/api/runs/{response['run']['run_id']}/events"))
    assert "PRIVATE_PERSONA_PROMPT" not in json.dumps(events)
    assert client.delete(f"/api/models/profiles/{selected_model['id']}").status_code == 409
    path = f"/api/sessions/{session['session_id']}"
    ok(client.patch(path, json={"model_profile_id": override_model["id"], "generation": {"temperature": 0.9}, "context_policy": {"mode": "current_message"}}))
    assert send(client, session, "second")["success"]
    assert upstream.calls[-1]["model"] == "fake" and upstream.calls[-1]["temperature"] == 0.9
    assert upstream.calls[-1]["messages"] == [{"role": "system", "content": "PRIVATE_PERSONA_PROMPT"}, {"role": "user", "content": "second"}]
    ok(client.patch(path, json={"generation": {}}))
    send(client, session, "third")
    assert upstream.calls[-1]["temperature"] == 0.3
    restored = ok(client.patch(path, json={"model_profile_id": global_model["id"], "generation": {}, "context_policy": {"mode": "session"}}))
    assert restored["effective"]["model_source"] == "session"
    send(client, session, "fourth")
    assert upstream.calls[-1]["model"] == "fake" and upstream.calls[-1]["temperature"] == 0.1
    ok(client.patch("/api/models/settings", json={"default_model_profile_id": None}))
    ok(client.patch(path, json={"model_profile_id": None}))
    assert send(client, session, "missing")["run"]["error_code"] == "MODEL_NOT_CONFIGURED"


def test_group_speakers_live_edits_retry_and_selected_context(chat_client):
    client, upstream = chat_client
    configure_model(client)
    first = persona(client, "First")
    second = persona(client, "Second")
    session = session_for(client, first["id"], second["id"], context_mode="group_transcript")
    path = f"/api/sessions/{session['session_id']}"
    initial = send(client, session, "first input")
    original = initial["messages"][-1]
    ok(client.patch(path, json={"current_persona_id": second["id"]}))
    result = send(client, session, "second input")
    assert result["messages"][-1]["speaker_id"] == second["id"]
    assert f"[First ({first['id']})] reply" in upstream.calls[-1]["messages"][-1]["content"]
    assert sum("current speaker" in m["content"] for m in upstream.calls[-1]["messages"]) == 1
    ok(client.patch(f"/api/personas/{first['id']}", json={"name": "Renamed", "system_prompt": "NEW_PROMPT"}))
    history = ok(client.get(path + "/messages"))
    assert history[1]["speaker_name"] == "First"
    retried = ok(client.post(f"/api/runs/{original['run_id']}/retry"))
    assert len(retried["messages"]) == 1 and retried["messages"][0]["speaker_name"] == "Renamed"
    assert retried["run"]["persona_id"] == first["id"]
    assert len(ok(client.get(path + "/messages"))) == 2
    assert retried["session"]["current_persona_id"] == second["id"]
    ok(client.patch(path, json={"context_policy": {"mode": "selected_message"}}))
    other_session = session_for(client, CHAT_PERSONA_ID)
    other_user = send(client, other_session, "SECRET_OTHER_SESSION")["messages"][0]
    failed = send(client, session, "cross session", source_message_id=other_user["message_id"])
    assert failed["error_code"] == "CONTEXT_MESSAGE_REQUIRED"
    selected = send(client, session, "selected", source_message_id=initial["messages"][0]["message_id"])
    assert selected["success"]
    assert "first input" in upstream.calls[-1]["messages"][-1]["content"]
    assert "SECRET_OTHER_SESSION" not in json.dumps(upstream.calls[-1])
    assert "second input" not in json.dumps(upstream.calls[-1])


def test_persona_bindings_survive_empty_session_additions_and_search_preview(chat_client):
    client, upstream = chat_client
    configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embed")
    base = ok(client.post("/api/knowledge/bases", json={"name": "A", "embedding_model_profile_id": embedding["id"]}))
    ok(client.post(f"/api/knowledge/bases/{base['id']}/sources", json={"title": "Fact", "text": "The artifact is green.", "source_type": "pasted_text"}))
    book = ok(client.post("/api/worldbooks", json={"name": "World"}))
    ok(client.post(f"/api/worldbooks/{book['id']}/entries", json={"name": "Always", "content": "WORLD_FACT", "activation_mode": "always"}))
    role = persona(client)
    ok(client.patch(f"/api/personas/{role['id']}/knowledge-bases", json={"knowledge_base_ids": [base["id"]]}))
    ok(client.patch(f"/api/personas/{role['id']}/worldbooks", json={"worldbook_ids": [book["id"]]}))
    session = session_for(client, role["id"], CHAT_PERSONA_ID)
    path = f"/api/sessions/{session['session_id']}"
    send(client, session, "artifact")
    assert "WORLD_FACT" in json.dumps(upstream.calls[-1]) and "artifact is green" in json.dumps(upstream.calls[-1])
    assert ok(client.get(path + "/knowledge-bases"))["effective_knowledge_base_ids"] == [base["id"]]
    assert ok(client.post("/api/knowledge/search", json={"query": "artifact", "session_id": session["session_id"]}))["results"]
    assert ok(client.post("/api/knowledge/search", json={"query": "artifact", "session_id": session["session_id"], "knowledge_base_ids": []}))["results"] == []
    assert client.delete(f"/api/knowledge/bases/{base['id']}").status_code == 409
    assert client.delete(f"/api/worldbooks/{book['id']}").status_code == 409
    for suffix, key in (("knowledge-bases", "knowledge_base_ids"), ("worldbooks", "worldbook_ids")):
        assert client.patch(path + "/" + suffix, json={key: ["missing"]}).status_code == 404
        ok(client.patch(path + "/" + suffix, json={key: []}))
    cleared = send(client, session, "artifact")
    assert cleared["session"]["effective"]["knowledge_base_ids"] == [base["id"]]
    assert "WORLD_FACT" in json.dumps(upstream.calls[-1]) and "artifact is green" in json.dumps(upstream.calls[-1])
    assert ok(client.post("/api/knowledge/search", json={"query": "artifact", "session_id": session["session_id"]}))["results"]
    ok(client.patch(path, json={"current_persona_id": CHAT_PERSONA_ID}))
    assert ok(client.get(path))["effective"]["worldbook_ids"] == []
    ok(client.patch(path, json={"current_persona_id": role["id"]}))
    assert ok(client.get(path))["effective"]["worldbook_ids"] == [book["id"]]


def test_avatar_reference_shared_with_messages_and_personas(chat_client):
    client, _ = chat_client
    configure_model(client)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=")
    image = ok(client.post("/api/attachments", files={"file": ("avatar.png", png, "image/png")}))
    attachment_id = image["uri"].removeprefix("local://attachments/")
    first = persona(client, "Avatar one", avatar_attachment_id=attachment_id)
    second = persona(client, "Avatar two", avatar_attachment_id=attachment_id)
    attachment_path = f"/api/attachments/{attachment_id}"
    assert client.delete(attachment_path).status_code == 409
    session = session_for(client, first["id"])
    message = send(client, session)["messages"][-1]
    assert message["metadata"]["speaker_avatar_attachment_id"] == attachment_id
    ok(client.patch(f"/api/personas/{first['id']}", json={"avatar_attachment_id": None}))
    ok(client.delete(f"/api/personas/{second['id']}"))
    assert client.get(attachment_path).content == png
    assert client.delete(attachment_path).status_code == 409
    ok(client.delete(f"/api/runs/{message['run_id']}"))
    assert client.get(attachment_path).status_code == 404


def test_sql_restart_preserves_persona_bindings_history_and_snapshot(tmp_path):
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    upstream = MockOpenAI()
    with TestClient(create_app(root=tmp_path, database_url=url, adapter_factory=upstream.factory)) as client:
        configure_model(client)
        role = persona(client, "Persistent")
        session = session_for(client, role["id"], CHAT_PERSONA_ID, generation={"seed": 123})
        run = send(client, session)["run"]
        ok(client.patch(f"/api/personas/{CHAT_PERSONA_ID}", json={"name": "Edited default"}))
        ok(client.delete(f"/api/personas/{TRANSLATE_PERSONA_ID}"))
    with TestClient(create_app(root=tmp_path, database_url=url, adapter_factory=upstream.factory)) as client:
        assert ok(client.get(f"/api/personas/{role['id']}"))["name"] == "Persistent"
        assert ok(client.get(f"/api/personas/{CHAT_PERSONA_ID}"))["name"] == "Edited default"
        assert client.get(f"/api/personas/{TRANSLATE_PERSONA_ID}").status_code == 404
        loaded = ok(client.get(f"/api/sessions/{session['session_id']}"))
        assert loaded["generation"]["seed"] == 123
        assert loaded["current_persona_id"] == role["id"] and len(loaded["personas"]) == 2
        assert client.app.state.runtime_state.runs.get_config_snapshot(run["run_id"])["system_prompt"] == "PRIVATE_PERSONA_PROMPT"
        history = ok(client.get(f"/api/sessions/{session['session_id']}/messages"))
        assert history[-1]["speaker_name"] == "Persistent"


def test_disabled_or_wrong_kind_session_model_never_substitutes(chat_client):
    client, upstream = chat_client
    model = configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embedding")
    bad = client.post("/api/sessions", json={"model_profile_id": embedding["id"]})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "MODEL_KIND_MISMATCH"
    role = persona(client)
    session = session_for(client, role["id"], model_profile_id=model["id"])
    ok(client.patch(f"/api/models/profiles/{model['id']}", json={"enabled": False}))
    result = send(client, session)
    assert not result["success"] and result["run"]["error_code"] == "MODEL_UNAVAILABLE"
    assert upstream.calls == []


def test_explicit_approval_retains_saved_persona_configuration(chat_client):
    client, upstream = chat_client
    configure_model(client, capabilities={"tools": True, "streaming": True})
    role = persona(client, "Waiting persona")
    session = session_for(client, role["id"], CHAT_PERSONA_ID, context_policy={"mode": "current_message"}, generation={"temperature": 0.25}, harness_enabled=True, tools_allowed=["read_file"])
    state = client.app.state.runtime_state
    path = state.repo_root / "data/knowledge/note.txt"
    path.parent.mkdir(parents=True)
    path.write_text("approved file")
    upstream.stream_events = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"data/knowledge/note.txt"}'}}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    waiting = send(client, session)
    run_id = waiting["run"]["run_id"]
    assert waiting["run"]["status"] == "WAITING_FOR_USER"
    upstream.stream_events = None
    ok(client.patch(f"/api/personas/{role['id']}", json={"name": "Later name", "system_prompt": "LATER_PROMPT"}))
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={"current_persona_id": CHAT_PERSONA_ID, "generation": {"temperature": 0.75}, "tools_allowed": [], "harness_enabled": False}))
    result = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
    assert result["run"]["status"] == "DONE" and result["run"]["run_id"] == run_id
    assert result["session"]["waiting_run_id"] is None
    assert result["messages"][-1]["speaker_name"] == "Waiting persona"
    assert upstream.calls[-1]["temperature"] == 0.25
    assert "LATER_PROMPT" not in json.dumps(upstream.calls[-1])


def test_disabled_harness_never_authorizes_unexpected_tools(chat_client):
    client, upstream = chat_client
    configure_model(client, capabilities={"streaming": True, "tools": True})
    role = persona(client)
    session = session_for(client, role["id"], harness_enabled=False, tools_allowed=["read_file"])
    upstream.stream_events = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    result = send(client, session)
    assert not result["success"] and result["error_code"] == "UNEXPECTED_TOOL_CALL"
    assert "tools" not in upstream.calls[-1]
    assert [m["role"] for m in ok(client.get(f"/api/sessions/{session['session_id']}/messages"))] == ["user"]


def test_history_budget_and_attachment_policy_apply_to_group_and_single():
    messages = MessageStore()
    for index in range(25):
        messages.add_message("s", "user", f"history-{index}", metadata={"attachments": [{"type": "file", "name": "note", "text": "PRIVATE_ATTACHMENT"}]})
    builder = ContextBuilder(messages)
    for mode in ("single_assistant", "group_transcript"):
        result = builder.build("s", "current", ContextPolicy(mode="recent_messages", include_attachments="none"), context_mode=mode)
        text = json.dumps(result.messages)
        assert "PRIVATE_ATTACHMENT" not in text
        assert "history-4\\n" not in text and "history-5" in text
        limited = builder.build("s", "current", ContextPolicy(mode="session", max_chars=3), context_mode=mode, persona_id="p", persona_name="Name")
        assert "current" in json.dumps(limited.messages)
        assert "history-" not in json.dumps(limited.messages)
        assert limited.warnings


def test_running_snapshot_survives_persona_edit_and_speaker_switch(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class BlockingUpstream(MockOpenAI):
            async def handle(self, request):
                if request.url.path.endswith("/chat/completions"):
                    entered.set()
                    await release.wait()
                return await super().handle(request)

        upstream = BlockingUpstream()
        app = create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            provider = ok(await client.post("/api/models/providers", json={"name": "provider", "base_url": "http://provider.test/v1"}))
            model = ok(await client.post("/api/models/profiles", json={"name": "model", "alias": "model", "kind": "llm", "model_ref": "fake", "provider_profile_id": provider["id"], "capabilities": {"streaming": True, "tools": True}, "parameters": {"temperature": 0.2}}))
            ok(await client.patch("/api/models/settings", json={"default_model_profile_id": model["id"]}))
            before = ok(await client.post("/api/personas", json={"name": "Before", "system_prompt": "BEFORE_PROMPT"}))
            session = ok(await client.post("/api/sessions", json={"current_persona_id": before["id"], "personas": [{"persona_id": before["id"]}, {"persona_id": CHAT_PERSONA_ID}], "context_mode": "group_transcript", "harness_enabled": True, "tools_allowed": ["read_file"]}))
            path = f"/api/sessions/{session['session_id']}"
            request = asyncio.create_task(client.post(path + "/messages", json={"content": "first"}))
            await asyncio.wait_for(entered.wait(), 5)
            try:
                run = app.state.runtime_state.runs.list_runs(session["session_id"])[0]
                events = app.state.runtime_state.run_events.list_events(run.run_id)
                started = next(e for e in events if e.type == "message_started")
                assert started.payload["message"]["speaker_name"] == "Before"
                assert (await client.delete(path)).status_code == 409
                assert (await client.patch(f"/api/models/profiles/{model['id']}", json={"parameters": {"temperature": 0.8}})).status_code == 409
                ok(await client.patch(f"/api/personas/{before['id']}", json={"name": "After", "system_prompt": "AFTER_PROMPT"}))
                ok(await client.patch(path, json={"current_persona_id": CHAT_PERSONA_ID, "generation": {"temperature": 0.7}}))
                release.set()
                response = ok(await asyncio.wait_for(request, 5))
            finally:
                release.set()
                if not request.done():
                    request.cancel()
                    await asyncio.gather(request, return_exceptions=True)
            assert response["messages"][-1]["speaker_name"] == "Before"
            assert response["messages"][-1]["speaker_id"] == before["id"]
            assert response["session"]["current_persona_id"] == CHAT_PERSONA_ID
            assert upstream.calls[-1]["temperature"] == 0.2
            assert "BEFORE_PROMPT" in json.dumps(upstream.calls[-1]) and "AFTER_PROMPT" not in json.dumps(upstream.calls[-1])
            assert [tool["function"]["name"] for tool in upstream.calls[-1]["tools"]] == ["read_file"]
            ok(await client.patch(path, json={"current_persona_id": before["id"], "generation": {}}))
            later = ok(await client.post(path + "/messages", json={"content": "second"}))
            assert later["messages"][-1]["speaker_name"] == "After"
            assert upstream.calls[-1]["temperature"] == 0.2

            entered.clear()
            release.clear()
            cancelled_request = asyncio.create_task(client.post(path + "/messages", json={"content": "cancel this"}))
            await asyncio.wait_for(entered.wait(), 5)
            cancelled_run = app.state.runtime_state.runs.list_runs(session["session_id"])[-1]
            ok(await client.post(f"/api/runs/{cancelled_run.run_id}/cancel"))
            assert ok(await asyncio.wait_for(cancelled_request, 5))["run"]["status"] == "CANCELLED"
            assert app.state.runtime_state.runs.get_run(cancelled_run.run_id).status == RunStatus.CANCELLED
            assert not any(m.run_id == cancelled_run.run_id and m.role == "assistant" for m in app.state.runtime_state.messages.list_messages(session["session_id"]))
            assert app.state.runtime_state.model_manager.status(model["id"]).active == 0

    asyncio.run(scenario())
