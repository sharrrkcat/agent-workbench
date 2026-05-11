from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.runtime_resources import RuntimeResourcesService
from tests.test_prompt_agent_execution import FakeLLMRuntime


def test_runtime_resources_api_returns_safe_fallback_without_gpu(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'resources.db'}"))
    response = client.get("/api/runtime/resources")

    assert response.status_code == 200
    payload = response.json()
    assert {"cpu", "memory", "gpus", "process", "updated_at"}.issubset(payload)
    assert isinstance(payload["cpu"]["available"], bool)
    assert isinstance(payload["memory"]["available"], bool)
    assert isinstance(payload["gpus"], list)


def test_runtime_resources_unavailable_gpu_backend_does_not_raise(monkeypatch) -> None:
    import ai_workbench.core.runtime_resources as runtime_resources

    class BrokenNvml:
        def nvmlInit(self):
            raise RuntimeError("nvml unavailable")

        def nvmlShutdown(self):
            return None

    monkeypatch.setattr(runtime_resources, "_import_nvml", lambda: BrokenNvml())
    service = RuntimeResourcesService(cache_ttl_seconds=0)

    payload = service.resources()

    assert payload["gpus"][0]["available"] is False
    assert payload["gpus"][0]["backend"] == "unavailable"


def test_resource_status_settings_defaults_are_safe(tmp_path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'settings.db'}"))
    response = client.get("/api/settings/general")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource_status_panel_enabled"] is False
    assert payload["resource_status_show_tokens"] is True
    assert payload["resource_status_show_cpu"] is True
    assert payload["resource_status_show_ram"] is True
    assert payload["resource_status_show_gpu"] is True
    assert payload["resource_status_show_vram"] is True
    assert payload["resource_status_ram_display_mode"] == "percent"
    assert payload["resource_status_vram_display_mode"] == "percent"
