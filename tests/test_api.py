from fastapi.testclient import TestClient
from pathlib import Path

import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.config_schema import parse_config_schema
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.run import RunStatus
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client(response: str = "fake reply") -> TestClient:
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(response=response), use_memory=True))


def create_session(client: TestClient, default_agent_id: str = "chat") -> dict:
    response = client.post("/api/sessions", json={"title": "Test", "default_agent_id": default_agent_id})
    assert response.status_code == 200
    return response.json()


def post_message(client: TestClient, session_id: str, content: str) -> dict:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return response.json()


def register_temp_agent(
    client: TestClient,
    tmp_path: Path,
    agent_id: str,
    avatar: str = "",
    files: dict[str, bytes] | None = None,
) -> None:
    agent_dir = tmp_path / agent_id
    agent_dir.mkdir()
    for filename, content in (files or {}).items():
        (agent_dir / filename).write_bytes(content)
    agent = AgentSchema.model_validate(
        {
            "id": agent_id,
            "name": agent_id.replace("_", " ").title(),
            "type": "prompt",
            "description": "Temporary test agent",
            "avatar": avatar,
            "actions": [{"id": "default", "description": "Default"}],
            "context_policy": {"mode": "current_message"},
            "model_lifecycle": {"load": "on_demand", "unload": "never", "unload_failure": "warn"},
        }
    )
    client.app.state.runtime_state.agents.register(agent, agent_dir=agent_dir)


def test_create_app_returns_fastapi_app() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)

    assert app.title == "Agent Workbench"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:6188",
    ],
)
def test_cors_preflight_allows_localhost_and_loopback_any_port(origin: str) -> None:
    response = make_client().options(
        "/api/sessions",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_health_returns_version_database_and_schema_version() -> None:
    response = make_client().get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0-alpha"
    assert payload["database"] == "ok"
    assert payload["schema_version"] == "1"


def test_health_details_returns_registry_counts_and_masks_llm_secret() -> None:
    client = make_client()
    client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "secret-token"}})

    response = client.get("/api/health/details")

    assert response.status_code == 200
    payload = response.json()
    assert payload["registries"]["agents"] >= 3
    assert payload["registries"]["capabilities"] >= 3
    assert payload["registries"]["commands"] >= 2
    assert payload["llm"]["api_key_set"] is True
    assert "secret-token" not in str(payload)


def test_list_agents_returns_builtin_agents() -> None:
    response = make_client().get("/api/agents")

    assert response.status_code == 200
    assert {"chat", "translate", "echo_script"}.issubset({agent["id"] for agent in response.json()})
    assert all("enabled" in agent for agent in response.json())
    assert all("avatar_type" in agent for agent in response.json())


def test_agent_api_returns_manifest_llm_fields() -> None:
    client = make_client()
    state = client.app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(
        update={"llm": {"profile": "myqwen3", "allow_session_override": False, "temperature": 0.2}}
    )

    response = client.get("/api/agents/chat")

    assert response.status_code == 200
    assert response.json()["llm"] == {"profile": "myqwen3", "allow_session_override": False, "temperature": 0.2}


def test_agent_directory_avatar_png_takes_priority(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "avatar_dir", avatar="TA", files={"avatar.png": b"png-avatar"})

    response = client.get("/api/agents/avatar_dir")

    assert response.status_code == 200
    payload = response.json()
    assert payload["avatar"] is None
    assert payload["avatar_type"] == "image"
    assert payload["avatar_url"] == "/api/agents/avatar_dir/avatar"


def test_agent_directory_avatar_overrides_manifest_avatar(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "avatar_override", avatar="📝", files={"avatar.png": b"png-avatar"})

    response = client.get("/api/agents/avatar_override")

    assert response.status_code == 200
    assert response.json()["avatar_type"] == "image"
    assert response.json()["avatar"] is None


def test_agent_avatar_prefers_avatar_png_before_agent_jpg(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(
        client,
        tmp_path,
        "avatar_priority",
        files={"avatar.png": b"png-avatar", "agent.jpg": b"jpg-avatar"},
    )

    response = client.get("/api/agents/avatar_priority/avatar")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"png-avatar"


def test_agent_manifest_emoji_avatar_returns_emoji_type(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "avatar_emoji", avatar="📝")

    response = client.get("/api/agents/avatar_emoji")

    assert response.status_code == 200
    assert response.json()["avatar"] == "📝"
    assert response.json()["avatar_type"] == "emoji"
    assert response.json()["avatar_url"] is None


def test_agent_manifest_http_avatar_returns_image_url(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "avatar_url", avatar="https://example.com/avatar.png")

    response = client.get("/api/agents/avatar_url")

    assert response.status_code == 200
    assert response.json()["avatar"] is None
    assert response.json()["avatar_type"] == "image"
    assert response.json()["avatar_url"] == "https://example.com/avatar.png"


def test_agent_manifest_local_avatar_stays_inside_agent_directory(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "avatar_local", avatar="./custom.webp", files={"custom.webp": b"webp-avatar"})

    response = client.get("/api/agents/avatar_local")
    avatar_response = client.get("/api/agents/avatar_local/avatar")

    assert response.status_code == 200
    assert response.json()["avatar_type"] == "image"
    assert avatar_response.status_code == 200
    assert avatar_response.headers["content-type"].startswith("image/webp")
    assert avatar_response.content == b"webp-avatar"


def test_agent_manifest_avatar_path_escape_falls_back_to_initials(tmp_path: Path) -> None:
    client = make_client()
    (tmp_path / "outside.png").write_bytes(b"outside")
    register_temp_agent(client, tmp_path, "avatar_escape", avatar="../outside.png")

    response = client.get("/api/agents/avatar_escape")

    assert response.status_code == 200
    assert response.json()["avatar"] is None
    assert response.json()["avatar_type"] == "initials"
    assert response.json()["avatar_url"] is None


def test_agent_avatar_endpoint_returns_404_without_local_avatar(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "avatar_none", avatar="📝")

    response = client.get("/api/agents/avatar_none/avatar")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_AVATAR_NOT_FOUND"


def test_list_commands_returns_base64_commands() -> None:
    response = make_client().get("/api/commands")

    assert response.status_code == 200
    assert {"/base64", "/base64-decode"}.issubset({command["name"] for command in response.json()})
    assert all("capability_enabled" in command for command in response.json())


def test_create_session() -> None:
    session = create_session(make_client())

    assert session["session_id"]
    assert session["default_agent_id"] == "chat"


def test_patch_session_can_change_default_agent() -> None:
    client = make_client()
    session = create_session(client)

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"default_agent_id": "translate"})

    assert response.status_code == 200
    assert response.json()["default_agent_id"] == "translate"


def test_patch_session_unknown_default_agent_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client)

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"default_agent_id": "missing"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"


def test_agent_config_api_lists_builtin_agents() -> None:
    response = make_client().get("/api/agent-configs")

    assert response.status_code == 200
    payload = response.json()
    assert {"chat", "translate", "echo_script"}.issubset({item["agent_id"] for item in payload})
    assert all(item["enabled"] is True for item in payload)
    assert all("manifest_summary" in item for item in payload)


def test_patch_agent_config_can_disable_agent() -> None:
    client = make_client()

    response = client.patch("/api/agent-configs/translate", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_disabled_translate_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client)
    client.patch("/api/agent-configs/translate", json={"enabled": False})

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "@translate hello"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_DISABLED"


def test_disabled_default_agent_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="chat")
    client.patch("/api/agent-configs/chat", json={"enabled": False})

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_DISABLED"


def test_patch_unknown_agent_config_returns_404() -> None:
    response = make_client().patch("/api/agent-configs/missing", json={"enabled": False})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_CONFIG_NOT_FOUND"


def test_patch_agent_config_rejects_unknown_user_config_field() -> None:
    response = make_client().patch("/api/agent-configs/chat", json={"user_config": {"unknown": True}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_CONFIG_FIELD"


def test_patch_agent_config_rejects_missing_required_field() -> None:
    client = make_client()
    state = client.app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(
        update={
            "config_schema": parse_config_schema(
                [{"name": "token", "type": "string", "label": "Token", "required": True}]
            )
        }
    )

    response = client.patch("/api/agent-configs/chat", json={"user_config": {}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_CONFIG"


def test_capability_config_api_lists_builtin_capabilities() -> None:
    response = make_client().get("/api/capability-configs")

    assert response.status_code == 200
    payload = response.json()
    assert {"base64", "llm", "storage"}.issubset({item["capability_id"] for item in payload})
    assert all(item["enabled"] is True for item in payload)


def test_patch_capability_config_can_disable_base64() -> None:
    client = make_client()

    response = client.patch("/api/capability-configs/base64", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_disabled_base64_command_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client)
    client.patch("/api/capability-configs/base64", json={"enabled": False})

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/base64 hello"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CAPABILITY_DISABLED"


def test_patch_unknown_capability_config_returns_404() -> None:
    response = make_client().patch("/api/capability-configs/missing", json={"enabled": False})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAPABILITY_CONFIG_NOT_FOUND"


def test_patch_capability_config_rejects_unknown_user_config_field() -> None:
    response = make_client().patch("/api/capability-configs/base64", json={"user_config": {"unknown": True}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_CONFIG_FIELD"


def test_patch_capability_config_rejects_invalid_enum_option() -> None:
    response = make_client().patch("/api/capability-configs/base64", json={"user_config": {"mode": "bad"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CONFIG_OPTION"


def test_patch_capability_config_rejects_invalid_numeric_type() -> None:
    response = make_client().patch("/api/capability-configs/llm", json={"user_config": {"timeout": "slow"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CONFIG_TYPE"


def test_capability_config_masks_secret_values_and_preserves_mask_patch() -> None:
    client = make_client()

    response = client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "secret-token"}})
    assert response.status_code == 200
    assert response.json()["user_config"]["api_key"] == "********"

    response = client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "********"}})
    assert response.status_code == 200
    assert response.json()["user_config"]["api_key"] == "********"

    raw = client.app.state.runtime_state.capability_configs.get_config("llm")
    assert raw["user_config"]["api_key"] == "secret-token"


def test_capability_config_secret_new_value_updates_store() -> None:
    client = make_client()

    client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "old"}})
    response = client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "new"}})

    assert response.status_code == 200
    assert client.app.state.runtime_state.capability_configs.get_config("llm")["user_config"]["api_key"] == "new"


def test_llm_profile_api_create_list_get_patch_delete_and_masks_secret() -> None:
    client = make_client()

    created = client.post(
        "/api/llm-profiles",
        json={
            "alias": "myqwen3",
            "name": "My Qwen3",
            "provider": "llama_cpp",
            "base_url": "http://localhost:8080/v1",
            "api_key": "secret-token",
            "model_id": "qwen3",
            "supports_vision": True,
        },
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["alias"] == "myqwen3"
    assert payload["api_key"] == "********"
    assert payload["api_key_set"] is True
    assert "secret-token" not in str(payload)

    listed = client.get("/api/llm-profiles")
    assert listed.status_code == 200
    assert listed.json()[0]["alias"] == "myqwen3"

    fetched = client.get("/api/llm-profiles/myqwen3")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]

    patched = client.patch(
        "/api/llm-profiles/myqwen3",
        json={"api_key": "********", "name": "Renamed", "supports_reasoning": True},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["supports_reasoning"] is True
    assert client.app.state.runtime_state.llm_profiles.get_by_id_or_alias("myqwen3").api_key == "secret-token"

    deleted = client.delete("/api/llm-profiles/myqwen3")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "profile_id": payload["id"]}
    assert client.get("/api/llm-profiles/myqwen3").status_code == 404


def test_llm_profile_api_rejects_alias_conflict_and_invalid_alias() -> None:
    client = make_client()
    body = {"alias": "myqwen3", "name": "My Qwen3", "model_id": "qwen3", "base_url": "http://local/v1"}

    assert client.post("/api/llm-profiles", json=body).status_code == 200
    conflict = client.post("/api/llm-profiles", json={**body, "name": "Duplicate"})
    invalid = client.post("/api/llm-profiles", json={**body, "alias": "bad alias"})

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "LLM_PROFILE_ALIAS_CONFLICT"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "LLM_PROFILE_INVALID"


def test_llm_profile_test_and_models_use_profile_config() -> None:
    llm = FakeDiagnosticLLMRuntime()
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    created = client.post(
        "/api/llm-profiles",
        json={"alias": "profile1", "name": "Profile 1", "base_url": "http://profile/v1", "model_id": "profile-model"},
    ).json()

    test_response = client.post(f"/api/llm-profiles/{created['id']}/test")
    models_response = client.get("/api/llm-profiles/profile1/models")

    assert test_response.status_code == 200
    assert test_response.json()["success"] is True
    assert models_response.status_code == 200
    assert models_response.json()["models"] == [{"id": "fake-model"}]


class FakeDiagnosticLLMRuntime(FakeLLMRuntime):
    def __init__(self, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail

    def list_models(self, model_config=None):
        if self.fail:
            raise RuntimeError("offline")
        return ["fake-model"]


def test_llm_test_endpoint_success_path() -> None:
    client = TestClient(create_app(llm_runtime=FakeDiagnosticLLMRuntime(), use_memory=True))

    response = client.post("/api/capability-configs/llm/test")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["models"] == ["fake-model"]


def test_llm_test_endpoint_failure_path() -> None:
    client = TestClient(create_app(llm_runtime=FakeDiagnosticLLMRuntime(fail=True), use_memory=True))

    response = client.post("/api/capability-configs/llm/test")

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "LLM_CONNECTION_FAILED"


def test_config_user_config_must_be_object() -> None:
    response = make_client().patch("/api/agent-configs/chat", json={"user_config": "bad"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_USER_CONFIG"


def test_post_message_base64_executes_command() -> None:
    client = make_client()
    session = create_session(client)

    payload = post_message(client, session["session_id"], "/base64 hello")

    assert payload["success"] is True
    assert payload["data"] == "aGVsbG8="
    assert payload["messages"][-1]["content"] == "aGVsbG8="


def test_command_run_events_include_started_and_done() -> None:
    client = make_client()
    session = create_session(client)
    payload = post_message(client, session["session_id"], "/base64 hello")

    response = client.get(f"/api/runs/{payload['run']['run_id']}/events")

    assert response.status_code == 200
    types = [event["type"] for event in response.json()]
    assert "run_started" in types
    assert "run_done" in types


def test_post_message_plain_text_uses_default_agent_with_fake_llm() -> None:
    client = make_client(response="chat reply")
    session = create_session(client, default_agent_id="chat")

    payload = post_message(client, session["session_id"], "hello")

    assert payload["success"] is True
    assert payload["data"] == "chat reply"
    assert payload["run"]["target_id"] == "chat"


def test_prompt_run_events_include_message_done() -> None:
    client = make_client(response="chat reply")
    session = create_session(client, default_agent_id="chat")
    payload = post_message(client, session["session_id"], "hello")

    response = client.get(f"/api/runs/{payload['run']['run_id']}/events")

    assert response.status_code == 200
    assert "message_done" in [event["type"] for event in response.json()]


def test_failed_prompt_run_events_include_run_failed() -> None:
    client = make_client()
    client.app.state.runtime_state.agent_runner.llm_runtime.fail = True
    session = create_session(client, default_agent_id="chat")

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})
    payload = response.json()
    run_id = payload["run"]["run_id"]
    events = client.get(f"/api/runs/{run_id}/events").json()

    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["run"]["metadata"]["input_message_id"] == payload["messages"][0]["message_id"]
    assert "run_failed" in [event["type"] for event in events]


def test_post_message_translate_uses_fake_llm() -> None:
    client = make_client(response="hello")
    session = create_session(client)

    payload = post_message(client, session["session_id"], "@translate bonjour")

    assert payload["success"] is True
    assert payload["data"] == "hello"
    assert payload["run"]["target_id"] == "translate"


def test_list_messages_shows_user_and_output_messages() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)

    post_message(client, session["session_id"], "hello")
    response = client.get(f"/api/sessions/{session['session_id']}/messages")

    assert response.status_code == 200
    roles = [message["role"] for message in response.json()]
    assert roles == ["user", "assistant"]


def test_list_messages_returns_markdown_content_as_plain_string() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    state.messages.add_message(
        session_id=session["session_id"],
        role="agent",
        content="# Title\n\n## Summary",
        agent_id="render_test",
        output_type="markdown",
    )

    response = client.get(f"/api/sessions/{session['session_id']}/messages")

    assert response.status_code == 200
    message = response.json()[-1]
    assert message["output_type"] == "markdown"
    assert message["content"] == "# Title\n\n## Summary"


def test_list_messages_returns_json_content_as_structured_object() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    state.messages.add_message(
        session_id=session["session_id"],
        role="agent",
        content={"ok": True, "items": [1, 2]},
        agent_id="render_test",
        output_type="json",
    )

    response = client.get(f"/api/sessions/{session['session_id']}/messages")

    assert response.status_code == 200
    message = response.json()[-1]
    assert message["output_type"] == "json"
    assert message["content"] == {"ok": True, "items": [1, 2]}


def test_action_api_invokes_translate_formal() -> None:
    client = make_client(response="hello")
    session = create_session(client)
    first = post_message(client, session["session_id"], "@translate bonjour")
    source_message = first["messages"][-1]

    response = client.post(
        f"/api/sessions/{session['session_id']}/actions",
        json={
            "agent_id": "translate",
            "action_id": "formal",
            "source_message_id": source_message["message_id"],
            "input_text": "",
            "prefill": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["run"]["action_id"] == "formal"


def test_action_api_missing_source_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/actions",
        json={"agent_id": "translate", "action_id": "formal", "source_message_id": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


def test_list_session_runs() -> None:
    client = make_client()
    session = create_session(client)
    post_message(client, session["session_id"], "/base64 hello")

    response = client.get(f"/api/sessions/{session['session_id']}/runs")

    assert response.status_code == 200
    assert response.json()[0]["target_id"] == "/base64"


def test_delete_session_removes_session_messages_and_runs() -> None:
    client = make_client()
    session = create_session(client)
    post_message(client, session["session_id"], "/base64 hello")

    response = client.delete(f"/api/sessions/{session['session_id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "session_id": session["session_id"]}
    assert client.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert client.get(f"/api/sessions/{session['session_id']}/messages").status_code == 404
    assert client.get(f"/api/sessions/{session['session_id']}/runs").status_code == 404


def test_delete_missing_session_returns_structured_404() -> None:
    response = make_client().delete("/api/sessions/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_delete_waiting_session_clears_and_removes_waiting_run() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    run = app.state.runtime_state.runs.create_run(kind="agent", target_id="chat", session_id=session["session_id"])
    app.state.runtime_state.runs.update_status(run.run_id, RunStatus.WAITING_FOR_USER, current_step="waiting")
    app.state.runtime_state.sessions.set_waiting_run(session["session_id"], run.run_id)

    response = client.delete(f"/api/sessions/{session['session_id']}")

    assert response.status_code == 200
    assert client.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert client.get(f"/api/runs/{run.run_id}").status_code == 404


def test_delete_session_does_not_affect_other_sessions() -> None:
    client = make_client()
    first = create_session(client)
    second = create_session(client)
    post_message(client, first["session_id"], "/base64 one")
    post_message(client, second["session_id"], "/base64 two")

    response = client.delete(f"/api/sessions/{first['session_id']}")

    assert response.status_code == 200
    assert client.get(f"/api/sessions/{first['session_id']}").status_code == 404
    assert client.get(f"/api/sessions/{second['session_id']}").status_code == 200
    messages = client.get(f"/api/sessions/{second['session_id']}/messages").json()
    assert messages[-1]["content"] == "dHdv"


def test_cancel_running_run_marks_cancelled() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    run = app.state.runtime_state.runs.create_run(kind="agent", target_id="chat", session_id=session["session_id"])
    app.state.runtime_state.runs.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

    response = client.post(f"/api/runs/{run.run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    assert response.json()["run"]["status"] == "CANCELLED"


def test_cancel_run_records_run_cancelled_event() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    run = app.state.runtime_state.runs.create_run(kind="agent", target_id="chat", session_id=session["session_id"])
    app.state.runtime_state.runs.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

    client.post(f"/api/runs/{run.run_id}/cancel")
    response = client.get(f"/api/runs/{run.run_id}/events")

    assert response.status_code == 200
    assert "run_cancelled" in [event["type"] for event in response.json()]


def test_cancel_waiting_run_clears_session_waiting_run() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    run = app.state.runtime_state.runs.create_run(kind="agent", target_id="chat", session_id=session["session_id"])
    app.state.runtime_state.runs.update_status(run.run_id, RunStatus.WAITING_FOR_USER, current_step="waiting")
    app.state.runtime_state.sessions.set_waiting_run(session["session_id"], run.run_id)

    response = client.post(f"/api/runs/{run.run_id}/cancel")
    updated_session = client.get(f"/api/sessions/{session['session_id']}").json()

    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    assert response.json()["run"]["status"] == "CANCELLED"
    assert updated_session["waiting_run_id"] is None


def test_cancel_done_run_returns_not_cancelled() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    run = app.state.runtime_state.runs.create_run(kind="agent", target_id="chat", session_id=session["session_id"])
    app.state.runtime_state.runs.update_status(run.run_id, RunStatus.DONE, current_step="done")

    response = client.post(f"/api/runs/{run.run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["cancelled"] is False
    assert "not cancellable" in response.json()["reason"]


def test_cancel_missing_run_returns_structured_404() -> None:
    response = make_client().post("/api/runs/missing/cancel")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_missing_run_events_returns_structured_404() -> None:
    response = make_client().get("/api/runs/missing/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_websocket_ping_pong() -> None:
    client = make_client()
    session = create_session(client)

    with client.websocket_connect(f"/api/ws/{session['session_id']}") as websocket:
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}


def test_websocket_can_receive_eventbus_event() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)

    with client.websocket_connect(f"/api/ws/{session['session_id']}") as websocket:
        app.state.runtime_state.events.emit("run_started", session_id=session["session_id"], run_id="run-1")
        websocket.send_json({"type": "next_event"})
        event = websocket.receive_json()

    assert event["type"] == "run_started"
    assert event["run_id"] == "run-1"
