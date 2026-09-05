from __future__ import annotations

import asyncio
import math
import os
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field

from ai_workbench.core.models.adapter import ProviderAdapter
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import (
    ChatChunk, ChatRequest, EmbeddingParameters, EmbeddingResult,
    ImagePart, ModelProfile, ModelStatus, ProviderProfile,
)
from ai_workbench.workers.protocol import WorkerError


@dataclass
class ProviderSlot:
    adapter: ProviderAdapter
    semaphore: asyncio.Semaphore
    active: int = 0
    queued: int = 0
    tasks: set[asyncio.Task] = field(default_factory=set)
    model_active: dict[tuple | None, int] = field(default_factory=dict)
    model_queued: dict[tuple | None, int] = field(default_factory=dict)


@dataclass
class ManagedQueue:
    concurrency: int = 1
    queue_size: int = 32
    queue_timeout_seconds: float = 30


class ModelManager:
    def __init__(self, profiles, providers, settings, events=None,
                 adapter_factory: Callable[[ProviderProfile], ProviderAdapter] = OpenAIAdapter,
                 runtime_supervisor=None):
        self.profiles = profiles
        self.providers = providers
        self.settings = settings
        self.events = events
        self.adapter_factory = adapter_factory
        self.runtime_supervisor = runtime_supervisor
        if runtime_supervisor:
            runtime_supervisor.manager = self
        self._slots: dict[str | tuple, ProviderSlot] = {}
        self._statuses: dict[tuple, ModelStatus] = {}
        self._idle: dict[tuple, asyncio.Task] = {}
        self._load_locks: dict[tuple, asyncio.Lock] = {}
        self._invalidating: set[str | tuple | None] = set()
        self._closed = False

    def profile(self, profile_id: str, kind: str | None = None) -> ModelProfile:
        try:
            profile = self.profiles.get(profile_id)
        except KeyError as exc:
            raise ModelError("MODEL_NOT_FOUND", "Model profile does not exist.", 404) from exc
        if kind and profile.kind != kind:
            raise ModelError("MODEL_KIND_MISMATCH", f"This operation requires a {kind} profile.")
        if not profile.enabled:
            raise ModelError("MODEL_UNAVAILABLE", "Model profile is disabled.", 503)
        return profile

    def external_profile(self, alias: str, kind: str | None = None) -> ModelProfile:
        profile = self.profiles.find_by_alias(alias)
        if profile is None or not profile.enabled or not profile.external_enabled:
            raise ModelError("MODEL_NOT_FOUND", "Model alias is not available to the external service.", 404)
        return self.profile(profile.id, kind)

    def chat_profile(self, session_model_profile_id: str | None) -> ModelProfile:
        profile_id = session_model_profile_id or self.settings.get().default_model_profile_id
        if not profile_id:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select a chat model in Models settings.", 503)
        return self.profile(profile_id, "llm")

    def backend_key(self, profile: ModelProfile):
        if not profile.runtime_id:
            return profile.provider_profile_id
        key = (profile.runtime_id, profile.runtime_variant)
        if profile.runtime_id == "llama-server":
            # Keep identity stable if a weight file/link disappears after loading.
            # Filesystem containment is rechecked at every health/load operation.
            path = self.runtime_supervisor.root / "data" / "models" / profile.model_ref
            key += (os.path.normcase(str(path)),)
        return key

    def _key(self, profile: ModelProfile) -> tuple:
        backend = self.backend_key(profile)
        return backend, profile.id if profile.runtime_id == "python-worker" else backend[-1] if profile.runtime_id else profile.model_ref

    def validate_binding(self, profile):
        if profile.runtime_id:
            self.runtime_supervisor.entry(profile.runtime_id, profile.runtime_variant)
        if profile.runtime_id == "llama-server":
            for alias in self.profiles.list("llm"):
                if alias.id != getattr(profile, "id", None) and self.backend_key(alias) == self.backend_key(profile) and alias.runtime_options != profile.runtime_options:
                    raise ModelError("MODEL_CONFLICT", "Aliases of a managed GGUF must use identical runtime options.", 409)

    def status(self, profile_id: str) -> ModelStatus:
        profile = self.profiles.get(profile_id)
        status = self._statuses.get(self._key(profile), ModelStatus()).model_copy()
        provider = next((p for p in self.providers.list() if p.id == profile.provider_profile_id), None)
        if profile.runtime_id and self.runtime_supervisor:
            from ai_workbench.core.models.runtimes.schema import model_path
            from ai_workbench.core.models.runtimes.schema import RuntimeStatus
            installation = self.runtime_supervisor.installation(profile.runtime_id, profile.runtime_variant)
            slot = self._slots.get(self.backend_key(profile))
            status = slot.adapter.snapshot(profile) if slot else ModelStatus(state="unloaded", residency="unloaded", unload_supported=True)
            status.runtime = RuntimeStatus(runtime_id=installation.runtime_id, variant=installation.variant, version=installation.version,
                install_state=installation.state, job_id=installation.job_id,
                process_state=slot.adapter.state if slot else "stopped")
            if installation.state != "installed":
                status.state = "unavailable"
                status.error_code = {"not_installed": "RUNTIME_NOT_INSTALLED", "installing": "RUNTIME_INSTALLING", "unsupported": "RUNTIME_UNSUPPORTED"}.get(installation.state, "RUNTIME_BROKEN")
            else:
                try:
                    path = model_path(self.runtime_supervisor.root, profile.model_ref)
                    if profile.runtime_id == "llama-server" and not path.is_file():
                        raise ValueError()
                    if profile.runtime_id == "python-worker":
                        from ai_workbench.workers.protocol import local_model
                        local_model(self.runtime_supervisor.root / "data" / "models", profile.model_ref,
                            wd14=profile.kind == "vision" and profile.parameters["architecture"] == "wd14")
                except (OSError, ValueError, WorkerError):
                    status.state, status.error_code = "unavailable", "MODEL_NOT_FOUND"
        if not profile.enabled or not profile.runtime_id and (provider is None or not provider.enabled):
            status.state = "unavailable"
            status.error_code = "MODEL_UNAVAILABLE"
        slot = self._slots.get(self.backend_key(profile))
        if slot:
            status.active = slot.model_active.get(self._key(profile), 0)
            status.queued = slot.model_queued.get(self._key(profile), 0)
        return status

    def _notify(self, profile: ModelProfile, status: ModelStatus) -> None:
        self._statuses[self._key(profile)] = status
        self._publish(self._key(profile))

    def _publish(self, key: tuple | None) -> None:
        if self.events:
            for profile in self.profiles.list():
                if self._key(profile) == key:
                    self.events.emit("model_status", session_id="", payload={
                        "model_profile_id": profile.id, "status": self.status(profile.id).model_dump(),
                    })

    def _slot(self, provider_id, profile=None, require_runtime=True):
        if self._closed:
            raise ModelError("MODEL_UNAVAILABLE", "Model manager is shutting down.", 503)
        if provider_id in self._invalidating:
            raise ModelError("MODEL_BUSY", "Provider configuration is changing.", 409)
        if profile and profile.runtime_id:
            supervisor = self.runtime_supervisor
            if supervisor.blocked == (profile.runtime_id, profile.runtime_variant):
                raise ModelError("RUNTIME_INSTALLING", "Runtime maintenance is in progress.", 409)
            if require_runtime:
                supervisor.assert_available(profile.runtime_id, profile.runtime_variant)
            if provider_id not in self._slots:
                from ai_workbench.core.models.runtimes.adapters import LlamaServerAdapter, PythonWorkerAdapter
                cls = LlamaServerAdapter if profile.runtime_id == "llama-server" else PythonWorkerAdapter
                adapter = cls(supervisor, profile, lambda: self._managed_changed(provider_id))
                self._slots[provider_id] = ProviderSlot(adapter, asyncio.Semaphore(1))
            return ManagedQueue(), self._slots[provider_id]
        try:
            provider = self.providers.get(provider_id)
        except KeyError as exc:
            raise ModelError("MODEL_UNAVAILABLE", "Configure an executable provider for this model.", 503) from exc
        if not provider.enabled:
            raise ModelError("MODEL_UNAVAILABLE", "Provider is disabled.", 503)
        if provider.id not in self._slots:
            self._slots[provider.id] = ProviderSlot(self.adapter_factory(provider), asyncio.Semaphore(provider.concurrency))
        return provider, self._slots[provider.id]

    @asynccontextmanager
    async def _provider_lease(self, provider_id, key: tuple | None = None, profile=None, require_runtime=True):
        provider, slot = self._slot(provider_id, profile, require_runtime)
        if slot.active + slot.queued >= provider.concurrency + provider.queue_size:
            raise ModelError("MODEL_BUSY", "Provider queue is full.", 429)
        slot.queued += 1
        slot.model_queued[key] = slot.model_queued.get(key, 0) + 1
        self._publish(key)
        task = asyncio.current_task()
        slot.tasks.add(task)
        acquired = False
        try:
            try:
                await asyncio.wait_for(slot.semaphore.acquire(), timeout=provider.queue_timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise ModelError("MODEL_BUSY", "Timed out waiting for the provider.", 429) from exc
            acquired = True
            slot.queued -= 1
            slot.model_queued[key] -= 1
            slot.active += 1
            slot.model_active[key] = slot.model_active.get(key, 0) + 1
            self._publish(key)
            yield slot
        finally:
            if acquired:
                slot.active -= 1
                slot.model_active[key] -= 1
                slot.semaphore.release()
            else:
                slot.queued -= 1
                slot.model_queued[key] -= 1
            slot.tasks.discard(task)
            self._publish(key)

    @asynccontextmanager
    async def _lease(self, profile: ModelProfile, *, autoload: bool = True, release: bool = True, require_runtime=True):
        key = self._key(profile)
        idle = self._idle.pop(key, None)
        if idle and idle is not asyncio.current_task():
            idle.cancel()
        try:
            async with self._provider_lease(self.backend_key(profile), key, profile, require_runtime) as slot:
                try:
                    if autoload:
                        async with self._load_locks.setdefault(key, asyncio.Lock()):
                            if self._statuses.get(key, ModelStatus()).state != "ready":
                                self._notify(profile, await slot.adapter.load(profile))
                    yield slot.adapter
                finally:
                    if release and slot.model_active[key] == 1 and not slot.model_queued[key] and not self._closed:
                        await self._release_policy(profile, slot.adapter)
        except ModelError as exc:
            if exc.code not in {"MODEL_BUSY", "UNLOAD_UNSUPPORTED"}:
                self._notify(profile, ModelStatus(state="failed", error_code=exc.code))
            raise

    async def _release_policy(self, profile, adapter):
        key = self._key(profile)
        if not self._statuses.get(key, ModelStatus()).unload_supported:
            return
        policies = [p.lifecycle for p in self.profiles.list() if p.enabled and self._key(p) == key]
        # A shared model stays resident if any enabled alias requests manual release.
        if any(p.unload == "manual" for p in policies):
            return
        idle_seconds = max((p.idle_seconds for p in policies if p.unload == "idle"), default=0)
        if idle_seconds:
            self._idle[key] = asyncio.create_task(self._idle_unload(profile, idle_seconds))
        else:
            try:
                self._notify(profile, await adapter.unload(profile))
            except ModelError as exc:
                self._notify(profile, ModelStatus(state="failed", error_code=exc.code))

    async def _idle_unload(self, profile, seconds):
        try:
            await asyncio.sleep(seconds)
            await self.unload(profile.id)
        except ModelError as exc:
            self._notify(profile, ModelStatus(state="failed", error_code=exc.code))
        finally:
            if self._idle.get(self._key(profile)) is asyncio.current_task():
                self._idle.pop(self._key(profile), None)

    async def health(self, profile_id: str) -> ModelStatus:
        profile = self.profile(profile_id)
        async with self._lease(profile, autoload=False, release=False) as adapter:
            result = await adapter.health(profile)
            self._notify(profile, result)
            return result

    async def load(self, profile_id: str) -> ModelStatus:
        profile = self.profile(profile_id)
        async with self._lease(profile, autoload=False, release=False) as adapter:
            result = await adapter.load(profile, explicit=True) if profile.runtime_id else await adapter.load(profile)
            self._notify(profile, result)
            return result

    async def unload(self, profile_id: str) -> ModelStatus:
        profile = self.profile(profile_id)
        slot = self._slots.get(self.backend_key(profile))
        if slot and (slot.active or slot.queued):
            raise ModelError("MODEL_BUSY", "Wait for active and queued requests before unloading.", 409)
        async with self._lease(profile, autoload=False, release=False, require_runtime=False) as adapter:
            result = await adapter.unload(profile)
            self._notify(profile, result)
            return result

    async def provider_models(self, provider_id: str) -> list[str]:
        async with self._provider_lease(provider_id) as slot:
            return await slot.adapter.models()

    def validate_chat(self, profile: ModelProfile, request: ChatRequest) -> None:
        caps = profile.capabilities
        required = {"streaming": request.stream,
                    "tools": bool(request.tools or any(m.tool_calls or m.role == "tool" for m in request.messages)),
                    "vision": any(isinstance(m.content, list) and any(isinstance(p, ImagePart) for p in m.content) for m in request.messages)}
        if request.response_format and request.response_format.type != "text":
            required[request.response_format.type] = True
        for capability, needed in required.items():
            if needed and not getattr(caps, capability):
                raise ModelError("UNSUPPORTED_CAPABILITY", f"Model profile does not support {capability}.", 422)

    async def chat(self, profile_id: str, request: ChatRequest):
        profile = self.profile(profile_id, "llm")
        self.validate_chat(profile, request)
        if request.stream:
            raise ModelError("INVALID_REQUEST", "Use chat_stream for a streaming request.")
        async with self._lease(profile) as adapter:
            return await adapter.chat(profile, request)

    async def chat_stream(self, profile_id: str, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        profile = self.profile(profile_id, "llm")
        self.validate_chat(profile, request)
        if not request.stream:
            raise ModelError("INVALID_REQUEST", "chat_stream requires stream=true.")
        async with self._lease(profile) as adapter:
            async with aclosing(adapter.chat_stream(profile, request)) as stream:
                async for chunk in stream:
                    yield chunk

    async def embed(self, profile_id: str, texts: list[str], *, purpose: str = "document", dimensions: int | None = None) -> EmbeddingResult:
        profile = self.profile(profile_id, "embedding")
        params = EmbeddingParameters.model_validate(profile.parameters)
        if purpose not in {"query", "document"} or not texts or any(not text.strip() for text in texts):
            raise ModelError("INVALID_REQUEST", "Embedding requires non-empty texts and query/document purpose.")
        if dimensions is not None and params.dimensions is not None and dimensions != params.dimensions:
            raise ModelError("EMBEDDING_DIMENSION_MISMATCH", "Requested dimensions differ from the model profile.", 422)
        dimension = dimensions or params.dimensions
        instruction = params.query_instruction if purpose == "query" else params.document_instruction
        prepared = [instruction + text for text in texts]
        vectors = []
        usage = None
        async with self._lease(profile) as adapter:
            for offset in range(0, len(prepared), params.batch_size):
                batch = prepared[offset:offset + params.batch_size]
                result = await adapter.embed(profile, batch, dimension)
                if len(result.vectors) != len(batch):
                    raise ModelError("PROVIDER_PROTOCOL_ERROR", "Embedding count does not match input.", 502)
                for vector in result.vectors:
                    dimension = dimension or len(vector)
                    if not vector or len(vector) != dimension or not all(math.isfinite(x) for x in vector):
                        raise ModelError("EMBEDDING_DIMENSION_MISMATCH", "Provider returned invalid embedding dimensions or values.", 502)
                    if params.normalize:
                        norm = math.sqrt(sum(x * x for x in vector))
                        if norm:
                            vector = [x / norm for x in vector]
                    vectors.append(vector)
                if result.usage:
                    if usage is None:
                        usage = result.usage.model_copy()
                    else:
                        usage.prompt_tokens += result.usage.prompt_tokens
                        usage.total_tokens += result.usage.total_tokens
        return EmbeddingResult(vectors=vectors, usage=usage)

    async def rerank(self, profile_id: str, query: str, documents: list[str]):
        profile = self.profile(profile_id, "reranker")
        async with self._lease(profile) as adapter:
            result = await adapter.rerank(profile, query, documents)
            if len(result.scores) != len(documents) or not all(math.isfinite(x) for x in result.scores):
                raise ModelError("PROVIDER_PROTOCOL_ERROR", "Reranker returned invalid scores.", 502)
            return result

    async def image_embed(self, profile_id: str, images: list[str]):
        profile = self.profile(profile_id, "image_embedding")
        if not images:
            raise ModelError("INVALID_REQUEST", "Image embedding requires at least one image.")
        async with self._lease(profile) as adapter:
            result = await adapter.image_embed(profile, images)
            dimension = profile.parameters.get("dimensions")
            if len(result.vectors) != len(images):
                raise ModelError("PROVIDER_PROTOCOL_ERROR", "Image embedding count did not match input.", 502)
            for vector in result.vectors:
                dimension = dimension or len(vector)
                if not vector or len(vector) != dimension or not all(math.isfinite(x) for x in vector):
                    raise ModelError("EMBEDDING_DIMENSION_MISMATCH", "Image embeddings have invalid dimensions or values.", 502)
                if profile.parameters.get("normalize", True):
                    norm = math.sqrt(sum(x * x for x in vector))
                    if norm:
                        vector[:] = [x / norm for x in vector]
            return result

    async def vision(self, profile_id: str, images: list[str]):
        profile = self.profile(profile_id, "vision")
        if not images:
            raise ModelError("INVALID_REQUEST", "Vision requires at least one image.")
        async with self._lease(profile) as adapter:
            return await adapter.vision(profile, images)

    def _managed_changed(self, backend):
        slot = self._slots.get(backend)
        if slot:
            for profile in self.profiles.list():
                if self.backend_key(profile) == backend:
                    self._notify(profile, slot.adapter.snapshot(profile))

    def runtime_changed(self, runtime_id, variant):
        for profile in self.profiles.list():
            if (profile.runtime_id, profile.runtime_variant) == (runtime_id, variant):
                self._publish(self._key(profile))

    def process_log(self, profile):
        slot = self._slots.get(self.backend_key(profile))
        path = getattr(slot.adapter, "log_path", None) if slot else None
        return path.read_text(encoding="utf-8", errors="replace") if path and path.is_file() else ""

    def require_runtime_idle(self, runtime_id, variant):
        for key in set(self._slots) | self._invalidating:
            if isinstance(key, tuple) and key[:2] == (runtime_id, variant):
                self.require_idle(key)

    async def invalidate_runtime(self, runtime_id, variant):
        self.require_runtime_idle(runtime_id, variant)
        for key in list(self._slots):
            if isinstance(key, tuple) and key[:2] == (runtime_id, variant):
                await self.invalidate(key)

    def require_idle(self, provider_id: str | None) -> None:
        slot = self._slots.get(provider_id)
        if provider_id in self._invalidating or slot and (slot.active or slot.queued):
            raise ModelError("MODEL_BUSY", "Wait for active and queued provider requests before editing.", 409)

    async def invalidate(self, provider_id: str | None) -> None:
        self.require_idle(provider_id)
        self._invalidating.add(provider_id)
        try:
            slot = self._slots.pop(provider_id, None)
            for key in set(self._statuses) | set(self._idle) | set(self._load_locks):
                if key[0] == provider_id:
                    self._statuses.pop(key, None)
                    self._load_locks.pop(key, None)
                    idle = self._idle.pop(key, None)
                    if idle:
                        idle.cancel()
            if slot:
                await slot.adapter.close()
        finally:
            self._invalidating.discard(provider_id)

    async def close(self) -> None:
        self._closed = True
        tasks = set(self._idle.values())
        for slot in self._slots.values():
            tasks.update(slot.tasks)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for slot in self._slots.values():
            await slot.adapter.close()
        self._slots.clear()
        self._idle.clear()
