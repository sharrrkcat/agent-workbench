from pathlib import Path

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.llm_config import resolve_llm_config
from ai_workbench.core.manifest_loader import load_capability_manifest
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.stores import LLMDefaultsStore, LLMProfileStore, ProviderProfileStore
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


class ProviderModelRuntime(InspectableLLMRuntime):
    def list_models(self, model_config=None):
        self.model_calls.append(model_config or {})
        return [
            {
                "id": "provider-model",
                "name": "Provider Model",
                "capabilities": {"vision": True, "tools": False, "reasoning": False},
                "api_key": "must-not-leak",
            }
        ]


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


def test_llm_capability_default_profile_precedes_direct_config(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_LLM_MODEL", "env-model")
    store = profile_store()

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        capability_config={"user_config": {"default_profile": "myqwen3", "model": "ui-model"}},
        llm_profile_store=store,
    )

    assert config.values["model"] == "qwen3-local"
    assert config.sources["model"] == "llm_capability_config"
    assert config.metadata["profile_alias"] == "myqwen3"


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


def test_provider_refresh_models_uses_provider_profile_id_without_model_profile() -> None:
    llm = ProviderModelRuntime()
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    provider = client.post(
        "/api/llm-provider-profiles",
        json={
            "name": "OpenAI-compatible local",
            "provider": "openai_compatible",
            "base_url": "http://provider/v1",
            "api_key": "secret",
        },
    ).json()

    response = client.post(f"/api/llm-provider-profiles/{provider['id']}/refresh-models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_profile_id"] == provider["id"]
    assert payload["provider"] == "openai_compatible"
    assert payload["models"][0]["id"] == "provider-model"
    assert payload["models"][0]["capabilities"]["vision"] is True
    assert "must-not-leak" not in str(payload)
    assert llm.model_calls[-1]["base_url"] == "http://provider/v1"
    assert llm.model_calls[-1]["provider"] == "openai_compatible"


def test_provider_refresh_models_missing_and_disabled_errors() -> None:
    client = TestClient(create_app(llm_runtime=ProviderModelRuntime(), use_memory=True))

    missing = client.post("/api/llm-provider-profiles/missing/refresh-models")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LLM_PROVIDER_PROFILE_NOT_FOUND"

    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Disabled", "provider": "llama_cpp", "base_url": "http://local/v1", "enabled": False},
    ).json()
    disabled = client.post(f"/api/llm-provider-profiles/{provider['id']}/refresh-models")
    assert disabled.status_code == 400
    assert disabled.json()["error"]["code"] == "LLM_PROVIDER_PROFILE_DISABLED"


def test_provider_refresh_models_passes_provider_kind_to_runtime() -> None:
    llm = ProviderModelRuntime()
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    for provider_kind in ("openai_compatible", "lm_studio", "llama_cpp"):
        provider = client.post(
            "/api/llm-provider-profiles",
            json={"name": provider_kind, "provider": provider_kind, "base_url": "http://local/v1"},
        ).json()
        response = client.post(f"/api/llm-provider-profiles/{provider['id']}/refresh-models")
        assert response.status_code == 200
        assert llm.model_calls[-1]["provider"] == provider_kind
    assert response.json()["warnings"]


def test_internal_provider_refresh_models_scans_safe_inventory(monkeypatch, tmp_path: Path) -> None:
    import ai_workbench.core.provider_inventory as inventory_module

    models_root = tmp_path / "data" / "models"
    (models_root / "llms" / "qwen").mkdir(parents=True)
    (models_root / "llms" / "qwen" / "config.json").write_text("{}", encoding="utf-8")
    (models_root / "llms" / "gguf-only").mkdir()
    (models_root / "llms" / "gguf-only" / "model.gguf").write_text("", encoding="utf-8")
    (models_root / "llms" / "direct.gguf").write_text("", encoding="utf-8")
    (models_root / "llms" / "qwen-gguf").mkdir()
    (models_root / "llms" / "qwen-gguf" / "model.gguf").write_text("", encoding="utf-8")
    (models_root / "embeddings" / "bge").mkdir(parents=True)
    (models_root / "embeddings" / "bge" / "model.safetensors").write_text("", encoding="utf-8")
    (models_root / "rerankers" / "ranker").mkdir(parents=True)
    (models_root / "rerankers" / "ranker" / "sentence_bert_config.json").write_text("{}", encoding="utf-8")
    (models_root / "utility_llms" / "old").mkdir(parents=True)
    (models_root / "utility_llms" / "old" / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(inventory_module, "models_root_path", lambda root=None: models_root)

    llm = ProviderModelRuntime()
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    transformers = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Local transformers", "provider": "internal_transformers"},
    ).json()
    llama_cpp = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Local llama.cpp", "provider": "internal_llama_cpp"},
    ).json()

    transformers_payload = client.post(f"/api/llm-provider-profiles/{transformers['id']}/refresh-models").json()
    llama_payload = client.post(f"/api/llm-provider-profiles/{llama_cpp['id']}/refresh-models").json()

    assert transformers["base_url"] == ""
    assert {item["id"] for item in transformers_payload["models"]} == {"llm/qwen", "embedding/bge", "reranker/ranker"}
    assert all(item["source"] == "internal" for item in transformers_payload["models"])
    assert all(not item["relative_path"].startswith("utility_llms") for item in transformers_payload["models"])
    assert transformers_payload["warnings"] == ["legacy_utility_llms_not_scanned"]
    assert {item["id"] for item in llama_payload["models"]} == {"llm/direct.gguf", "llm/qwen-gguf/model.gguf", "llm/gguf-only/model.gguf"}
    assert all(item["backend"] == "internal_llama_cpp" for item in llama_payload["models"])
    assert not llm.model_calls


def test_builtin_llm_runtime_model_listing_provider_urls(monkeypatch) -> None:
    from capabilities.llm import CapabilityRuntime
    import capabilities.llm as llm_module

    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload, fail: bool = False) -> None:
            self.payload = payload
            self.fail = fail

        def raise_for_status(self) -> None:
            if self.fail:
                raise llm_module.httpx.ConnectError("offline")

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, timeout) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, headers=None):
            calls.append(url)
            return FakeResponse({"data": [{"id": "model-a"}]})

    monkeypatch.setattr(llm_module.httpx, "Client", FakeClient)
    runtime = CapabilityRuntime()

    assert runtime.list_models({"provider": "openai_compatible", "base_url": "http://local/v1"}) == ["model-a"]
    assert calls[-1] == "http://local/v1/models"
    assert runtime.list_models({"provider": "llama_cpp", "base_url": "http://llama/v1"}) == ["model-a"]
    assert calls[-1] == "http://llama/v1/models"
    assert runtime.list_models({"provider": "lm_studio", "base_url": "http://studio/v1"}) == ["model-a"]
    assert calls[-1] == "http://studio/api/v1/models"


def test_builtin_llm_runtime_lm_studio_native_models_key_items(monkeypatch) -> None:
    from capabilities.llm import CapabilityRuntime
    import capabilities.llm as llm_module

    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, timeout) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, headers=None):
            calls.append(url)
            return FakeResponse(
                {
                    "models": [
                        {
                            "key": "chat-model",
                            "display_name": "Chat Model",
                            "type": "llm",
                            "loaded_instances": [{"id": "instance-1"}],
                            "capabilities": {
                                "vision": True,
                                "trained_for_tool_use": True,
                                "reasoning": True,
                            },
                        },
                        {
                            "key": "embed-model",
                            "display_name": "Embedding Model",
                            "type": "embedding",
                        },
                    ]
                }
            )

    monkeypatch.setattr(llm_module.httpx, "Client", FakeClient)
    runtime = CapabilityRuntime()

    assert runtime.list_models({"provider": "lm_studio", "base_url": "http://studio/api/v1"}) == ["chat-model", "embed-model"]
    assert calls == ["http://studio/api/v1/models"]
    items = runtime.list_model_items({"provider": "lm_studio", "base_url": "http://studio/v1"})
    assert items[0]["id"] == "chat-model"
    assert items[0]["name"] == "Chat Model"
    assert items[0]["type"] == "llm"
    assert items[0]["loaded"] is True
    assert items[0]["loaded_instance_ids"] == ["instance-1"]
    assert items[0]["capabilities"]["vision"] is True
    assert items[0]["capabilities"]["tools"] is True
    assert items[0]["capabilities"]["reasoning"] is True
    assert items[1]["type"] == "embedding"


def test_builtin_llm_runtime_lm_studio_falls_back_to_openai_models(monkeypatch) -> None:
    from capabilities.llm import CapabilityRuntime
    import capabilities.llm as llm_module

    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload, fail: bool = False) -> None:
            self.payload = payload
            self.fail = fail

        def raise_for_status(self) -> None:
            if self.fail:
                raise llm_module.httpx.ConnectError("offline")

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, timeout) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, headers=None):
            calls.append(url)
            if url.endswith("/api/v1/models"):
                return FakeResponse({}, fail=True)
            return FakeResponse({"data": [{"id": "fallback-model"}]})

    monkeypatch.setattr(llm_module.httpx, "Client", FakeClient)

    assert CapabilityRuntime().list_models({"provider": "lm_studio", "base_url": "http://studio/v1"}) == ["fallback-model"]
    assert calls == ["http://studio/api/v1/models", "http://studio/v1/models"]


def test_new_model_profile_create_requires_provider_profile_and_model_id() -> None:
    client = TestClient(create_app(llm_runtime=ProviderModelRuntime(), use_memory=True))
    missing_provider = client.post("/api/llm-profiles", json={"alias": "draft", "name": "Draft", "model_id": "model"})
    assert missing_provider.status_code == 400
    assert missing_provider.json()["error"]["code"] == "LLM_PROFILE_INVALID"

    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Provider", "provider": "openai_compatible", "base_url": "http://local/v1"},
    ).json()
    missing_model = client.post("/api/llm-profiles", json={"alias": "draft", "name": "Draft", "provider_profile_id": provider["id"]})
    assert missing_model.status_code == 400
    assert missing_model.json()["error"]["code"] == "LLM_PROFILE_INVALID"


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


def test_session_llm_profile_override_precedes_agent_manifest_profile(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    store = profile_store()
    store.create(
        LLMProfileSchema(
            id="profile-2",
            alias="session-model",
            name="Session Model",
            provider="llama_cpp",
            base_url="http://session/v1",
            model_id="session-local",
        )
    )
    agent = chat_agent().model_copy(update={"llm": {"profile": "myqwen3"}})

    config = resolve_llm_config(
        agent_schema=agent,
        capability_schema=llm_capability(),
        llm_profile_store=store,
        session_llm_profile_id="profile-2",
    )

    assert config.values["model"] == "session-local"
    assert config.metadata["source"] == "session_override"
    assert config.metadata["session_override_applied"] is True


def test_locked_agent_ignores_session_llm_profile_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    store = profile_store()
    store.create(
        LLMProfileSchema(
            id="profile-2",
            alias="session-model",
            name="Session Model",
            provider="llama_cpp",
            base_url="http://session/v1",
            model_id="session-local",
        )
    )
    agent = chat_agent().model_copy(update={"llm": {"profile": "myqwen3", "allow_session_override": False}})

    config = resolve_llm_config(
        agent_schema=agent,
        capability_schema=llm_capability(),
        llm_profile_store=store,
        session_llm_profile_id="profile-2",
    )

    assert config.values["model"] == "qwen3-local"
    assert config.metadata["source"] == "agent_llm_profile"
    assert config.metadata["session_override_requested"] == "profile-2"
    assert config.metadata["session_override_applied"] is False


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


def test_runtime_resolution_uses_model_and_provider_profiles(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    providers = ProviderProfileStore()
    providers.create(
        ProviderProfileSchema(
            id="provider-1",
            name="LM Studio local",
            provider="lm_studio",
            base_url="http://provider/v1",
            api_key="secret",
            timeout_seconds=45,
        )
    )
    models = LLMProfileStore()
    models.create(
        LLMProfileSchema(
            id="model-1",
            alias="model_one",
            name="Model One",
            provider_profile_id="provider-1",
            model_id="provider-model",
            supports_streaming=True,
            supports_vision=True,
        )
    )

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        llm_profile_store=models,
        provider_profile_store=providers,
        session_llm_profile_id="model-1",
    )

    assert config.values["provider"] == "lm_studio"
    assert config.values["base_url"] == "http://provider/v1"
    assert config.values["model"] == "provider-model"
    assert config.values["timeout"] == 45
    assert config.values["supports_streaming"] is True
    assert config.values["supports_vision"] is True
    assert config.metadata["provider_profile_id"] == "provider-1"


def test_default_model_profile_is_used_before_legacy_and_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_LLM_MODEL", "env-model")
    providers = ProviderProfileStore()
    providers.create(ProviderProfileSchema(id="provider-1", name="Provider", base_url="http://default/v1"))
    models = LLMProfileStore()
    models.create(
        LLMProfileSchema(
            id="model-1",
            alias="default_model",
            name="Default Model",
            provider_profile_id="provider-1",
            model_id="default-model",
        )
    )
    defaults = LLMDefaultsStore()
    defaults.patch({"default_model_profile_id": "model-1"})

    config = resolve_llm_config(
        capability_schema=llm_capability(),
        capability_config={"user_config": {"model": "legacy-model"}},
        llm_profile_store=models,
        provider_profile_store=providers,
        llm_defaults_store=defaults,
    )

    assert config.values["model"] == "default-model"
    assert config.metadata["source"] == "global_default"


def test_missing_and_disabled_provider_profile_raise_clear_errors() -> None:
    models = LLMProfileStore()
    models.create(
        LLMProfileSchema(
            id="model-1",
            alias="missing_provider",
            name="Missing Provider",
            provider_profile_id="provider-missing",
            model_id="model",
        )
    )
    try:
        resolve_llm_config(llm_profile_store=models, provider_profile_store=ProviderProfileStore(), session_llm_profile_id="model-1")
    except Exception as exc:
        assert getattr(exc, "code") == "LLM_PROVIDER_PROFILE_NOT_FOUND"
    else:
        raise AssertionError("expected missing provider profile error")

    providers = ProviderProfileStore()
    providers.create(ProviderProfileSchema(id="provider-missing", name="Provider", base_url="http://local/v1", enabled=False))
    try:
        resolve_llm_config(llm_profile_store=models, provider_profile_store=providers, session_llm_profile_id="model-1")
    except Exception as exc:
        assert getattr(exc, "code") == "LLM_PROVIDER_PROFILE_DISABLED"
    else:
        raise AssertionError("expected disabled provider profile error")


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
