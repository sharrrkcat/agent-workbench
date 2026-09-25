"""Actual worker RPC and lifecycle with synthetic embedding engines."""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import math
import re
import struct

import httpx
import psutil
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ModelProfile
from tests.test_phase2b_runtime import installed_worker
from tests.test_text_embeddings import PARAMETERS, REF, model_tree, profile, write_json
from tests.test_wd14_runtime import wait_for

FAKE_ENGINE = '''
import os, subprocess, sys, time
from common import WorkerError
class EmbeddingEngine:
    def __init__(self, path, options, information):
        self.device, self.device_name = options['device'], 'Fixture device'
        self.dtype, self.dimensions = 'float32', 2
        self.information = information
    def embed(self, texts, purpose, dimensions):
        if dimensions is not None and dimensions != self.dimensions:
            raise WorkerError('EMBEDDING_DIMENSION_MISMATCH')
        if texts[0] == 'crash': os._exit(7)
        if texts[0] == 'wait':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            print('waiting child_id=' + str(child.pid), flush=True)
            time.sleep(60)
        prompt_name = self.information[purpose + '_prompt_name']
        prompt = self.information['prompts'][prompt_name] if prompt_name else ''
        special = {'search': [1.0, 0.0], 'near': [1.0, 0.0], 'large': [100.0, 1.0], 'zero': [0.0, 0.0]}
        return {'vectors': [special.get(value, [float(len(prompt + value)), 1.0]) for value in texts],
            'similarity': self.information['similarity']}
'''


@asynccontextmanager
async def runtime(tmp_path, *, memory=True, similarity="cosine", **values):
    service, manager, _ = await installed_worker(tmp_path)
    (service.worker_root / "embedding_engine.py").write_text(FAKE_ENGINE, encoding="utf-8")
    path = model_tree(tmp_path, normalize=False)
    config = json.loads((path / "config_sentence_transformers.json").read_text())
    write_json(path / "config_sentence_transformers.json", {**config, "similarity_fn_name": similarity})
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'application.db'}")
    state = app.state.runtime_state
    await state.model_manager.close()
    manager.profiles, manager.providers, manager.settings = state.model_profiles, state.provider_profiles, state.model_settings
    state.model_manager, state.runtime_supervisor = manager, service
    state.knowledge_service.model_manager = manager
    service.settings = state.local_runtime_settings
    model = manager.profiles.create(profile(**values))
    manager.settings.patch({"external_enabled": True, "external_api_key": "embedding-test"})
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 40001)),
                base_url="http://cogita.test", headers={"Authorization": "Bearer embedding-test"}) as caller:
            yield service, manager, model, caller
    finally:
        await manager.close()
        await service.close()
    assert not list((service.base / ".processes").glob("*"))


def test_api_native_processing_order_encoding_and_whole_request_failure(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, caller):
            payload = {"model": model.alias, "input": ["abc", "de"]}
            response = await caller.post("/v1/embeddings", json=payload)
            assert response.status_code == 200, response.text
            assert [item["embedding"] for item in response.json()["data"]] == [[3, 1], [2, 1]]
            assert "usage" not in response.json() and "similarity" not in response.json()
            query = await caller.post("/v1/embeddings", json={**payload, "purpose": "query", "encoding_format": "base64"})
            prefix = len("Retrieve documents: ")
            assert [struct.unpack("<2f", base64.b64decode(item["embedding"])) for item in query.json()["data"]] == [(prefix + 3, 1), (prefix + 2, 1)]
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            assert manager.status(model.id).runtime.engine == "sentence-transformers"
            assert (await caller.post("/v1/embeddings", json={**payload, "dimensions": 2})).status_code == 200
            assert (await caller.post("/v1/embeddings", json={**payload, "dimensions": 3})).status_code == 422
            assert adapter.process.process is process
            for patch, status in (({"purpose": "other"}, 400), ({"input": []}, 400), ({"input": [1, 2]}, 400), ({"input": [" "]}, 400), ({"extra": True}, 400)):
                assert (await caller.post("/v1/embeddings", json={**payload, **patch})).status_code == status
            async with httpx.AsyncClient(trust_env=False) as private:
                assert (await private.get(str(adapter.client.base_url) + "/health")).status_code == 401
            failed = await caller.post("/v1/embeddings", json={**payload, "input": ["abc", "zero"]})
            assert failed.status_code == 503 and "data" not in failed.json()
            assert process.returncode is not None
    asyncio.run(scenario())


def test_profiles_reuse_independently_cancel_process_trees_and_recover_crashes(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, _):
            assert (await manager.health(model.id)).residency == "unloaded"
            await manager.embed(model.id, ["first"])
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            await manager.embed(model.id, ["again"])
            assert adapter.process.process is process
            other = manager.profiles.create(profile(name="Other", alias="other"))
            await manager.embed(other.id, ["other"])
            other_adapter = manager._managed_slot(other).adapter
            other_process = other_adapter.process.process
            assert other_process.pid != process.pid
            active = asyncio.create_task(manager.embed(model.id, ["wait"]))
            await wait_for(lambda: "waiting child_id=" in adapter.log_path.read_text())
            child = int(re.search(r"waiting child_id=(\d+)", adapter.log_path.read_text())[1])
            queued = asyncio.create_task(manager.embed(model.id, ["queued"]))
            await wait_for(lambda: manager.status(model.id).queued == 1)
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            assert process.returncode is None and psutil.pid_exists(child)
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
            assert process.returncode is not None and not psutil.pid_exists(child)
            assert other_process.returncode is None and manager.status(model.id).active == 0
            await manager.embed(model.id, ["automatic reload"])
            with pytest.raises(ModelError):
                await manager.embed(model.id, ["crash"])
            with pytest.raises(ModelError):
                await manager.embed(model.id, ["explicit reload required"])
            await manager.load(model.id)
            assert (await manager.embed(model.id, ["recovered"])).vectors
            await manager.unload(model.id)
            assert manager.status(model.id).residency == "unloaded" and other_process.returncode is None
    asyncio.run(scenario())


@pytest.mark.parametrize("policy", ["after_request", "idle"])
def test_automatic_release(tmp_path, policy):
    async def scenario():
        async with runtime(tmp_path, source={"type": "local", "lifecycle": {"unload": policy, "idle_seconds": 0.1}}) as (_, manager, model, _):
            await manager.embed(model.id, ["text"])
            await wait_for(lambda: manager._managed_slot(model).adapter.process is None)
            assert manager.status(model.id).residency == "unloaded"
    asyncio.run(scenario())


@pytest.mark.parametrize("memory", [True, False])
@pytest.mark.parametrize("similarity,first", [("cosine", "near"), ("dot", "large")])
def test_knowledge_scores_and_invalidation_use_effective_model_semantics(tmp_path, memory, similarity, first):
    async def scenario():
        async with runtime(tmp_path, memory=memory, similarity=similarity) as (_, manager, model, caller):
            assert (await caller.patch("/api/knowledge/settings", json={"hybrid_search_enabled": False})).status_code == 200
            base_response = await caller.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": model.id})
            assert base_response.status_code == 200, base_response.text
            base = base_response.json()["id"]
            for document in ("near", "large"):
                result = await caller.post(f"/api/knowledge/bases/{base}/sources", json={"title": document, "text": document})
                assert result.status_code == 200 and result.json()["status"] == "indexed", result.text
            payload = {"query": "search", "knowledge_base_ids": [base], "debug": True, "min_score_threshold": 0}
            response = await caller.post("/api/knowledge/search", json=payload)
            assert response.status_code == 200, response.text
            assert response.json()["results"][0]["content"] == first
            scores = {item["content"]: item["vector_score"] for item in response.json()["results"]}
            assert scores["near"] == pytest.approx(1)
            assert scores["large"] == pytest.approx(100 if similarity == "dot" else 100 / math.sqrt(10001))
            changed = await caller.patch(f"/api/models/profiles/{model.id}", json={"parameters": {**PARAMETERS, "query_prompt_name": "sts_query"}})
            assert changed.status_code == 200, changed.text
            assert (await caller.get(f"/api/knowledge/bases/{base}")).json()["index_status"] == "needs_reindex"
            assert (await caller.post("/api/knowledge/search", json=payload)).json()["results"] == []
            rebuilt = await caller.post(f"/api/knowledge/bases/{base}/reindex")
            assert rebuilt.status_code == 200, rebuilt.text
            assert (await caller.post("/api/knowledge/search", json=payload)).json()["results"][0]["content"] == first
    asyncio.run(scenario())
