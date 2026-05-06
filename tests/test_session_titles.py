from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from tests.test_api import make_client
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run
from tests.test_script_agent import ScriptRuntimeFixture


class SequenceLLMRuntime(FakeLLMRuntime):
    def __init__(self, responses: list[str], fail_from_call: int | None = None) -> None:
        super().__init__(response="")
        self.responses = responses
        self.fail_from_call = fail_from_call

    def chat(self, messages, model_config=None, stream=False):
        self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": stream})
        if self.fail_from_call is not None and len(self.calls) >= self.fail_from_call:
            raise RuntimeError("title LLM failed")
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def test_patch_session_updates_title_and_touches_updated_at() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "  Renamed chat  "})

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Renamed chat"
    assert payload["updated_at"] > session["updated_at"]


def test_patch_session_rejects_empty_title() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "   "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_TITLE_EMPTY"


def test_patch_session_rejects_overlong_title() -> None:
    client = make_client()
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "x" * 121})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_TITLE_TOO_LONG"


def test_default_title_generates_after_first_successful_prompt_interaction() -> None:
    llm = SequenceLLMRuntime(["assistant reply", '"Generated Title."'])
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Generated Title"
    assert len(llm.calls) == 2


def test_title_generation_failure_does_not_fail_main_conversation() -> None:
    llm = SequenceLLMRuntime(["assistant reply"], fail_from_call=2)
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Session 1"
    assert "Session title generation skipped: title LLM failed" in prompt_run.metadata["warnings"]


def test_prompt_agent_title_generation_reuses_resolved_model_config() -> None:
    llm = SequenceLLMRuntime(["assistant reply", "Short title"])
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    run(fixture.runtime.handle_input(session, "hello"))

    assert llm.calls[0]["model_config"]["model"] == "qwen2.5-3b-instruct"
    assert llm.calls[1]["model_config"]["model"] == "qwen2.5-3b-instruct"


def test_script_agent_title_generation_falls_back_to_session_default_agent_llm() -> None:
    llm = SequenceLLMRuntime(["Script title"])
    fixture = ScriptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "@echo_script hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Script title"
    assert llm.calls[0]["model_config"]["model"] == "qwen2.5-3b-instruct"


def test_no_available_llm_skips_title_generation_without_failing_command(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    app = create_app(llm_runtime=FakeLLMRuntime(response="unused"), use_memory=True)
    client = TestClient(app)
    state = app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(update={"model": None, "llm": None})
    session = client.post("/api/sessions", json={"title": "Session 1", "default_agent_id": "chat"}).json()

    response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/base64 hello"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["session"]["title"] == "Session 1"


def test_title_prompt_uses_only_current_turn_and_truncates_output() -> None:
    long_output = "reply-" + ("x" * 1500)
    llm = SequenceLLMRuntime([long_output, "Current turn"])
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")
    fixture.messages.add_message(session_id=session.session_id, role="user", content="old secret history")
    fixture.messages.add_message(session_id=session.session_id, role="assistant", content="old assistant history", agent_id="chat")

    run(fixture.runtime.handle_input(session, "new question"))
    title_prompt = llm.calls[1]["messages"][0]["content"]

    assert "new question" in title_prompt
    assert "reply-" in title_prompt
    assert "old secret history" not in title_prompt
    assert "old assistant history" not in title_prompt
    assert len(title_prompt) < 1400


def test_non_default_session_title_is_not_overwritten() -> None:
    llm = SequenceLLMRuntime(["assistant reply", "Generated Title"])
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat", title="Manual title")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Manual title"
    assert len(llm.calls) == 1
