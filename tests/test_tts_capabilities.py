"""Capabilities describe the same contract as inference, without admitting work."""
import sys
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.schema import GROK_VOICES
from tests.model_fixtures import write_local_model
from tests.test_provider_tts import api, HEADERS
from tests.test_tts import model_tree


def test_provider_catalog_is_complete_read_only_and_credential_free(api):
    client, profile, provider, calls = api
    manager = client.app.state.runtime_state.model_manager
    manager.load = AsyncMock(side_effect=AssertionError("Discovery must not load models"))
    before = set(sys.modules)
    response = client.get("/v1/audio/capabilities", headers=HEADERS)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["contract_version"] == 1 and catalog["object"] == "list" and not catalog["issues"]
    model = catalog["data"][0]
    assert model["id"] == "speech" and model["available"]
    assert model["named"]["default_voice_id"] == "alloy"
    assert [voice["id"] for voice in model["named"]["voices"]] == list(GROK_VOICES)
    assert all(voice["languages"] == [language["id"] for language in model["languages"]]
               for voice in model["named"]["voices"])
    assert not model["cloned"]["supported"] and not model["supports_seed"] and model["supports_auto_language"]
    assert model["parameters"] == [{"key": "speed", "value_type": "number", "required": False, "nullable": False,
        "default_value": 1.0, "minimum": 0.25, "maximum": 4.0, "exclusive_minimum": False,
        "exclusive_maximum": False, "choices": [], "affects_output": True, "wire_target": "speed"}]
    assert model["response_formats"] == ["mp3", "wav"]
    assert model["limits"]["max_text_scalars"] == 4096 and model["limits"]["max_audio_bytes"] == 32 * 1024 * 1024
    assert not calls and not manager._slots and manager._voice_references is None
    assert not {"torch", "onnxruntime", "spacy", "numpy"} & (set(sys.modules) - before)
    assert client.get(f"/api/models/profiles/{profile['id']}").json() == profile
    for private in (provider["id"], "upstream-secret", "provider.test", "upstream-id", "execution_options"):
        assert private not in response.text


def test_binding_identity_and_default_changes_are_separate(api):
    client, profile, provider, _ = api
    def model():
        return client.get("/v1/audio/capabilities?model=speech", headers=HEADERS).json()["data"][0]
    original = model()
    client.patch(f"/api/models/profiles/{profile['id']}", json={"name": "New display", "parameters": {
        "architecture": "grok-voice-latest", "voice": "eve", "speed": 1.5}}).raise_for_status()
    client.patch(f"/api/models/providers/{provider['id']}", json={"connection": {"api_key": "rotated"}}).raise_for_status()
    changed = model()
    assert changed["binding_fingerprint"] == original["binding_fingerprint"]
    assert changed["named"]["default_voice_id"] == "eve" and changed["parameters"][0]["default_value"] == 1.5
    client.patch(f"/api/models/providers/{provider['id']}", json={"connection": {"base_url": "https://other.test/v1"}}).raise_for_status()
    assert model()["binding_fingerprint"] != original["binding_fingerprint"]


def test_custom_voice_and_visibility(api):
    client, profile, provider, calls = api
    client.patch(f"/api/models/profiles/{profile['id']}", json={"parameters": {
        "architecture": "customize", "voice": "MyVoice"}}).raise_for_status()
    model = client.get("/v1/audio/capabilities?model=speech", headers=HEADERS).json()["data"][0]
    assert model["named"] == {"supported": True, "selection": "custom", "default_voice_id": "MyVoice", "voices": []}
    assert not calls
    client.patch(f"/api/models/providers/{provider['id']}", json={"enabled": False}).raise_for_status()
    catalog = client.get("/v1/audio/capabilities", headers=HEADERS).json()
    assert not catalog["data"][0]["available"] and catalog["issues"][0]["model"] == "speech"
    client.patch(f"/api/models/profiles/{profile['id']}", json={"external_enabled": False}).raise_for_status()
    assert client.get("/v1/audio/capabilities", headers=HEADERS).json()["data"] == []
    assert client.get("/v1/audio/capabilities?model=speech", headers=HEADERS).status_code == 404
    assert client.get("/v1/audio/capabilities").status_code == 401


def test_local_engines_use_resolved_defaults_and_isolate_broken_models(tmp_path):
    kokoro = model_tree(tmp_path)
    for engine in ("chatterbox", "qwen3tts"):
        write_local_model(tmp_path, f"tts/{engine}", engine)
    with TestClient(create_app(root=tmp_path, use_memory=True), client=("127.0.0.1", 40001)) as client:
        for engine in ("kokoro", "chatterbox", "qwen3tts"):
            response = client.post("/api/models/profiles", json={"name": engine, "alias": engine, "kind": "tts",
                "model_ref": f"tts/{engine}", "source": {"type": "local"}, "external_enabled": True})
            assert response.status_code == 200, response.text
            assert "architecture" not in response.json()["parameters"]
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"})
        manager = client.app.state.runtime_state.model_manager
        manager.load = AsyncMock(side_effect=AssertionError("Discovery must not load models"))
        catalog = client.get("/v1/audio/capabilities", headers=HEADERS).json()
        assert not catalog["issues"]
        models = {model["id"]: model for model in catalog["data"]}
        assert models["kokoro"]["named"]["voices"][0]["languages"] == ["en-US"]
        assert not models["kokoro"]["supports_seed"]
        for engine in ("chatterbox", "qwen3tts"):
            model = models[engine]
            assert model["supports_seed"] and model["supports_auto_language"]
            assert not model["named"]["supported"] and model["cloned"]["max_reference_pairs"] == 1
            assert model["limits"]["max_reference_bytes"] == 8 * 1024 * 1024
            assert model["limits"]["max_reference_duration_ms"] == 30000
            fields = {field["key"]: field for field in model["parameters"]}
            assert fields["seed"]["nullable"] and fields["seed"]["default_value"] is None
            assert fields["seed"]["wire_target"] == "model_options" and fields["seed"]["maximum"] == 4294967295
            assert fields["temperature"]["exclusive_minimum"]
        assert models["qwen3tts"]["cloned"]["reference_text_mode"] == "optional"
        assert models["chatterbox"]["cloned"]["reference_text_mode"] == "unsupported"

        provider = client.post("/api/models/providers", json={"name": "Online speech", "connection": {
            "base_url": "https://provider.test/v1", "api_key": "unused-secret"}})
        provider.raise_for_status()
        online = client.post("/api/models/profiles", json={"name": "Online", "alias": "online", "kind": "tts",
            "source": {"type": "provider", "provider_profile_id": provider.json()["id"]},
            "model_ref": "speech", "parameters": {"architecture": "grok-voice-latest", "voice": "alloy"},
            "external_enabled": True})
        online.raise_for_status()
        pending = client.post("/api/models/profiles", json={"name": "Pending", "alias": "pending", "kind": "tts",
            "source": {"type": "local"}, "model_ref": "tts/not-yet-configured", "external_enabled": True})
        pending.raise_for_status()
        (kokoro / "model.onnx").unlink()
        with patch("httpx.AsyncClient.send", side_effect=AssertionError("Discovery must not call upstream")):
            catalog = client.get("/v1/audio/capabilities", headers=HEADERS).json()
        assert {model["id"] for model in catalog["data"]} == {"chatterbox", "qwen3tts", "online"}
        assert {issue["model"] for issue in catalog["issues"]} == {"kokoro", "pending"}
        assert not manager._slots and manager._voice_references is None
