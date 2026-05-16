from fastapi.testclient import TestClient
from pathlib import Path
import asyncio

import pytest

from ai_workbench.api.main import create_app
from ai_workbench.api.ws import websocket_endpoint
from ai_workbench.core.config_schema import parse_config_schema
from ai_workbench.core.message_parts import make_image_part, make_json_part, make_text_part
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.run import RunStatus
from tests.test_prompt_agent_execution import FakeLLMRuntime, run


SVG_DATA_URL = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMjAiIGhlaWdodD0iNjAiPjx0ZXh0IHg9IjgiIHk9IjM1Ij5vazwvdGV4dD48L3N2Zz4="
)


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


def image_attachment(name: str = "image.svg", data_url: str = SVG_DATA_URL, size: int = 120, mime_type: str = "image/svg+xml") -> dict:
    return {
        "id": name,
        "type": "image",
        "mime_type": mime_type,
        "name": name,
        "size": size,
        "data_url": data_url,
    }


def create_llm_profile(client: TestClient, alias: str = "myqwen3", enabled: bool = True) -> dict:
    provider = create_provider_profile(client, name=f"{alias} Provider")
    response = client.post(
        "/api/llm-profiles",
        json={
            "alias": alias,
            "name": alias.replace("-", " ").title(),
            "provider_profile_id": provider["id"],
            "model_id": f"{alias}-model",
            "enabled": enabled,
        },
    )
    assert response.status_code == 200
    return response.json()


def create_provider_profile(client: TestClient, name: str = "Local Provider", enabled: bool = True) -> dict:
    response = client.post(
        "/api/llm-provider-profiles",
        json={
            "name": name,
            "provider": "lm_studio",
            "base_url": "http://provider/v1",
            "api_key": "secret-provider-key",
            "timeout_seconds": 45,
            "enabled": enabled,
        },
    )
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


def test_agent_config_returns_resolved_defaults_and_llm_section() -> None:
    client = make_client()

    response = client.get("/api/agent-configs/chat")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved"]["runtime"]["timeout_seconds"] == 120
    assert payload["field_sources"]["runtime.timeout_seconds"] == "default"
    assert payload["resolved"]["runtime"]["prompt"] == "You are a concise, reliable assistant.\n"
    assert payload["field_sources"]["runtime.prompt"] == "manifest"
    assert {"id": "prompt", "label": "Prompt"} in payload["resolved"]["sections"]
    assert {"id": "llm_runtime", "label": "LLM Runtime Settings", "capability_id": "llm"} in payload["resolved"]["sections"]


def test_agent_config_display_override_updates_resolved_agent_list() -> None:
    client = make_client()

    response = client.patch("/api/agent-configs/chat", json={"display": {"name": "My Chat", "avatar": "MC"}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved"]["display"]["name"] == "My Chat"
    assert payload["field_sources"]["display.name"] == "override"
    agents = client.get("/api/agents").json()
    chat = next(agent for agent in agents if agent["id"] == "chat")
    assert chat["name"] == "My Chat"
    assert chat["avatar"] == "MC"
    assert chat["resolved_display"]["avatar"] == "MC"
    assert chat["resolved_display"]["avatar_type"] == "text"


def test_agent_config_avatar_override_returns_resolved_display_avatar() -> None:
    client = make_client()

    response = client.patch("/api/agent-configs/chat", json={"display": {"avatar": "https://example.com/chat.png"}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved"]["display"]["avatar_type"] == "image"
    assert payload["resolved"]["display"]["avatar_url"] == "https://example.com/chat.png"
    assert payload["field_sources"]["display.avatar"] == "override"


def test_agent_config_resolved_avatar_uses_package_fallback_without_override(tmp_path: Path) -> None:
    client = make_client()
    register_temp_agent(client, tmp_path, "resolved_avatar", avatar="RA", files={"avatar.png": b"png-avatar"})

    response = client.get("/api/agent-configs/resolved_avatar")

    assert response.status_code == 200
    display = response.json()["resolved"]["display"]
    assert display["avatar_type"] == "image"
    assert display["avatar_url"] == "/api/agents/resolved_avatar/avatar"
    assert display["avatar"] == "RA"


def test_agent_config_empty_display_clears_override() -> None:
    client = make_client()
    client.patch("/api/agent-configs/chat", json={"display": {"name": "My Chat"}})

    response = client.patch("/api/agent-configs/chat", json={"display": {"name": ""}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["display"] == {}
    assert payload["resolved"]["display"]["name"] == "Chat Agent"
    assert payload["field_sources"]["display.name"] == "manifest"


def test_reset_overrides_keeps_user_config() -> None:
    client = make_client()
    client.patch(
        "/api/agent-configs/chat",
        json={"display": {"name": "My Chat"}, "runtime": {"timeout_seconds": 90}, "user_config": {"temperature": 0.2}},
    )

    response = client.post("/api/agent-configs/chat/reset-overrides")

    assert response.status_code == 200
    payload = response.json()
    assert payload["display"] == {}
    assert payload["runtime"] == {}
    assert payload["user_config"]["temperature"] == 0.2


def test_non_llm_agent_does_not_expose_llm_section() -> None:
    client = make_client()

    response = client.get("/api/agent-configs/echo_script")

    assert response.status_code == 200
    section_ids = [section["id"] for section in response.json()["resolved"]["sections"]]
    assert "basic" in section_ids
    assert "llm_runtime" not in section_ids


def test_agent_config_llm_profile_override_and_session_precedence() -> None:
    client = make_client()
    profile_a = create_llm_profile(client, alias="profile-a")
    profile_b = create_llm_profile(client, alias="profile-b")
    client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile_a["id"], "allow_session_override": True}})
    session = create_session(client)
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile_b["id"]})

    result = post_message(client, session["session_id"], "hello")

    assert result["success"] is True
    message = result["messages"][-1]
    assert message["metadata"]["llm_resolution"]["profile_id"] == profile_b["id"]


def test_agent_config_resolved_runtime_uses_llm_profile_override() -> None:
    client = make_client()
    profile = create_llm_profile(client, alias="profile-resolved")

    response = client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile["id"]}})

    assert response.status_code == 200
    runtime = response.json()["resolved"]["runtime"]
    assert runtime["llm_profile_id"] == profile["id"]
    assert runtime["llm_profile_label"] == profile["name"]
    assert runtime["llm_profile_model_id"] == profile["model_id"]
    assert runtime["llm_profile_source"] == "override"


def test_agent_config_disallows_session_override() -> None:
    client = make_client()
    profile_a = create_llm_profile(client, alias="profile-c")
    profile_b = create_llm_profile(client, alias="profile-d")
    client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile_a["id"], "allow_session_override": False}})
    session = create_session(client)
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile_b["id"]})

    result = post_message(client, session["session_id"], "hello")

    assert result["success"] is True
    message = result["messages"][-1]
    assert message["metadata"]["llm_resolution"]["profile_id"] == profile_a["id"]


def test_session_default_model_uses_agent_config_profile_override() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    profile = create_llm_profile(client, alias="agent-default")
    client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile["id"]}})
    session = create_session(client)

    result = post_message(client, session["session_id"], "hello")

    assert result["success"] is True
    assert llm.calls[-1]["model_config"]["model"] == profile["model_id"]
    assert result["messages"][-1]["metadata"]["llm_resolution"]["profile_id"] == profile["id"]


def test_reset_overrides_restores_manifest_profile_resolution() -> None:
    client = make_client()
    profile = create_llm_profile(client, alias="temporary-profile")
    client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile["id"]}})

    response = client.post("/api/agent-configs/chat/reset-overrides")

    assert response.status_code == 200
    runtime = response.json()["resolved"]["runtime"]
    assert runtime["llm_profile_id"] != profile["id"]
    assert runtime["llm_profile_source"] != "override"


def test_deleted_llm_profile_override_returns_missing_status_and_runtime_error() -> None:
    client = make_client()
    profile = create_llm_profile(client, alias="deleted-profile")
    client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile["id"]}})
    client.delete(f"/api/llm-profiles/{profile['id']}")

    config_response = client.get("/api/agent-configs/chat")
    session = create_session(client)
    run_response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})

    assert config_response.json()["resolved"]["runtime"]["llm_profile_status"] == "missing"
    assert run_response.status_code == 200
    assert run_response.json()["run"]["status"] == "FAILED"
    assert run_response.json()["run"]["error"] == f"LLM profile not found: {profile['id']}"


def test_disabled_saved_llm_profile_override_returns_disabled_status_and_runtime_error() -> None:
    client = make_client()
    profile = create_llm_profile(client, alias="later-disabled-profile")
    client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile["id"]}})
    client.patch(f"/api/llm-profiles/{profile['id']}", json={"enabled": False})

    config_response = client.get("/api/agent-configs/chat")
    session = create_session(client)
    run_response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})

    assert config_response.json()["resolved"]["runtime"]["llm_profile_status"] == "disabled"
    assert run_response.status_code == 200
    assert run_response.json()["run"]["status"] == "FAILED"
    assert run_response.json()["run"]["error"] == f"LLM profile is disabled: {profile['alias']}"


def test_disabled_llm_profile_override_returns_clear_error() -> None:
    client = make_client()
    profile = create_llm_profile(client, alias="disabled-profile", enabled=False)

    response = client.patch("/api/agent-configs/chat", json={"runtime": {"llm_profile_id": profile["id"]}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LLM_PROFILE_DISABLED"


def test_provider_profile_api_masks_secret_and_supports_crud_duplicate() -> None:
    client = make_client()
    provider = create_provider_profile(client)

    assert provider["api_key"] == "********"
    assert provider["api_key_set"] is True
    assert "secret-provider-key" not in str(provider)

    patched = client.patch(
        f"/api/llm-provider-profiles/{provider['id']}",
        json={"base_url": "http://patched/v1", "timeout_seconds": 30, "enabled": False},
    )
    assert patched.status_code == 200
    assert patched.json()["base_url"] == "http://patched/v1"
    assert patched.json()["timeout_seconds"] == 30
    assert patched.json()["enabled"] is False

    duplicate = client.post(f"/api/llm-provider-profiles/{provider['id']}/duplicate")
    assert duplicate.status_code == 200
    assert duplicate.json()["name"].endswith("copy")
    assert duplicate.json()["api_key_set"] is True


def test_provider_profile_delete_rejects_when_model_profile_uses_it() -> None:
    client = make_client()
    provider = create_provider_profile(client)
    response = client.post(
        "/api/llm-profiles",
        json={
            "alias": "provider_model",
            "name": "Provider Model",
            "provider_profile_id": provider["id"],
            "model_id": "model-id",
        },
    )
    assert response.status_code == 200

    delete_response = client.delete(f"/api/llm-provider-profiles/{provider['id']}")

    assert delete_response.status_code == 409
    assert delete_response.json()["error"]["code"] == "LLM_PROVIDER_PROFILE_IN_USE"


def test_model_profile_provider_reference_duplicate_and_default_resolution() -> None:
    llm = FakeLLMRuntime(response="reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    provider = create_provider_profile(client)
    profile_response = client.post(
        "/api/llm-profiles",
        json={
            "alias": "provider_model",
            "name": "Provider Model",
            "provider_profile_id": provider["id"],
            "model_id": "provider-model",
            "supports_streaming": False,
            "supports_vision": True,
        },
    )
    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["provider_profile_id"] == provider["id"]

    duplicate = client.post(f"/api/llm-profiles/{profile['id']}/duplicate")
    assert duplicate.status_code == 200
    assert duplicate.json()["provider_profile_id"] == provider["id"]
    assert duplicate.json()["name"].endswith("copy")

    defaults = client.patch("/api/settings/llm-defaults", json={"default_model_profile_id": profile["id"]})
    assert defaults.status_code == 200
    assert client.get("/api/settings/llm-defaults").json()["default_model_profile_id"] == profile["id"]

    state = client.app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(update={"model": None, "llm": None})
    session = create_session(client)
    result = post_message(client, session["session_id"], "hello")

    assert result["success"] is True
    assert llm.calls[-1]["model_config"]["base_url"] == "http://provider/v1"
    assert llm.calls[-1]["model_config"]["model"] == "provider-model"
    assert result["messages"][-1]["metadata"]["llm_resolution"]["profile_id"] == profile["id"]
    assert result["messages"][-1]["metadata"]["llm_resolution"]["provider_profile_id"] == provider["id"]


def test_write_manifest_requires_confirm() -> None:
    client = make_client()

    response = client.post("/api/agent-configs/chat/write-manifest", json={"confirm": False})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_MANIFEST_WRITE_CONFIRM_REQUIRED"


def test_prompt_override_affects_prompt_agent_runtime() -> None:
    runtime = FakeLLMRuntime(response="ok")
    client = TestClient(create_app(llm_runtime=runtime, use_memory=True))
    client.patch("/api/agent-configs/chat", json={"runtime": {"prompt": "Custom system prompt"}})
    session = create_session(client)

    result = post_message(client, session["session_id"], "hello")

    assert result["success"] is True
    assert runtime.calls[0]["messages"][0] == {"role": "system", "content": "Custom system prompt"}


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


def test_unknown_command_returns_structured_api_error_without_run() -> None:
    client = make_client()
    session = create_session(client)

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/pppp"})
    runs = client.get(f"/api/sessions/{session['session_id']}/runs").json()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_command"
    assert response.json()["error"]["message"] == "Unknown command: /pppp"
    assert runs == []


def test_multiline_command_args_route_and_preserve_args() -> None:
    client = make_client()
    session = create_session(client)

    payload = post_message(client, session["session_id"], "/base64 hello\n\nworld")

    assert payload["success"] is True
    assert payload["data"] == "aGVsbG8KCndvcmxk"
    assert payload["run"]["metadata"]["args"] == "hello\n\nworld"


def test_create_session() -> None:
    session = create_session(make_client())

    assert session["session_id"]
    assert session["default_agent_id"] == "chat"
    assert session["context_mode"] == "single_assistant"


def test_patch_session_can_change_default_agent() -> None:
    client = make_client()
    session = create_session(client)

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"default_agent_id": "translate"})

    assert response.status_code == 200
    assert response.json()["default_agent_id"] == "translate"


def test_patch_session_can_change_context_mode_and_persist_separator() -> None:
    client = make_client()
    session = create_session(client)
    client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "hello"})
    before = client.get(f"/api/sessions/{session['session_id']}/messages").json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"context_mode": "group_transcript"})
    after = client.get(f"/api/sessions/{session['session_id']}/messages").json()

    assert response.status_code == 200
    assert response.json()["context_mode"] == "group_transcript"
    assert after[: len(before)] == before
    assert len(after) == len(before) + 1
    separator = after[-1]
    assert separator["role"] == "system"
    assert separator["speaker_type"] == "system"
    assert separator["origin"] == "context_mode_changed"
    assert "output_type" not in separator
    assert "content" not in separator
    assert separator["parts"][0] == {"id": "part_1", "type": "text", "format": "plain", "text": "Conversation mode changed to Group transcript"}
    assert separator["metadata"]["event_type"] == "context_mode_changed"
    assert separator["metadata"]["context_mode"] == "group_transcript"
    assert separator["metadata"]["previous_context_mode"] == "single_assistant"


def test_patch_session_same_context_mode_does_not_duplicate_separator() -> None:
    client = make_client()
    session = create_session(client)

    first = client.patch(f"/api/sessions/{session['session_id']}", json={"context_mode": "group_transcript"})
    second = client.patch(f"/api/sessions/{session['session_id']}", json={"context_mode": "group_transcript"})
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()

    assert first.status_code == 200
    assert second.status_code == 200
    separators = [message for message in messages if message["metadata"].get("event_type") == "context_mode_changed"]
    assert len(separators) == 1


def test_patch_session_can_change_llm_profile_id_and_default() -> None:
    client = make_client()
    session = create_session(client)
    profile = create_llm_profile(client)

    selected = client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})
    cleared = client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": None})

    assert selected.status_code == 200
    assert selected.json()["llm_profile_id"] == profile["id"]
    assert cleared.status_code == 200
    assert cleared.json()["llm_profile_id"] is None


def test_patch_session_unknown_llm_profile_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client)

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": "missing"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LLM_PROFILE_NOT_FOUND"


def test_patch_session_disabled_llm_profile_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client)
    profile = create_llm_profile(client, enabled=False)

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LLM_PROFILE_DISABLED"


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


def test_patch_comfyui_agent_config_rejects_unset_enum_business_value() -> None:
    response = make_client().patch("/api/agent-configs/comfyui_agent", json={"user_config": {"default_input_mode": "unset"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CONFIG_OPTION"


def test_patch_comfyui_agent_config_clears_empty_enum_override_to_default() -> None:
    client = make_client()

    response = client.patch(
        "/api/agent-configs/comfyui_agent",
        json={"user_config": {"default_input_mode": "raw", "llm_operation_default": "fresh"}},
    )
    assert response.status_code == 200
    assert response.json()["user_config"]["default_input_mode"] == "raw"
    assert response.json()["user_config"]["llm_operation_default"] == "fresh"

    response = client.patch(
        "/api/agent-configs/comfyui_agent",
        json={"user_config": {"default_input_mode": None, "llm_operation_default": ""}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "default_input_mode" not in payload["user_config"]
    assert "llm_operation_default" not in payload["user_config"]
    assert payload["resolved_config"]["default_input_mode"] == "llm"
    assert payload["resolved_config"]["llm_operation_default"] == "refine"


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
    provider = create_provider_profile(client)

    created = client.post(
        "/api/llm-profiles",
        json={
            "alias": "myqwen3",
            "name": "My Qwen3",
            "provider_profile_id": provider["id"],
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
    provider = create_provider_profile(client)
    body = {"alias": "myqwen3", "name": "My Qwen3", "model_id": "qwen3", "provider_profile_id": provider["id"]}

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
    provider = create_provider_profile(client)
    created = client.post(
        "/api/llm-profiles",
        json={"alias": "profile1", "name": "Profile 1", "provider_profile_id": provider["id"], "model_id": "profile-model"},
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
    assert "content" not in payload["messages"][-1]
    assert payload["messages"][-1]["parts"][0] == {"id": "part_1", "type": "text", "format": "plain", "text": "aGVsbG8="}


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


def test_session_model_change_inserts_event_before_next_user_message() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)
    profile = create_llm_profile(client, alias="myqwen3")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})

    payload = post_message(client, session["session_id"], "hello")

    assert "output_type" not in payload["messages"][0]
    assert payload["messages"][0]["parts"][0]["type"] == "text"
    assert payload["messages"][0]["metadata"]["event_type"] == "model_changed"
    assert payload["messages"][0]["metadata"]["profile_id"] == profile["id"]
    assert payload["messages"][1]["role"] == "user"


def test_multiple_session_model_changes_insert_only_final_event() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)
    first = create_llm_profile(client, alias="first")
    second = create_llm_profile(client, alias="second")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": first["id"]})
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": second["id"]})

    payload = post_message(client, session["session_id"], "hello")

    events = [message for message in payload["messages"] if message["metadata"].get("event_type") == "model_changed"]
    assert len(events) == 1
    assert events[0]["metadata"]["profile_id"] == second["id"]


def test_switching_session_model_back_to_default_inserts_default_event() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)
    profile = create_llm_profile(client, alias="myqwen3")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})
    post_message(client, session["session_id"], "first")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": None})

    payload = post_message(client, session["session_id"], "second")

    assert "output_type" not in payload["messages"][0]
    assert payload["messages"][0]["parts"][0]["text"] == "Session model switched to Default"
    assert payload["messages"][0]["metadata"]["is_default"] is True


def test_session_model_override_records_resolution_metadata() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)
    profile = create_llm_profile(client, alias="myqwen3")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})

    payload = post_message(client, session["session_id"], "hello")
    resolution = payload["run"]["metadata"]["llm_resolution"]

    assert llm.calls[-1]["model_config"]["model"] == "myqwen3-model"
    assert resolution["source"] == "session_override"
    assert resolution["profile_id"] == profile["id"]
    assert resolution["session_override_applied"] is True
    assert payload["messages"][-1]["metadata"]["llm_resolution"]["source"] == "session_override"


def test_locked_agent_records_session_override_requested_but_not_applied() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    state = client.app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(
        update={"llm": {"profile": "locked", "allow_session_override": False}, "model": None}
    )
    create_llm_profile(client, alias="locked")
    session_profile = create_llm_profile(client, alias="session")
    session = create_session(client, default_agent_id="chat")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": session_profile["id"]})

    payload = post_message(client, session["session_id"], "hello")
    resolution = payload["run"]["metadata"]["llm_resolution"]

    assert llm.calls[-1]["model_config"]["model"] == "locked-model"
    assert resolution["source"] == "agent_llm_profile"
    assert resolution["session_override_requested"] == session_profile["id"]
    assert resolution["session_override_applied"] is False


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


def test_session_timeline_includes_failed_run_notification_with_stable_created_at() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    user = state.messages.add_message(session_id=session["session_id"], role="user", content="hello")
    run_record = state.runs.create_run(
        kind="agent",
        target_id="chat",
        session_id=session["session_id"],
        metadata={"input_message_id": user.message_id},
    )
    failed_run = state.runs.update_status(run_record.run_id, RunStatus.FAILED, error="boom")

    response = client.get(f"/api/sessions/{session['session_id']}/timeline")

    assert response.status_code == 200
    notification = [item["notification"] for item in response.json() if item["kind"] == "notification"][0]
    assert notification["id"] == f"run-error:{failed_run.run_id}"
    assert notification["code"] == "RUN_FAILED"
    assert notification["message"] == "boom"
    assert notification["created_at"].endswith("Z") or notification["created_at"].endswith("+00:00")


def test_session_timeline_sorts_notifications_by_created_at() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    first_user = state.messages.add_message(session_id=session["session_id"], role="user", content="first")
    run_record = state.runs.create_run(
        kind="agent",
        target_id="chat",
        session_id=session["session_id"],
        metadata={"input_message_id": first_user.message_id},
    )
    failed_run = state.runs.update_status(run_record.run_id, RunStatus.FAILED, error="boom")
    second_user = state.messages.add_message(session_id=session["session_id"], role="user", content="second")

    response = client.get(f"/api/sessions/{session['session_id']}/timeline")

    assert response.status_code == 200
    ids = [
        item["message"]["message_id"] if item["kind"] == "message" else item["notification"]["id"]
        for item in response.json()
    ]
    assert ids == [first_user.message_id, f"run-error:{failed_run.run_id}", second_user.message_id]


def test_dismiss_notification_hides_timeline_item_and_preserves_run() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    message = state.messages.add_message(session_id=session["session_id"], role="user", content="hello")
    run_record = state.runs.create_run(
        kind="agent",
        target_id="chat",
        session_id=session["session_id"],
        metadata={"input_message_id": message.message_id},
    )
    failed_run = state.runs.update_status(run_record.run_id, RunStatus.FAILED, error="boom")
    notification_id = f"run-error:{failed_run.run_id}"

    response = client.post(f"/api/sessions/{session['session_id']}/notifications/{notification_id}/dismiss")
    timeline = client.get(f"/api/sessions/{session['session_id']}/timeline").json()
    preserved_run = state.runs.get_run(failed_run.run_id)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "notification_id": notification_id, "dismissed": True}
    assert [item for item in timeline if item["kind"] == "notification"] == []
    assert preserved_run.status == RunStatus.FAILED
    assert preserved_run.error == "boom"
    assert preserved_run.metadata["notification_dismissed"] is True


def test_dismiss_notification_is_idempotent_and_does_not_affect_messages() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    message = state.messages.add_message(session_id=session["session_id"], role="user", content="hello")
    run_record = state.runs.create_run(kind="agent", target_id="chat", session_id=session["session_id"])
    failed_run = state.runs.update_status(run_record.run_id, RunStatus.FAILED, error="boom")
    notification_id = f"run-error:{failed_run.run_id}"

    first = client.post(f"/api/sessions/{session['session_id']}/notifications/{notification_id}/dismiss")
    second = client.post(f"/api/sessions/{session['session_id']}/notifications/{notification_id}/dismiss")
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert messages[0]["message_id"] == message.message_id


def test_dismiss_missing_notification_returns_clear_error() -> None:
    client = make_client()
    session = create_session(client)

    response = client.post(f"/api/sessions/{session['session_id']}/notifications/run-error:missing/dismiss")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


def test_user_message_can_save_single_image_attachment() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "see image", "attachments": [image_attachment()]},
    )

    assert response.status_code == 200
    user_message = response.json()["messages"][0]
    assert user_message["role"] == "user"
    attachment = user_message["metadata"]["attachments"][0]
    assert attachment["uri"].startswith("local://attachments/")
    assert "data_url" not in attachment


def test_user_message_can_save_multiple_image_attachments() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "see images", "attachments": [image_attachment("one.svg"), image_attachment("two.svg")]},
    )

    assert response.status_code == 200
    user_message = response.json()["messages"][0]
    assert [item["name"] for item in user_message["metadata"]["attachments"]] == ["one.svg", "two.svg"]


def test_user_message_rejects_non_image_attachment_mime() -> None:
    client = make_client()
    session = create_session(client)
    attachment = image_attachment(mime_type="text/plain")
    attachment["data_url"] = "data:text/plain;base64,aGVsbG8="

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "bad", "attachments": [attachment]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ATTACHMENTS"


def test_user_message_rejects_large_image_attachment() -> None:
    client = make_client()
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "large", "attachments": [image_attachment(size=10 * 1024 * 1024 + 1)]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ATTACHMENTS"


def test_image_only_message_is_allowed_and_uses_llm_placeholder() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "", "attachments": [image_attachment()]},
    )

    assert response.status_code == 200
    user_message = response.json()["messages"][0]
    assert "content" not in user_message
    assert user_message["parts"] == []
    assert user_message["metadata"]["attachments"][0]["uri"].startswith("local://attachments/")
    sent_text = "\n".join(message["content"] for message in llm.calls[-1]["messages"])
    assert "User attached 1 image, but the selected model does not support vision." in sent_text
    assert SVG_DATA_URL not in sent_text


def test_image_base64_api_reads_current_user_message_attachment() -> None:
    client = make_client()
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "/image-base64", "attachments": [image_attachment()]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["messages"][0]["metadata"]["attachments"][0]["uri"].startswith("local://attachments/")
    assert payload["messages"][-1]["command_name"] == "/image-base64"
    assert payload["messages"][-1]["parts"][0]["type"] == "json"
    assert payload["messages"][-1]["parts"][0]["data"]["data_url"] == SVG_DATA_URL


def test_list_messages_returns_markdown_content_as_plain_string() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    state.messages.add_message(
        session_id=session["session_id"],
        role="agent",
        content="",
        parts=[make_text_part("# Title\n\n## Summary", format="markdown")],
        agent_id="render_test",
    )

    response = client.get(f"/api/sessions/{session['session_id']}/messages")

    assert response.status_code == 200
    message = response.json()[-1]
    assert "output_type" not in message
    assert "content" not in message
    assert message["parts"][0] == {"id": "part_1", "type": "text", "format": "markdown", "text": "# Title\n\n## Summary"}


def test_list_messages_returns_json_content_as_structured_object() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    state.messages.add_message(
        session_id=session["session_id"],
        role="agent",
        content="",
        parts=[make_json_part({"ok": True, "items": [1, 2]})],
        agent_id="render_test",
    )

    response = client.get(f"/api/sessions/{session['session_id']}/messages")

    assert response.status_code == 200
    message = response.json()[-1]
    assert "output_type" not in message
    assert "content" not in message
    assert message["parts"][0] == {"id": "part_1", "type": "json", "data": {"ok": True, "items": [1, 2]}}


def test_list_messages_returns_image_content_as_structured_object() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    state.messages.add_message(
        session_id=session["session_id"],
        role="agent",
        content="",
        parts=[make_image_part("https://example.test/image.png", alt="Example")],
        agent_id="render_test",
    )

    response = client.get(f"/api/sessions/{session['session_id']}/messages")

    assert response.status_code == 200
    message = response.json()[-1]
    assert "output_type" not in message
    assert "content" not in message
    assert message["parts"][0] == {"id": "part_1", "type": "image", "url": "https://example.test/image.png", "alt": "Example"}


def test_delete_user_message_removes_only_selected_message() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)
    first = post_message(client, session["session_id"], "first")
    second = post_message(client, session["session_id"], "second")
    user_message = first["messages"][0]

    response = client.delete(f"/api/messages/{user_message['message_id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "message_id": user_message["message_id"]}
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    ids = [message["message_id"] for message in messages]
    assert user_message["message_id"] not in ids
    assert second["messages"][0]["message_id"] in ids
    assert second["messages"][-1]["message_id"] in ids


def test_delete_agent_message_removes_only_selected_message() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)
    first = post_message(client, session["session_id"], "first")
    second = post_message(client, session["session_id"], "second")
    assistant_message = first["messages"][-1]

    response = client.delete(f"/api/messages/{assistant_message['message_id']}")

    assert response.status_code == 200
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    ids = [message["message_id"] for message in messages]
    assert assistant_message["message_id"] not in ids
    assert first["messages"][0]["message_id"] in ids
    assert second["messages"][-1]["message_id"] in ids


def test_delete_command_message_removes_only_selected_message() -> None:
    client = make_client()
    session = create_session(client)
    first = post_message(client, session["session_id"], "/base64 hello")
    second = post_message(client, session["session_id"], "later")
    command_message = first["messages"][-1]

    response = client.delete(f"/api/messages/{command_message['message_id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "message_id": command_message["message_id"]}
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    ids = [message["message_id"] for message in messages]
    assert command_message["message_id"] not in ids
    assert first["messages"][0]["message_id"] in ids
    assert second["messages"][0]["message_id"] in ids
    assert second["messages"][-1]["message_id"] in ids


def test_delete_missing_message_returns_structured_404() -> None:
    response = make_client().delete("/api/messages/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


def test_agent_retry_deletes_target_and_later_messages_then_regenerates() -> None:
    llm = FakeLLMRuntime(response="retry reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)
    first = post_message(client, session["session_id"], "first")
    target = first["messages"][-1]
    later = post_message(client, session["session_id"], "later")

    response = client.post(f"/api/messages/{target['message_id']}/retry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "content" not in payload["messages"][-1]
    assert payload["messages"][-1]["parts"][0]["text"] == "retry reply"
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    ids = [message["message_id"] for message in messages]
    assert target["message_id"] not in ids
    assert later["messages"][0]["message_id"] not in ids
    assert later["messages"][-1]["message_id"] not in ids
    assert messages[-1]["metadata"]["llm_resolution"]
    assert llm.calls[-1]["messages"][-1]["content"] == "first"


def test_agent_retry_without_source_user_returns_cannot_retry() -> None:
    client = make_client()
    session = create_session(client)
    state = client.app.state.runtime_state
    message = state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content="orphan",
        agent_id="chat",
        action_id="default",
    )

    response = client.post(f"/api/messages/{message.message_id}/retry")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CANNOT_RETRY_MESSAGE"


def test_user_edit_updates_content_deletes_later_messages_and_regenerates() -> None:
    llm = FakeLLMRuntime(response="edited reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)
    first = post_message(client, session["session_id"], "first")
    user_message = first["messages"][0]
    later = post_message(client, session["session_id"], "later")

    response = client.post(f"/api/messages/{user_message['message_id']}/edit", json={"content": "edited", "rerun": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    ids = [message["message_id"] for message in messages]
    assert user_message["message_id"] in ids
    assert later["messages"][0]["message_id"] not in ids
    assert later["messages"][-1]["message_id"] not in ids
    assert next(message for message in messages if message["message_id"] == user_message["message_id"])["parts"][0]["text"] == "edited"
    assert "content" not in messages[-1]
    assert messages[-1]["parts"][0]["text"] == "edited reply"
    assert messages[-1]["metadata"]["llm_resolution"]
    assert llm.calls[-1]["messages"][-1]["content"] == "edited"


def test_user_edit_rejects_assistant_message() -> None:
    client = make_client(response="chat reply")
    session = create_session(client)
    payload = post_message(client, session["session_id"], "hello")
    assistant_message = payload["messages"][-1]

    response = client.post(f"/api/messages/{assistant_message['message_id']}/edit", json={"content": "edited", "rerun": True})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CANNOT_EDIT_MESSAGE"


def test_deleted_messages_do_not_enter_context() -> None:
    llm = FakeLLMRuntime(response="reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)
    first = post_message(client, session["session_id"], "deleted text")
    client.delete(f"/api/messages/{first['messages'][0]['message_id']}")

    post_message(client, session["session_id"], "fresh")

    sent_text = "\n".join(message["content"] for message in llm.calls[-1]["messages"])
    assert "deleted text" not in sent_text


def test_retry_edit_use_current_session_model_override_and_model_change_range() -> None:
    llm = FakeLLMRuntime(response="profile reply")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)
    profile = create_llm_profile(client, alias="retryprofile")
    first = post_message(client, session["session_id"], "first")
    user_message = first["messages"][0]
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})

    retry_response = client.post(f"/api/messages/{first['messages'][-1]['message_id']}/retry")

    assert retry_response.status_code == 200
    assert llm.calls[-1]["model_config"]["model"] == "retryprofile-model"
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    assert any(message["metadata"].get("event_type") == "model_changed" and message["metadata"]["profile_id"] == profile["id"] for message in messages)
    assert messages[-1]["metadata"]["llm_resolution"]["source"] == "session_override"

    edit_response = client.post(f"/api/messages/{user_message['message_id']}/edit", json={"content": "edited again", "rerun": True})

    assert edit_response.status_code == 200
    assert llm.calls[-1]["model_config"]["model"] == "retryprofile-model"
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    assert messages[-1]["metadata"]["llm_resolution"]["source"] == "session_override"


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


def test_agent_action_text_route_preserves_raw_user_message_and_parsed_args() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="chat")

    payload = post_message(client, session["session_id"], "@render_test:image 1")

    messages = payload["messages"]
    user_message = messages[0]
    assert user_message["role"] == "user"
    assert user_message["parts"][0]["text"] == "@render_test:image 1"
    assert user_message["metadata"]["invocation"]["raw_text"] == "@render_test:image 1"
    assert user_message["metadata"]["invocation"]["args"] == "1"
    assert payload["run"]["metadata"]["args"] == "1"
    assert all("output_type" not in message for message in messages[1:])
    assert [message["parts"][0]["type"] for message in messages[1:]] == ["image", "text", "media_group"]
    assert all("llm_resolution" not in message["metadata"] for message in messages[1:])


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
    assert "content" not in messages[-1]
    assert messages[-1]["parts"][0]["text"] == "dHdv"


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


def test_session_messages_include_run_steps_after_prompt_run() -> None:
    client = make_client(response="hello")
    session = create_session(client)

    result = post_message(client, session["session_id"], "@chat hello")
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    assistant = next(message for message in messages if message.get("run_id") == result["run"]["run_id"])

    assert assistant["run"]["status"] == "DONE"
    assert [step["label"] for step in assistant["run_steps"]][-2:] == ["Saving response", "Cleanup"]
    assert "parent_step_id" in assistant["run_steps"][0]


def test_run_steps_endpoint_returns_persisted_steps() -> None:
    client = make_client(response="hello")
    session = create_session(client)
    result = post_message(client, session["session_id"], "@chat hello")

    response = client.get(f"/api/runs/{result['run']['run_id']}/steps")

    assert response.status_code == 200
    assert response.json()[0]["label"] == "Resolving agent"
    assert "parent_step_id" in response.json()[0]


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
    state = client.app.state.runtime_state

    with client.websocket_connect(f"/api/ws/{session['session_id']}") as websocket:
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    assert state.events._subscribers == []


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
    assert app.state.runtime_state.events._subscribers == []


def test_app_shutdown_closes_events_and_cancels_active_runs() -> None:
    class FakeActiveRuns:
        def __init__(self) -> None:
            self.cancelled = False

        async def cancel_all(self) -> None:
            self.cancelled = True

    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    fake_active_runs = FakeActiveRuns()
    app.state.runtime_state.active_runs = fake_active_runs
    queue = app.state.runtime_state.events.subscribe()

    with TestClient(app):
        pass

    assert fake_active_runs.cancelled is True
    assert queue.get_nowait() is None
    assert app.state.runtime_state.events._subscribers == []


def test_websocket_cancelled_path_unsubscribes_eventbus_queue() -> None:
    class FakeWebSocket:
        def __init__(self, app) -> None:
            self.app = app
            self.accepted = False

        async def accept(self) -> None:
            self.accepted = True

        async def receive_json(self) -> dict:
            await asyncio.Event().wait()
            return {}

        async def send_json(self, payload) -> None:
            pass

    async def scenario():
        app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
        websocket = FakeWebSocket(app)
        task = asyncio.create_task(websocket_endpoint(websocket, "session-1"))
        for _ in range(20):
            if app.state.runtime_state.events._subscribers:
                break
            await asyncio.sleep(0)

        task.cancel()
        await task

        assert websocket.accepted is True
        assert app.state.runtime_state.events._subscribers == []

    run(scenario())
