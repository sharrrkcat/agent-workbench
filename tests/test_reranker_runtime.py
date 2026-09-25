"""Reranker API, RAG and real worker lifecycle with a synthetic scoring engine."""
import asyncio
from contextlib import asynccontextmanager
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import psutil
import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.adapters import RerankerWorkerAdapter
from ai_workbench.core.models.runtimes.catalog import catalog
from tests.test_rerankers import model_tree, profile
from tests.test_text_embedding_runtime import runtime as embedding_runtime
from tests.test_tts import wav_bytes
from tests.test_wd14_runtime import wait_for

FAKE_ENGINE = '''
import os, subprocess, sys, time
from common import WorkerError
class RerankerEngine:
    def __init__(self, path, options, information):
        self.device, self.device_name, self.dtype = options['device'], 'Fixture device', 'float32'
    def rerank(self, query, documents):
        if query == 'crash': os._exit(7)
        if query == 'fail': raise WorkerError('MODEL_UNAVAILABLE', 503)
        if query == 'wait':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            print('waiting child_id=' + str(child.pid), flush=True)
            time.sleep(60)
        if query == 'wrong-count': return {'scores': [1.0]}
        if query == 'bad-type': return {'scores': ['invalid'] * len(documents)}
        if query == 'bad-shape': return {'scores': [[1.0, 2.0]] * len(documents)}
        return {'scores': [1.0 if query == 'ties' else float(len(document)) for document in documents]}
'''


@asynccontextmanager
async def runtime(tmp_path, *, memory=True, **values):
    async with embedding_runtime(tmp_path, memory=memory) as (service, manager, embedding, caller):
        (service.worker_root / "reranker_engine.py").write_text(FAKE_ENGINE, encoding="utf-8")
        model_tree(tmp_path)
        model = manager.profiles.create(profile(**values))
        yield service, manager, model, embedding, caller


@pytest.mark.parametrize("audio_format", [None, "wav"])
def test_rpc_cancellation_stops_worker_when_transport_swallows_cancellation(audio_format):
    async def scenario():
        started, stopped, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def transport():
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                await stopped.wait()
            finally:
                finished.set()
            return httpx.Response(200, content=wav_bytes(), headers={"content-type": "audio/wav"}) if audio_format else httpx.Response(200, json={"scores": [1.0]})
        class Client:
            async def request(self, *_args, **_kwargs):
                return await transport()
            @asynccontextmanager
            async def stream(self, *_args, **_kwargs):
                yield await transport()
        adapter = RerankerWorkerAdapter(SimpleNamespace(release=catalog("windows", "x86_64")), profile(), lambda: None)
        adapter.client = Client()
        adapter._stop = AsyncMock(side_effect=stopped.set)
        task = asyncio.create_task(adapter._rpc("POST", "/rerank", {"documents": ["text"]}, audio_format=audio_format))
        await started.wait()
        task.cancel()
        try:
            done, _ = await asyncio.wait([task], timeout=1)
            assert done, "Worker cleanup must not depend on transport cancellation propagation"
            with pytest.raises(asyncio.CancelledError):
                await task
            adapter._stop.assert_awaited_once()
            assert finished.is_set()
        finally:
            stopped.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("memory", [True, False])
def test_public_ranking_aliases_top_n_documents_and_statelessness(tmp_path, memory):
    async def scenario():
        async with runtime(tmp_path, memory=memory) as (_, manager, model, _, caller):
            before = {path: (await caller.get(path)).json() for path in ("/api/sessions", "/api/knowledge/bases")}
            assert (await caller.get("/v1/models", params={"kind": "reranker"})).json()["data"][0]["id"] == model.alias
            assert manager._slots == {}
            payload = {"model": model.alias, "query": "search", "documents": ["a", "longest", "equal", "equal"]}
            response = await caller.post("/v1/rerank", json=payload)
            assert response.status_code == 200, response.text
            assert response.headers["x-request-id"]
            assert response.json() == {"model": model.alias, "results": [
                {"index": 1, "relevance_score": 7.0}, {"index": 2, "relevance_score": 5.0},
                {"index": 3, "relevance_score": 5.0}, {"index": 0, "relevance_score": 1.0}]}
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            assert manager.status(model.id).runtime.engine == "cross-encoder"
            limited = (await caller.post("/v1/rerank", json={**payload, "top_n": 2, "return_documents": True})).json()
            assert limited["results"] == [{"index": 1, "relevance_score": 7.0, "document": {"text": "longest"}},
                {"index": 2, "relevance_score": 5.0, "document": {"text": "equal"}}]
            assert len((await caller.post("/v1/rerank", json={**payload, "top_n": 99})).json()["results"]) == 4
            ties = (await caller.post("/v1/rerank", json={**payload, "query": "ties", "top_n": None})).json()
            assert [item["index"] for item in ties["results"]] == [0, 1, 2, 3]
            assert process is adapter.process.process
            async with httpx.AsyncClient(trust_env=False) as private:
                assert (await private.get(str(adapter.client.base_url) + "/health")).status_code == 401
            for path, value in before.items():
                assert (await caller.get(path)).json() == value
            await manager.unload(model.id)
            assert process.returncode is not None
    asyncio.run(scenario())


def test_invalid_requests_and_visibility_fail_before_loading(tmp_path, monkeypatch):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, embedding, caller):
            payload = {"model": model.alias, "query": "search", "documents": ["a", "b"]}
            for patch in ({"query": " "}, {"documents": []}, {"documents": [" "]}, {"documents": [1]},
                    {"top_n": 0}, {"top_n": True}, {"return_documents": 1}, {"extra": True}):
                response = await caller.post("/v1/rerank", json={**payload, **patch})
                assert response.status_code == 400, response.text
            assert (await caller.post("/v1/rerank", json={**payload, "model": embedding.alias})).status_code == 400
            assert (await caller.post("/v1/rerank", json={**payload, "model": model.id})).status_code == 404
            assert (await caller.post("/v1/rerank", json=payload, headers={"Authorization": "Bearer wrong"})).status_code == 401
            await caller.patch(f"/api/models/profiles/{model.id}", json={"external_enabled": False})
            assert (await caller.get("/v1/models", params={"kind": "reranker"})).json()["data"] == []
            assert (await caller.post("/v1/rerank", json=payload)).status_code == 404
            await caller.patch(f"/api/models/profiles/{model.id}", json={"external_enabled": True})
            monkeypatch.setattr("ai_workbench.api.routes.openai_compatible.MAX_RERANK_BYTES", 10)
            assert (await caller.post("/v1/rerank", json=payload)).status_code == 413
            monkeypatch.setattr("ai_workbench.core.models.manager.MAX_RERANK_BYTES", 10)
            with pytest.raises(ModelError) as failure:
                await manager.rerank(model.id, "search", ["a", "b"])
            assert failure.value.code == "REQUEST_TOO_LARGE"
            assert manager._slots == {}
    asyncio.run(scenario())


@pytest.mark.parametrize("query", ["wrong-count", "bad-type", "bad-shape"])
def test_invalid_worker_scores_reject_whole_request_and_stop_process(tmp_path, query):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, _, caller):
            await manager.load(model.id)
            process = manager._managed_slot(model).adapter.process.process
            response = await caller.post("/v1/rerank", json={"model": model.alias, "query": query, "documents": ["a", "b"]})
            assert response.status_code == 503 and "results" not in response.json()
            assert process.returncode is not None and manager.status(model.id).active == 0
    asyncio.run(scenario())


def test_profile_isolation_queue_cancellation_process_trees_and_crash_recovery(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, embedding, caller):
            assert (await manager.health(model.id)).residency == "unloaded"
            await manager.rerank(model.id, "first", ["a"])
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            other = manager.profiles.create(profile(alias="other"))
            await manager.rerank(other.id, "other", ["b"])
            other_process = manager._managed_slot(other).adapter.process.process
            await manager.embed(embedding.id, ["text"])
            embed_process = manager._managed_slot(embedding).adapter.process.process
            assert len({process.pid, other_process.pid, embed_process.pid}) == 3
            active = asyncio.create_task(caller.post("/v1/rerank", json={"model": model.alias, "query": "wait", "documents": ["a"]}))
            await wait_for(lambda: "waiting child_id=" in adapter.log_path.read_text())
            child = int(re.search(r"waiting child_id=(\d+)", adapter.log_path.read_text())[1])
            queued = asyncio.create_task(manager.rerank(model.id, "queued", ["b"]))
            await wait_for(lambda: manager.status(model.id).queued == 1)
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            assert process.returncode is None and psutil.pid_exists(child)
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
            assert process.returncode is not None and not psutil.pid_exists(child)
            assert other_process.returncode is None and embed_process.returncode is None
            assert manager.status(model.id).active == manager.status(model.id).queued == 0
            await manager.rerank(model.id, "reload after cancellation", ["a"])
            with pytest.raises(ModelError):
                await manager.rerank(model.id, "crash", ["a"])
            with pytest.raises(ModelError):
                await manager.rerank(model.id, "explicit reload required", ["a"])
            await manager.load(model.id)
            assert (await manager.rerank(model.id, "recovered", ["abc"])).scores == [3.0]
            await manager.unload(model.id)
            assert manager.status(model.id).residency == "unloaded"
    asyncio.run(scenario())


@pytest.mark.parametrize("policy", ["after_request", "idle"])
def test_release_policies(tmp_path, policy):
    async def scenario():
        async with runtime(tmp_path, source={"type": "local", "lifecycle": {"unload": policy, "idle_seconds": 0.1}}) as (_, manager, model, _, _):
            await manager.rerank(model.id, "search", ["a"])
            await wait_for(lambda: manager._managed_slot(model).adapter.process is None)
            assert manager.status(model.id).residency == "unloaded"
    asyncio.run(scenario())


@pytest.mark.parametrize("memory", [True, False])
def test_knowledge_ranking_ties_fallback_and_no_reindex_on_reranker_changes(tmp_path, memory):
    async def scenario():
        async with runtime(tmp_path, memory=memory) as (_, manager, model, embedding, caller):
            await caller.patch("/api/knowledge/settings", json={"hybrid_search_enabled": False})
            response = await caller.post("/api/knowledge/bases", json={"name": "Facts", "embedding_model_profile_id": embedding.id})
            assert response.status_code == 200, response.text
            base = response.json()["id"]
            for document in ("near", "large"):
                response = await caller.post(f"/api/knowledge/bases/{base}/sources", json={"title": document, "text": document})
                assert response.status_code == 200, response.text
            async def search(query):
                result = await caller.post("/api/knowledge/search", json={"query": query, "knowledge_base_ids": [base], "debug": True})
                assert result.status_code == 200, result.text
                return result.json()
            baseline = {query: await search(query) for query in ("search", "ties", "fail")}
            await caller.patch("/api/knowledge/settings", json={"reranker_enabled": True, "reranker_model_profile_id": model.id})
            ranked = await search("search")
            assert ranked["metadata"] == {"reranker_used": True, "rerank_fallback": False, "reranker_enabled": True}
            assert ranked["results"][0]["content"] == "large" and ranked["results"][0]["rerank_score"] == 5.0
            ties = await search("ties")
            assert [item["chunk_id"] for item in ties["results"]] == [item["chunk_id"] for item in baseline["ties"]["results"]]
            failed = await search("fail")
            assert failed["metadata"]["rerank_fallback"] and not failed["metadata"]["reranker_used"]
            assert failed["results"] == baseline["fail"]["results"]
            await caller.patch(f"/api/models/profiles/{model.id}", json={"model_ref": "rerankers/missing"})
            assert (await caller.get(f"/api/knowledge/bases/{base}")).json()["index_status"] != "needs_reindex"
            unavailable = await search("search")
            assert unavailable["metadata"]["rerank_fallback"] and unavailable["results"] == baseline["search"]["results"]
    asyncio.run(scenario())
