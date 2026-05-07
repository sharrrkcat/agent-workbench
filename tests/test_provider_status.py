from datetime import datetime
import asyncio

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.provider_status import _lm_studio_native_models_url, unload_model
from ai_workbench.core.script import LLMProxy
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.stores import LLMProfileStore, ProviderProfileStore


class FakeResponse:
    def __init__(self, payload=None, fail=False, status_code=200) -> None:
        self.payload = payload or {}
        self.fail = fail
        self.status_code = status_code
        self.text = "failed" if fail else ""

    def raise_for_status(self) -> None:
        if self.fail:
            import ai_workbench.core.provider_status as status_module

            raise status_module.httpx.ConnectError("offline")

    def json(self):
        return self.payload


class FakeClient:
    calls: list[tuple[str, str, dict | None]] = []
    routes: dict[str, FakeResponse] = {}

    def __init__(self, timeout) -> None:
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        response = self.routes.get(url)
        if response is None:
            return FakeResponse(fail=True)
        return response

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        response = self.routes.get(url)
        if response is None:
            return FakeResponse(fail=True)
        return response


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    import ai_workbench.core.provider_status as status_module

    FakeClient.calls = []
    FakeClient.routes = {}
    monkeypatch.setattr(status_module.httpx, "Client", FakeClient)


def create_provider_and_models(client: TestClient, provider_kind: str, base_url: str = "http://local/v1"):
    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Local Provider", "provider": provider_kind, "base_url": base_url, "api_key": "secret"},
    ).json()
    model = client.post(
        "/api/llm-profiles",
        json={"alias": "local", "name": "Local", "provider_profile_id": provider["id"], "model_id": "model-a"},
    ).json()
    missing = client.post(
        "/api/llm-profiles",
        json={"alias": "missing", "name": "Missing", "provider_profile_id": provider["id"], "model_id": "missing-model"},
    ).json()
    return provider, model, missing


def test_lm_studio_status_uses_native_models_and_loaded_instances() -> None:
    client = TestClient(create_app(use_memory=True))
    provider, model, missing = create_provider_and_models(client, "lm_studio", "http://localhost:1234/v1")
    FakeClient.routes["http://localhost:1234/api/v1/models"] = FakeResponse(
        {
            "data": [
                {
                    "id": "model-a",
                    "display_name": "Model A",
                    "loaded_instances": [{"id": "instance-1"}],
                    "capabilities": {"vision": True},
                }
            ]
        }
    )

    response = client.post("/api/llm-provider-profiles/status/refresh", json={"provider_profile_ids": [provider["id"]]})

    assert response.status_code == 200
    payload = response.json()["providers"][0]
    assert payload["mode"] == "lm_studio_native"
    assert payload["models"][0]["id"] == "model-a"
    assert payload["models"][0]["available"] is True
    assert payload["models"][0]["loaded"] is True
    assert payload["models"][0]["loaded_instance_ids"] == ["instance-1"]
    assert payload["models"][1]["status"] == "MODEL_NOT_AVAILABLE"
    assert "secret" not in str(payload)
    assert FakeClient.calls[0][1] == "http://localhost:1234/api/v1/models"


def test_lm_studio_native_models_key_response_is_normalized() -> None:
    client = TestClient(create_app(use_memory=True))
    provider, _, _ = create_provider_and_models(client, "lm_studio", "http://localhost:1234/v1")
    FakeClient.routes["http://localhost:1234/api/v1/models"] = FakeResponse(
        {
            "models": [
                {
                    "key": "qwen/qwen3-8b",
                    "display_name": "Qwen3 8B",
                    "type": "llm",
                    "loaded_instances": [{"id": "loaded-1"}],
                    "capabilities": {
                        "vision": True,
                        "trained_for_tool_use": True,
                        "reasoning": True,
                    },
                },
                {
                    "key": "text-embedding",
                    "display_name": "Text Embedding",
                    "type": "embedding",
                    "loaded_instances": [],
                    "capabilities": {},
                },
            ]
        }
    )

    payload = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert payload["mode"] == "lm_studio_native"
    assert payload["models"][0]["id"] == "model-a"
    assert payload["models"][0]["status"] == "MODEL_NOT_AVAILABLE"

    no_profiles = client.post(
        "/api/llm-provider-profiles",
        json={"name": "No Profiles", "provider": "lm_studio", "base_url": "http://localhost:1234/v1"},
    ).json()
    payload = client.post(f"/api/llm-provider-profiles/{no_profiles['id']}/status/refresh").json()["providers"][0]
    assert [item["id"] for item in payload["models"]] == ["qwen/qwen3-8b", "text-embedding"]
    assert payload["models"][0]["name"] == "Qwen3 8B"
    assert payload["models"][0]["type"] == "llm"
    assert payload["models"][0]["loaded"] is True
    assert payload["models"][0]["loaded_instance_ids"] == ["loaded-1"]
    assert payload["models"][0]["capabilities"]["vision"] is True
    assert payload["models"][0]["capabilities"]["tools"] is True
    assert payload["models"][0]["capabilities"]["reasoning"] is True
    assert payload["models"][1]["type"] == "embedding"


def test_lm_studio_native_display_name_fallback_and_capability_aliases() -> None:
    client = TestClient(create_app(use_memory=True))
    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Studio", "provider": "lm_studio", "base_url": "http://studio/v1"},
    ).json()
    FakeClient.routes["http://studio/api/v1/models"] = FakeResponse(
        {
            "models": [
                {
                    "id": "fallback-id",
                    "type": "llm",
                    "capabilities": {
                        "image_input": True,
                        "tools": True,
                        "reasoning_output": True,
                    },
                }
            ]
        }
    )

    payload = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert payload["models"][0]["id"] == "fallback-id"
    assert payload["models"][0]["name"] == "fallback-id"
    assert payload["models"][0]["capabilities"] == {"vision": True, "tools": True, "reasoning": True}


def test_lm_studio_native_nonempty_unrecognized_models_do_not_fallback() -> None:
    client = TestClient(create_app(use_memory=True))
    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Studio", "provider": "lm_studio", "base_url": "http://studio/v1"},
    ).json()
    FakeClient.routes["http://studio/api/v1/models"] = FakeResponse({"models": [{"display_name": "No Key"}]})
    FakeClient.routes["http://studio/v1/models"] = FakeResponse({"data": [{"id": "fallback"}]})

    payload = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert payload["mode"] == "lm_studio_native"
    assert payload["status"] == "MODEL_STATUS_UNKNOWN"
    assert payload["models"] == []
    assert payload["warnings"]
    assert [call[1] for call in FakeClient.calls] == ["http://studio/api/v1/models"]


def test_lm_studio_native_fallback_is_partial_unknown_not_unavailable() -> None:
    client = TestClient(create_app(use_memory=True))
    provider, _, _ = create_provider_and_models(client, "lm_studio", "http://studio/v1")
    FakeClient.routes["http://studio/v1/models"] = FakeResponse({"data": [{"id": "other"}]})

    response = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh")

    payload = response.json()["providers"][0]
    assert payload["mode"] == "lm_studio_openai_compatible_partial"
    assert payload["status"] == "MODEL_STATUS_UNKNOWN"
    assert all(item["status"] == "MODEL_STATUS_UNKNOWN" for item in payload["models"])


def test_lm_studio_native_url_normalization() -> None:
    assert _lm_studio_native_models_url("http://localhost:1234/v1") == "http://localhost:1234/api/v1/models"
    assert _lm_studio_native_models_url("http://localhost:1234") == "http://localhost:1234/api/v1/models"
    assert _lm_studio_native_models_url("http://localhost:1234/api/v1") == "http://localhost:1234/api/v1/models"


def test_lm_studio_unload_uses_loaded_instance_ids() -> None:
    provider = ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1")
    profile = LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id="provider", model_id="model-a")
    FakeClient.routes["http://studio/api/v1/models"] = FakeResponse({"data": [{"id": "model-a", "loaded_instances": [{"id": "i1"}, {"id": "i2"}]}]})
    FakeClient.routes["http://studio/api/v1/models/unload"] = FakeResponse({"ok": True})

    result = unload_model(provider, [profile], model_profile_id="profile")

    assert result["ok"] is True
    assert result["unloaded"] == [{"model_id": "model-a", "instance_id": "i1"}, {"model_id": "model-a", "instance_id": "i2"}]
    assert ("POST", "http://studio/api/v1/models/unload", {"instance_id": "i1"}) in FakeClient.calls
    assert ("POST", "http://studio/api/v1/models/unload", {"instance_id": "i2"}) in FakeClient.calls


def test_llama_cpp_router_and_single_status_modes() -> None:
    client = TestClient(create_app(use_memory=True))
    provider, _, _ = create_provider_and_models(client, "llama_cpp", "http://localhost:8080/v1")
    FakeClient.routes["http://localhost:8080/models"] = FakeResponse({"data": [{"id": "model-a", "status": {"value": "loaded"}}]})

    router_response = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert router_response["mode"] == "llama_cpp_router"
    assert router_response["models"][0]["status"] == "READY"
    assert router_response["models"][1]["status"] == "MODEL_NOT_AVAILABLE"

    FakeClient.routes = {"http://localhost:8080/v1/models": FakeResponse({"data": [{"id": "different"}]})}
    single_response = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert single_response["mode"] == "llama_cpp_single"
    assert single_response["models"][0]["status"] == "MODEL_MISMATCH"
    assert single_response["models"][0]["actual_model_id"] == "different"

    FakeClient.routes = {"http://localhost:8080/v1/models": FakeResponse({"data": [{"id": "model-a"}]})}
    ready_response = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert ready_response["models"][0]["status"] == "READY"


def test_openai_compatible_status_and_unreachable() -> None:
    client = TestClient(create_app(use_memory=True))
    provider, _, _ = create_provider_and_models(client, "openai_compatible", "http://openai/v1")
    FakeClient.routes["http://openai/v1/models"] = FakeResponse({"data": [{"id": "model-a"}]})

    response = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]

    assert response["mode"] == "openai_compatible"
    assert response["models"][0]["status"] == "READY"
    assert response["models"][1]["status"] == "MODEL_NOT_AVAILABLE"

    FakeClient.routes = {}
    unreachable = client.post(f"/api/llm-provider-profiles/{provider['id']}/status/refresh").json()["providers"][0]
    assert unreachable["status"] == "PROVIDER_UNREACHABLE"
    assert unreachable["error"]["code"] == "PROVIDER_UNREACHABLE"


def test_status_refresh_all_only_enabled_and_missing_is_clear() -> None:
    client = TestClient(create_app(use_memory=True))
    provider, _, _ = create_provider_and_models(client, "openai_compatible", "http://enabled/v1")
    client.post(
        "/api/llm-provider-profiles",
        json={"name": "Disabled", "provider": "openai_compatible", "base_url": "http://disabled/v1", "enabled": False},
    )
    FakeClient.routes["http://enabled/v1/models"] = FakeResponse({"data": [{"id": "model-a"}]})

    response = client.post("/api/llm-provider-profiles/status/refresh").json()

    assert [item["provider_profile_id"] for item in response["providers"]] == [provider["id"]]

    missing = client.post("/api/llm-provider-profiles/status/refresh", json={"provider_profile_ids": ["missing"]})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LLM_PROVIDER_PROFILE_NOT_FOUND"


def test_unload_unsupported_provider_returns_structured_error() -> None:
    provider = ProviderProfileSchema(id="provider", name="OpenAI", provider="openai_compatible", base_url="http://openai/v1")
    result = unload_model(provider, [], model_id="model-a")
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "MODEL_UNLOAD_UNSUPPORTED"


def test_script_runtime_unload_unsupported_provider_returns_structured_error() -> None:
    providers = ProviderProfileStore()
    profiles = LLMProfileStore()
    provider = providers.create(ProviderProfileSchema(id="provider", name="OpenAI", provider="openai_compatible", base_url="http://openai/v1"))
    profile = profiles.create(
        LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a", created_at=datetime.utcnow())
    )
    proxy = LLMProxy(object(), provider_profile_store=providers, llm_profile_store=profiles)

    result = asyncio.run(proxy.unload_model(model_profile_id=profile.id))

    assert result.success is False
    assert result.data["errors"][0]["code"] == "MODEL_UNLOAD_UNSUPPORTED"
