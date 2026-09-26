"""Configurable HTTP/model budgets and their private transport boundaries."""
import asyncio
from contextlib import asynccontextmanager
from http.server import ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session
from starlette.requests import Request

from ai_workbench.api.main import create_app
from ai_workbench.core.models import images
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.http import read_body
from ai_workbench.core.models.schema import ChatRequest, ImageEmbeddingRequest, ModelProfile, ModelSettings, VisionRequest
from ai_workbench.db.models import AppMetadataRecord
from ai_workbench.workers import server, transformers_server
from tests.test_vision_input import manager, profile as chat_profile
from tests.test_wd14 import DEFAULTS, data_url, model_tree, profile as tagging_profile

MIB = 1024 * 1024


def test_settings_defaults_bounds_strict_patch_and_openapi(tmp_path):
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        path = "/api/models/settings"
        initial = client.get(path).json()
        assert (initial["max_request_mb"], initial["max_normalized_request_mb"]) == (32, 128)
        for field, bounds in (("max_request_mb", (1, 100)), ("max_normalized_request_mb", (1, 1024))):
            for value in bounds:
                response = client.patch(path, json={field: value})
                assert response.status_code == 200 and response.json()[field] == value
            for value in (None, 0, -1, bounds[1] + 1):
                assert client.patch(path, json={field: value}).status_code == 422
        for value in (True, False, 128.0, 1.5, "128", "", [], {}):
            assert client.patch(path, json={"max_normalized_request_mb": value}).status_code == 422
        retained = client.patch(path, json={"external_api_key": "fixture-key"}).json()
        assert retained["max_normalized_request_mb"] == 1024 and retained["max_request_mb"] == 100
        assert retained["has_external_api_key"] and "external_api_key" not in retained
        assert client.patch(path, json={}).json() == retained
        assert client.get(path).json() == retained
        schemas = client.get("/openapi.json").json()["components"]["schemas"]
        for name in ("Documented__ModelSettingsPatch", "ModelSettingsResponse"):
            field = schemas[name]["properties"]["max_normalized_request_mb"]
            assert field["type"] == "integer" and field["minimum"] == 1 and field["maximum"] == 1024


def test_settings_preserve_saved_http_limit_and_persist_normalized_limit(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    with TestClient(create_app(root=tmp_path, database_url=database_url)) as client:
        store = client.app.state.runtime_state.model_settings
        with Session(store.engine) as db:
            db.add(AppMetadataRecord(key="model_settings", value=json.dumps({"max_request_mb": 10})))
            db.commit()
        value = client.get("/api/models/settings").json()
        assert value["max_request_mb"] == 10 and value["max_normalized_request_mb"] == 128
        response = client.patch("/api/models/settings", json={"max_normalized_request_mb": 256})
        assert response.status_code == 200 and response.json()["max_request_mb"] == 10
    with TestClient(create_app(root=tmp_path, database_url=database_url)) as reopened:
        value = reopened.get("/api/models/settings").json()
        assert value["max_request_mb"] == 10 and value["max_normalized_request_mb"] == 256


@pytest.mark.parametrize("declared_length", [None, "1", str(MIB)])
def test_http_budget_counts_received_bytes_at_the_exact_boundary(declared_length):
    async def scenario(extra):
        chunks = [b"x" * (MIB // 2), b"y" * (MIB // 2 + extra)]
        async def receive():
            chunk = chunks.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}
        headers = [] if declared_length is None else [(b"content-length", declared_length.encode())]
        return await read_body(Request({"type": "http", "headers": headers}, receive), ModelSettings(max_request_mb=1))
    assert len(asyncio.run(scenario(0))) == MIB
    with pytest.raises(ModelError) as error:
        asyncio.run(scenario(1))
    assert error.value.status == 413 and error.value.code == "REQUEST_TOO_LARGE"


def test_default_http_budget_accepts_above_ten_mib_and_rejects_declared_overflow():
    async def scenario():
        async def receive():
            return {"type": "http.request", "body": b"x" * (11 * MIB), "more_body": False}
        assert len(await read_body(Request({"type": "http", "headers": []}, receive), ModelSettings())) == 11 * MIB
        unread = AsyncMock(side_effect=AssertionError("An oversized declared body was read"))
        request = Request({"type": "http", "headers": [(b"content-length", str(32 * MIB + 1).encode())]}, unread)
        with pytest.raises(ModelError) as error:
            await read_body(request, ModelSettings())
        assert error.value.status == 413
        unread.assert_not_called()
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["chat", "tags", "siglip_image", "siglip_text"])
def test_normalization_budget_matches_complete_transport_json(operation, monkeypatch):
    monkeypatch.setattr(images, "_normalized_image", lambda url, **_: url)
    if operation == "chat":
        profile = chat_profile().model_copy(update={"parameters": {"stop": ["default stop"]}})
        messages = [{"role": "user", "content": "历史"}, {"role": "assistant", "content": "reply"},
                    {"role": "user", "content": "next"}]
        request = ChatRequest(model="public-alias", messages=messages)
        payload = {"model": "managed", "messages": messages, "stream": False, "stop": ["default stop"]}
        prepare = lambda limit: images.prepare_local_images(profile, request, limit)
    elif operation == "tags":
        payload = {"profile_id": "profile", "images": [data_url()], "thresholds": DEFAULTS}
        prepare = lambda limit: images.prepare_tagging_images("profile", payload["images"], DEFAULTS, limit)
    else:
        tower = "image" if operation == "siglip_image" else "text"
        payload = {"inputs": [data_url()] if tower == "image" else ["文字", "another input"]}
        prepare = lambda limit: images.prepare_image_embedding_inputs(tower, payload["inputs"], limit)
    size = len(httpx.Request("POST", "http://worker.test", json=payload).content)
    prepare(size)
    with pytest.raises(ModelError) as error:
        prepare(size - 1)
    assert error.value.status == 413 and error.value.code == "REQUEST_TOO_LARGE"


@pytest.mark.parametrize("operation", ["chat", "chat_stream", "prepared_stream", "tags", "siglip_image", "siglip_text", "rerank"])
def test_saved_limit_applies_before_admission_and_changes_without_reloading(tmp_path, monkeypatch, operation):
    service = manager(tmp_path)
    if operation in {"chat", "chat_stream", "prepared_stream"}:
        model = service.profiles.create(chat_profile())
    elif operation == "tags":
        model_tree(tmp_path)
        model = service.profiles.create(tagging_profile())
    else:
        kind = "reranker" if operation == "rerank" else "image_embedding"
        model = service.profiles.create(ModelProfile(name="Fixture", alias="fixture", kind=kind,
            model_ref="fixture", source={"type": "local"}))
    # Small image input expands past 1 MiB, independently of the public HTTP budget.
    monkeypatch.setattr(images, "_normalized_image", lambda _url, **_: "data:image/png;base64," + "x" * MIB)
    admitted = []
    infer = AsyncMock(return_value="accepted")
    async def stream(*_):
        yield "accepted"
    adapter = SimpleNamespace(chat=infer, chat_stream=stream, vision=infer, image_embed=infer, rerank=infer)
    @asynccontextmanager
    async def lease(profile, **_):
        admitted.append(profile.id)
        yield adapter
    monkeypatch.setattr(service, "_lease", lease)
    monkeypatch.setattr(service, "load", AsyncMock())

    async def invoke():
        if operation in {"chat", "chat_stream", "prepared_stream"}:
            request = ChatRequest(model=model.alias, messages=[{"role": "user", "content": "x" * MIB}], stream=operation != "chat")
            if operation == "chat":
                return await service.chat(model.id, request)
            chunks = (await service.prepare_chat_stream(model.id, request)) if operation == "prepared_stream" else service.chat_stream(model.id, request)
            return "".join([chunk async for chunk in chunks])
        if operation == "tags":
            return await service.vision(model.id, VisionRequest(model=model.alias, images=[data_url()]))
        if operation == "rerank":
            return await service.rerank(model.id, "search", ["x" * MIB])
        tower = "image" if operation == "siglip_image" else "text"
        return await service.image_embed(model.id, ImageEmbeddingRequest(model=model.alias, input_type=tower,
            input=data_url() if tower == "image" else "界" * (MIB // 3)))

    async def scenario():
        assert not service.settings.get().external_enabled
        for limit in (1, 2, 1):
            service.settings.patch({"max_normalized_request_mb": limit})
            if limit == 2:
                assert await invoke() == "accepted"
            else:
                with pytest.raises(ModelError) as error:
                    await invoke()
                assert error.value.status == 413 and "configured 1 MiB" in str(error.value)
        assert admitted == [model.id]
        assert service.load.await_count == (1 if operation == "prepared_stream" else 0)
    asyncio.run(scenario())


def test_rerank_complete_private_body_exact_boundary(tmp_path, monkeypatch):
    service = manager(tmp_path)
    model = service.profiles.create(ModelProfile(name="Reranker", alias="reranker", kind="reranker", model_ref="fixture", source={"type": "local"}))
    service.settings.patch({"max_normalized_request_mb": 1})
    body = {"profile_id": model.id, "query": "查询", "documents": [""]}
    document = "x" * (MIB - len(httpx.Request("POST", "http://worker.test", json=body).content))
    calls = []
    @asynccontextmanager
    async def lease(_):
        calls.append(True)
        yield SimpleNamespace(rerank=AsyncMock(return_value="accepted"))
    monkeypatch.setattr(service, "_lease", lease)
    async def scenario():
        assert await service.rerank(model.id, body["query"], [document]) == "accepted"
        with pytest.raises(ModelError) as error:
            await service.rerank(model.id, body["query"], [document + "x"])
        assert error.value.status == 413 and calls == [True]
    asyncio.run(scenario())


def test_shared_worker_accepts_above_old_limit_and_enforces_transport_ceiling(monkeypatch):
    assert server.MAX_BODY == 1024 * MIB
    worker = SimpleNamespace(dispatch=lambda _path, body: {"length": len(body["input"])})
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(worker, "token"))
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{http.server_port}", headers={"X-Worker-Token": "token"}, trust_env=False) as client:
            response = client.post("/embed", json={"input": "x" * (33 * MIB)})
            assert response.status_code == 200 and response.json()["length"] == 33 * MIB
            body = b'{"input":"text"}'
            monkeypatch.setattr(server, "MAX_BODY", len(body))
            assert client.post("/embed", content=body).status_code == 200
            assert client.post("/embed", content=body + b" ").status_code == 413
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_transformers_worker_accepts_above_old_limit_and_checks_chunked_transport(monkeypatch):
    assert transformers_server.MAX_BODY == 1024 * MIB
    async def chat(body, _request_id):
        return JSONResponse({"length": len(body["messages"][0]["content"])})
    engine = SimpleNamespace(chat=chat, close=lambda: None)
    with TestClient(transformers_server.build_app(engine, "token")) as client:
        headers = {"Authorization": "Bearer token"}
        body = {"model": "managed", "messages": [{"role": "user", "content": "x" * (33 * MIB)}]}
        response = client.post("/v1/chat/completions", headers=headers, json=body)
        assert response.status_code == 200 and response.json()["length"] == 33 * MIB
        body["messages"][0]["content"] = "text"
        raw = httpx.Request("POST", "http://worker.test", json=body).content
        monkeypatch.setattr(transformers_server, "MAX_BODY", len(raw))
        assert client.post("/v1/chat/completions", headers=headers, content=raw).status_code == 200
        rejected = client.post("/v1/chat/completions", headers=headers, content=iter([raw, b" "]))
        assert rejected.status_code == 413 and rejected.json()["error"]["code"] == "REQUEST_TOO_LARGE"
