from pathlib import Path

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.llm_config import resolve_llm_config
from ai_workbench.core.manifest_loader import load_capability_manifest
from ai_workbench.core.schema.llm_profile import LLMProfileSchema
from ai_workbench.core.stores import LLMProfileStore
from tests.test_api import create_session, post_message
from tests.test_prompt_agent_execution import FakeLLMRuntime, run
from tests.test_script_agent import ScriptRuntimeFixture, write_script_agent


ROOT = Path(__file__).resolve().parents[1]


class InspectableLLMRuntime(FakeLLMRuntime):
    def __init__(self, response: str = "fake response", fail_models: bool = False) -> None:
        super().__init__(response=response)
        self.fail_models = fail_models
        self.model_calls = []

    def list_models(self, model_config=None):
        self.model_calls.append(model_config or {})
        if self.fail_models:
            raise RuntimeError("models offline")
        return ["fake-a", "fake-b"]


def llm_capability():
    return load_capability_manifest(ROOT / "capabilities" / "llm" / "capability.yaml")


def chat_agent():
    agents = AgentRegistry()
    agents.load_from_directory(ROOT / "agents")
    return agents.get("chat")


def test_resolve_llm_config_uses_capability_schema_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)

    config = resolve_llm_config(capability_schema=llm_capability(), capability_config={"user_config": {}})

    assert config.values["base_url"] == "http://localhost:1234/v1"
    assert config.values["timeout"] == 60.0
    assert config.sources["base_url"] == "manifest_default"


def test_resolve_llm_config_uses_persisted_capability_config(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_BASE_URL", raising=False)

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        capability_config={"user_config": {"base_url": "http://local/v1", "model": "ui-model"}},
    )

    assert config.values["base_url"] == "http://local/v1"
    assert config.values["model"] == "ui-model"
    assert config.sources["model"] == "llm_capability_config"


def test_agent_manifest_model_overrides_capability_model(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)

    config = resolve_llm_config(
        agent_schema=chat_agent(),
        capability_schema=llm_capability(),
        capability_config={"user_config": {"model": "ui-model"}},
    )

    assert config.values["model"] == "qwen2.5-3b-instruct"
    assert config.sources["model"] == "agent_legacy_model"


def test_env_fallback_is_used_when_no_saved_config(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("AGENT_WORKBENCH_LLM_API_KEY", "env-key")
    monkeypatch.setenv("AGENT_WORKBENCH_LLM_MODEL", "env-model")

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        capability_config={"user_config": {}},
    )

    assert config.values["base_url"] == "http://env/v1"
    assert config.values["api_key"] == "env-key"
    assert config.values["model"] == "env-model"
    assert config.sources["api_key"] == "env"


def test_capability_config_precedes_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_LLM_MODEL", "env-model")

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        capability_config={"user_config": {"model": "ui-model"}},
    )

    assert config.values["model"] == "ui-model"
    assert config.sources["model"] == "llm_capability_config"


def test_secret_mask_does_not_override_real_secret(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_API_KEY", raising=False)

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        capability_config={"user_config": {"api_key": "********"}},
    )

    assert "api_key" not in config.values


def test_prompt_agent_uses_resolved_capability_config_when_agent_has_no_model(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    llm = InspectableLLMRuntime(response="reply")
    app = create_app(llm_runtime=llm, use_memory=True)
    client = TestClient(app)
    state = app.state.runtime_state
    chat = state.agents.get("chat")
    state.agents._agents["chat"] = chat.model_copy(update={"model": None})
    client.patch("/api/capability-configs/llm", json={"user_config": {"model": "ui-model", "base_url": "http://ui/v1"}})
    session = create_session(client, default_agent_id="chat")

    payload = post_message(client, session["session_id"], "hello")

    assert payload["success"] is True
    assert llm.calls[-1]["model_config"]["model"] == "ui-model"
    assert llm.calls[-1]["model_config"]["base_url"] == "http://ui/v1"


def test_script_agent_llm_generate_uses_resolved_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    registry = write_script_agent(
        tmp_path,
        "llm_script",
        "async def run(ctx):\n"
        "    generated = await ctx.llm.generate(prompt=ctx.input.text)\n"
        "    await ctx.reply(generated.data)\n",
    )
    llm = InspectableLLMRuntime(response="generated")
    fixture = ScriptRuntimeFixture(agents=registry, llm=llm)
    fixture.agent_runner.capability_registry = llm_capability_registry()
    fixture.agent_runner.capability_config_store = fixture_capability_store({"model": "script-model"})
    fixture.agent_runner.script_runner.capability_registry = fixture.agent_runner.capability_registry
    fixture.agent_runner.script_runner.capability_config_store = fixture.agent_runner.capability_config_store
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_script hello"))

    assert result.success is True
    assert llm.calls[-1]["model_config"]["model"] == "script-model"


def test_llm_test_endpoint_uses_resolved_config(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_BASE_URL", raising=False)
    llm = InspectableLLMRuntime()
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    client.patch("/api/capability-configs/llm", json={"user_config": {"base_url": "http://ui/v1"}})

    response = client.post("/api/capability-configs/llm/test")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert llm.model_calls[-1]["base_url"] == "http://ui/v1"


def test_llm_models_endpoint_success_path() -> None:
    client = TestClient(create_app(llm_runtime=InspectableLLMRuntime(), use_memory=True))

    response = client.get("/api/capability-configs/llm/models")

    assert response.status_code == 200
    assert response.json() == {"success": True, "models": [{"id": "fake-a"}, {"id": "fake-b"}]}


def test_llm_models_endpoint_failure_path() -> None:
    client = TestClient(create_app(llm_runtime=InspectableLLMRuntime(fail_models=True), use_memory=True))

    response = client.get("/api/capability-configs/llm/models")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_MODEL_LIST_FAILED"


def test_saved_model_is_used_by_resolved_config(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    client = TestClient(create_app(llm_runtime=InspectableLLMRuntime(), use_memory=True))
    client.patch("/api/capability-configs/llm", json={"user_config": {"model": "saved-model"}})

    response = client.get("/api/capability-configs/llm/resolved")

    assert response.status_code == 200
    assert response.json()["model"] == "saved-model"


def test_agent_manifest_llm_profile_resolves_profile_before_legacy_model(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    store = profile_store()
    agent = chat_agent().model_copy(update={"llm": {"profile": "myqwen3"}, "model": {"model": "legacy-model"}})

    config = resolve_llm_config(
        agent_schema=agent,
        capability_schema=llm_capability(),
        capability_config={"user_config": {"model": "ui-model"}},
        llm_profile_store=store,
    )

    assert config.values["model"] == "qwen3-local"
    assert config.values["base_url"] == "http://qwen3/v1"
    assert config.metadata["source"] == "agent_llm_profile"
    assert config.metadata["profile_alias"] == "myqwen3"


def test_llm_profile_disabled_raises_clear_error() -> None:
    store = profile_store(enabled=False)
    agent = chat_agent().model_copy(update={"llm": {"profile": "myqwen3"}})

    try:
        resolve_llm_config(agent_schema=agent, capability_schema=llm_capability(), llm_profile_store=store)
    except Exception as exc:
        assert getattr(exc, "code") == "LLM_PROFILE_DISABLED"
    else:
        raise AssertionError("expected disabled profile error")


def test_llm_profile_missing_raises_clear_error() -> None:
    agent = chat_agent().model_copy(update={"llm": {"profile": "missing"}})

    try:
        resolve_llm_config(agent_schema=agent, capability_schema=llm_capability(), llm_profile_store=LLMProfileStore())
    except Exception as exc:
        assert getattr(exc, "code") == "LLM_PROFILE_NOT_FOUND"
    else:
        raise AssertionError("expected missing profile error")


def test_llm_profile_invalid_raises_clear_error() -> None:
    store = profile_store(model_id="")
    agent = chat_agent().model_copy(update={"llm": {"profile": "myqwen3"}})

    try:
        resolve_llm_config(agent_schema=agent, capability_schema=llm_capability(), llm_profile_store=store)
    except Exception as exc:
        assert getattr(exc, "code") == "LLM_PROFILE_INVALID"
    else:
        raise AssertionError("expected invalid profile error")


def test_llm_profile_overrides_apply_to_profile_config() -> None:
    store = profile_store(temperature=0.7)
    agent = chat_agent().model_copy(update={"llm": {"profile": "myqwen3", "temperature": 0.2, "max_tokens": 2048}})

    config = resolve_llm_config(agent_schema=agent, capability_schema=llm_capability(), llm_profile_store=store)

    assert config.values["temperature"] == 0.2
    assert config.values["max_tokens"] == 2048


def test_resolved_config_does_not_return_api_key_plaintext() -> None:
    client = TestClient(create_app(llm_runtime=InspectableLLMRuntime(), use_memory=True))
    client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "secret"}})

    response = client.get("/api/capability-configs/llm/resolved")

    assert response.status_code == 200
    assert response.json()["api_key_set"] is True
    assert "secret" not in str(response.json())


def llm_capability_registry():
    from ai_workbench.core.capability_registry import CapabilityRegistry

    registry = CapabilityRegistry()
    registry.register(llm_capability())
    return registry


def fixture_capability_store(user_config):
    from ai_workbench.core.stores import CapabilityConfigStore

    store = CapabilityConfigStore()
    store.set_config("llm", user_config=user_config)
    return store


def profile_store(**overrides):
    store = LLMProfileStore()
    store.create(
        LLMProfileSchema(
            id="profile-1",
            alias="myqwen3",
            name="My Qwen3",
            provider="llama_cpp",
            base_url=overrides.pop("base_url", "http://qwen3/v1"),
            api_key=overrides.pop("api_key", "secret"),
            model_id=overrides.pop("model_id", "qwen3-local"),
            enabled=overrides.pop("enabled", True),
            **overrides,
        )
    )
    return store
