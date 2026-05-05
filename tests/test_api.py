from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
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


def test_create_app_returns_fastapi_app() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)

    assert app.title == "Agent Workbench"


def test_list_agents_returns_builtin_agents() -> None:
    response = make_client().get("/api/agents")

    assert response.status_code == 200
    assert {"chat", "translate", "echo_script"}.issubset({agent["id"] for agent in response.json()})
    assert all("enabled" in agent for agent in response.json())


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


def test_post_message_plain_text_uses_default_agent_with_fake_llm() -> None:
    client = make_client(response="chat reply")
    session = create_session(client, default_agent_id="chat")

    payload = post_message(client, session["session_id"], "hello")

    assert payload["success"] is True
    assert payload["data"] == "chat reply"
    assert payload["run"]["target_id"] == "chat"


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
