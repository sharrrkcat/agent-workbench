"""Real worker/process plumbing with synthetic engines and disposable files only."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from ai_workbench.api.routes.openai_compatible import inference_until_disconnect
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.adapters import PythonWorkerAdapter
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.schema import ModelProfile, ProviderProfile, SpeechRequest, VisionRequest
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.models import AppMetadataRecord, RuntimeInstallationRecord, SessionRecord
from tests.test_phase2b_runtime import FAKE_ENGINE, installed_worker
from tests.test_wd14 import DEFAULTS, data_url, model_tree, profile

FAKE_WD14 = '''
import os
import time
class WD14Engine:
    def __init__(self, path, kind, params, options):
        self.kind = kind
    def tags(self, images, thresholds):
        if thresholds['general'] == 0.17: os._exit(7)
        if thresholds['general'] == 0.18: time.sleep(60)
        return {'outputs': [{'object': 'image.tags', 'index': i,
            'tags': [{'name': 'tag_name', 'category': 'general', 'score': 0.9}]}
            for i in range(len(images))]}
'''


@asynccontextmanager
async def runtime(tmp_path):
    service, manager, kokoro = await installed_worker(tmp_path)
    (service.worker_root / "wd14_engine.py").write_text(FAKE_WD14, encoding="utf-8")
    model_tree(tmp_path)
    wd14 = manager.profiles.create(profile())
    try:
        yield service, manager, wd14, kokoro
    finally:
        await manager.close()
        await service.close()
    assert not list((service.base / ".processes").iterdir())


async def wait_for(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout=5)


def test_wd14_process_reuse_isolation_rpc_auth_crash_and_explicit_reload(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (service, manager, wd14, kokoro):
            # WD14 must not initialize or even import the unrelated language engine.
            tts_source = service.worker_root / "tts_engine.py"
            tts_source.write_text("raise RuntimeError('Kokoro must stay isolated')", encoding="utf-8")
            request = VisionRequest(model=wd14.alias, images=[data_url(), data_url()])
            assert (await manager.health(wd14.id)).residency == "unloaded"
            first = await manager.vision(wd14.id, request)
            assert [item.index for item in first.outputs] == [0, 1] and first.usage is None
            adapter = manager._slots[manager.execution_key(wd14)].adapter
            process = adapter.process.process
            assert (await manager.vision(wd14.id, request)).outputs == first.outputs
            assert adapter.process.process is process
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.get(str(adapter.client.base_url) + "/health")).status_code == 401
            wrong = await adapter.client.post("/tags", json={"profile_id": wd14.id, "images": ["https://private"], "thresholds": DEFAULTS})
            assert wrong.status_code == 422
            wrong_kind = await adapter.client.post("/speech", json={"profile_id": wd14.id, "input": "hello", "voice": "af_heart",
                "speed": 1, "response_format": "wav", "language": None})
            assert wrong_kind.json()["error"]["code"] == "MODEL_KIND_MISMATCH"
            clone = manager.profiles.create(profile(alias="clone"))
            assert manager.execution_key(clone) != manager.execution_key(wd14)
            await manager.vision(clone.id, request)
            cloned_adapter = manager._slots[manager.execution_key(clone)].adapter
            assert cloned_adapter.process.process.pid != process.pid
            tts_source.write_text(FAKE_ENGINE, encoding="utf-8")
            await manager.speech(kokoro.id, SpeechRequest(model=kokoro.alias, input="Hello", voice="af_heart", response_format="wav"))
            kokoro_adapter = manager._slots[manager.execution_key(kokoro)].adapter
            assert len({process.pid, cloned_adapter.process.process.pid, kokoro_adapter.process.process.pid}) == 3
            failure = VisionRequest(model=wd14.alias, images=request.images, thresholds={"general": 0.17})
            with pytest.raises(ModelError):
                await manager.vision(wd14.id, failure)
            assert process.returncode is not None
            assert manager.status(wd14.id).state == "failed"
            with pytest.raises(ModelError, match="process failed"):
                await manager.vision(wd14.id, request)
            assert manager.status(clone.id).residency == manager.status(kokoro.id).residency == "loaded"
            await manager.load(wd14.id)
            assert (await manager.vision(wd14.id, request)).outputs == first.outputs
            assert adapter.process.process.pid != process.pid
            await manager.unload(wd14.id)
            assert manager.status(wd14.id).residency == "unloaded"
            assert manager.status(clone.id).residency == manager.status(kokoro.id).residency == "loaded"
    asyncio.run(scenario())


def test_cancellation_stops_only_affected_process_before_queued_request_resumes(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, wd14, kokoro):
            clone = manager.profiles.create(profile(alias="clone"))
            for p in (wd14, clone, kokoro):
                await manager.load(p.id)
            adapter = manager._slots[manager.execution_key(wd14)].adapter
            old = adapter.process.process
            ordinary = VisionRequest(model=wd14.alias, images=[data_url()])
            waiting = VisionRequest(model=wd14.alias, images=ordinary.images, thresholds={"general": 0.18})
            active = asyncio.create_task(manager.vision(wd14.id, waiting))
            await wait_for(lambda: manager.status(wd14.id).active == 1)
            queued = asyncio.create_task(manager.vision(wd14.id, ordinary))
            await wait_for(lambda: manager.status(wd14.id).queued == 1)
            clone_process = manager._slots[manager.execution_key(clone)].adapter.process.process
            kokoro_process = manager._slots[manager.execution_key(kokoro)].adapter.process.process
            assert (await manager.vision(clone.id, ordinary)).outputs[0].tags
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert old.returncode is not None
            assert (await queued).outputs[0].tags
            assert manager.status(wd14.id).active == manager.status(wd14.id).queued == 0
            assert adapter.process.process.pid != old.pid
            assert clone_process.returncode is kokoro_process.returncode is None
    asyncio.run(scenario())


def test_queue_rejection_cancellation_and_release_policies(tmp_path, monkeypatch):
    from ai_workbench.core.models import manager as manager_module
    async def scenario():
        async with runtime(tmp_path) as (_, manager, wd14, _):
            monkeypatch.setattr(manager_module, "ManagedQueue", lambda: SimpleNamespace(concurrency=1, queue_size=0, queue_timeout_seconds=1))
            await manager.load(wd14.id)
            request = VisionRequest(model=wd14.alias, images=[data_url()])
            active = asyncio.create_task(manager.vision(wd14.id,
                VisionRequest(model=wd14.alias, images=request.images, thresholds={"general": 0.18})))
            await wait_for(lambda: manager.status(wd14.id).active == 1)
            try:
                with pytest.raises(ModelError) as busy:
                    await manager.vision(wd14.id, request)
                assert busy.value.code == "MODEL_BUSY" and busy.value.status == 429
            finally:
                active.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await active
            for policy in ("after_request", "idle"):
                p = manager.profiles.update(wd14.id, {"source": {"type": "local", "lifecycle": {"unload": policy, "idle_seconds": 0.05}}})
                await manager.vision(p.id, request)
                await wait_for(lambda: manager.status(p.id).runtime.process_state == "stopped" and manager.status(p.id).active == 0)
                assert manager.status(p.id).residency == "unloaded"
                assert manager.status(p.id).active == manager.status(p.id).queued == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("result", [
    {"outputs": []}, {"outputs": [{"index": 1, "tags": []}]},
    {"outputs": [{"index": 0, "tags": [{"name": "a", "score": 0.5, "category": "rating"}]}]},
    {"outputs": [{"index": 0, "tags": [{"name": "a", "score": "0.5", "category": "general"}]}]},
    {"outputs": [{"index": 0, "tags": [], "extra": True}]},
])
def test_malformed_worker_results_fail_and_stop_before_returning(result):
    async def scenario():
        adapter = PythonWorkerAdapter(SimpleNamespace(release=catalog("windows", "x86_64")), profile(), lambda: None)
        adapter._stop = AsyncMock()
        adapter.client = httpx.AsyncClient(base_url="http://worker.test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)))
        try:
            with pytest.raises(ModelError) as error:
                await adapter.vision(profile(), [data_url()], DEFAULTS)
            assert error.value.code == "MODEL_UNAVAILABLE"
            adapter._stop.assert_awaited_once()
        finally:
            await adapter.client.aclose()
    asyncio.run(scenario())


def test_public_disconnect_cancels_and_waits_for_worker_cleanup():
    async def scenario():
        started, disconnected, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def inference():
            started.set()
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)
                stopped.set()
        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}
        request = SimpleNamespace(state=SimpleNamespace(), receive=receive)
        task = asyncio.create_task(inference_until_disconnect(request, inference()))
        await started.wait()
        disconnected.set()
        with pytest.raises(ModelError) as error:
            await task
        assert error.value.status == 499 and request.state.inference_error_code == "REQUEST_CANCELLED"
        assert stopped.is_set()
    asyncio.run(scenario())


def test_revision_deletes_only_old_vision_drafts_and_preserves_other_rows_and_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        migrations.upgrade(engine, migrations.PROVIDER_RUNTIME_REVISION)
        providers, profiles = ProviderProfileStore(engine), ModelProfileStore(engine)
        provider = providers.create(ProviderProfile(name="Provider", connection={"base_url": "https://provider.test/v1"}))
        profiles.create(ModelProfile(name="LLM", alias="llm", kind="llm", model_ref="remote", source={"type": "provider", "provider_profile_id": provider.id}))
        profiles.create(ModelProfile(name="Kokoro", alias="kokoro", kind="tts", model_ref="tts/kokoro", source={"type": "local"}))
        with engine.begin() as db:
            db.execute(text("""INSERT INTO model_profiles
                (id,alias,name,kind,model_ref,capabilities_json,parameters_json,enabled,external_enabled,created_at,updated_at)
                VALUES ('old','old','Old draft','vision','vision/old','{}',:params,1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),
                {"params": json.dumps({"architecture": "wd14", "task": "tags", "batch_size": 16})})
        with Session(engine) as db:
            db.add(AppMetadataRecord(key="model_settings", value='{"external_enabled":true,"external_api_key":"retained"}'))
            db.add(RuntimeInstallationRecord(id="local", version="1.0.0", state="installed", manifest_sha256="a" * 64))
            db.add(SessionRecord(session_id="keep", current_persona_id="00000000-0000-4000-8000-000000000001", context_policy_json="{}"))
            db.commit()
        tables = ("model_profiles", "provider_profiles", "runtime_installations", "runtime_jobs", "appmetadatarecord", "sessionrecord")
        def rows():
            with engine.connect() as db:
                return {table: [dict(row) for row in db.execute(text(
                    f"SELECT * FROM {table}" + (" WHERE kind != 'vision'" if table == "model_profiles" else ""))).mappings()]
                    for table in tables}
        before = rows()
        files = [tmp_path / "data" / folder / "keep" for folder in ("models", "attachments", "runtimes", "knowledge")]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"protected test fixture")
        contents = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        init_db(engine)
        init_db(engine)
        assert migrations.current_revision(engine) == migrations.WD14_REVISION
        assert rows() == before and not profiles.list("vision")
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == contents
        created = profiles.create(profile())
        init_db(engine)
        assert profiles.get(created.id).source.execution_options["device"] == "cpu"
        with engine.begin() as db, pytest.raises(IntegrityError):
            db.execute(text("UPDATE model_profiles SET source_type='provider', provider_profile_id=:provider, execution_options_json=NULL, lifecycle_json=NULL WHERE id=:id"),
                       {"provider": provider.id, "id": created.id})
    finally:
        engine.dispose()
