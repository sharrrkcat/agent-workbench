"""Two SigLIP tower clients under one ModelManager queue and release policy."""
from __future__ import annotations

import asyncio
from uuid import uuid4

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.process import RuntimeLog
from ai_workbench.core.models.runtimes.schema import RuntimeStatus, SiglipOptions
from ai_workbench.core.models.schema import ModelStatus, SiglipTowers, SiglipTowerStatus, Tower
from ai_workbench.core.models.siglip import SiglipModelUse, SiglipTowerClient
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.siglip_catalog import model_presence
from ai_workbench.workers.timing import LoadTrace, current_trace, stage, tracing


class SiglipAdapter:
    def __init__(self, supervisor, profile, changed):
        self.supervisor, self.profile, self.changed = supervisor, profile, changed
        self.options = SiglipOptions.model_validate(profile.source.execution_options)
        self.model_use: SiglipModelUse | None = None
        self.clients: dict[Tower, SiglipTowerClient] = {}
        self.towers = SiglipTowers()
        self.lock = asyncio.Lock()
        self.log_paths = {}
        self._traces = {}
        # ModelManager owns the timers and decides when the shared queue has drained.
        self.idle_deadline: float | None = None
        self.release_pending = False

    def ready(self, tower: Tower) -> bool:
        return getattr(self.towers, tower).process_state == "ready"

    def begin_trace(self, profile, trigger, *, tower=None):
        if tower is None:
            return None
        load_id = str(uuid4())
        log = RuntimeLog(self.supervisor.logs / f"process-siglip2-{load_id}.log", self.supervisor.root)
        self.log_paths[tower] = log.path
        self._traces[load_id] = log
        SiglipTowerClient._trace_logs.add(log.path)
        log.write(f"SigLIP {tower} tower: {trigger}")

        def finished():
            self._traces.pop(load_id, None)
            SiglipTowerClient._trace_logs.discard(log.path)
            SiglipTowerClient.prune_logs(self.supervisor.logs)

        return LoadTrace({"load_id": load_id, "model_profile_id": profile.id, "source_type": "local",
            "engine": "siglip2", "version": self.supervisor.release.version, "device": self.options.device,
            "trigger": trigger, "operation": "health" if trigger == "health" else "load"},
            log.write, on_finish=finished)

    def snapshot(self, profile):
        values = (self.towers.image, self.towers.text)
        loaded = [value for value in values if value.residency == "loaded"]
        failure = next((value.error_code for value in values if value.process_state == "failed"), None)
        process_state = "starting" if any(value.process_state == "starting" for value in values) else (
            "failed" if failure else "ready" if loaded else "stopped")
        installation = self.supervisor.installation(check=False)
        return ModelStatus(state="failed" if failure else "ready" if loaded else "unloaded",
            residency="loaded" if loaded else "unloaded", unload_supported=True, error_code=failure,
            runtime=RuntimeStatus(engine="siglip2", version=installation.version, install_state=installation.state,
                job_id=installation.job_id, process_state=process_state,
                device_name=loaded[0].info.device_name if loaded else None),
            towers=self.towers.model_copy(deep=True))

    def _discard_unused_identity(self):
        if not any(getattr(self.towers, tower).process_state in {"starting", "ready"} for tower in ("image", "text")):
            self.model_use = None
            self.towers.model_revision = self.towers.vector_space_id = self.towers.dimensions = None

    def _failed(self, tower, code):
        setattr(self.towers, tower, SiglipTowerStatus(process_state="failed", error_code=code))
        self._discard_unused_identity()
        self.changed()

    async def _stop_tower(self, tower):
        client = self.clients.get(tower)
        if client:
            await client.close()
        value = getattr(self.towers, tower)
        setattr(self.towers, tower, SiglipTowerStatus(
            process_state="failed" if value.error_code else "stopped", error_code=value.error_code))
        self.changed()

    def _accept_info(self, info):
        if self.towers.vector_space_id is not None and (info.vector_space_id, info.dimensions) != (
                self.towers.vector_space_id, self.towers.dimensions):
            raise ModelError("MODEL_UNAVAILABLE", "The SigLIP towers reported different vector spaces.", 503)
        self.towers.vector_space_id, self.towers.dimensions = info.vector_space_id, info.dimensions

    async def load(self, profile, *, tower: Tower, explicit=False):
        trace = current_trace() or (self.begin_trace(profile, "explicit" if explicit else "autoload", tower=tower)
                                    if explicit or not self.ready(tower) else None)
        with tracing(trace):
            async with self.lock:
                previous_error = getattr(self.towers, tower).error_code
                if previous_error and not explicit:
                    raise ModelError("MODEL_UNAVAILABLE", "Load the failed SigLIP tower explicitly from Models settings.", 503)
                log = self._traces[trace.metadata["load_id"]] if trace else None
                self.towers.active_tower = tower
                try:
                    if profile.parameters["unload_other_tower_on_call"]:
                        with stage("other_tower_stop"):
                            await self._stop_tower("text" if tower == "image" else "image")
                    if self.ready(tower):
                        client = self.clients[tower]
                        if log:
                            client.use_log(log)
                            self.log_paths[tower] = log.path
                        if explicit:
                            await client.health()
                        if trace:
                            trace.reused.update(process_reused=True, model_reused=True)
                        return self.snapshot(profile)
                    await self._stop_tower(tower)
                    setattr(self.towers, tower, SiglipTowerStatus(process_state="starting"))
                    self.changed()
                    with stage("model_identity"):
                        if self.model_use is None:
                            self.model_use = await SiglipModelUse.prepare(self.supervisor.root, profile.model_ref)
                            self.towers.model_revision = self.model_use.model_revision
                    client = SiglipTowerClient(self.supervisor, self.model_use, tower, self.options, log=log,
                        on_exit=lambda: self._failed(tower, "MODEL_UNAVAILABLE"))
                    self.clients[tower] = client
                    if log:
                        self.log_paths[tower] = log.path
                    with stage("tower_load"):
                        info = await client.load()
                    self._accept_info(info)
                    setattr(self.towers, tower, SiglipTowerStatus(process_state="ready", residency="loaded", info=info))
                    self.changed()
                    return self.snapshot(profile)
                except asyncio.CancelledError:
                    await self._stop_tower(tower)
                    setattr(self.towers, tower, SiglipTowerStatus(
                        process_state="failed" if previous_error else "stopped", error_code=previous_error))
                    self._discard_unused_identity()
                    raise
                except ModelError as exc:
                    await self._stop_tower(tower)
                    self._failed(tower, exc.code)
                    raise
                finally:
                    self.towers.active_tower = None
                    self.changed()

    async def image_embed(self, profile, tower: Tower, inputs: list[str]):
        async with self.lock:
            self.towers.active_tower = tower
            self.changed()
            try:
                return await self.clients[tower].embed(inputs)
            except asyncio.CancelledError:
                await self._stop_tower(tower)
                self._discard_unused_identity()
                raise
            except ModelError as exc:
                await self._stop_tower(tower)
                self._failed(tower, exc.code)
                raise
            finally:
                self.towers.active_tower = None
                self.changed()

    async def health(self, profile):
        async with self.lock:
            self.supervisor.executable("siglip2", self.options.device)
            try:
                model_presence(self.supervisor.root / "data/models", profile.model_ref)
            except WorkerError as exc:
                raise ModelError(exc.code, "The local SigLIP model files are missing or outside data/models.", exc.status) from exc
            for tower in ("image", "text"):
                if not self.ready(tower):
                    continue
                with tracing(self.begin_trace(profile, "health", tower=tower)) as trace:
                    client = self.clients[tower]
                    client.use_log(self._traces[trace.metadata["load_id"]])
                    try:
                        with stage("health_rpc"):
                            await client.health()
                    except asyncio.CancelledError:
                        await self._stop_tower(tower)
                        self._discard_unused_identity()
                        raise
                    except ModelError as exc:
                        await self._stop_tower(tower)
                        self._failed(tower, exc.code)
                        trace.finish(exc)
            return self.snapshot(profile)

    async def unload(self, profile):
        async with self.lock:
            for tower in ("image", "text"):
                await self._stop_tower(tower)
            self.clients.clear()
            self._discard_unused_identity()
            self.idle_deadline = None
            self.release_pending = False
            self.changed()
            return self.snapshot(profile)

    async def close(self):
        await self.unload(self.profile)
