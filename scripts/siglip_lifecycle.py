"""Opt-in extended CUDA scenarios for an explicit user acceptance request.

Observers wrap real operations without substituting workers or inference results.
All fault injection, measurements and evidence stay in this acceptance process.
The 20 switches and 10 alternating pairs are not routine regression or CI gates.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import time
import traceback
from unittest.mock import patch
from uuid import uuid4

import httpx

from ai_workbench.api.schemas.inference import ImageEmbeddingResponse
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.process import ManagedProcess
from ai_workbench.core.models.schema import ImageEmbeddingRequest
from ai_workbench.core.models import observability, siglip
from scripts.smoke_siglip_runtime import compare, fixture_inputs

GROUPS = ("switching", "residency", "cancellation", "faults", "identity", "release")


class LifecycleAcceptance:
    def __init__(self, root, state, caller, profile, shutdown, groups):
        self.root, self.state, self.caller = root, state, caller
        self.manager, self.profile, self.shutdown = state.model_manager, profile, shutdown
        self.groups = [group for group in GROUPS if group in (groups or GROUPS)]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.output = root / "build/siglip-smoke/lifecycle" / stamp
        (self.output / "logs").mkdir(parents=True)
        self.started = time.monotonic()
        self.inputs = fixture_inputs()
        self.expected = {"image": {}, "text": {}}
        self.identity = None
        self.hashes = 0
        self.owned = []
        self.inflight = set()
        self.tasks = []
        self.events = []
        self.request_ids = set()
        self.report = {"status": "running", "started_at": stamp, "groups": self.groups,
            "complete_matrix": self.groups == list(GROUPS), "model_ref": profile.model_ref,
            "platform": platform.platform(), "device": "cuda", "dtype": "float16", "max_batch_size": 1,
            "runtime_version": state.runtime_supervisor.release.version,
            "installation_manifest": state.runtime_supervisor.installation(check=False).manifest_sha256,
            "cases": [], "events": self.events, "limitations": ["No real CPU or FixRes acceptance",
                "Timings and device-wide memory snapshots are observations, not performance guarantees"]}

    @property
    def path(self):
        return f"/api/models/profiles/{self.profile.id}"

    @property
    def adapter(self):
        return self.manager._managed_slot(self.profile).adapter

    def status(self):
        return self.manager.status(self.profile.id)

    def snapshot(self):
        return {"model": self.status().model_dump(mode="json") if not self.manager._closed else {"closed": True},
            "identity_calculations": self.hashes,
            "workers": [{"pid": item["process"].process.pid, "tower": item["tower"],
                         "returncode": item["process"].process.returncode} for item in self.owned]}

    def event(self, operation, **values):
        event = {"operation": operation, "seconds": round(time.monotonic() - self.started, 6), **values}
        self.events.append(event)
        return event

    def save(self):
        (self.output / "report.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")

    def copy_log(self, client):
        if client.log and client.log.path.exists():
            shutil.copyfile(client.log.path, self.output / "logs" / client.log.path.name)

    async def gpu(self):
        process = await asyncio.create_subprocess_exec("nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used", "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode == 0, stderr.decode(errors="replace")
        name, driver, total, used = stdout.decode().strip().splitlines()[0].split(", ")
        return {"name": name, "driver": driver, "total_mib": int(total), "used_mib": int(used)}

    @asynccontextmanager
    async def case(self, name):
        entry = {"case": name, "status": "running", "before": self.snapshot(), "gpu_before": await self.gpu()}
        self.report["cases"].append(entry)
        self.save()
        started = time.monotonic()
        print(json.dumps({"case": name, "status": "running"}), flush=True)
        try:
            yield entry
            entry["status"] = "passed"
        except BaseException as exc:
            entry.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
            raise
        finally:
            entry.update(seconds=round(time.monotonic() - started, 3), after=self.snapshot(), gpu_after=await self.gpu())
            self.save()
            print(json.dumps({key: entry[key] for key in ("case", "status", "seconds")}), flush=True)

    @contextmanager
    def observe(self):
        original_start, original_stop = ManagedProcess.start, ManagedProcess.stop
        original_embed, original_load = siglip.SiglipTowerClient.embed, siglip.SiglipTowerClient.load
        original_hash = siglip.model_revision
        original_log = observability._write_event

        async def start(args, *, env, cwd, log):
            tower = env.get("COGITA_SIGLIP_TOWER")
            if tower and self.profile.parameters["unload_other_tower_on_call"]:
                assert all(item["process"].process.returncode is not None for item in self.owned
                           if item["tower"] != tower), "The old tower is alive at the new process startup boundary"
            process = await original_start(args, env=env, cwd=cwd, log=log)
            if tower:
                self.owned.append({"process": process, "tower": tower,
                    "directory": Path(env["COGITA_WORKER_READY"]).parent})
                self.event("process_started", tower=tower, pid=process.process.pid, state=self.snapshot())
            return process

        async def stop(process):
            owned = next((item for item in self.owned if item["process"] is process), None)
            await original_stop(process)
            if owned:
                assert process.process.returncode is not None and process.close_job is None
                self.event("process_tree_stopped", tower=owned["tower"], pid=process.process.pid,
                    returncode=process.process.returncode)

        async def load(client):
            try:
                return await original_load(client)
            finally:
                self.copy_log(client)

        async def embed(client, inputs):
            assert not self.inflight, "Two SigLIP inferences overlap"
            self.inflight.add(client.tower)
            self.event("inference_started", tower=client.tower, pid=client.process.process.pid,
                active=self.status().active, queued=self.status().queued, count=len(inputs))
            assert self.status().active == 1
            try:
                result = await original_embed(client, inputs)
                assert (result.device, result.dtype, result.output_dtype) == ("cuda", "float16", "float32")
                assert result.usage is result.timing is None
                return result
            finally:
                self.inflight.discard(client.tower)
                self.event("inference_finished", tower=client.tower)
                self.copy_log(client)

        def identity(path):
            result = original_hash(path)
            self.hashes += 1
            self.event("identity_calculated", model_revision=result, calculation=self.hashes)
            return result

        def request_log(root, value):
            original_log(root, value)
            if value.get("request_id") in self.request_ids:
                self.event("request_log", **{key: value.get(key) for key in
                    ("event", "request_id", "status_code", "error_code")})

        with patch.object(ManagedProcess, "start", start), patch.object(ManagedProcess, "stop", stop), \
                patch.object(siglip.SiglipTowerClient, "load", load), \
                patch.object(siglip.SiglipTowerClient, "embed", embed), patch.object(siglip, "model_revision", identity), \
                patch.object(observability, "_write_event", request_log):
            yield

    async def until(self, predicate, *, running=None, timeout=310):
        async def poll():
            while not predicate():
                if running is not None and running.done():
                    await running
                    raise AssertionError("The operation completed before the required observation")
                await asyncio.sleep(0.002)
        await asyncio.wait_for(poll(), timeout)

    def spawn(self, operation):
        task = asyncio.create_task(operation)
        self.tasks.append(task)
        return task

    async def cancel(self, task):
        assert not task.done(), "The cancellation target has already finished"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return
        raise AssertionError("The task did not propagate cancellation")

    async def call(self, method, path, **kwargs):
        response = await self.caller.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def payload(self, tower, count=1, encoding="float"):
        values = self.inputs[tower]
        return {"model": self.profile.alias, "input_type": tower,
            "input": [values[i % len(values)] for i in range(count)], "encoding_format": encoding}

    async def infer(self, tower, count=1, *, internal=False, encoding="float"):
        payload = self.payload(tower, count, encoding)
        if internal:
            result = await self.manager.image_embed(self.profile.id, ImageEmbeddingRequest.model_validate(payload))
            vectors = result.vectors
            assert result.usage is result.timing is None
        else:
            raw = await self.call("POST", "/v1/images/embeddings", json=payload)
            assert set(raw) == {"object", "model", "input_type", "dimensions", "model_revision", "vector_space_id", "data"}
            result = ImageEmbeddingResponse.model_validate(raw)
            assert result.model == self.profile.alias and result.input_type == tower
            assert [item.index for item in result.data] == list(range(count))
            vectors = [list(struct.unpack("<" + "f" * result.dimensions, base64.b64decode(item.embedding)))
                if isinstance(item.embedding, str) else item.embedding for item in result.data]
        identity = (result.model_revision, result.vector_space_id, result.dimensions)
        if self.identity is None:
            self.identity = identity
            self.report["identity"] = dict(zip(("model_revision", "vector_space_id", "dimensions"), identity))
        assert identity == self.identity
        assert len(vectors) == count
        for value, vector in zip(payload["input"], vectors, strict=True):
            assert len(vector) == result.dimensions and all(math.isfinite(v) for v in vector)
            assert abs(sum(v * v for v in vector) - 1) < 0.00001
            previous = self.expected[tower].get(value)
            if previous is not None:
                compare([vector], [previous])
            else:
                self.expected[tower][value] = vector
        return vectors

    def process(self, tower):
        return self.adapter.clients[tower].process.process

    async def configure(self, *, switching, policy="manual", idle_seconds=300):
        await self.call("PATCH", self.path, json={"parameters": {"unload_other_tower_on_call": switching},
            "source": {"type": "local", "execution_options": {"device": "cuda", "intraop_threads": 4, "max_batch_size": 1},
                "lifecycle": {"unload": policy, "idle_seconds": idle_seconds}}})
        self.profile = self.manager.profiles.get(self.profile.id)
        assert all(item["process"].process.returncode is not None for item in self.owned)

    async def unload(self):
        await self.call("POST", self.path + "/unload")
        assert self.adapter.model_use is None
        assert self.status().towers.model_revision is None
        assert all(item["process"].process.returncode is not None for item in self.owned)

    async def load_both(self):
        for tower in ("image", "text"):
            await self.call("POST", self.path + "/load", json={"tower": tower})
        assert self.process("image").returncode is self.process("text").returncode is None
        assert all(getattr(self.status().towers, tower).residency == "loaded" for tower in ("image", "text"))

    def retained(self, tower, process, use):
        assert process.returncode is None and self.process(tower) is process
        assert self.adapter.model_use is use

    async def expected_error(self, tower, code, status):
        request_id = "siglip-cuda-" + uuid4().hex
        self.request_ids.add(request_id)
        response = await self.caller.post("/v1/images/embeddings", json=self.payload(tower, 16),
            headers={"X-Request-ID": request_id})
        assert response.status_code == status, response.text
        assert response.json()["error"]["code"] == code, response.text
        self.event("expected_api_error", tower=tower, code=code, status=status,
            request_id=response.headers.get("x-request-id"))

    async def passive_reads(self):
        count, workers = self.hashes, len(self.owned)
        before = self.status().towers.model_dump()
        for path in (self.path + "/status", "/api/models/inventory?kind=image_embedding",
                "/api/models/inspect?kind=image_embedding&model_ref=" + self.profile.model_ref):
            await self.call("GET", path)
        response = await self.caller.post("/v1/images/embeddings", json={"model": self.profile.alias,
            "input_type": "image", "input": "invalid"})
        assert response.status_code == 422
        assert (self.hashes, len(self.owned)) == (count, workers)
        assert self.status().towers.model_dump() == before

    async def switching(self):
        await self.configure(switching=True)
        async with self.case("switching_initial_image"):
            await self.passive_reads()
            before = self.hashes
            await self.infer("image", len(self.inputs["image"]))
            use = self.adapter.model_use
        for iteration in range(1, 11):
            for tower in ("text", "image"):
                async with self.case(f"switching_{iteration:02d}_{tower}"):
                    old = self.process("image" if tower == "text" else "text")
                    await self.infer(tower, len(self.inputs[tower]), internal=iteration % 2 == 0)
                    process = self.process(tower)
                    await self.infer(tower, len(self.inputs[tower]), encoding="base64")
                    assert old.returncode is not None and self.process(tower) is process
                    assert self.adapter.model_use is use and self.hashes == before + 1
                    assert self.status().active == self.status().queued == 0
        await self.passive_reads()

    async def residency(self):
        await self.configure(switching=False)
        async with self.case("dual_residency"):
            await self.infer("image", len(self.inputs["image"]))
            await self.infer("text", len(self.inputs["text"]))
            image, text, use = self.process("image"), self.process("text"), self.adapter.model_use
            for _ in range(10):
                await self.infer("image", internal=True)
                await self.infer("text", encoding="base64")
                self.retained("image", image, use)
                self.retained("text", text, use)
            await self.passive_reads()
        async with self.case("shared_fifo_and_batch_16"):
            start = len(self.events)
            active = self.spawn(self.infer("image", 16, internal=True))
            await self.until(lambda: "image" in self.inflight, running=active)
            queued = self.spawn(self.infer("text", 16, encoding="base64"))
            await self.until(lambda: self.status().queued == 1, running=active)
            last = self.spawn(self.infer("image", internal=True))
            await self.until(lambda: self.status().queued == 2, running=active)
            await asyncio.gather(active, queued, last)
            assert [event["tower"] for event in self.events[start:] if event["operation"] == "inference_started"] == ["image", "text", "image"]
            self.retained("image", image, use)
            self.retained("text", text, use)
            assert self.status().active == self.status().queued == 0

    async def cancellation(self):
        await self.configure(switching=False)
        for tower in ("image", "text"):
            other = "text" if tower == "image" else "image"
            async with self.case(tower + "_startup_cancel"):
                await self.unload()
                await self.infer(other)
                healthy, use = self.process(other), self.adapter.model_use
                active = self.spawn(self.manager.load(self.profile.id, tower=tower))
                await self.until(lambda: tower in self.adapter.clients and self.adapter.clients[tower].process is not None,
                    running=active)
                target = self.process(tower)
                assert getattr(self.status().towers, tower).process_state == "starting"
                self.event("cancel_startup", tower=tower, pid=target.pid, state=self.snapshot())
                await self.cancel(active)
                assert target.returncode is not None and getattr(self.status().towers, tower).process_state == "stopped"
                self.retained(other, healthy, use)
                await self.infer(tower)
            async with self.case(tower + "_queued_cancel"):
                target = self.process(tower)
                active = self.spawn(self.infer(other, 16, internal=True))
                await self.until(lambda: other in self.inflight, running=active)
                queued = self.spawn(self.infer(tower))
                await self.until(lambda: self.status().queued == 1, running=active)
                self.event("cancel_waiter", tower=tower, state=self.snapshot())
                await self.cancel(queued)
                await self.until(lambda: self.status().queued == 0, running=active)
                assert self.process(tower) is target and target.returncode is None
                self.retained(other, healthy, use)
                await active
            async with self.case(tower + "_inference_cancel"):
                active = self.spawn(self.infer(tower, 16, internal=True))
                await self.until(lambda: tower in self.inflight, running=active)
                queued = self.spawn(self.infer(other))
                await self.until(lambda: self.status().queued == 1, running=active)
                marker = len(self.events)
                self.event("cancel_inference", tower=tower, state=self.snapshot())
                await self.cancel(active)
                assert target.returncode is not None
                await queued
                self.retained(other, healthy, use)
                events = self.events[marker:]
                stopped = next(i for i, event in enumerate(events) if event["operation"] == "process_tree_stopped" and event["pid"] == target.pid)
                resumed = next(i for i, event in enumerate(events) if event["operation"] == "inference_started" and event["tower"] == other)
                assert stopped < resumed
                await self.infer(tower)
            async with self.case(tower + "_http_disconnect"):
                target = self.process(tower)
                request_id = "siglip-cuda-disconnect-" + uuid4().hex
                self.request_ids.add(request_id)
                host, port = self.caller.base_url.host, self.caller.base_url.port
                _, writer = await asyncio.open_connection(host, port)
                body = json.dumps(self.payload(tower, 16)).encode()
                try:
                    writer.write((f"POST /v1/images/embeddings HTTP/1.1\r\nHost: {host}:{port}\r\n"
                        f"Authorization: {self.caller.headers['authorization']}\r\nX-Request-ID: {request_id}\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
                    await writer.drain()
                    await self.until(lambda: tower in self.inflight, timeout=10)
                    self.event("http_disconnect", tower=tower, pid=target.pid, state=self.snapshot())
                finally:
                    writer.close()
                    await writer.wait_closed()
                await self.until(lambda: self.status().active == self.status().queued == 0, timeout=15)
                assert target.returncode is not None and getattr(self.status().towers, tower).process_state == "stopped"
                await self.until(lambda: any(event.get("request_id") == request_id and event.get("event") == "access"
                    and event.get("status_code") == 499 and event.get("error_code") == "REQUEST_CANCELLED"
                    for event in self.events), timeout=10)
                self.retained(other, healthy, use)
                await self.infer(tower)

    async def faults(self):
        await self.configure(switching=False)
        await self.load_both()
        for tower in ("image", "text"):
            other = "text" if tower == "image" else "image"
            for failure in ("timeout", "crash"):
                async with self.case(tower + "_" + failure + "_recovery"):
                    target, healthy, use = self.process(tower), self.process(other), self.adapter.model_use
                    if failure == "timeout":
                        transport = self.adapter.clients[tower].client
                        previous = transport.timeout
                        transport.timeout = httpx.Timeout(connect=5, write=5, pool=5, read=0.001)
                        try:
                            await self.expected_error(tower, "MODEL_TIMEOUT", 504)
                        finally:
                            transport.timeout = previous
                    else:
                        active = self.spawn(self.infer(tower, 16, internal=True))
                        await self.until(lambda: tower in self.inflight, running=active)
                        self.event("kill_owned_worker", tower=tower, pid=target.pid)
                        target.kill()
                        try:
                            await active
                        except ModelError as exc:
                            assert exc.code == "MODEL_UNAVAILABLE" and exc.status == 503
                            self.event("expected_internal_error", tower=tower, code=exc.code, status=exc.status)
                        else:
                            raise AssertionError("Inference succeeded after its worker was killed")
                    await self.until(lambda: getattr(self.status().towers, tower).process_state == "failed", timeout=15)
                    assert target.returncode is not None
                    self.retained(other, healthy, use)
                    before = self.hashes
                    await self.expected_error(tower, "MODEL_UNAVAILABLE", 503)
                    assert self.hashes == before
                    await self.infer(other)
                    self.retained(other, healthy, use)
                    log = await self.call("GET", self.path + "/log?tower=" + tower)
                    assert "SigLIP " + tower in log["text"]
                    await self.call("POST", self.path + "/load", json={"tower": tower})
                    assert self.process(tower).pid != target.pid and self.status().state == "ready"
                    await self.infer(tower)
                    self.retained(other, healthy, use)

    async def identity_checks(self):
        await self.configure(switching=True)
        await self.infer("image")
        for number, tower in enumerate(("image", "text", "image"), 1):
            async with self.case(f"identity_release_reload_{number}"):
                use, count = self.adapter.model_use, self.hashes
                await self.unload()
                await self.passive_reads()
                await self.infer(tower, internal=number == 2)
                assert self.hashes == count + 1 and self.adapter.model_use is not use
        for tower in ("image", "text"):
            async with self.case(tower + "_last_tower_cancel"):
                await self.unload()
                await self.infer(tower)
                target, count = self.process(tower), self.hashes
                active = self.spawn(self.infer(tower, 16, internal=True))
                await self.until(lambda: tower in self.inflight, running=active)
                await self.cancel(active)
                assert target.returncode is not None and self.adapter.model_use is None
                assert self.status().towers.model_revision is None
                await self.infer(tower)
                assert self.hashes == count + 1
            async with self.case(tower + "_last_tower_crash"):
                target, count = self.process(tower), self.hashes
                self.event("kill_owned_idle_worker", tower=tower, pid=target.pid)
                target.kill()
                await self.until(lambda: getattr(self.status().towers, tower).process_state == "failed", timeout=15)
                assert self.adapter.model_use is None and self.status().towers.model_revision is None
                await self.unload()
                assert getattr(self.status().towers, tower).process_state == "failed"
                await self.expected_error(tower, "MODEL_UNAVAILABLE", 503)
                assert self.hashes == count
                await self.call("POST", self.path + "/load", json={"tower": tower})
                await self.infer(tower)
                assert self.hashes == count + 1

    async def release(self):
        await self.configure(switching=False)
        async with self.case("manual_residency"):
            await self.load_both()
            image, text, use = self.process("image"), self.process("text"), self.adapter.model_use
            await self.infer("image")
            await self.infer("text", internal=True)
            await self.call("POST", self.path + "/health")
            self.retained("image", image, use)
            self.retained("text", text, use)
        async with self.case("after_request_queue_drain"):
            await self.configure(switching=False, policy="after_request")
            await self.load_both()
            image, text = self.process("image"), self.process("text")
            active = self.spawn(self.infer("image", 16, internal=True))
            await self.until(lambda: "image" in self.inflight, running=active)
            queued = self.spawn(self.infer("text"))
            await self.until(lambda: self.status().queued == 1, running=active)
            assert image.returncode is text.returncode is None
            await asyncio.gather(active, queued)
            assert image.returncode is not None and text.returncode is not None
            assert self.adapter.model_use is None and self.status().active == self.status().queued == 0
        async with self.case("idle_health_does_not_extend"):
            await self.configure(switching=False, policy="idle", idle_seconds=2)
            await self.load_both()
            image, text, deadline = self.process("image"), self.process("text"), self.adapter.idle_deadline
            for _ in range(3):
                await self.call("POST", self.path + "/health")
                assert self.adapter.idle_deadline == deadline
                await asyncio.sleep(0.15)
            await self.until(lambda: image.returncode is not None and text.returncode is not None, timeout=10)
            await self.until(lambda: self.status().active == 0 and self.adapter.model_use is None, timeout=10)
        async with self.case("configuration_invalidates_both"):
            await self.configure(switching=False)
            await self.load_both()
            image, text, adapter, count = self.process("image"), self.process("text"), self.adapter, self.hashes
            await self.call("PATCH", self.path, json={"name": "SigLIP CUDA lifecycle edited"})
            self.profile = self.manager.profiles.get(self.profile.id)
            assert image.returncode is not None and text.returncode is not None and adapter.model_use is None
            await self.passive_reads()
            assert self.hashes == count
            await self.infer("image")
            assert self.hashes == count + 1
        async with self.case("application_shutdown"):
            await self.load_both()
            await self.shutdown()
            assert self.manager._closed
            assert all(item["process"].process.returncode is not None for item in self.owned)

    async def run(self):
        with self.observe():
            try:
                self.report["gpu"] = await self.gpu()
                for group in self.groups:
                    await (self.identity_checks if group == "identity" else getattr(self, group))()
                assert not self.state.runs.list_all_runs() and not self.state.sessions.list_sessions()
                self.report["status"] = "passed"
            except BaseException as exc:
                self.report.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
                raise
            finally:
                try:
                    for task in self.tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*self.tasks, return_exceptions=True)
                    await self.shutdown()
                    self.report["cleanup"] = {"workers_exited": all(item["process"].process.returncode is not None for item in self.owned),
                        "process_directories_removed": all(not item["directory"].exists() for item in self.owned),
                        "manager_closed": self.manager._closed}
                    assert all(self.report["cleanup"].values()), self.report["cleanup"]
                except BaseException as exc:
                    self.report.update(status="failed", cleanup_error=f"{type(exc).__name__}: {exc}")
                    raise
                finally:
                    self.report.update(seconds=round(time.monotonic() - self.started, 3), final=self.snapshot())
                    self.save()
                    print(json.dumps({"siglip_lifecycle": self.report["status"], "complete_matrix": self.report["complete_matrix"],
                        "report": str(self.output / "report.json")}), flush=True)


async def acceptance(root, state, caller, profile, shutdown, groups=None):
    await LifecycleAcceptance(root, state, caller, profile, shutdown, groups).run()
