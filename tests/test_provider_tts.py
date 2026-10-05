"""Provider speech uses mock transport only; no user databases or live credentials."""
import asyncio
from io import BytesIO
import json
import wave

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import GROK_VOICES, ModelInput, ModelProfile, ProviderProfile, SpeechRequest
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.test_provider_inference import make_manager


PARAMS = {"architecture": "grok-voice-latest", "voice": "alloy"}
HEADERS = {"Authorization": "Bearer test-key"}


def audio(fmt):
    if fmt == "mp3":
        return b"\xff\xfb\x90\x00" + bytes(413)  # MPEG-1, 44.1 kHz; not local 24 kHz output.
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(400))
    return output.getvalue()


def add_tts(manager, provider, **parameters):
    return manager.profiles.create(ModelProfile(name="Speech", alias="speech", kind="tts", model_ref="upstream-id",
        source={"type": "provider", "provider_profile_id": provider.id}, parameters={**PARAMS, **parameters}))


@pytest.fixture
def api(tmp_path):
    calls = []
    async def handler(request):
        assert request.url.path == "/v1/audio/speech"
        assert request.headers["authorization"] == "Bearer upstream-secret"
        payload = json.loads(request.content)
        calls.append(payload)
        fmt = payload["response_format"]
        return httpx.Response(200, content=audio(fmt), headers={"Content-Type": "audio/wav" if fmt == "wav" else "audio/mpeg"})
    with TestClient(create_app(root=tmp_path, use_memory=True,
            adapter_factory=lambda connection: OpenAIAdapter(connection, httpx.MockTransport(handler))),
            client=("127.0.0.1", 40001)) as client:
        provider = client.post("/api/models/providers", json={"name": "Mock speech", "connection": {
            "base_url": "https://provider.test/v1", "api_key": "upstream-secret"}}).json()
        response = client.post("/api/models/profiles", json={"name": "Speech", "alias": "speech", "kind": "tts",
            "source": {"type": "provider", "provider_profile_id": provider["id"]}, "model_ref": "upstream-id",
            "parameters": PARAMS, "external_enabled": True})
        assert response.status_code == 200, response.text
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"})
        yield client, response.json(), provider, calls


def test_api_defaults_overrides_discovery_and_visibility(api):
    client, profile, provider, calls = api
    path = f"/api/models/profiles/{profile['id']}"
    assert profile["parameters"] == {**PARAMS, "speed": 1, "response_format": "mp3"}
    voices = client.get("/v1/audio/voices?model=speech", headers=HEADERS).json()["data"]
    assert [item["id"] for item in voices] == list(GROK_VOICES)
    assert all(item["source"] == "preset" and item["language"] is None for item in voices)
    assert len(client.get(path + "/voices").json()) == 8
    assert not calls
    for patch, voice, fmt, speed in [({}, "alloy", "mp3", 1), ({"voice": None}, "alloy", "mp3", 1),
            ({"voice": "eve", "response_format": "wav", "speed": 1.2}, "eve", "wav", 1.2)]:
        response = client.post("/v1/audio/speech", headers=HEADERS, json={"model": "speech", "input": "Hello", **patch})
        assert response.status_code == 200, response.text
        assert response.content == audio(fmt)
        assert calls[-1] == dict(model="upstream-id", input="Hello", voice=voice, speed=speed, response_format=fmt)
    assert client.get(path).json()["parameters"] == profile["parameters"]
    assert client.patch(path, json={"source": None}).status_code == 422
    assert client.patch(path, json={"name": "Renamed"}).json()["parameters"] == profile["parameters"]
    assert client.delete(f"/api/models/providers/{provider['id']}").status_code == 409
    custom = {"architecture": "customize", "voice": "MyVoice", "response_format": "wav", "speed": 0.8}
    assert client.patch(path, json={"parameters": custom}).json()["parameters"] == custom
    assert client.get("/v1/audio/voices?model=speech", headers=HEADERS).json()["data"] == []
    assert client.post("/v1/audio/speech", headers=HEADERS, json={"model": "speech", "input": "Hi"}).status_code == 200
    assert calls[-1]["voice"] == "MyVoice"
    assert calls[-1]["response_format"] == "wav"
    assert client.post("/v1/audio/speech", headers=HEADERS, json={"model": "speech", "input": "Hi", "voice": "other"}).status_code == 200
    assert calls[-1]["voice"] == "other"
    client.patch(f"/api/models/providers/{provider['id']}", json={"enabled": False})
    count = len(calls)
    assert client.post("/v1/audio/speech", headers=HEADERS, json={"model": "speech", "input": "Hi"}).status_code == 503
    assert len(calls) == count
    client.patch(path, json={"external_enabled": False})
    assert client.get("/v1/audio/voices?model=speech", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("patch", [{"voice": "unknown"}, {"voice": " "}, {"tts": {"language": "en-US"}},
    {"tts": {"model_options": {"seed": 0}}}, {"tts": {"reference_audio": {"format": "wav", "data_base64": "AAAA"}}}])
def test_unsupported_inputs_never_reach_provider(api, patch):
    client, _, _, calls = api
    response = client.post("/v1/audio/speech", headers=HEADERS, json={"model": "speech", "input": "Hi", **patch})
    assert response.status_code in {400, 404}
    assert not calls


@pytest.mark.parametrize("parameters", [{}, {"voice": "alloy"}, {**PARAMS, "voice": "unknown"},
    {**PARAMS, "seed": 0}, {**PARAMS, "architecture": "other"}, {"architecture": "customize", "voice": " "}])
def test_strict_provider_parameters(parameters):
    with pytest.raises(ValidationError):
        ModelInput(name="Speech", alias="speech", kind="tts", model_ref="remote",
            source={"type": "provider", "provider_profile_id": "mock"}, parameters=parameters)


@pytest.mark.parametrize("failure,code", [("http", "PROVIDER_ERROR"), ("timeout", "MODEL_TIMEOUT"),
    ("mime", "PROVIDER_PROTOCOL_ERROR"), ("empty", "PROVIDER_PROTOCOL_ERROR"),
    ("signature", "PROVIDER_PROTOCOL_ERROR"), ("oversize", "PROVIDER_PROTOCOL_ERROR")])
def test_transport_failures_release_queue_and_recover(failure, code):
    async def scenario():
        broken = True
        async def handler(request):
            if broken:
                if failure == "http":
                    return httpx.Response(401, json={"error": "private-secret"})
                if failure == "timeout":
                    raise httpx.ReadTimeout("private-secret")
                content = {"mime": audio("mp3"), "empty": b"", "signature": b"invalid", "oversize": bytes(32 * 1024 * 1024 + 1)}[failure]
                return httpx.Response(200, content=content, headers={"Content-Type": "application/json" if failure == "mime" else "audio/mpeg"})
            return httpx.Response(200, content=audio("mp3"), headers={"Content-Type": "audio/mpeg"})
        manager, provider = make_manager(handler)
        profile = add_tts(manager, provider)
        try:
            with pytest.raises(ModelError) as error:
                await manager.speech(profile.id, SpeechRequest(model="speech", input="Hi"))
            assert error.value.code == code
            assert "private-secret" not in error.value.message
            status = manager.status(profile.id)
            assert status.active == status.queued == 0
            assert status.state == "failed"
            broken = False
            await manager.speech(profile.id, SpeechRequest(model="speech", input="Hi"))
            assert manager.status(profile.id).state == "ready"
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_cancelled_stream_closes_before_queue_release():
    async def scenario():
        started, closed = asyncio.Event(), asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield audio("mp3")
                started.set()
                await asyncio.Event().wait()
            async def aclose(self):
                closed.set()
        async def handler(request):
            return httpx.Response(200, stream=Stream(), headers={"Content-Type": "audio/mpeg"})
        manager, provider = make_manager(handler)
        profile = add_tts(manager, provider)
        task = asyncio.create_task(manager.speech(profile.id, SpeechRequest(model="speech", input="Hi")))
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert manager.status(profile.id).active == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set()
            assert manager.status(profile.id).active == manager.status(profile.id).queued == 0
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_migration_preserves_rows_and_directories(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'speech.db'}")
    migrations.upgrade(engine, migrations.QQ_MEDIA_REVISION)
    providers, profiles = ProviderProfileStore(engine), ModelProfileStore(engine)
    provider = providers.create(ProviderProfile(name="Mock", connection={"base_url": "https://provider.test/v1"}))
    local = profiles.create(ModelProfile(name="Local", alias="local", kind="tts", model_ref="tts/missing"))
    local = profiles.get(local.id)
    files = [tmp_path / "data" / directory / "keep.bin" for directory in ("models", "attachments", "runtimes")]
    for file in files:
        file.parent.mkdir(parents=True)
        file.write_bytes(b"keep")
    try:
        migrations.upgrade(engine)
        assert profiles.get(local.id) == local
        remote = profiles.create(ModelProfile(name="Remote", alias="remote", kind="tts", model_ref="upstream",
            source={"type": "provider", "provider_profile_id": provider.id}, parameters=PARAMS))
        remote = profiles.get(remote.id)
        migrations.upgrade(engine)
        assert profiles.get(remote.id) == remote
        assert all(file.read_bytes() == b"keep" for file in files)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == migrations.PROVIDER_TTS_REVISION
    finally:
        engine.dispose()
