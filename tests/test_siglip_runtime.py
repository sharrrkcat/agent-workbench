"""Real SigLIP HTTP/process plumbing with a stdlib fixture engine, never CPU inference."""
import asyncio
from contextlib import asynccontextmanager, nullcontext
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import psutil
import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.siglip import SiglipModelUse, SiglipTowerClient
from ai_workbench.core.models.runtimes.schema import SiglipOptions
from ai_workbench.core.models.runtimes.process import RuntimeLog
from ai_workbench.core.models.schema import SiglipTowerInfo
from ai_workbench.workers import timing
from tests.test_load_timing import events, metadata
from tests.test_phase2b_runtime import installed_worker
from tests.test_siglip import REF, model_tree
from tests.test_wd14 import data_url

FAKE_ENGINE = '''
import math, os, subprocess, sys, time
class SiglipEngine:
    def __init__(self, path, tower, options, revision):
        if options['max_batch_size'] == 13: time.sleep(60)
        self.info = {'tower': tower, 'device': options['device'], 'device_name': 'Fixture device',
            'dtype': 'float16' if options['device'] == 'cuda' else 'float32', 'output_dtype': 'float32',
            'dimensions': 2, 'model_revision': revision, 'vector_space_id': 'sha256:' + 'b'*64}
    def embed(self, inputs):
        if inputs[0] == 'crash': os._exit(7)
        if inputs[0] == 'wait':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            print('waiting child_id=' + str(child.pid), flush=True)
            time.sleep(60)
        return {**self.info, 'vectors': [[len(value)/math.sqrt(len(value)**2+1), 1/math.sqrt(len(value)**2+1)] for value in inputs],
            'usage': None, 'timing': None}
'''


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.02)
    await asyncio.wait_for(poll(), 8)


@asynccontextmanager
async def runtime(tmp_path):
    supervisor, manager, _ = await installed_worker(tmp_path)
    (supervisor.worker_root / "siglip_engine.py").write_text(FAKE_ENGINE, encoding="utf-8")
    model_tree(tmp_path)
    use = await SiglipModelUse.prepare(tmp_path, REF)
    clients = []
    def client(tower="text", **options):
        value = SiglipTowerClient(supervisor, use, tower, SiglipOptions(**options))
        clients.append(value)
        return value
    try:
        yield client, use
    finally:
        for value in clients:
            await value.close()
        await manager.close()
        await supervisor.close()
    assert not list((supervisor.base / ".processes").iterdir())


def test_independent_towers_reuse_authentication_identity_cancel_and_crash(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (client, use):
            image = client("image")
            first = await image.embed([data_url()])
            process = image.process.process
            assert first == await image.embed([data_url()])
            assert image.process.process is process
            assert first.model_revision == use.model_revision and first.usage is first.timing is None
            async with httpx.AsyncClient(trust_env=False) as caller:
                assert (await caller.get(str(image.client.base_url) + "/health")).status_code == 401
            assert (await image.client.post("/embed", json={"inputs": ["https://example.test/a.png"]})).status_code == 422
            assert (await image.client.post("/load", json={"tower": "text"})).status_code == 404
            await image.close()
            assert process.returncode is not None
            text = client("text")
            second = await text.embed(["red", "blue"])
            assert second.model_revision == first.model_revision and second.vector_space_id == first.vector_space_id
            assert second.vectors[0] != second.vectors[1]
            old = text.process.process
            active = asyncio.create_task(text.embed(["wait"]))
            await until(lambda: "waiting child_id=" in text.log.path.read_text())
            child_id = int(re.search(r"waiting child_id=(\d+)", text.log.path.read_text())[1])
            assert psutil.pid_exists(child_id)
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert old.returncode is not None and text.process is None and text.run_dir is None
            await until(lambda: not psutil.pid_exists(child_id))
            assert (await text.embed(["again"])).model_revision == use.model_revision
            old = text.process.process
            with pytest.raises(ModelError):
                await text.embed(["crash"])
            assert old.returncode is not None and text.process is None
            await text.load()
            assert (await text.health()).tower == "text"
    asyncio.run(scenario())


def test_cancel_during_cold_load_waits_for_process_cleanup(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (client, _):
            tower = client(max_batch_size=13)
            active = asyncio.create_task(tower.load())
            await until(lambda: tower.process is not None)
            process = tower.process.process
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert process.returncode is not None and tower.process is None and tower.run_dir is None
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [False, True])
def test_worker_startup_trace_correlates_with_host_and_finishes_before_inference(tmp_path, failure):
    async def scenario():
        async with runtime(tmp_path) as (client, _):
            tower = client()
            if failure:
                (tower.supervisor.worker_root / "siglip_engine.py").write_text("raise RuntimeError('fixture engine failure')\n")
            tower.log = RuntimeLog(tmp_path / "trace.log", tmp_path)
            value = metadata(engine="siglip2", device="cuda")
            with pytest.raises(ModelError) if failure else nullcontext() as error:
                with timing.tracing(timing.LoadTrace(value, tower.log.write)):
                    await tower.load()
            if failure:
                assert error.value.code == "MODEL_UNAVAILABLE"
            else:
                assert (await tower.embed(["fixture"])).timing is None
            await tower.close()  # Drain the worker's log pipe before reading its final events.
            records = events(tower.log.path.read_text())
            assert {item["load_id"] for item in records} == {value["load_id"]}
            assert all(item["model_profile_id"] == value["model_profile_id"] for item in records)
            worker = [item for item in records if item["scope"] == "worker"]
            assert worker[0]["stage"] == "worker_startup" and worker[0]["result"] == "started"
            terminal = [item for item in worker if item["stage"] == "worker_startup" and item["result"] != "started"]
            assert len(terminal) == 1 and terminal[0]["result"] == ("failed" if failure else "completed")
            if failure:
                assert [(item["stage"], item["error_code"]) for item in worker if item["result"] == "failed"] == [
                    ("engine_init", "MODEL_UNAVAILABLE"), ("worker_startup", "MODEL_UNAVAILABLE")]
                assert not any(item["stage"] == "ready_file" for item in worker)
            else:
                assert [item["stage"] for item in worker if item["result"] == "completed"] == [
                    "worker_setup", "model_resources", "engine_init", "http_setup", "ready_file", "worker_startup"]
    asyncio.run(scenario())


INFO = {"tower": "text", "device": "cuda", "device_name": "Fixture", "dtype": "float16", "output_dtype": "float32",
        "dimensions": 2, "model_revision": "sha256:" + "a"*64, "vector_space_id": "sha256:" + "b"*64}


@pytest.mark.parametrize("changes", [
    {"vectors": []}, {"vectors": [[1.0]]}, {"vectors": [[0.0, 0.0]]}, {"vectors": [[float("inf"), 1.0]]},
    {"vectors": [["1", 1.0]]}, {"vectors": [[True, 1.0]]}, {"vectors": [[0.6, 0.8], [0.6, 0.8]]},
    {"dimensions": 3}, {"device": "cpu"}, {"tower": "image"}, {"extra": 1}, {"model_revision": "sha256:" + "c"*64},
    {"vector_space_id": "sha256:" + "d"*64},
])
def test_invalid_worker_vectors_and_identity_stop_the_process(changes):
    async def scenario():
        use = SiglipModelUse(Path("."), REF, Path("."), INFO["model_revision"])
        tower = SiglipTowerClient(SimpleNamespace(), use, "text")
        value = {**INFO, "vectors": [[0.6, 0.8]], **changes}
        tower.client = httpx.AsyncClient(base_url="http://worker.test",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value)))
        tower.process = SimpleNamespace()
        tower.info = SiglipTowerInfo(**INFO)
        tower.close = AsyncMock()
        try:
            with pytest.raises(ModelError) as error:
                await tower.embed(["input"])
            assert error.value.code == "MODEL_UNAVAILABLE"
            tower.close.assert_awaited_once()
        finally:
            await tower.client.aclose()
    asyncio.run(scenario())
