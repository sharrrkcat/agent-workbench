import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.settings import AppSettings
from ai_workbench.core.utility_llm import UtilityLLMService, extract_json_object, normalize_utility_model_path, scan_utility_models, validate_intent_prediction
from tests.test_session_titles import set_chat_title_profile
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run
from tests.test_intent_routing import enable_semantic_router


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
    assert normalize_utility_model_path("utility_llms/qwen3/Qwen3-Q4_K_M.GGUF", "llama_cpp") == "utility_llms/qwen3/Qwen3-Q4_K_M.GGUF"
    for invalid in ["C:/models/qwen", "../qwen", "utility_llms/../qwen", "llms/Qwen3-0.6B"]:
        try:
            normalize_utility_model_path(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid path: {invalid}")
    for invalid in ["utility_llms/model.gguf", "Qwen3-Q4_K_M.gguf", "utility_llms/qwen3"]:
        try:
            normalize_utility_model_path(invalid, "llama_cpp")
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid llama_cpp path: {invalid}")


def test_settings_accepts_backend_specific_paths_and_rejects_mismatches() -> None:
    assert AppSettings(intent_routing_utility_llm_backend="transformers", intent_routing_utility_llm_model_path="utility_llms/Qwen3").intent_routing_utility_llm_model_path == "utility_llms/Qwen3"
    assert AppSettings(intent_routing_utility_llm_backend="llama_cpp", intent_routing_utility_llm_model_path="utility_llms/qwen3/model.gguf").intent_routing_utility_llm_model_path == "utility_llms/qwen3/model.gguf"
    for kwargs in [
        {"intent_routing_utility_llm_backend": "llama_cpp", "intent_routing_utility_llm_model_path": "utility_llms/Qwen3"},
        {"intent_routing_utility_llm_backend": "transformers", "intent_routing_utility_llm_model_path": "utility_llms/qwen3/model.gguf"},
        {"intent_routing_utility_llm_backend": "llama_cpp", "intent_routing_utility_llm_model_path": "utility_llms/model.gguf"},
    ]:
        try:
            AppSettings(**kwargs)
        except Exception:
            pass
        else:
            raise AssertionError(f"expected invalid settings: {kwargs}")


def test_scan_utility_models_returns_hf_and_nested_gguf(tmp_path: Path) -> None:
    utility_root = tmp_path / "data" / "models" / "utility_llms"
    (utility_root / "Qwen3-0.6B").mkdir(parents=True)
    (utility_root / "Qwen3-0.6B" / "config.json").write_text("{}", encoding="utf-8")
    (utility_root / "qwen3-gguf").mkdir()
    (utility_root / "qwen3-gguf" / "Qwen3-Q4_K_M.gguf").write_bytes(b"fake")
    (utility_root / "root.gguf").write_bytes(b"ignored")

    result = scan_utility_models(tmp_path)

    assert result["transformers_models"][0]["model_path"] == "utility_llms/Qwen3-0.6B"
    assert result["gguf_models"][0]["model_path"] == "utility_llms/qwen3-gguf/Qwen3-Q4_K_M.gguf"
    assert "root_gguf_ignored" in result["warnings"]


def test_llama_cpp_status_missing_dependency_does_not_fail_startup(tmp_path: Path) -> None:
    service = UtilityLLMService(tmp_path)
    settings = AppSettings(
        intent_routing_utility_llm_backend="llama_cpp",
        intent_routing_utility_llm_model_path="utility_llms/qwen3/model.gguf",
    )

    status = service.status(settings)

    assert status["backend"] == "llama_cpp"
    assert status["available"] is False
    assert status["reason"] in {"llama_cpp_unavailable", "model_not_found"}


def test_status_reports_backend_path_mismatch() -> None:
    service = UtilityLLMService()
    settings = SimpleNamespace(
        intent_routing_utility_llm_backend="transformers",
        intent_routing_utility_llm_model_path="utility_llms/qwen3/model.gguf",
        intent_routing_device="cpu",
        intent_routing_utility_llm_context_size=4096,
        intent_routing_utility_llm_gpu_layers=0,
        intent_routing_utility_llm_threads=None,
    )

    status = service.status(settings)

    assert status["available"] is False
    assert status["reason"] == "backend_model_path_mismatch"


def test_llama_cpp_fake_backend_generates_title_and_json(monkeypatch, tmp_path: Path) -> None:
    utility_root = tmp_path / "data" / "models" / "utility_llms" / "tiny"
    utility_root.mkdir(parents=True)
    (utility_root / "tiny.gguf").write_bytes(b"fake")
    module = ModuleType("llama_cpp")

    class FakeLlama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_chat_completion(self, messages, max_tokens, temperature, stop):
            prompt = messages[0]["content"]
            if "one key: title" in prompt:
                return {"choices": [{"message": {"content": '{"title":"Tiny Title"}'}}]}
            return {"choices": [{"message": {"content": '{"intent":"knowledge_query","confidence":0.88,"kb_hint":"KB","query":"Q"}'}}]}

    module.Llama = FakeLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    original_find_spec = __import__("importlib").util.find_spec

    def fake_find_spec(name):
        if name == "llama_cpp":
            return object()
        return original_find_spec(name)

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)
    service = UtilityLLMService(tmp_path)
    settings = AppSettings(
        intent_routing_utility_llm_backend="llama_cpp",
        intent_routing_utility_llm_model_path="utility_llms/tiny/tiny.gguf",
        intent_routing_utility_llm_context_size=1024,
        intent_routing_utility_llm_gpu_layers=0,
        intent_routing_utility_llm_threads=2,
    )

    title = run(service.generate_title("hello", settings))
    extracted = run(service.extract_intent_json("ask kb", settings))
    unloaded = service.unload()

    assert title["title"] == "Tiny Title"
    assert title["backend"] == "utility_llm:llama_cpp"
    assert extracted["intent"] == "knowledge_query"
    assert extracted["kb_hint"] == "KB"
    assert unloaded["removed"] == 1


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


def test_title_generation_falls_back_to_model_profile_when_utility_fails() -> None:
    llm = FakeLLMRuntime(response="Main Title")
    fixture = PromptRuntimeFixture(llm=llm)
    set_chat_title_profile(fixture)
    fixture.agent_runner.utility_llm_service = FakeUtilityLLM(fail_title=True)
    fixture.app_settings.patch({"auto_generate_session_titles": True, "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B"})
    session = fixture.sessions.create_session(default_agent_id="chat", title="Session 1")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert fixture.sessions.get_session(session.session_id).title == "Main Title"
    metadata = fixture.runs.get_run(result.run_id).metadata["title_generation"]
    assert metadata["backend"] == "model_profile"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_reason"] == "utility_llm_generation_failed"
    assert "utility_error" in metadata


def test_intent_shadow_uses_utility_extractor_for_slots_without_reroute() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_semantic_router(fixture)
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
    assert intent["source"] == "embedding_semantic_router+utility_llm"
    assert intent["predicted_intent"] == "knowledge_query"
    assert intent["slots"]["kb_hint"] == "Star Wars"
    assert fixture.runs.get_run(result.run_id).target_id == "chat"


def test_intent_shadow_utility_failure_records_slots_failed_without_rule_based_fallback() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    enable_semantic_router(fixture)
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
    assert intent["source"] == "embedding_semantic_router"
    assert intent["utility_required"] is True
    assert intent["utility_used"] is True
    assert intent["utility_ok"] is False
    assert intent["not_executed_reason"] == "utility_llm_slots_failed"
    assert "utility_llm_slots_failed" in intent["warnings"]
