"""SigLIP profiles, public schemas and ModelManager's shared tower lifecycle."""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from ai_workbench.api.main import create_app
from ai_workbench.core.models import manager as manager_module
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ImageEmbeddingRequest, ModelProfile
from ai_workbench.core.models.siglip import SiglipModelUse
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.test_phase2b_runtime import installed_worker
from tests.test_siglip import REF, model_tree
from tests.test_siglip_runtime import FAKE_ENGINE, until
from tests.test_wd14 import data_url

HEADERS = {"Authorization": "Bearer siglip-test"}


def profile(**values):
    return ModelProfile(**{"name": "SigLIP", "alias": "siglip", "kind": "image_embedding", "model_ref": REF,
                           "source": {"type": "local"}, "external_enabled": True, **values})


def request(tower="text", inputs="hello"):
    return ImageEmbeddingRequest(model="siglip", input_type=tower, input=inputs)


@asynccontextmanager
async def managed_runtime(tmp_path, **values):
    service, manager, kokoro = await installed_worker(tmp_path)
    (service.worker_root / "siglip_engine.py").write_text(FAKE_ENGINE, encoding="utf-8")
    model_tree(tmp_path)
    model = manager.profiles.create(profile(**values))
    manager.settings.patch({"external_enabled": True, "external_api_key": "siglip-test"})
    app = create_app(root=tmp_path, use_memory=True)
    state = app.state.runtime_state
    state.model_manager, state.model_settings = manager, manager.settings
    state.model_profiles, state.provider_profiles = manager.profiles, manager.providers
    state.runtime_supervisor = service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 40001)),
                                   base_url="http://cogita.test", headers=HEADERS) as caller:
            yield service, manager, model, caller, kokoro
    finally:
        await manager.close()
        await service.close()
    assert not list((service.base / ".processes").glob("*"))


@pytest.mark.parametrize("memory", [True, False])
def test_profile_and_inspection_defaults_roundtrip_and_removed_fields(tmp_path, memory):
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")) as caller:
        value = profile().model_dump(exclude={"id", "created_at", "updated_at"})
        response = caller.post("/api/models/profiles", json=value)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["parameters"] == {"unload_other_tower_on_call": True}
        assert saved["source"]["execution_options"] == {"device": "cuda", "intraop_threads": 4, "max_batch_size": 1}
        assert saved["source"]["lifecycle"] == {"unload": "manual", "idle_seconds": 300}
        path = "/api/models/profiles/" + saved["id"]
        assert caller.patch(path, json={"parameters": {"unload_other_tower_on_call": False}}).status_code == 200
        assert caller.get(path).json()["parameters"] == {"unload_other_tower_on_call": False}
        for parameters in ({"architecture": "siglip2"}, {"dimensions": 1152}, {"normalize": True}, {"batch_size": 1},
                           *({"unload_other_tower_on_call": v} for v in (None, 1, "false"))):
            assert caller.patch(path, json={"parameters": parameters}).status_code == 422
        for source in ({"type": "provider", "provider_profile_id": "missing"},
                       {"type": "local", "execution_options": {"max_batch_size": 17}},
                       {"type": "local", "execution_options": {"max_batch_size": True}}):
            assert caller.patch(path, json={"source": source}).status_code == 422
        assert caller.patch(path, json={"source": {"type": "local", "execution_options": {"device": "cpu", "max_batch_size": 16}}}).status_code == 200
        model_tree(tmp_path)
        (tmp_path / "data/models" / REF / "config.json").write_text("broken", encoding="utf-8")
        assert caller.get("/api/models/inspect", params={"kind": "image_embedding", "model_ref": REF}).json()["diagnostics"]
        assert caller.patch(path, json={"name": "Incomplete local model"}).status_code == 200
        assert caller.patch(path, json={"source": None}).status_code == 422
        assert caller.get(path).json()['source']['type'] == 'local'
        catalog = caller.get("/api/models/local-runtime/catalog").json()
        entry = next(item for item in catalog["engines"] if item["engine"] == "siglip2")
        assert entry["kind"] == "image_embedding" and entry["options_schema"]["properties"]["max_batch_size"]["maximum"] == 16


@pytest.mark.parametrize("patch", [
    {"input_type": None}, {"input_type": "both"}, {"input": []}, {"input": ["x"] * 17},
    {"input": " "}, {"input": ["ok", " "]}, {"input": [1]}, {"input": [{"text": "x"}]},
    {"encoding_format": None}, {"encoding_format": "bytes"}, {"dimensions": 2}, {"normalize": False},
    {"images": ["data:image/png;base64,AAAA"]},
])
def test_strict_request_schema(patch):
    with pytest.raises(ValueError):
        ImageEmbeddingRequest.model_validate({"model": "siglip", "input_type": "text", "input": "hello", **patch})


def test_switching_serializes_process_exit_and_reuses_one_identity(tmp_path, monkeypatch):
    prepare = AsyncMock(wraps=SiglipModelUse.prepare)
    monkeypatch.setattr(SiglipModelUse, "prepare", prepare)
    async def scenario():
        async with managed_runtime(tmp_path) as (_, manager, model, caller, _):
            assert manager.status(model.id).towers.image.process_state == "stopped"
            await manager.health(model.id)
            assert prepare.await_count == 0
            assert manager._slot(manager.execution_key(model), model)[0].queue_timeout_seconds == 120
            adapter = manager._managed_slot(model).adapter
            loaded = await caller.post(f"/api/models/profiles/{model.id}/load", json={"tower": "image"})
            assert loaded.status_code == 200, loaded.text
            assert loaded.json()["towers"]["active_tower"] is None
            image_process = adapter.clients["image"].process.process
            first = await manager.image_embed(model.id, request("image", [data_url()]))
            assert image_process is adapter.clients["image"].process.process
            assert first.usage is first.timing is None
            # Observe the old process at the next worker's startup boundary.
            original_load = adapter.clients["image"].__class__.load
            old_processes = []
            async def ordered_load(client):
                assert all(process.returncode is not None for process in old_processes)
                return await original_load(client)
            monkeypatch.setattr(adapter.clients["image"].__class__, "load", ordered_load)
            old_processes.append(image_process)
            second = await manager.image_embed(model.id, request())
            old_processes.append(adapter.clients["text"].process.process)
            third = await manager.image_embed(model.id, request("image", data_url()))
            assert first.model_revision == second.model_revision == third.model_revision
            assert first.vector_space_id == second.vector_space_id == third.vector_space_id
            assert prepare.await_count == 1
            assert manager.status(model.id).towers.text.process_state == "stopped"
            assert manager.status(model.id).active == manager.status(model.id).queued == 0
            await manager.unload(model.id)
            assert manager.status(model.id).towers.model_revision is None
            old_processes.clear()
            (Path(manager.runtime_supervisor.root) / "data/models" / REF / "model.safetensors").write_bytes(b"replacement weights")
            fourth = await manager.image_embed(model.id, request())
            assert prepare.await_count == 2 and fourth.model_revision != first.model_revision
    asyncio.run(scenario())


def test_two_resident_towers_and_other_profiles_have_independent_failure_scopes(tmp_path):
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False}) as (_, manager, model, _, kokoro):
            clone = manager.profiles.create(profile(alias="clone"))
            for p, tower in ((model, "image"), (model, "text"), (clone, "text")):
                await manager.load(p.id, tower=tower)
            await manager.load(kokoro.id)
            adapter = manager._managed_slot(model).adapter
            image_process = adapter.clients["image"].process.process
            text_process = adapter.clients["text"].process.process
            clone_process = manager._managed_slot(clone).adapter.clients["text"].process.process
            kokoro_process = manager._managed_slot(kokoro).adapter.process.process
            identity = adapter.towers.model_revision
            with pytest.raises(ModelError):
                await manager.image_embed(model.id, request(inputs="crash"))
            assert text_process.returncode is not None
            assert manager.status(model.id).state == "failed"
            assert manager.status(model.id).towers.text.process_state == "failed"
            assert adapter.towers.model_revision == identity
            assert (await manager.image_embed(model.id, request("image", data_url()))).tower == "image"
            with pytest.raises(ModelError):
                await manager.image_embed(model.id, request())
            assert image_process.returncode is clone_process.returncode is kokoro_process.returncode is None
            await manager.load(model.id, tower="text")
            assert manager.status(model.id).state == "ready"
            assert adapter.clients["text"].process.process.pid != text_process.pid
            await manager.unload(model.id)
            assert image_process.returncode is not None
            assert clone_process.returncode is kokoro_process.returncode is None
    asyncio.run(scenario())


def test_public_and_internal_requests_share_queue_and_cancel_only_target(tmp_path):
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False}) as (_, manager, model, caller, _):
            await manager.load(model.id, tower="image")
            await manager.load(model.id, tower="text")
            adapter = manager._managed_slot(model).adapter
            image_process = adapter.clients["image"].process.process
            text_process = adapter.clients["text"].process.process
            active = asyncio.create_task(manager.image_embed(model.id, request(inputs="wait")))
            await until(lambda: "waiting child_id=" in adapter.clients["text"].log.path.read_text())
            queued = asyncio.create_task(caller.post("/v1/images/embeddings", json=request().model_dump()))
            await until(lambda: manager.status(model.id).queued == 1)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            assert manager.status(model.id).queued == 0
            assert text_process.returncode is None
            queued = asyncio.create_task(caller.post("/v1/images/embeddings", json=request().model_dump()))
            await until(lambda: manager.status(model.id).queued == 1)
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert text_process.returncode is not None
            response = await queued
            assert response.status_code == 200, response.text
            assert image_process.returncode is None
            assert adapter.clients["text"].process.process.pid != text_process.pid
            assert manager.status(model.id).active == manager.status(model.id).queued == 0
    asyncio.run(scenario())


def test_public_vectors_visibility_limits_and_invalid_input_preserve_residency(tmp_path):
    async def scenario():
        async with managed_runtime(tmp_path) as (_, manager, model, caller, kokoro):
            path = f"/api/models/profiles/{model.id}"
            assert (await caller.post(path + "/load")).status_code == 422
            assert (await caller.post(path + "/load", json={"tower": "both"})).status_code == 422
            assert (await caller.get(path + "/log")).status_code == 422
            assert (await caller.post(f"/api/models/profiles/{kokoro.id}/load", json={"tower": "text"})).status_code == 422
            assert (await caller.get(f"/api/models/profiles/{kokoro.id}/log?tower=text")).status_code == 422
            listed = await caller.get("/v1/models?kind=image_embedding")
            assert [item["id"] for item in listed.json()["data"]] == [model.alias]
            body = request(inputs=["red", "longer blue"]).model_dump()
            first = await caller.post("/v1/images/embeddings", json=body)
            assert first.status_code == 200, first.text
            assert first.headers["x-request-id"]
            value = first.json()
            assert set(value) == {"object", "model", "input_type", "dimensions", "model_revision", "vector_space_id", "data"}
            assert value["dimensions"] == 2 and [item["index"] for item in value["data"]] == [0, 1]
            second = await caller.post("/v1/images/embeddings", json={**body, "encoding_format": "base64"})
            for float_item, encoded in zip(value["data"], second.json()["data"]):
                assert struct.unpack("<2f", base64.b64decode(encoded["embedding"])) == pytest.approx(float_item["embedding"])
            adapter = manager._managed_slot(model).adapter
            process = adapter.clients["text"].process.process
            for inputs in ("https://example.test/a.png", "../file.png", "data:image/png;base64,broken", [data_url(), "bad"]):
                bad = await caller.post("/v1/images/embeddings", json=request("image", inputs).model_dump())
                assert bad.status_code == 422, bad.text
                assert process is adapter.clients["text"].process.process and process.returncode is None
            assert (await caller.post("/v1/images/embeddings", json=body, headers={"Authorization": "Bearer wrong"})).status_code == 401
            assert (await caller.post("/v1/embeddings", json={"model": model.alias, "input": "hello"})).json()["error"]["code"] == "MODEL_KIND_MISMATCH"
            for values in ({"external_enabled": False}, {"enabled": False}):
                manager.profiles.update(model.id, values)
                assert (await caller.post("/v1/images/embeddings", json=body)).status_code == 404
                manager.profiles.update(model.id, {key: True for key in values})
            manager.settings.patch({"max_normalized_request_mb": 1})
            assert (await caller.post("/v1/images/embeddings", content=json.dumps(body) + " " * (1024 * 1024))).status_code == 413
            async def chunks():
                yield json.dumps(body).encode()
                yield b" " * (1024 * 1024)
            assert (await caller.post("/v1/images/embeddings", content=chunks())).status_code == 413
            manager.settings.patch({"max_request_mb": 1, "max_normalized_request_mb": 128})
            assert (await caller.post("/v1/images/embeddings", json=request(inputs="x" * 1024 * 1024).model_dump())).status_code == 413
            assert process.returncode is None
            assert (await caller.get("/api/sessions")).json() == []
            assert not caller._transport.app.state.runtime_state.runs.list_all_runs()
            assert (await caller.get(path + "/log?tower=text")).json()["text"].find("SigLIP text") >= 0
    asyncio.run(scenario())


def test_queue_overflow_timeout_and_cold_load_cancel(tmp_path, monkeypatch):
    async def scenario():
        async with managed_runtime(tmp_path, source={"type": "local", "execution_options": {"max_batch_size": 13}}) as (_, manager, model, _, _):
            active = asyncio.create_task(manager.image_embed(model.id, request()))
            adapter = manager._managed_slot(model).adapter
            await until(lambda: "text" in adapter.clients and adapter.clients["text"].process is not None)
            process = adapter.clients["text"].process.process
            limits = SimpleNamespace(concurrency=1, queue_size=1, queue_timeout_seconds=120)
            monkeypatch.setattr(manager_module, "ManagedQueue", lambda **_: limits)
            waiting = asyncio.create_task(manager.image_embed(model.id, request()))
            await until(lambda: manager.status(model.id).queued == 1)
            with pytest.raises(ModelError, match="queue is full"):
                await manager.image_embed(model.id, request())
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            limits.queue_timeout_seconds = 0.01
            with pytest.raises(ModelError, match="Timed out"):
                await manager.image_embed(model.id, request())
            assert process.returncode is None and manager.status(model.id).queued == 0
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert process.returncode is not None and adapter.model_use is None
            assert manager.status(model.id).towers.text.process_state == "stopped"
            assert manager.status(model.id).active == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("policy", ["after_request", "idle"])
def test_release_both_towers_and_health_does_not_extend_idle(tmp_path, policy):
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False},
                source={"type": "local", "lifecycle": {"unload": policy, "idle_seconds": 0.5}}) as (_, manager, model, _, _):
            await manager.load(model.id, tower="image")
            await manager.load(model.id, tower="text")
            adapter = manager._managed_slot(model).adapter
            processes = [client.process.process for client in adapter.clients.values()]
            if policy == "idle":
                deadline = adapter.idle_deadline
                await manager.health(model.id)
                assert adapter.idle_deadline == deadline
            else:
                assert all(process.returncode is None for process in processes)
                await manager.image_embed(model.id, request())
            await until(lambda: manager.status(model.id).residency == "unloaded")
            assert all(process.returncode is not None for process in processes)
            assert adapter.model_use is None and manager.status(model.id).towers.model_revision is None
    asyncio.run(scenario())


def test_migration_deletes_only_obsolete_drafts_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'app.db'}")
    try:
        migrations.upgrade(engine, migrations.WD14_REVISION)
        from ai_workbench.core.models.store import ModelProfileStore
        profiles = ModelProfileStore(engine)
        retained = profiles.create(ModelProfile(name="Keep WD14", alias="keep", kind="vision", model_ref="vision/keep", source={"type": "local"}))
        before_profile = profiles.get(retained.id).model_dump()
        with engine.begin() as db:
            db.execute(text("INSERT INTO model_profiles (id, name, alias, kind, model_ref, capabilities_json, parameters_json, enabled, external_enabled, created_at, updated_at) "
                "VALUES ('draft', 'Draft', 'draft', 'image_embedding', 'old', '{}', '{\"architecture\":\"clip\"}', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        paths = [tmp_path / "data" / name / "keep" for name in ("models", "attachments", "runtimes", "knowledge")]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"protected fixture")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        migrations.upgrade(engine, migrations.SIGLIP_REVISION)
        migrations.upgrade(engine, migrations.SIGLIP_REVISION)
        assert migrations.current_revision(engine) == migrations.SIGLIP_REVISION
        with engine.connect() as db:
            assert db.execute(text("SELECT COUNT(*) FROM model_profiles WHERE kind='image_embedding'")).scalar_one() == 0
        assert profiles.get(retained.id).model_dump() == before_profile
        saved = ModelProfileStore(engine).create(profile())
        migrations.upgrade(engine, migrations.SIGLIP_REVISION)
        assert ModelProfileStore(engine).get(saved.id).source.execution_options["device"] == "cuda"
        with engine.begin() as db, pytest.raises(IntegrityError):
            db.execute(text("UPDATE model_profiles SET source_type='provider', provider_profile_id='invalid', execution_options_json=NULL, lifecycle_json=NULL WHERE id=:id"), {"id": saved.id})
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    finally:
        engine.dispose()


def test_crash_detection_and_automatic_release_preserve_failure_until_explicit_load(tmp_path):
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False},
                source={"type": "local", "lifecycle": {"unload": "after_request"}}) as (_, manager, model, _, _):
            for tower in ("image", "text"):
                await manager.load(model.id, tower=tower)
            adapter = manager._managed_slot(model).adapter
            image = adapter.clients["image"].process.process
            text = adapter.clients["text"].process.process
            text.kill()
            await until(lambda: adapter.towers.text.process_state == "failed")
            assert image.returncode is None and adapter.model_use is not None
            await manager.image_embed(model.id, request("image", data_url()))
            assert image.returncode is not None and adapter.model_use is None
            assert manager.status(model.id).towers.text.process_state == "failed"
            with pytest.raises(ModelError, match="explicitly"):
                await manager.image_embed(model.id, request())
            await manager.load(model.id, tower="text")
            assert manager.status(model.id).state == "ready"
    asyncio.run(scenario())


@pytest.mark.parametrize("change", [{"dimensions": 3}, {"vector_space_id": "sha256:" + "c" * 64}])
def test_cross_tower_space_mismatch_stops_only_new_tower(tmp_path, monkeypatch, change):
    from ai_workbench.core.models.siglip import SiglipTowerClient
    original = SiglipTowerClient.load
    async def load(client):
        info = await original(client)
        return info.model_copy(update=change) if client.tower == "text" else info
    monkeypatch.setattr(SiglipTowerClient, "load", load)
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False}) as (_, manager, model, _, _):
            await manager.load(model.id, tower="image")
            adapter = manager._managed_slot(model).adapter
            use = adapter.model_use
            image = adapter.clients["image"].process.process
            with pytest.raises(ModelError, match="different vector spaces"):
                await manager.load(model.id, tower="text")
            assert image.returncode is None and adapter.model_use is use
            assert adapter.clients["text"].process is None
            assert manager.status(model.id).towers.text.process_state == "failed"
    asyncio.run(scenario())


def test_health_reports_release_when_existing_idle_deadline_has_expired(tmp_path):
    async def scenario():
        async with managed_runtime(tmp_path, source={"type": "local", "lifecycle": {"unload": "idle", "idle_seconds": 10}}) as (_, manager, model, _, _):
            await manager.load(model.id, tower="text")
            adapter = manager._managed_slot(model).adapter
            process = adapter.clients["text"].process.process
            adapter.idle_deadline = asyncio.get_running_loop().time() - 1
            status = await manager.health(model.id)
            assert status.residency == "unloaded" and status.towers.model_revision is None
            assert process.returncode is not None
    asyncio.run(scenario())


def test_timeout_and_loading_cancellation_keep_the_healthy_tower(tmp_path, monkeypatch):
    from ai_workbench.core.models.siglip import SiglipTowerClient
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False}) as (_, manager, model, _, _):
            await manager.load(model.id, tower="image")
            adapter = manager._managed_slot(model).adapter
            use = adapter.model_use
            image = adapter.clients["image"].process.process
            original = SiglipTowerClient._connect
            async def blocked(client, ready, token):
                if client.tower == "text":
                    await asyncio.Event().wait()
                return await original(client, ready, token)
            monkeypatch.setattr(SiglipTowerClient, "_connect", blocked)
            active = asyncio.create_task(manager.load(model.id, tower="text"))
            await until(lambda: "text" in adapter.clients and adapter.clients["text"].process is not None)
            text = adapter.clients["text"].process.process
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert text.returncode is not None and image.returncode is None
            assert adapter.model_use is use and adapter.towers.text.process_state == "stopped"
            monkeypatch.setattr(SiglipTowerClient, "_connect", original)
            await manager.image_embed(model.id, request())
            text = adapter.clients["text"].process.process
            adapter.clients["text"].client.timeout = httpx.Timeout(0.05)
            with pytest.raises(ModelError) as error:
                await manager.image_embed(model.id, request(inputs="wait"))
            assert error.value.code == "MODEL_TIMEOUT"
            assert text.returncode is not None and image.returncode is None
            assert adapter.model_use is use and adapter.towers.text.process_state == "failed"
    asyncio.run(scenario())


def test_public_disconnect_waits_for_target_cleanup_and_keeps_other_tower(tmp_path):
    from ai_workbench.api.routes.openai_compatible import image_embeddings
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False}) as (_, manager, model, caller, _):
            for tower in ("image", "text"):
                await manager.load(model.id, tower=tower)
            adapter = manager._managed_slot(model).adapter
            image, text = [adapter.clients[tower].process.process for tower in ("image", "text")]
            disconnected = asyncio.Event()
            sent = False
            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": request(inputs="wait").model_dump_json().encode(), "more_body": False}
                await disconnected.wait()
                return {"type": "http.disconnect"}
            incoming = Request({"type": "http", "method": "POST", "path": "/v1/images/embeddings",
                "headers": [(b"authorization", b"Bearer siglip-test")], "client": ("127.0.0.1", 40001)}, receive)
            active = asyncio.create_task(image_embeddings(incoming, caller._transport.app.state.runtime_state))
            await until(lambda: "waiting child_id=" in adapter.clients["text"].log.path.read_text())
            disconnected.set()
            with pytest.raises(ModelError) as error:
                await active
            assert error.value.status == 499
            assert text.returncode is not None and image.returncode is None
            assert manager.status(model.id).active == 0 and adapter.towers.text.process_state == "stopped"
    asyncio.run(scenario())


def test_busy_edits_and_all_profile_or_runtime_release_paths(tmp_path):
    async def scenario():
        async with managed_runtime(tmp_path, parameters={"unload_other_tower_on_call": False}) as (_, manager, model, caller, _):
            await manager.load(model.id, tower="text")
            adapter = manager._managed_slot(model).adapter
            active = asyncio.create_task(manager.image_embed(model.id, request(inputs="wait")))
            await until(lambda: "waiting child_id=" in adapter.clients["text"].log.path.read_text())
            path = f"/api/models/profiles/{model.id}"
            assert (await caller.patch(path, json={"name": "Busy"})).status_code == 409
            assert (await caller.delete(path)).status_code == 409
            with pytest.raises(ModelError, match="Wait for"):
                await manager.invalidate_local()
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            for operation in ("edit", "source", "disable", "delete", "maintenance", "shutdown"):
                current = manager.profiles.create(profile(alias="release-" + operation,
                    parameters={"unload_other_tower_on_call": False}))
                for tower in ("image", "text"):
                    await manager.load(current.id, tower=tower)
                owned = manager._managed_slot(current).adapter
                processes = [client.process.process for client in owned.clients.values()]
                path = f"/api/models/profiles/{current.id}"
                if operation == "maintenance":
                    await manager.invalidate_local()
                elif operation == "shutdown":
                    await manager.close()
                elif operation == "delete":
                    assert (await caller.delete(path)).status_code == 200
                else:
                    patch = {"edit": {"name": "Edited"}, "source": {"source": {"type": "local", "execution_options": {"intraop_threads": 2}}}, "disable": {"enabled": False}}[operation]
                    response = await caller.patch(path, json=patch)
                    assert response.status_code == 200, response.text
                assert all(process.returncode is not None for process in processes)
                assert owned.model_use is None
    asyncio.run(scenario())


def test_inventory_status_and_inspection_never_read_weights(tmp_path, monkeypatch):
    original = Path.open
    def open_file(path, *args, **kwargs):
        assert path.suffix != ".safetensors", "Metadata reads opened model weights"
        return original(path, *args, **kwargs)
    async def scenario():
        async with managed_runtime(tmp_path) as (_, manager, model, caller, _):
            monkeypatch.setattr(Path, "open", open_file)
            assert (await caller.get("/api/models/inventory?kind=image_embedding")).status_code == 200
            assert (await caller.get("/api/models/inspect", params={"kind": "image_embedding", "model_ref": REF})).status_code == 200
            for _ in range(2):
                assert manager.status(model.id).towers.model_revision is None
                await manager.health(model.id)
            assert manager._managed_slot(model).adapter.model_use is None
    asyncio.run(scenario())
