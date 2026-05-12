from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.utility_llm import extract_json_object, normalize_utility_model_path, validate_intent_prediction
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run


class FakeUtilityLLM:
    def __init__(self, title: str = "Utility Title", prediction: dict | None = None, fail_title: bool = False, fail_json: bool = False) -> None:
        self.title = title
        self.prediction = prediction or {
            "intent": "knowledge_query",
            "confidence": 0.84,
            "target_agent_hint": None,
            "kb_hint": "Star Wars",
            "query": "stormtrooper ranks",
            "command_hint": None,
        }
        self.fail_title = fail_title
        self.fail_json = fail_json
        self.title_calls: list[str] = []
        self.json_calls: list[str] = []

    async def generate_title(self, user_input, settings):
        self.title_calls.append(user_input)
        if self.fail_title:
            raise RuntimeError("utility title failed")
        return {"title": self.title, "model_path": settings.intent_routing_utility_llm_model_path}

    async def extract_intent_json(self, text, settings):
        self.json_calls.append(text)
        if self.fail_json:
            raise RuntimeError("utility json failed")
        return self.prediction

    def unload(self):
        return {"ok": True, "status": "unloaded"}


def test_status_unconfigured_returns_unavailable() -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    response = client.get("/api/intent/utility-llm/status")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["available"] is False
    assert response.json()["reason"] == "model_path_not_configured"


def test_api_test_endpoints_use_runtime_utility_service() -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    app.state.runtime_state.utility_llm = FakeUtilityLLM(title="API Title")
    app.state.runtime_state.app_settings.patch({"intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B"})

    title = client.post("/api/intent/utility-llm/test-title", json={"text": "hello"})
    extracted = client.post("/api/intent/utility-llm/test-json", json={"text": "what does the kb say"})
    unloaded = client.post("/api/intent/utility-llm/unload")

    assert title.status_code == 200
    assert title.json()["title"] == "API Title"
    assert extracted.status_code == 200
    assert extracted.json()["result"]["intent"] == "knowledge_query"
    assert unloaded.status_code == 200


def test_utility_model_path_validation() -> None:
    assert normalize_utility_model_path("") == ""
    assert normalize_utility_model_path("utility_llms/Qwen3-0.6B") == "utility_llms/Qwen3-0.6B"
    for invalid in ["C:/models/qwen", "../qwen", "utility_llms/../qwen", "llms/Qwen3-0.6B"]:
        try:
            normalize_utility_model_path(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid path: {invalid}")


def test_json_extractor_validation_clamps_and_filters_slots() -> None:
    data = validate_intent_prediction(extract_json_object('prefix {"intent":"knowledge_query","confidence":2,"kb_hint":"KB","query":"Q"} suffix'))

    assert data["intent"] == "knowledge_query"
    assert data["confidence"] == 1.0
    assert data["kb_hint"] == "KB"
    assert data["query"] == "Q"


def test_title_generation_prefers_utility_llm_when_available() -> None:
    llm = FakeLLMRuntime(response="assistant reply")
    fixture = PromptRuntimeFixture(llm=llm)
    utility = FakeUtilityLLM(title="Utility Session")
    fixture.agent_runner.utility_llm_service = utility
    fixture.app_settings.patch({"auto_generate_session_titles": True, "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Utility Session"
    assert len(llm.calls) == 1
    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert metadata["backend"] == "utility_llm"
    assert metadata["fallback_used"] is False
    assert metadata["utility_model_path"] == "utility_llms/Qwen3-0.6B"


def test_title_generation_falls_back_to_main_llm_when_utility_fails() -> None:
    llm = FakeLLMRuntime(response="Main Title")
    fixture = PromptRuntimeFixture(llm=llm)
    fixture.agent_runner.utility_llm_service = FakeUtilityLLM(fail_title=True)
    fixture.app_settings.patch({"auto_generate_session_titles": True, "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Main Title"
    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert metadata["backend"] == "main_llm"
    assert metadata["fallback_used"] is True
    assert "utility_error" in metadata


def test_intent_shadow_uses_utility_extractor_for_slots_without_reroute() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    utility = FakeUtilityLLM()
    fixture.agent_runner.utility_llm_service = utility
    fixture.app_settings.patch({
        "intent_routing_enabled": True,
        "intent_routing_default_for_prompt_agents": True,
        "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B",
    })
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "what do docs say about stormtrooper ranks"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert result.success is True
    assert intent["source"] == "rule_based_shadow+utility_llm"
    assert intent["predicted_intent"] == "knowledge_query"
    assert intent["slots"]["kb_hint"] == "Star Wars"
    assert fixture.runs.get_run(result.run_id).target_id == "chat"


def test_intent_shadow_utility_failure_falls_back_to_rule_based() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    fixture.agent_runner.utility_llm_service = FakeUtilityLLM(fail_json=True)
    fixture.app_settings.patch({
        "intent_routing_enabled": True,
        "intent_routing_default_for_prompt_agents": True,
        "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B",
    })
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "what do docs say"))

    intent = fixture.runs.get_run(result.run_id).metadata["intent_routing"]
    assert result.success is True
    assert intent["source"] == "rule_based_shadow"
    assert "utility_extractor_failed" in intent["warnings"]
