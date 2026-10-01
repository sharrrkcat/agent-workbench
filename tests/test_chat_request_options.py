"""Request controls, local preflight decisions and durable chat degradation."""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from ai_workbench.api.main import create_app
from ai_workbench.core.models.chat_support import local_chat_support
from ai_workbench.core.models.schema import ExternalConnection, ModelInput, ModelProfile, ModelStatus
from ai_workbench.core.models.store import ModelProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.workers.transformers_engine import TransformersEngine
from ai_workbench.workers.transformers_server import build_app
from tests.model_fixtures import configure_model, resolve_local_profile, write_local_model
from tests.test_vision_input import image_bytes, part
from tests.tool_fixtures import ToolOpenAI, completion, ok, tool_call


DEFAULTS = {"streaming": True, "skip_tool_capability_check": False, "skip_vision_capability_check": False}


@pytest.mark.parametrize("memory", [True, False])
def test_model_crud_defaults_and_source_change_clear_only_inapplicable_skips(tmp_path, memory):
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'models.db'}")
    with TestClient(app) as client:
        model = ok(client.post("/api/models/profiles", json={"name": "LLM", "alias": "llm", "kind": "llm",
            "model_ref": "llms/missing", "source": {"type": "local"}}))
        assert model["request_options"] == DEFAULTS and "capabilities" not in model
        path = f"/api/models/profiles/{model['id']}"
        assert client.patch(path, json={"capabilities": {"vision": True}}).status_code == 422
        options = {"streaming": False, "skip_tool_capability_check": True, "skip_vision_capability_check": True}
        assert ok(client.patch(path, json={"request_options": options}))["request_options"] == options
        assert ok(client.get(path))["request_options"] == options
        provider = ok(client.post("/api/models/providers", json={"name": "P", "connection": {"base_url": "http://provider.test/v1"}}))
        source = {"type": "provider", "provider_profile_id": provider["id"]}
        assert client.patch(path, json={"source": source, "request_options": options}).status_code == 422
        changed = ok(client.patch(path, json={"source": source}))
        assert changed["request_options"] == {**DEFAULTS, "streaming": False}


def test_request_options_are_strict_and_kind_source_scoped():
    base = dict(name="Local", alias="local", kind="llm", model_ref="llms/model", source={"type": "local"})
    assert ModelInput(**base).request_options.model_dump() == DEFAULTS
    for options in ({"streaming": "false"}, {"skip_tool_capability_check": 1}, {"json_schema": True}):
        with pytest.raises(ValidationError):
            ModelInput(**base, request_options=options)
    with pytest.raises(ValidationError):
        ModelInput(**base, capabilities={})
    for flag in ("skip_tool_capability_check", "skip_vision_capability_check"):
        with pytest.raises(ValidationError):
            ModelInput(**{**base, "source": {"type": "provider", "provider_profile_id": "p"}}, request_options={flag: True})
    embedding = {**base, "kind": "embedding", "source": None}
    assert ModelInput(**embedding).request_options is None
    with pytest.raises(ValidationError):
        ModelInput(**embedding, request_options=DEFAULTS)


def test_migration_discards_declarations_and_preserves_records_and_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.RUNTIME_ALWAYS_ENABLED_REVISION)
    kept = tmp_path / "data/models/llms/model/model.gguf"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"model")
    with Session(engine) as db:
        db.execute(text("""INSERT INTO model_profiles
            (id,alias,name,kind,model_ref,capabilities_json,parameters_json,enabled,external_enabled,created_at,updated_at)
            VALUES ('keep','keep','Keep','llm','llms/model',:caps,'{}',1,0,'2026-01-01','2026-01-01')"""),
            {"caps": '{"streaming":false,"vision":true,"tools":true}'})
        db.commit()
    migrations.upgrade(engine)
    assert "capabilities_json" not in migrations.inspect_schema(engine).columns["model_profiles"]
    assert ModelProfileStore(engine).get("keep").request_options.model_dump() == DEFAULTS
    assert kept.read_bytes() == b"model"
    engine.dispose()


@pytest.mark.parametrize("projector", [False, True])
def test_gguf_only_missing_projector_is_conclusive(tmp_path, projector):
    directory = write_local_model(tmp_path, "llms/model", "llama-server")
    if projector:
        (directory / "mmproj.gguf").write_bytes(b"fixture")
    profile = resolve_local_profile(tmp_path, ModelProfile(name="m", alias="m", kind="llm", model_ref="llms/model", source={"type": "local"}))
    support = local_chat_support(profile)
    assert support.tools.state == "unknown"
    assert support.vision.state == ("unknown" if projector else "unsupported")


def install_fake_worker(app, client, tmp_path, monkeypatch, *, engine="transformers", tools=False, vision=False,
                        options=None, release="manual"):
    """Keep real admission, adapters and HTTP serialization, replacing only process loading."""
    write_local_model(tmp_path, "llms/model", engine)
    profile = ok(client.post("/api/models/profiles", json={"name": "Local", "alias": "local", "kind": "llm",
        "model_ref": "llms/model", "source": {"type": "local", "lifecycle": {"unload": release}},
        "request_options": options or DEFAULTS, "external_enabled": True}))
    state = app.state.runtime_state
    manager = state.model_manager
    monkeypatch.setattr(manager, "events", None)
    monkeypatch.setattr(manager.runtime_supervisor, "assert_available", lambda **_: None)
    resolved = manager.profile(profile["id"])
    adapter = manager._managed_slot(resolved).adapter
    upstream = ToolOpenAI(completion(content="answered"))
    monkeypatch.setattr(adapter, "begin_trace", lambda *_, **__: None)

    async def load(*_, **__):
        adapter.tool_calls_supported, adapter.vision_supported = tools, vision
        adapter.state = "ready"
        adapter.failed = False
        if adapter.openai is None:
            adapter.openai = upstream.factory(ExternalConnection(base_url="http://worker.test/v1"))
        return ModelStatus(state="ready", residency="loaded", unload_supported=True)

    monkeypatch.setattr(adapter, "load", AsyncMock(side_effect=load))
    ok(client.patch("/api/models/settings", json={"default_model_profile_id": profile["id"],
        "external_enabled": True, "external_api_key": "test-key"}))
    return profile, adapter, upstream


@pytest.mark.parametrize("memory", [True, False])
@pytest.mark.parametrize("streaming", [True, False])
def test_chat_drops_images_and_tools_persists_warning_and_retry_recomputes(tmp_path, monkeypatch, memory, streaming):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "data/attachments"))
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'chat.db'}")
    with TestClient(app) as client:
        profile, adapter, upstream = install_fake_worker(app, client, tmp_path, monkeypatch,
            options={**DEFAULTS, "streaming": streaming}, release="after_request")
        session = ok(client.post("/api/sessions", json={"harness_enabled": True, "tools_allowed": ["base64_encode"]}))
        attachment = ok(client.post("/api/attachments", files={"file": ("picture.png", image_bytes(), "image/png")}))
        path = f"/api/sessions/{session['session_id']}/messages"
        response = ok(client.post(path, json={"content": "Describe this", "attachments": [attachment]}))
        assert response["success"], response
        assert len(upstream.calls) == 1 and adapter.load.await_count == 1
        assert not upstream.calls[0].get("tools")
        assert all(isinstance(m["content"], str) for m in upstream.calls[0]["messages"])
        assert upstream.calls[0]["stream"] == streaming
        user = next(m for m in response["messages"] if m["role"] == "user")
        expected = {"run_id": response["run"]["run_id"], "codes": ["images_ignored", "tools_ignored"]}
        assert user["metadata"]["request_warnings"] == expected
        assert user["metadata"]["attachments"] == [attachment]
        assert ok(client.get(path))[0]["metadata"]["request_warnings"] == expected
        assert ok(client.get(f"/api/sessions/{session['session_id']}"))["harness_enabled"]
        assert adapter.state == "stopped"
        events = app.state.runtime_state.events._events
        assert any(event.type == "message_updated" and event.message_id == user["message_id"] and event.payload.get("message", {}).get("metadata", {}).get("request_warnings") == expected for event in events)
        provider = configure_model(client, alias="provider")
        ok(client.patch(f"/api/sessions/{session['session_id']}", json={"model_profile_id": provider["id"], "harness_enabled": False}))
        # Replace the provider transport with the same scripted responder for a successful retry.
        app.state.runtime_state.model_manager.adapter_factory = upstream.factory
        retried = ok(client.post(f"/api/runs/{response['run']['run_id']}/retry"))
        assert retried["success"], retried
        refreshed = next(m for m in ok(client.get(path)) if m["message_id"] == user["message_id"])
        assert "request_warnings" not in refreshed["metadata"]
        assert refreshed["metadata"]["attachments"] == [attachment]


@pytest.mark.parametrize("engine", ["llama-server", "transformers"])
def test_image_only_stops_without_generation_or_auxiliary_title(tmp_path, monkeypatch, engine):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "data/attachments"))
    app = create_app(root=tmp_path, use_memory=True)
    with TestClient(app) as client:
        _, adapter, upstream = install_fake_worker(app, client, tmp_path, monkeypatch, engine=engine, release="after_request")
        session = ok(client.post("/api/sessions", json={}))
        attachment = ok(client.post("/api/attachments", files={"file": ("picture.png", image_bytes(), "image/png")}))
        runner = app.state.runtime_state.chat_runner
        monkeypatch.setattr(runner, "maybe_title", AsyncMock())
        response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "", "attachments": [attachment]}))
        assert not response["success"] and response["run"]["status"] == "FAILED"
        assert upstream.calls == []
        runner.maybe_title.assert_not_awaited()
        assert response["messages"][0]["metadata"]["request_warnings"]["codes"] == ["images_require_text"]
        assert adapter.load.await_count == (1 if engine == "transformers" else 0)
        assert adapter.state == "stopped"


@pytest.mark.parametrize("feature", ["tools", "vision"])
@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_public_local_support_checks_and_private_override(tmp_path, monkeypatch, feature, skip, stream):
    app = create_app(root=tmp_path, use_memory=True)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        flag = "skip_tool_capability_check" if feature == "tools" else "skip_vision_capability_check"
        _, adapter, upstream = install_fake_worker(app, client, tmp_path, monkeypatch, options={**DEFAULTS, flag: skip})
        body = {"model": "local", "messages": [{"role": "user", "content": [part()] if feature == "vision" else "hello"}], "stream": stream}
        if feature == "tools":
            body["tools"] = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=body)
        assert response.status_code == (200 if skip else 422), response.text
        if skip:
            assert upstream.calls[0]["cogita_request_options"][flag] is True
            assert upstream.calls[0]["messages"] == body["messages"] if feature == "tools" else "image_url" in json.dumps(upstream.calls[0])
        else:
            assert not upstream.calls
            assert response.headers["content-type"].startswith("application/json")
        body["cogita_request_options"] = {flag: True}
        assert client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=body).status_code == 400


def test_worker_override_is_typed_and_removed_before_generation():
    calls = []
    engine = TransformersEngine.__new__(TransformersEngine)
    engine.metadata = {"tool_calls": False, "vision": False}
    engine.manager = engine.generation = None
    engine.close = lambda: None

    class Handler:
        def __init__(self, *_):
            pass

        async def handle_request(self, body, request_id):
            calls.append(body)
            return {"accepted": True}

    engine.handler_type = Handler
    body = {"model": "managed", "messages": [{"role": "user", "content": [part()]}],
        "tools": [{"type": "function", "function": {"name": "lookup"}}]}
    with TestClient(build_app(engine, "token")) as client:
        headers = {"Authorization": "Bearer token"}
        assert client.post("/v1/chat/completions", headers=headers, json=body).status_code == 422
        body["cogita_request_options"] = {"skip_vision_capability_check": True, "skip_tool_capability_check": False}
        assert client.post("/v1/chat/completions", headers=headers, json=body).status_code == 422
        body["cogita_request_options"]["skip_tool_capability_check"] = True
        assert client.post("/v1/chat/completions", headers=headers, json=body).status_code == 200
        assert "cogita_request_options" not in calls[0]
        body["cogita_request_options"]["skip_tool_capability_check"] = "true"
        assert client.post("/v1/chat/completions", headers=headers, json=body).status_code == 422



def test_history_images_are_omitted_without_rewriting_old_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "data/attachments"))
    app = create_app(root=tmp_path, use_memory=True)
    with TestClient(app) as client:
        _, _, upstream = install_fake_worker(app, client, tmp_path, monkeypatch, engine="llama-server")
        session = ok(client.post("/api/sessions", json={}))
        attachment = ok(client.post("/api/attachments", files={"file": ("old.png", image_bytes(), "image/png")}))
        old = app.state.runtime_state.messages.add_message(session["session_id"], "user", "",
            metadata={"attachments": [attachment]})
        response = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Continue in text"}))
        assert response["success"], response
        messages = upstream.calls[0]["messages"]
        assert not any(m["role"] == "user" and not m["content"] for m in messages)
        assert all(isinstance(m["content"], str) for m in messages)
        current = next(m for m in response["messages"] if m["role"] == "user")
        assert current["metadata"]["request_warnings"]["codes"] == ["images_ignored"]
        assert app.state.runtime_state.messages.get_message(old.message_id).metadata == {"attachments": [attachment]}


@pytest.mark.parametrize("supported,skip", [(True, False), (False, True)])
def test_harness_sends_tools_when_supported_or_explicitly_unchecked(tmp_path, monkeypatch, supported, skip):
    app = create_app(root=tmp_path, use_memory=True)
    with TestClient(app) as client:
        _, adapter, upstream = install_fake_worker(app, client, tmp_path, monkeypatch, tools=supported,
            options={**DEFAULTS, "skip_tool_capability_check": skip})
        upstream.turns = [completion(tool_call()), completion(content="finished")]
        session = ok(client.post("/api/sessions", json={"harness_enabled": True, "tools_allowed": ["base64_encode"]}))
        result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Encode hello"}))
        assert result["success"], result
        assert len(upstream.calls) == 2 and adapter.load.await_count == 1
        assert upstream.calls[0]["tools"]
        assert any(part["type"] == "tool_result" for message in result["messages"] for part in message["parts"])
        assert "request_warnings" not in result["messages"][0]["metadata"]
