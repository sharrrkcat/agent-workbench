"""Reasoning is a native request mode, independent of response text presentation."""
import asyncio
import json
from itertools import product
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_workbench.api.main import create_app
from ai_workbench.core.models.chat_support import ChatSupport, Support, chat_reasoning_mode, require_chat_support
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.runtimes.adapters import LlamaServerAdapter
from ai_workbench.core.models.schema import ChatRequest, ChatRequestOptions, ExternalConnection, ModelProfile
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID, USER_PERSONA_ID
from ai_workbench.workers.reasoning import generation_prefix, template_reasoning_support
from ai_workbench.workers.transformers_engine import TransformersEngine
from ai_workbench.workers.transformers_server import build_app
from tests.test_chat_request_options import DEFAULTS, install_fake_worker
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, ok, tool_call


@pytest.mark.parametrize("template,prefixes,expected", [
    ("enable_thinking <think></think>", {True: "assistant\n<think>\n", False: "assistant\n<think>\n\n</think>\n"}, ("supported", "supported")),
    ("enable_thinking <think></think>", {True: "assistant\n<think>\n", False: "assistant\n"}, ("supported", "supported")),
    ("<think></think>", {True: "assistant\n<think>\n", False: "assistant\n<think>\n"}, ("unsupported", "supported")),
    ("plain chat template", {True: "assistant\n", False: "assistant\n"}, ("unknown", "unknown")),
    ("<think></think>", {True: "assistant\n<think>\n</think>\n", False: "assistant\n<think>\n</think>\n"}, ("supported", "unsupported")),
    ("unknown reasoning_strength control", {True: "assistant", False: "assistant"}, ("unknown", "unknown")),
    ("<think> parse history", {True: "assistant", False: "assistant"}, ("unknown", "unknown")),
    (None, {True: None, False: None}, ("unknown", "unknown")),
    ("<think></think>", {True: "assistant<think>", False: None}, ("unknown", "supported")),
    ("enable_thinking <|channel>thought<channel|>", {True: "model<|channel>thought\n", False: "model"}, ("supported", "supported")),
])
def test_native_generation_prefix_evidence(template, prefixes, expected):
    support = template_reasoning_support(template, prefixes)
    assert (support["instant"], support["reasoning"]) == expected


def test_history_and_template_render_errors_are_not_mode_evidence():
    assert generation_prefix("history<think>example</think>assistant<think>", "history<think>example</think>") == "assistant<think>"
    assert generation_prefix("changed template", "original template") is None
    assert generation_prefix(None, "history") is None


@pytest.mark.parametrize("instant,reasoning,requested", product((False, True), repeat=3))
@pytest.mark.parametrize("selected,alternative", product(("supported", "unsupported", "unknown"), repeat=2))
def test_preflight_truth_table_and_chat_adjustment(instant, reasoning, requested, selected, alternative):
    profile = SimpleNamespace(request_options=ChatRequestOptions(
        skip_instant_capability_check=instant, skip_reasoning_capability_check=reasoning))
    support = ChatSupport(**{
        "reasoning" if requested else "instant": Support(selected),
        "instant" if requested else "reasoning": Support(alternative)})
    skipped = (instant, reasoning) == ((False, True) if requested else (True, False))
    adjusted = not requested if not skipped and selected == "unsupported" and alternative == "supported" else requested
    assert chat_reasoning_mode(profile, support, requested) is adjusted
    if selected == "unsupported" and not skipped:
        with pytest.raises(ModelError) as error:
            require_chat_support(profile, support, tools=False, vision=False, reasoning=requested)
        assert error.value.code == "UNSUPPORTED_CAPABILITY" and error.value.status == 422
    else:
        require_chat_support(profile, support, tools=False, vision=False, reasoning=requested)
    require_chat_support(profile, support, tools=False, vision=False, reasoning=None)


@pytest.mark.parametrize("invalid", [0, 1, "false", [], {}])
def test_reasoning_request_is_a_strict_optional_boolean(invalid):
    with pytest.raises(ValidationError):
        ChatRequest(model="m", messages=[{"role": "user", "content": "hi"}], reasoning=invalid)
    for key in ("skip_instant_capability_check", "skip_reasoning_capability_check"):
        with pytest.raises(ValidationError):
            ChatRequestOptions(**{key: invalid})


@pytest.mark.parametrize("requested", [None, False, True])
def test_provider_and_local_payloads_control_generation_without_filtering(requested):
    async def scenario():
        turn = completion(content="<think>raw thoughts</think>answer")
        turn["message"]["reasoning_content"] = "native thoughts"
        upstream = ToolOpenAI(turn)
        adapter = upstream.factory(ExternalConnection(base_url="http://provider.test/v1"))
        profile = ModelProfile(name="p", alias="p", kind="llm", model_ref="native-id",
            source={"type": "provider", "provider_profile_id": "p"})
        request = ChatRequest(model="p", messages=[{"role": "user", "content": "hi"}], reasoning=requested)
        try:
            result = await adapter.chat(profile, request)
            assert result.message.content == "<think>raw thoughts</think>answer"
            assert result.message.reasoning_content == "native thoughts"
            upstream.turns = [turn]
            chunks = [chunk async for chunk in adapter.chat_stream(profile, request.model_copy(update={"stream": True}))]
            assert "".join(chunk.delta.content or "" for chunk in chunks) == result.message.content
            assert "".join(chunk.delta.reasoning_content or "" for chunk in chunks) == "native thoughts"
            body = upstream.calls[0]
            assert "reasoning" not in body and "cogita" not in body and "chat_template_kwargs" not in body
            if requested is None:
                assert "reasoning_effort" not in body
            else:
                assert body["reasoning_effort"] == ("medium" if requested else "none")
            local = ModelProfile(name="l", alias="l", kind="llm", model_ref="llms/local", source={"type": "local"})
            body = OpenAIAdapter._payload(local, request)
            assert "reasoning_effort" not in body and "reasoning" not in body
            if requested is None:
                assert "chat_template_kwargs" not in body
            else:
                assert body["chat_template_kwargs"] == {"enable_thinking": requested}
        finally:
            await adapter.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("render_rejected", [False, True])
def test_native_gguf_preflight_uses_only_properties_and_template_rendering(render_rejected):
    async def scenario():
        calls = []
        def handle(request):
            calls.append(request.url.path)
            assert request.headers["Authorization"] == "Bearer private"
            if request.url.path == "/props":
                return httpx.Response(200, json={"chat_template": "enable_thinking <think></think>"})
            assert request.url.path == "/apply-template"
            if render_rejected:
                return httpx.Response(400, json={"error": {"message": "Template could not render this mode"}})
            body = json.loads(request.content)
            prompt = "user: Hello."
            if body["add_generation_prompt"]:
                prompt += "assistant:<think>\n" if body["chat_template_kwargs"]["enable_thinking"] else "assistant:<think>\n</think>\n"
            return httpx.Response(200, json={"prompt": prompt})
        adapter = LlamaServerAdapter.__new__(LlamaServerAdapter)
        async with httpx.AsyncClient(base_url="http://worker.test", headers={"Authorization": "Bearer private"},
                                    transport=httpx.MockTransport(handle)) as client:
            adapter.client = client
            await adapter._read_llama_reasoning_support()
        expected = "unknown" if render_rejected else "supported"
        assert adapter.reasoning_support == {"instant": expected, "reasoning": expected}
        assert calls == ["/props", *["/apply-template"] * 4]
    asyncio.run(scenario())


def test_worker_mode_checks_and_private_skip_fields():
    calls = []
    engine = TransformersEngine.__new__(TransformersEngine)
    engine.manager = engine.generation = None
    engine.close = lambda: None
    engine.metadata = {"tool_calls": True, "vision": False,
                       "reasoning_support": {"instant": "unsupported", "reasoning": "unsupported"}}
    class Handler:
        def __init__(self, *_):
            pass
        async def handle_request(self, body, request_id):
            calls.append(body)
            return {"accepted": True}
    engine.handler_type = Handler
    with TestClient(build_app(engine, "token")) as client:
        for instant, reasoning, requested in product((False, True), repeat=3):
            body = {"model": "managed", "messages": [{"role": "user", "content": "hi"}],
                    "chat_template_kwargs": {"enable_thinking": requested},
                    "cogita_request_options": {"skip_instant_capability_check": instant, "skip_reasoning_capability_check": reasoning}}
            response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer token"}, json=body)
            skipped = (instant, reasoning) == ((False, True) if requested else (True, False))
            assert response.status_code == (200 if skipped else 422)
            if skipped:
                assert calls[-1]["chat_template_kwargs"] == {"enable_thinking": requested}
                assert "cogita_request_options" not in calls[-1]
        for kwargs in ({"enable_thinking": "false"}, {"enable_thinking": 0}, {"enable_thinking": True, "other": True}):
            assert client.post("/v1/chat/completions", headers={"Authorization": "Bearer token"}, json={
                **body, "chat_template_kwargs": kwargs}).status_code == 422


@pytest.mark.parametrize("engine,streaming", product(("llama-server", "transformers"), (False, True)))
def test_public_rejection_and_home_adjustment_do_not_change_saved_mode(tmp_path, monkeypatch, engine, streaming):
    app = create_app(root=tmp_path, use_memory=True)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        profile, adapter, upstream = install_fake_worker(app, client, tmp_path, monkeypatch, engine=engine,
            options={**DEFAULTS, "streaming": streaming})
        adapter.reasoning_support = {"instant": "supported", "reasoning": "unsupported"}
        body = {"model": profile["alias"], "messages": [{"role": "user", "content": "hi"}], "reasoning": True, "stream": streaming}
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"
        assert response.headers["content-type"].startswith("application/json") and not upstream.calls
        body["reasoning"] = False
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=body)
        assert response.status_code == 200
        assert upstream.calls[-1]["chat_template_kwargs"] == {"enable_thinking": False}
        session = ok(client.post("/api/sessions", json={"model_profile_id": profile["id"]}))
        path = f"/api/sessions/{session['session_id']}"
        response = ok(client.post(path + "/messages", json={"content": "hello"}))
        assert response["success"]
        assert response["run"]["metadata"]["reasoning"] == {"requested": True, "effective": False}
        assert response["messages"][0]["metadata"]["request_warnings"]["codes"] == ["reasoning_disabled"]
        assert ok(client.get(path))["reasoning"] is True
        assert upstream.calls[-1]["chat_template_kwargs"] == {"enable_thinking": False}
        adapter.reasoning_support = {"instant": "unknown", "reasoning": "unknown"}
        retried = ok(client.post(f"/api/runs/{response['run']['run_id']}/retry"))
        assert retried["success"] and retried["run"]["metadata"]["reasoning"]["effective"] is True
        assert "request_warnings" not in retried["messages"][0]["metadata"]
        assert upstream.calls[-1]["chat_template_kwargs"] == {"enable_thinking": True}


@pytest.mark.parametrize("memory", [True, False])
def test_session_reasoning_is_independent_and_workspace_null_restores_default(tmp_path, memory):
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'chat.db'}")
    with TestClient(app) as client:
        first = configure_model(client, alias="first")
        second = configure_model(client, alias="second")
        ordinary = ok(client.post("/api/sessions", json={"model_profile_id": first["id"]}))
        assert ordinary["reasoning"] is True and ordinary["effective"]["reasoning"] is True
        path = f"/api/sessions/{ordinary['session_id']}"
        ok(client.patch(path, json={"reasoning": False}))
        assert ok(client.patch(path, json={"model_profile_id": second["id"]}))["reasoning"] is False
        assert ok(client.get(path))["effective"]["reasoning"] is False
        for value in (None, 0, "false"):
            assert client.patch(path, json={"reasoning": value}).status_code == 422
        project = ok(client.post("/api/projects", json={"kind": "workspace", "name": "Work",
            "agent_persona_id": COGITA_PERSONA_ID, "cogita_persona_id": USER_PERSONA_ID,
            "context_policy": {"mode": "session"}, "harness_enabled": False, "tools_allowed": []}))
        session = ok(client.post(f"/api/projects/{project['id']}/sessions", json={}))
        path = f"/api/sessions/{session['session_id']}"
        assert session["effective"]["reasoning"] is True
        assert ok(client.patch(path, json={"overrides": {"reasoning": False}}))["effective"]["reasoning"] is False
        assert ok(client.get(path))["overrides"]["reasoning"] is False
        restored = ok(client.patch(path, json={"overrides": {"reasoning": None}}))
        assert restored["effective"]["reasoning"] is True and "reasoning" not in restored["overrides"]


def test_adjusted_mode_survives_harness_approval_and_session_edits(tmp_path, monkeypatch):
    app = create_app(root=tmp_path, use_memory=False, database_url=f"sqlite:///{tmp_path / 'chat.db'}")
    with TestClient(app) as client:
        profile, adapter, upstream = install_fake_worker(app, client, tmp_path, monkeypatch, tools=True)
        adapter.reasoning_support = {"instant": "unsupported", "reasoning": "supported"}
        upstream.turns = [completion(tool_call("read_file", {"path": "data/knowledge/note.txt"})), completion(content="answer")]
        note = tmp_path / "data/knowledge/note.txt"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("A note")
        session = ok(client.post("/api/sessions", json={"model_profile_id": profile["id"],
            "reasoning": False, "harness_enabled": True, "tools_allowed": ["read_file"]}))
        path = f"/api/sessions/{session['session_id']}"
        waiting = ok(client.post(path + "/messages", json={"content": "read the note"}))
        run_id = waiting["run"]["run_id"]
        assert waiting["run"]["status"] == "WAITING_FOR_USER"
        assert waiting["run"]["metadata"]["reasoning"] == {"requested": False, "effective": True}
        assert app.state.runtime_state.runs.get_config_snapshot(run_id)["reasoning"] is False
        assert app.state.runtime_state.runs.get_harness_state(run_id)["reasoning"] is True
        ok(client.patch(path, json={"reasoning": True}))
        ok(client.patch(path, json={"reasoning": False}))
        response = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
        assert response["run"]["status"] == "DONE"
        assert len(upstream.calls) == 2 and all(body["chat_template_kwargs"] == {"enable_thinking": True} for body in upstream.calls)
        assert ok(client.get(path))["reasoning"] is False
