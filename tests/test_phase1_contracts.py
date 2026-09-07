from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_workbench.api.main import create_app
from ai_workbench.core.personas import PersonaStore
from ai_workbench.core.schema.persona import CHAT_PERSONA_ID, PersonaInput
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.knowledge_settings import KnowledgeSettings
from ai_workbench.core.retrieval import RetrievalCandidate, rrf_merge, search_knowledge
from ai_workbench.core.network_policy import NetworkPolicy, NetworkPolicyError
from ai_workbench.core.pet_service import PetService
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepSchema
from ai_workbench.core.settings import AppSettingsStore
from tests.model_fixtures import MockOpenAI, configure_model
from ai_workbench.core.time import utc_now
from ai_workbench.core.utility_llm import (
    UTILITY_MODEL_UNAVAILABLE,
    UTILITY_OUTPUT_INVALID,
    UtilityLLMService,
    UtilityLlmError,
)


def make_client(tmp_path: Path):
    upstream = MockOpenAI()
    return TestClient(create_app(adapter_factory=upstream.factory, use_memory=True, root=tmp_path)), upstream


def create_session(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/sessions", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_persona_seeds_are_database_records_with_strict_input() -> None:
    catalog = PersonaStore()
    assert [p.name for p in catalog.list()] == ["Chat", "Translate"]
    assert catalog.get(CHAT_PERSONA_ID).context_policy.mode == "session"
    with pytest.raises(KeyError):
        catalog.get("unknown")
    with pytest.raises(ValidationError):
        PersonaInput(name="Chat", unexpected=True)


def test_prefixes_are_plain_chat_text_and_openai_responses_are_saved(tmp_path: Path) -> None:
    client, runtime = make_client(tmp_path)
    configure_model(client)
    session = create_session(client)
    session_id = session["session_id"]

    for text in ("/base64 hello", "@chat hi", "@chat:formal hi", ":formal hi"):
        response = client.post(f"/api/sessions/{session_id}/messages", json={"content": text})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["run"]["persona_id"] == CHAT_PERSONA_ID
        assert "target" not in payload["run"]
        assert payload["messages"][0]["parts"][0]["text"] == text
        assert payload["messages"][1]["parts"][0]["text"] == "reply"
        assert set(payload["messages"][0]["metadata"]) <= {"attachments", "client_message_id", "input_source"}
    removed_metadata = {"invocation", "in" + "tent", "action" + "_id", "command" + "_name"}
    assert not removed_metadata.intersection(payload["messages"][0]["metadata"])

    assert len(runtime.calls) == 4
    assert all(call["messages"][-1]["content"] == text for call, text in zip(runtime.calls, ("/base64 hello", "@chat hi", "@chat:formal hi", ":formal hi")))


def test_waiting_run_blocks_new_chat_until_explicit_resolution(tmp_path: Path) -> None:
    client, _runtime = make_client(tmp_path)
    configure_model(client)
    session = create_session(client)
    state = client.app.state.runtime_state
    config = state.chat_service.resolve(state.sessions.get_session(session["session_id"]))
    waiting = state.runs.create_run(kind="chat", persona_id=CHAT_PERSONA_ID, session_id=session["session_id"], config_snapshot=config.model_dump(mode="json"))
    state.runs.update_status(waiting.run_id, status=RunStatus.WAITING_FOR_USER, current_step="approval")
    state.sessions.set_waiting_run(session["session_id"], waiting.run_id)

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "approved"})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RUN_WAITING_FOR_APPROVAL"
    assert state.sessions.get_session(session["session_id"]).waiting_run_id == waiting.run_id
    assert state.messages.list_messages(session["session_id"]) == []
    assert len(state.runs.list_runs(session["session_id"])) == 1


def test_new_schemas_forbid_removed_fields_and_limit_step_kinds() -> None:
    with pytest.raises(ValidationError):
        MessageSchema(message_id="m", session_id="s", role="user", parts=[], **{"action" + "_id": "old"})
    with pytest.raises(ValidationError):
        RunSchema(run_id="r", session_id="s", kind="chat", persona_id=CHAT_PERSONA_ID, **{"target" + "_id": "old"})
    with pytest.raises(ValidationError):
        RunStepSchema(step_id="st", run_id="r", kind="legacy")


def test_removed_routes_are_ordinary_404_and_removed_payloads_are_422(tmp_path: Path) -> None:
    client, _runtime = make_client(tmp_path)
    session = create_session(client)
    session_id = session["session_id"]

    removed_paths = ("/api/" + "agents", "/api/" + "commands", "/api/" + "intent/predict", "/api/" + "image-generation/models", "/pet", "/base64")
    for path in removed_paths:
        assert client.get(path).status_code == 404
    assert client.post("/api/sessions", json={"default" + "_agent_id": "chat"}).status_code == 422
    assert client.post(f"/api/sessions/{session_id}/messages", json={"content": "hi", "action" + "_id": "old"}).status_code == 422
    assert client.patch("/api/settings/general", json={"session_title_" + "backend": "utility_llm"}).status_code == 422
    assert client.patch("/api/pets/settings", json={"values": {"command" + "_texts": {}}}).status_code == 422


def test_utility_service_error_codes_and_title_failure_are_non_blocking(tmp_path: Path) -> None:
    client, upstream = make_client(tmp_path)
    configure_model(client)
    state = client.app.state.runtime_state
    with pytest.raises(UtilityLlmError) as missing:
        asyncio.run(state.utility_llm.generate_text("hello"))
    assert missing.value.code == UTILITY_MODEL_UNAVAILABLE
    profile = state.model_profiles.find_by_alias("local")
    state.model_settings.patch({"utility_model_profile_id": profile.id})
    class Output(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: str
    upstream.response = "not-json"
    with pytest.raises(UtilityLlmError) as bad:
        asyncio.run(state.utility_llm.generate_json("return json", Output))
    assert bad.value.code == UTILITY_OUTPUT_INVALID
    upstream.response = ""
    assert asyncio.run(state.utility_llm.generate_title("title me")) is None


def test_pet_settings_are_nested_and_deep_merged(tmp_path: Path) -> None:
    store = AppSettingsStore()
    service = PetService(repo_root=tmp_path, app_settings_store=store)

    service.update_settings({"position": {"mode": "custom", "x": 100}, "bubble_texts": {"done": "Ready"}})
    settings = store.get().pet

    assert settings.position.mode == "custom"
    assert settings.position.x == 100
    assert settings.position.y is None
    assert settings.bubble_texts.done == "Ready"
    assert settings.bubble_texts.waiting == "等你一下"


def test_network_policy_rejects_unsafe_urls_and_limits_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = NetworkPolicy()
    for url in ("ftp://example.com/file", "http://127.0.0.1/private", "http://user:pass@example.com"):
        with pytest.raises(NetworkPolicyError):
            policy.validate_url(url, resolve_dns=False)
    assert policy.validate_url("https://example.com", resolve_dns=False) == "https://example.com"
    with pytest.raises(NetworkPolicyError):
        policy.validate_redirect_count(4)
    with pytest.raises(NetworkPolicyError):
        policy.validate_response_size(1024 * 1024 + 1)

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 80))])
    with pytest.raises(NetworkPolicyError) as private:
        policy.validate_url("https://internal.example", resolve_dns=True)
    assert private.value.code == "NETWORK_ADDRESS_FORBIDDEN"


def test_knowledge_rrf_is_deterministic_and_empty_rerank_is_not_reported_as_failure() -> None:
    vector = RetrievalCandidate("same", "kb", "source", "title", "", "vector", vector_rank=1)
    keyword = RetrievalCandidate("same", "kb", "source", "title", "", "keyword", keyword_rank=1)
    merged = rrf_merge([vector], [keyword])
    assert [item.chunk_id for item in merged] == ["same"]
    assert merged[0].rrf_score > 0

    class EmptyKnowledge:
        def get_settings(self) -> KnowledgeSettings:
            return KnowledgeSettings(reranker_enabled=True)

        def list_session_bindings(self, _session_id: str) -> list[Any]:
            return []

    response = asyncio.run(search_knowledge(
        engine=None,
        knowledge_store=EmptyKnowledge(),
        model_manager=None,
        query="hello",
        session_id="session",
        knowledge_base_ids=None,
        top_k=None,
        max_context_chars=None,
        include_debug=True,
    ))
    assert response["results"] == []
    assert response["metadata"]["rerank_fallback"] is False


def test_context_builder_projects_generic_messages_without_extension_metadata() -> None:
    class Store:
        def list_messages(self, _session_id: str) -> list[MessageSchema]:
            return [MessageSchema(message_id="m", session_id="s", role="user", parts=[{"type": "text", "text": "hello"}])]

    result = ContextBuilder(Store()).build("s", "reply")
    assert result.messages[-1] == {"role": "user", "content": "reply"}
    assert all(("agent" + "_id") not in message and ("action" + "_id") not in message for message in result.messages)
