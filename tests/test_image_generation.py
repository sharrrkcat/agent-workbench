"""Provider image generation: isolated databases and mock transport, never live credentials."""
import asyncio
import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import ImageGenerationRequest, ModelInput, ModelProfile, ProviderProfile
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.test_provider_inference import make_manager


HEADERS = {"Authorization": "Bearer test-key"}
URL = "https://images.test/result.png?signature=retained"
B64 = base64.b64encode(b"image payload").decode()
PROFILE = dict(name="Image", alias="image", kind="image_generation", model_ref="upstream-image")


def add_image(manager, provider, **values):
    return manager.profiles.create(ModelProfile(**{**PROFILE, **values},
        source={"type": "provider", "provider_profile_id": provider.id}))


@pytest.fixture
def api(tmp_path):
    calls = []
    async def handler(request):
        assert request.url.path == "/v1/images/generations"
        assert request.headers["authorization"] == "Bearer upstream-secret"
        payload = json.loads(request.content)
        calls.append(payload)
        fmt = payload.get("response_format", "url")
        return httpx.Response(200, json={"created": 1, "provider_metadata": "private",
            "data": [{fmt: URL if fmt == "url" else B64, "revised_prompt": "Revised", "metadata": "private"}
                     for _ in range(payload["n"])]})
    with TestClient(create_app(root=tmp_path, use_memory=True,
            adapter_factory=lambda connection: OpenAIAdapter(connection, httpx.MockTransport(handler))),
            client=("127.0.0.1", 40001)) as client:
        provider = client.post("/api/models/providers", json={"name": "Mock images", "connection": {
            "base_url": "https://provider.test/v1", "api_key": "upstream-secret"}}).json()
        response = client.post("/api/models/profiles", json={**PROFILE,
            "source": {"type": "provider", "provider_profile_id": provider["id"]}, "external_enabled": True})
        assert response.status_code == 200, response.text
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"})
        yield client, response.json(), provider, calls


def test_profile_sources_discovery_visibility_and_local_exclusion(api):
    client, profile, provider, calls = api
    path = f"/api/models/profiles/{profile['id']}"
    assert profile["parameters"] == {"n": 1}
    assert client.get("/api/models/profiles?kind=image_generation").json() == [profile]
    assert client.get("/v1/models?kind=image_generation", headers=HEADERS).json()["data"][0]["id"] == "image"
    for source in (None, {"type": "local"}):
        assert client.patch(path, json={"source": source}).status_code == 422
    assert client.patch(path, json={"name": "Renamed"}).json()["source"] == profile["source"]
    assert client.patch(path, json={"kind": "llm"}).status_code == 409
    for action in ("load", "unload", "health"):
        assert client.post(path + "/" + action).status_code == 422
    assert client.get(path + "/status").json()["state"] == "unknown"
    assert client.get("/api/models/inventory?kind=image_generation").json() == []
    assert client.get("/api/models/inspect?kind=image_generation&model_ref=remote").status_code == 422
    assert client.delete(f"/api/models/providers/{provider['id']}").status_code == 409
    assert not calls
    body = {"model": "image", "prompt": "An apple"}
    assert client.post("/v1/images/generations", json=body).status_code == 401
    client.patch(f"/api/models/providers/{provider['id']}", json={"enabled": False})
    assert client.post("/v1/images/generations", headers=HEADERS, json=body).status_code == 503
    client.patch(path, json={"external_enabled": False})
    assert client.post("/v1/images/generations", headers=HEADERS, json=body).status_code == 404
    assert client.get("/v1/models?kind=image_generation", headers=HEADERS).json()["data"] == []
    assert not calls


def test_api_defaults_overrides_and_standard_results(api):
    client, profile, _, calls = api
    path = f"/api/models/profiles/{profile['id']}"
    before = int(time.time())
    body = {"model": "image", "prompt": "  An apple  "}
    response = client.post("/v1/images/generations", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert before <= response.json()["created"] <= int(time.time())
    assert response.json()["data"] == [{"url": URL, "revised_prompt": "Revised"}]
    assert response.headers["X-Request-Id"]
    assert calls[-1] == {"model": "upstream-image", "prompt": body["prompt"], "n": 1}
    status = client.get(path + "/status").json()
    assert (status["state"], status["active"], status["queued"], status["runtime"]) == ("ready", 0, 0, None)
    parameters = dict(n=2, size="1024x1024", quality="standard", style="natural", response_format="b64_json")
    assert client.patch(path, json={"parameters": parameters}).status_code == 200
    for overrides in ({}, {key: None for key in parameters}, {"n": 1, "size": "auto", "quality": "high", "style": "vivid"}):
        response = client.post("/v1/images/generations", headers=HEADERS, json={**body, **overrides})
        assert response.status_code == 200, response.text
        expected = {**parameters, **{key: value for key, value in overrides.items() if value is not None}}
        assert calls[-1] == {**expected, "model": "upstream-image", "prompt": body["prompt"]}
        assert response.json()["data"] == [{"b64_json": B64, "revised_prompt": "Revised"}] * expected["n"]
        assert client.get(path).json()["parameters"] == parameters
    assert client.patch(path, json={"parameters": {"n": 1, "size": None}}).json()["parameters"] == {"n": 1}


@pytest.mark.parametrize("source", [None, {}, {"source": None}, {"source": {"type": "local"}}])
def test_saved_profiles_require_provider(source):
    with pytest.raises(ValidationError):
        ModelInput(**PROFILE, **(source or {}))


def test_invalid_requests_and_parameters_never_reach_provider(api):
    client, profile, _, calls = api
    invalid = [{"prompt": " "}, {"prompt": "x" * 32001}, {"n": True}, {"n": 0}, {"n": 11}, {"n": "2"},
               {"size": "0x1024"}, {"size": "1024X1024"}, {"quality": "best"}, {"style": "other"},
               {"response_format": "png"}, {"stream": True}, {"aspect_ratio": "1:1"}]
    for patch in invalid:
        response = client.post("/v1/images/generations", headers=HEADERS, json={"model": "image", "prompt": "Apple", **patch})
        assert response.status_code == 400, response.text
        if "prompt" not in patch:
            assert client.patch(f"/api/models/profiles/{profile['id']}", json={"parameters": patch}).status_code == 422
    assert client.post("/v1/images/generations", headers=HEADERS, json={"model": "image"}).status_code == 400
    other = client.post("/api/models/profiles", json={"name": "Chat", "alias": "chat", "kind": "llm", "model_ref": "chat",
        "external_enabled": True}).json()
    assert client.post("/v1/images/generations", headers=HEADERS, json={"model": other["alias"], "prompt": "Apple"}).status_code == 400
    assert not calls


@pytest.mark.parametrize("failure,code", [
    ("http", "PROVIDER_ERROR"), ("timeout", "MODEL_TIMEOUT"), ("connection", "MODEL_UNAVAILABLE"),
    *[(value, "PROVIDER_PROTOCOL_ERROR") for value in ["json", "duplicate", "nan", "empty", "count", "item", "base64",
        "url", "both", "missing", "wrong_format", "error"]],
])
def test_transport_errors_release_queue_and_recover(failure, code):
    async def scenario():
        broken = True
        async def handler(request):
            if not broken:
                return httpx.Response(200, json={"data": [{"url": URL}]})
            if failure == "http":
                return httpx.Response(401, json={"error": "private-secret"})
            if failure == "timeout":
                raise httpx.ReadTimeout("private-secret")
            if failure == "connection":
                raise httpx.ConnectError("private-secret")
            content = {"json": b"private-secret", "duplicate": b'{"data":[],"data":[]}', "nan": b'{"data":[],"x":NaN}'}
            if failure in content:
                return httpx.Response(200, content=content[failure])
            items = {"empty": [], "count": [{"url": URL}] * 2, "item": [1], "base64": [{"b64_json": "%%%"}],
                "url": [{"url": "file:///private-secret"}], "both": [{"url": URL, "b64_json": B64}],
                "missing": [{}], "wrong_format": [{"b64_json": B64}], "error": [{"url": URL}]}
            return httpx.Response(200, json={"data": items[failure], **({"error": "private-secret"} if failure == "error" else {})})
        manager, provider = make_manager(handler)
        profile = add_image(manager, provider)
        request = ImageGenerationRequest(model="image", prompt="Apple", response_format="url")
        try:
            with pytest.raises(ModelError) as error:
                await manager.generate_images(profile.id, request)
            assert error.value.code == code
            assert "private-secret" not in str(error.value)
            status = manager.status(profile.id)
            assert (status.state, status.active, status.queued) == ("failed", 0, 0)
            broken = False
            assert (await manager.generate_images(profile.id, request)).data[0].url == URL
            assert manager.status(profile.id).state == "ready"
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_response_limit_stops_reading_and_closes_stream():
    async def scenario():
        closed = asyncio.Event()
        chunks = 0
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                nonlocal chunks
                for _ in range(100):
                    chunks += 1
                    yield b" " * (1024 * 1024)
            async def aclose(self):
                closed.set()
        manager, provider = make_manager(lambda request: httpx.Response(200, stream=Stream()))
        profile = add_image(manager, provider)
        try:
            with pytest.raises(ModelError) as error:
                await manager.generate_images(profile.id, ImageGenerationRequest(model="image", prompt="Apple"))
            assert error.value.code == "PROVIDER_PROTOCOL_ERROR"
            assert chunks == 65 and closed.is_set()
            assert manager.status(profile.id).active == manager.status(profile.id).queued == 0
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_aliases_share_provider_queue_and_cancellation_closes_transport():
    async def scenario():
        started, closed = asyncio.Event(), asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"data":['
                started.set()
                await asyncio.Event().wait()
            async def aclose(self):
                closed.set()
        manager, provider = make_manager(lambda request: httpx.Response(200, stream=Stream()))
        manager.providers.update(provider.id, {"connection": {**provider.connection.model_dump(), "queue_size": 0}})
        profile = add_image(manager, provider)
        alias = add_image(manager, provider, alias="other")
        request = ImageGenerationRequest(model="image", prompt="Apple")
        task = asyncio.create_task(manager.generate_images(profile.id, request))
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert manager.status(alias.id).active == 1
            with pytest.raises(ModelError) as error:
                await manager.generate_images(alias.id, request)
            assert error.value.code == "MODEL_BUSY"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set()
            assert manager.status(profile.id).active == manager.status(profile.id).queued == 0
            assert manager.status(profile.id).state == "unknown"
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_migration_preserves_existing_rows_files_and_rejects_local_sources(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'images.db'}")
    migrations.upgrade(engine, migrations.PROVIDER_TTS_REVISION)
    providers, profiles = ProviderProfileStore(engine), ModelProfileStore(engine)
    provider = providers.create(ProviderProfile(name="Mock", connection={"base_url": "https://provider.test/v1"}))
    provider = providers.get(provider.id)
    previous = profiles.create(ModelProfile(name="Chat", alias="chat", kind="llm", model_ref="chat"))
    previous = profiles.get(previous.id)
    files = [tmp_path / "data" / directory / "keep.bin" for directory in ("models", "attachments", "runtimes")]
    for file in files:
        file.parent.mkdir(parents=True)
        file.write_bytes(b"keep")
    try:
        migrations.upgrade(engine, migrations.IMAGE_GENERATION_REVISION)
        profile = profiles.create(ModelProfile(**PROFILE, source={"type": "provider", "provider_profile_id": provider.id}))
        profile = profiles.get(profile.id)
        for statement in ["source_type=NULL,provider_profile_id=NULL", "source_type='local',provider_profile_id=NULL,execution_options_json='{}',lifecycle_json='{}'"]:
            with pytest.raises(IntegrityError), engine.begin() as db:
                db.exec_driver_sql(f"UPDATE model_profiles SET {statement} WHERE id=?", (profile.id,))
        migrations.upgrade(engine, migrations.IMAGE_GENERATION_REVISION)
        assert migrations.current_revision(engine) == migrations.IMAGE_GENERATION_REVISION
        assert profiles.get(previous.id) == previous and profiles.get(profile.id) == profile
        assert providers.get(provider.id) == provider
        assert all(file.read_bytes() == b"keep" for file in files)
    finally:
        engine.dispose()
