from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field

from ai_workbench.core.models.adapter import InferenceAdapter, LocalAdapter, ProviderAdapter
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.images import prepare_image_embedding_inputs, prepare_local_images, prepare_tagging_images, validate_local_image_options
from ai_workbench.core.models.runtimes.schema import engine_options, is_transformers, local_engine
from ai_workbench.core.models.resolution import configure_profile, require_directory, resolve_profile
from ai_workbench.core.models.schema import (
    ChatChunk, ChatRequest, EmbeddingParameters, EmbeddingPurpose, EmbeddingResult,
    ImagePart, LocalSource, ProviderSource, ModelProfile, ModelStatus, ExternalConnection, SpeechRequest,
    ImageEmbeddingRequest, MAX_RERANK_BYTES, SiglipResult, SiglipTowers, Tower, VisionRequest, VisionResult,
    ASRParameters, TranscriptionRequest, TranscriptionResult, ImageProcessRequest, ImageOutput,
)
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.timing import current_trace, tracing


@dataclass
class InferenceSlot:
    adapter: InferenceAdapter
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
                 adapter_factory: Callable[[ExternalConnection], ProviderAdapter] = OpenAIAdapter,
                 runtime_supervisor=None):
        self.profiles = profiles
        self.providers = providers
        self.settings = settings
        self.events = events
        self.adapter_factory = adapter_factory
        self.runtime_supervisor = runtime_supervisor
        if runtime_supervisor:
            runtime_supervisor.manager = self
        self._slots: dict[tuple, InferenceSlot] = {}
        self._statuses: dict[tuple, ModelStatus] = {}
        self._idle: dict[tuple, asyncio.Task] = {}
        self._load_locks: dict[tuple, asyncio.Lock] = {}
        self._invalidating: set[tuple] = set()
        self._closed = False
        self._voice_references = None
        self._asr_inputs = None

    @property
    def asr_inputs(self):
        if self._asr_inputs is None:
            from ai_workbench.core.models.asr_inputs import ASRInputs
            self._asr_inputs = ASRInputs(self.runtime_supervisor.root)
        return self._asr_inputs

    @property
    def voice_references(self):
        if self._voice_references is None:
            from ai_workbench.core.models.voice_references import VoiceReferences
            if not self.runtime_supervisor:
                raise ModelError("RUNTIME_UNSUPPORTED", "Managed Audio is not configured.", 503)
            self._voice_references = VoiceReferences(self.runtime_supervisor.root)
        return self._voice_references

    def voice_binding(self, profile):
        configure_profile(self._resolve(profile))
        version = self.runtime_supervisor.release.version
        value = [profile.id, profile.model_ref, profile.source.type, local_engine(profile),
                 profile.source.execution_options, version]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _resolve(self, profile):
        if not isinstance(profile.source, LocalSource) or profile.kind not in {"llm", "tts", "vision"} or profile._directory is not None:
            return profile
        for slot in self._slots.values():
            if not (getattr(slot.adapter, "process", None) or getattr(slot.adapter, "failed", False) or slot.active or slot.queued):
                continue
            for info in getattr(slot.adapter, "directories", {}).values():
                if info.kind == profile.kind and info.model_ref == profile.model_ref:
                    profile._directory = info
                    return profile
        return resolve_profile(self.runtime_supervisor.root, profile) if self.runtime_supervisor else profile

    def profile(self, profile_id: str, kind: str | None = None) -> ModelProfile:
        try:
            profile = self.profiles.get(profile_id)
        except KeyError as exc:
            raise ModelError("MODEL_NOT_FOUND", "Model profile does not exist.", 404) from exc
        if kind and profile.kind != kind:
            raise ModelError("MODEL_KIND_MISMATCH", f"This operation requires a {kind} profile.")
        if not profile.enabled:
            raise ModelError("MODEL_UNAVAILABLE", "Model profile is disabled.", 503)
        return configure_profile(self._resolve(profile))

    def external_profile(self, alias: str, kind: str | None = None) -> ModelProfile:
        profile = self.profiles.find_by_alias(alias)
        if profile is None or not profile.enabled or not profile.external_enabled:
            raise ModelError("MODEL_NOT_FOUND", "Model alias is not available to the external service.", 404)
        return self.profile(profile.id, kind)

    def default_chat_profile(self) -> ModelProfile | None:
        profiles = [profile for profile in self.profiles.list("llm") if profile.enabled]
        default_id = self.settings.get().default_model_profile_id
        return next((profile for profile in profiles if profile.id == default_id),
                    profiles[0] if profiles else None)

    def execution_key(self, profile: ModelProfile):
        if profile.source is None:
            return ("unbound", getattr(profile, "id", "draft"))
        if isinstance(profile.source, ProviderSource):
            return ("provider", profile.source.provider_profile_id)
        engine = local_engine(self._resolve(profile))
        key = ("local", engine)
        if engine is None:
            return key + (getattr(profile, "id", "draft"),)
        options = {**engine_options(engine, profile.source.execution_options)().model_dump(), **profile.source.execution_options}
        if engine in {"chatterbox", "qwen3tts", "whisper", "wd14", "siglip2", "sentence-transformers", "cross-encoder", "dlss5nr"}:
            return key + (getattr(profile, "id", "draft"), profile.model_ref,
                          json.dumps(options, sort_keys=True, separators=(",", ":")))
        if engine in {"llama-server", "transformers"}:
            from ai_workbench.core.models.runtimes.schema import model_path
            reference = profile._directory.main_model_ref if engine == "llama-server" else profile.model_ref
            path = model_path(self.runtime_supervisor.root, reference or profile.model_ref)
            key += (options["device"], os.path.normcase(str(path)))
        if engine == "transformers":
            key += (json.dumps(options, sort_keys=True, separators=(",", ":")),)
        if engine == "llama-server":
            projector = profile._directory.mmproj_ref if profile.capabilities.vision else None
            key += (os.path.normcase(str(model_path(self.runtime_supervisor.root, projector))) if projector else None,)
        return key

    def _key(self, profile: ModelProfile) -> tuple:
        source_key = self.execution_key(profile)
        engine = local_engine(profile)
        return source_key, source_key if engine in {"llama-server", "transformers"} else profile.id if engine else profile.model_ref

    def validate_binding(self, profile):
        if isinstance(profile.source, ProviderSource):
            self.providers.get(profile.source.provider_profile_id)
        if isinstance(profile.source, LocalSource) and self.runtime_supervisor:
            configure_profile(resolve_profile(self.runtime_supervisor.root, profile))
        if local_engine(profile) == "llama-server":
            for alias in self.profiles.list("llm"):
                if alias.id != getattr(profile, "id", None) and self.execution_key(alias) == self.execution_key(profile) and configure_profile(alias).source.execution_options != profile.source.execution_options:
                    raise ModelError("MODEL_CONFLICT", "Aliases of a managed GGUF must use identical execution options.", 409)
        return profile

    def status(self, profile_id: str) -> ModelStatus:
        profile = self.profiles.get(profile_id)
        try:
            self._resolve(profile)
        except ModelError as exc:
            return ModelStatus(state="unavailable", error_code=exc.code, residency="unloaded", unload_supported=True)
        status = self._statuses.get(self._key(profile), ModelStatus()).model_copy()
        source = profile.source
        provider = next((p for p in self.providers.list() if isinstance(source, ProviderSource) and p.id == source.provider_profile_id), None)
        engine = local_engine(profile)
        if engine and self.runtime_supervisor:
            from ai_workbench.core.models.runtimes.schema import model_path, RuntimeStatus
            installation = self.runtime_supervisor.installation(check=False)
            slot = self._slots.get(self.execution_key(profile))
            status = slot.adapter.snapshot(profile) if slot else ModelStatus(state="unloaded", residency="unloaded", unload_supported=True)
            if not slot:
                status.runtime = RuntimeStatus(engine=engine, version=installation.version,
                    install_state=installation.state, job_id=installation.job_id, process_state="stopped")
                if engine == "siglip2":
                    status.towers = SiglipTowers()
            if engine == "dlss5nr":
                from ai_workbench.core.models.runtimes.schema import ComponentStatus
                component = self.runtime_supervisor.component(check=False)
                status.runtime.component = ComponentStatus.model_validate(component.model_dump(include=set(ComponentStatus.model_fields)))
            if installation.state != "installed":
                status.state = "unavailable"
                status.error_code = {"not_installed": "RUNTIME_NOT_INSTALLED", "installing": "RUNTIME_INSTALLING", "unsupported": "RUNTIME_UNSUPPORTED"}.get(installation.state, "RUNTIME_BROKEN")
            else:
                try:
                    path = model_path(self.runtime_supervisor.root, profile.model_ref)
                    require_directory(profile)
                    if engine == "dlss5nr":
                        from ai_workbench.core.models.runtimes.components import require_component
                        from ai_workbench.core.models.processing import processor_resource
                        require_component(component)
                        processor_resource(self.runtime_supervisor.root, profile.model_ref)
                    elif engine == "llama-server":
                        if not all(model_path(self.runtime_supervisor.root, ref).is_file() for ref in profile._directory.model_files):
                            raise ValueError()
                        projector = profile._directory.mmproj_ref if profile.capabilities.vision else None
                        if projector and not model_path(self.runtime_supervisor.root, projector).is_file():
                            raise ValueError()
                    elif engine in {"chatterbox", "qwen3tts"}:
                        from ai_workbench.workers.audio_catalog import audio_model
                        audio_model(self.runtime_supervisor.root / "data" / "models", profile.model_ref, engine)
                    elif engine == "siglip2":
                        from ai_workbench.workers.siglip_catalog import model_presence
                        model_presence(self.runtime_supervisor.root / "data/models", profile.model_ref)
                    elif engine in {"sentence-transformers", "cross-encoder", "whisper"}:
                        from ai_workbench.workers.embedding_catalog import package_path
                        package_path(self.runtime_supervisor.root / "data/models", profile.model_ref)
                    else:
                        from ai_workbench.workers.common import local_model
                        local_model(self.runtime_supervisor.root / "data" / "models", profile.model_ref,
                                    tts=engine == "kokoro", wd14=engine == "wd14")
                        if engine == "kokoro":
                            from ai_workbench.workers.tts_catalog import language_model
                            language_model(self.runtime_supervisor.root / "data" / "models")
                except (OSError, ValueError, WorkerError, ModelError) as exc:
                    status.state = "unavailable"
                    status.error_code = exc.code if isinstance(exc, (WorkerError, ModelError)) else "MODEL_NOT_FOUND"
        elif isinstance(source, LocalSource) and profile._directory is not None:
            status.state, status.residency, status.unload_supported = "unavailable", "unloaded", True
            try:
                require_directory(profile)
            except ModelError as exc:
                status.error_code = exc.code
        if source is None:
            status.state, status.error_code = "unavailable", "MODEL_NOT_CONFIGURED"
        elif not profile.enabled or (isinstance(source, ProviderSource) and (provider is None or not provider.enabled)) or (
            isinstance(source, LocalSource) and self.runtime_supervisor and not self.runtime_supervisor.settings.get().enabled
        ):
            status.state = "unavailable"
            status.error_code = "MODEL_UNAVAILABLE"
        slot = self._slots.get(self.execution_key(profile))
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

    def _slot(self, execution_key, profile=None, require_runtime=True):
        if self._closed:
            raise ModelError("MODEL_UNAVAILABLE", "Model manager is shutting down.", 503)
        if execution_key in self._invalidating or execution_key[0] == "local" and ("local",) in self._invalidating:
            raise ModelError("MODEL_BUSY", "Model source configuration is changing.", 409)
        if execution_key[0] == "local":
            supervisor = self.runtime_supervisor
            if not supervisor.settings.get().enabled:
                raise ModelError("MODEL_UNAVAILABLE", "The local runtime is disabled.", 503)
            if supervisor.blocked:
                raise ModelError("RUNTIME_INSTALLING", "Local runtime maintenance is in progress.", 409)
            if require_runtime:
                supervisor.assert_available(check=False)
                if local_engine(profile) == "dlss5nr":
                    from ai_workbench.core.models.runtimes.components import require_component
                    require_component(supervisor.component(check=False))
            limits = ManagedQueue(queue_timeout_seconds=120) if local_engine(profile) == "siglip2" else ManagedQueue()
            return limits, self._managed_slot(profile)
        try:
            provider = self.providers.get(execution_key[1])
        except KeyError as exc:
            raise ModelError("MODEL_UNAVAILABLE", "The configured provider does not exist.", 503) from exc
        if not provider.enabled:
            raise ModelError("MODEL_UNAVAILABLE", "Provider is disabled.", 503)
        if execution_key not in self._slots:
            self._slots[execution_key] = InferenceSlot(self.adapter_factory(provider.connection), asyncio.Semaphore(provider.connection.concurrency))
        return provider.connection, self._slots[execution_key]

    def _managed_slot(self, profile):
        configure_profile(self._resolve(profile))
        if local_engine(profile) is None:
            require_directory(profile)
            raise ModelError("RUNTIME_UNSUPPORTED", "No local engine was identified for this model directory.", 503)
        key = self.execution_key(profile)
        if key not in self._slots:
            from ai_workbench.core.models.runtimes.adapters import ASRWorkerAdapter, AudioWorkerAdapter, EmbeddingWorkerAdapter, LlamaServerAdapter, ProcessorWorkerAdapter, PythonWorkerAdapter, RerankerWorkerAdapter, TransformersServerAdapter
            from ai_workbench.core.models.siglip_adapter import SiglipAdapter
            engine = local_engine(profile)
            cls = ProcessorWorkerAdapter if engine == "dlss5nr" else SiglipAdapter if engine == "siglip2" else EmbeddingWorkerAdapter if engine == "sentence-transformers" else RerankerWorkerAdapter if engine == "cross-encoder" else ASRWorkerAdapter if engine == "whisper" else AudioWorkerAdapter if engine in {"chatterbox", "qwen3tts"} else TransformersServerAdapter if engine == "transformers" else LlamaServerAdapter if engine == "llama-server" else PythonWorkerAdapter
            adapter: LocalAdapter = cls(self.runtime_supervisor, profile, lambda: self._managed_changed(key))
            self._slots[key] = InferenceSlot(adapter, asyncio.Semaphore(1))
        return self._slots[key]

    @asynccontextmanager
    async def _execution_lease(self, execution_key, key: tuple | None = None, profile=None, require_runtime=True, on_admit=None):
        trace = current_trace()
        queue = trace.start_stage("queue_wait") if trace else None
        task = asyncio.current_task()
        slot = None
        registered = False
        acquired = False
        try:
            limits, slot = self._slot(execution_key, profile, require_runtime)
            if slot.active + slot.queued >= limits.concurrency + limits.queue_size:
                raise ModelError("MODEL_BUSY", "Model source queue is full.", 429)
            if on_admit:
                on_admit()
            slot.queued += 1
            slot.model_queued[key] = slot.model_queued.get(key, 0) + 1
            slot.tasks.add(task)
            registered = True
            self._publish(key)
            try:
                await asyncio.wait_for(slot.semaphore.acquire(), timeout=limits.queue_timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise ModelError("MODEL_BUSY", "Timed out waiting for model source admission.", 429) from exc
            acquired = True
            slot.queued -= 1
            slot.model_queued[key] -= 1
            slot.active += 1
            slot.model_active[key] = slot.model_active.get(key, 0) + 1
            self._publish(key)
            if queue:
                queue.finish()
            yield slot
        except BaseException as exc:
            if queue:
                queue.finish(exc)
            raise
        finally:
            if registered:
                try:
                    if (profile is not None and profile.kind == "image_embedding" and not self._closed
                            and ((acquired and slot.active == 1 and slot.queued == 0)
                                 or (not acquired and slot.active == 0 and slot.queued == 1))):
                        # A cancelled last waiter can drain the queue after the active
                        # request finished. Keep teardown serialized with new admission.
                        if not acquired:
                            await slot.semaphore.acquire()
                        try:
                            await self._release_policy(profile, slot.adapter)
                        finally:
                            if not acquired:
                                slot.semaphore.release()
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
    async def _lease(self, profile: ModelProfile, *, autoload: bool = True, release: bool = True, require_runtime=True, on_admit=None, load_trigger=None, tower: Tower | None = None):
        if profile.source is None:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select a local runtime or provider for this model.", 503)
        local = isinstance(profile.source, LocalSource)
        siglip = local_engine(profile) == "siglip2"
        executing = False
        key = self._key(profile)
        trace = None
        if local and self.runtime_supervisor and not self._closed and (
            load_trigger or autoload and (not self._managed_slot(profile).adapter.ready(tower) if siglip
                                         else self._statuses.get(key, ModelStatus()).state != "ready")
        ):
            adapter = self._managed_slot(profile).adapter
            trace = adapter.begin_trace(profile, load_trigger or "autoload", tower=tower) if siglip else adapter.begin_trace(profile, load_trigger or "autoload")
        def admitted():
            if on_admit:
                on_admit()
            if not siglip:
                self._cancel_idle(key)
        with tracing(trace):
            try:
                async with self._execution_lease(self.execution_key(profile), key, profile, require_runtime, admitted) as slot:
                    try:
                        if siglip and load_trigger != "health":
                            self._cancel_idle(key)
                        if local and autoload:
                            if siglip:
                                self._notify(profile, await slot.adapter.load(profile, tower=tower))
                            else:
                                async with self._load_locks.setdefault(key, asyncio.Lock()):
                                    if self._statuses.get(key, ModelStatus()).state != "ready":
                                        self._notify(profile, await slot.adapter.load(profile))
                                        if trace:
                                            trace.finish()
                                    elif trace:
                                        trace.reused.update(process_reused=True, model_reused=True)
                                        trace.finish()
                        executing = True
                        yield slot.adapter
                        if not local:
                            self._notify(profile, ModelStatus(state="ready"))
                    finally:
                        if siglip and release and executing:
                            self._siglip_activity(profile, slot.adapter, inference=True)
                        elif local and not siglip and release and slot.model_active[key] == 1 and not slot.model_queued[key] and not self._closed:
                            await self._release_policy(profile, slot.adapter)
            except ModelError as exc:
                if (local and not siglip and exc.code not in {"MODEL_BUSY", "UNLOAD_UNSUPPORTED", "INVALID_AUDIO", "AUDIO_TOO_LONG", "AUDIO_TOO_LARGE"}) or (
                    not local and executing and exc.code in {"MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "PROVIDER_ERROR", "PROVIDER_PROTOCOL_ERROR", "MODEL_REFUSAL", "EMBEDDING_DIMENSION_MISMATCH"}
                ):
                    self._notify(profile, ModelStatus(state="failed", error_code=exc.code))
                raise

    def _cancel_idle(self, key):
        idle = self._idle.pop(key, None)
        if idle and idle is not asyncio.current_task():
            idle.cancel()

    @staticmethod
    def _siglip_activity(profile, adapter, *, inference=False):
        if inference:
            adapter.release_pending = True
        if profile.source.lifecycle.unload == "idle":
            adapter.idle_deadline = asyncio.get_running_loop().time() + profile.source.lifecycle.idle_seconds

    async def _release_policy(self, profile, adapter):
        key = self._key(profile)
        if profile.kind == "image_embedding":
            self._cancel_idle(key)
            if not any(getattr(adapter.towers, tower).residency == "loaded" for tower in ("image", "text")):
                adapter.release_pending = False
                adapter.idle_deadline = None
                return
            policy = profile.source.lifecycle
            if policy.unload == "manual" or policy.unload == "after_request" and not adapter.release_pending:
                return
            if policy.unload == "idle":
                if adapter.idle_deadline is None:
                    return
                remaining = adapter.idle_deadline - asyncio.get_running_loop().time()
                if remaining > 0:
                    self._idle[key] = asyncio.create_task(self._idle_unload(profile, remaining))
                    return
            try:
                self._notify(profile, await adapter.unload(profile))
            except ModelError as exc:
                self._notify(profile, ModelStatus(state="failed", error_code=exc.code))
            return
        if not self._statuses.get(key, ModelStatus()).unload_supported:
            return
        policies = [p.source.lifecycle for p in self.profiles.list() if p.enabled and self._key(p) == key]
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
            if profile.kind != "image_embedding" or exc.code != "MODEL_BUSY":
                self._notify(profile, ModelStatus(state="failed", error_code=exc.code))
        finally:
            if self._idle.get(self._key(profile)) is asyncio.current_task():
                self._idle.pop(self._key(profile), None)

    async def health(self, profile_id: str) -> ModelStatus:
        profile = self.profile(profile_id)
        self.require_local(profile)
        async with self._lease(profile, autoload=False, release=False, load_trigger="health") as adapter:
            result = await adapter.health(profile)
            self._notify(profile, result)
        return self.status(profile_id) if profile.kind == "image_embedding" else result

    async def load(self, profile_id: str, *, tower: Tower | None = None) -> ModelStatus:
        profile = self.profile(profile_id)
        self.require_local(profile)
        self.validate_tower(profile, tower)
        async with self._lease(profile, autoload=False, release=False, load_trigger="explicit", tower=tower) as adapter:
            if profile.kind == "image_embedding":
                result = await adapter.load(profile, explicit=True, tower=tower)
                self._siglip_activity(profile, adapter)
            else:
                result = await adapter.load(profile, explicit=True)
            self._notify(profile, result)
        return self.status(profile_id) if profile.kind == "image_embedding" else result

    @staticmethod
    def validate_tower(profile, tower):
        if (profile.kind == "image_embedding" and tower not in {"image", "text"}
                or profile.kind != "image_embedding" and tower is not None):
            raise ModelError("INVALID_REQUEST", "Specify image or text only for an image_embedding profile.", 422)

    async def unload(self, profile_id: str) -> ModelStatus:
        profile = self.profile(profile_id)
        self.require_local(profile)
        slot = self._slots.get(self.execution_key(profile))
        if slot and (slot.active or slot.queued):
            raise ModelError("MODEL_BUSY", "Wait for active and queued requests before unloading.", 409)
        async with self._lease(profile, autoload=False, release=False, require_runtime=False) as adapter:
            result = await adapter.unload(profile)
            self._notify(profile, result)
            return result

    @staticmethod
    def require_local(profile):
        if profile.source is None:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select a local runtime or provider for this model.", 503)
        if not isinstance(profile.source, LocalSource):
            raise ModelError("UNSUPPORTED_CAPABILITY", "This operation requires a local model.", 422)

    async def provider_models(self, provider_id: str) -> list[str]:
        self.providers.get(provider_id)
        async with self._execution_lease(("provider", provider_id)) as slot:
            return await slot.adapter.models()

    async def prepare_chat_stream(self, profile_id: str, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Resolve source admission and local startup before SSE headers."""
        profile = self.profile(profile_id, "llm")
        request = await self._prepare_chat(profile, request)
        if isinstance(profile.source, LocalSource):
            await self.load(profile_id)
        elif profile.source is None:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select a local runtime or provider for this model.", 503)
        else:
            async with self._execution_lease(self.execution_key(profile), self._key(profile), profile):
                pass
        return self._chat_stream(profile, request)

    def validate_chat(self, profile: ModelProfile, request: ChatRequest) -> None:
        if is_transformers(profile) and (
            any(getattr(request, name) not in (None, 0) for name in ("presence_penalty", "frequency_penalty"))
            or request.tool_choice not in (None, "auto") or request.parallel_tool_calls is not None
        ):
            raise ModelError("UNSUPPORTED_CAPABILITY", "Transformers does not support penalties or explicit tool-call controls.", 422)
        caps = profile.capabilities
        required = {"streaming": request.stream,
                    "tools": bool(request.tools or any(m.tool_calls or m.role == "tool" for m in request.messages)),
                    "vision": any(isinstance(m.content, list) and any(isinstance(p, ImagePart) for p in m.content) for m in request.messages)}
        if request.response_format and request.response_format.type != "text":
            required[request.response_format.type] = True
        for capability, needed in required.items():
            if needed and not getattr(caps, capability):
                raise ModelError("UNSUPPORTED_CAPABILITY", f"Model profile does not support {capability}.", 422)
        if isinstance(profile.source, LocalSource):
            validate_local_image_options(request)

    async def _prepare_chat(self, profile, request):
        self.validate_chat(profile, request)
        if isinstance(profile.source, LocalSource):
            return await asyncio.to_thread(prepare_local_images, profile, request)
        return request

    async def chat(self, profile_id: str, request: ChatRequest):
        profile = self.profile(profile_id, "llm")
        if request.stream:
            raise ModelError("INVALID_REQUEST", "Use chat_stream for a streaming request.")
        request = await self._prepare_chat(profile, request)
        async with self._lease(profile) as adapter:
            return await adapter.chat(profile, request)

    async def chat_stream(self, profile_id: str, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        profile = self.profile(profile_id, "llm")
        if not request.stream:
            raise ModelError("INVALID_REQUEST", "chat_stream requires stream=true.")
        request = await self._prepare_chat(profile, request)
        async with aclosing(self._chat_stream(profile, request)) as stream:
            async for chunk in stream:
                yield chunk

    async def _chat_stream(self, profile, request):
        async with self._lease(profile) as adapter:
            async with aclosing(adapter.chat_stream(profile, request)) as stream:
                async for chunk in stream:
                    yield chunk

    async def embed(self, profile_id: str, texts: list[str], *, purpose: EmbeddingPurpose = "document", dimensions: int | None = None) -> EmbeddingResult:
        profile = self.profile(profile_id, "embedding")
        local = isinstance(profile.source, LocalSource)
        params = None if local else EmbeddingParameters.model_validate(profile.parameters)
        if purpose not in ("query", "document") or not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ModelError("INVALID_REQUEST", "Embedding requires non-empty texts and query/document purpose.")
        if dimensions is not None and (type(dimensions) is not int or not 1 <= dimensions <= 65536):
            raise ModelError("INVALID_REQUEST", "Embedding dimensions must be a positive integer up to 65536.", 422)
        if params and dimensions is not None and params.dimensions is not None and dimensions != params.dimensions:
            raise ModelError("EMBEDDING_DIMENSION_MISMATCH", "Requested dimensions differ from the model profile.", 422)
        dimension = dimensions or (params.dimensions if params else None)
        batch_size = profile.source.execution_options["max_batch_size"] if local else params.batch_size
        vectors = []
        usage = None
        similarity = "dot"
        async with self._lease(profile) as adapter:
            for offset in range(0, len(texts), batch_size):
                batch = texts[offset:offset + batch_size]
                result = await adapter.embed(profile, batch, dimension, purpose=purpose)
                similarity = result.similarity
                if len(result.vectors) != len(batch):
                    raise ModelError("PROVIDER_PROTOCOL_ERROR", "Embedding count does not match input.", 502)
                for vector in result.vectors:
                    dimension = dimension or len(vector)
                    if not vector or len(vector) != dimension or not all(math.isfinite(x) for x in vector):
                        raise ModelError("EMBEDDING_DIMENSION_MISMATCH", "The model returned invalid embedding dimensions or values.", 502)
                    if params and params.normalize:
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
        return EmbeddingResult(vectors=vectors, usage=usage, similarity=similarity)

    async def rerank(self, profile_id: str, query: str, documents: list[str]):
        profile = self.profile(profile_id, "reranker")
        size = await asyncio.to_thread(lambda: len(json.dumps(
            {"profile_id": profile.id, "query": query, "documents": documents},
            ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")))
        if size > MAX_RERANK_BYTES:
            raise ModelError("REQUEST_TOO_LARGE", "The private rerank request exceeds 32 MiB.", 413)
        async with self._lease(profile) as adapter:
            return await adapter.rerank(profile, query, documents)

    async def image_embed(self, profile_id: str, request: ImageEmbeddingRequest) -> SiglipResult:
        profile = self.profile(profile_id, "image_embedding")
        self.require_local(profile)
        inputs = [request.input] if isinstance(request.input, str) else request.input
        prepared = await asyncio.to_thread(prepare_image_embedding_inputs, request.input_type, inputs)
        async with self._lease(profile, tower=request.input_type) as adapter:
            return await adapter.image_embed(profile, request.input_type, prepared)

    async def vision(self, profile_id: str, request: VisionRequest) -> VisionResult:
        profile = self.profile(profile_id, "vision")
        if profile.source is None:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select the local runtime for this model.", 503)
        thresholds = {**profile.parameters["thresholds"],
                      **(request.thresholds.model_dump(exclude_none=True) if request.thresholds else {})}
        images = await asyncio.to_thread(prepare_tagging_images, profile.id, request.images, thresholds)
        async with self._lease(profile) as adapter:
            return await adapter.vision(profile, images, thresholds)

    async def process_image(self, profile_id: str, data: bytes, request: ImageProcessRequest) -> ImageOutput:
        from ai_workbench.core.models.processing import prepare_process_image
        profile = self.profile(profile_id, "processor")
        image = await asyncio.to_thread(prepare_process_image, data)
        options = {**profile.parameters, **request.model_dump(exclude_none=True)}
        options.pop("task")
        async with self._lease(profile) as adapter:
            return await adapter.process_image(profile, image, options)

    async def transcribe(self, profile_id: str, data: bytes, audio_format: str,
                         request: TranscriptionRequest) -> TranscriptionResult:
        profile = self.profile(profile_id, "asr")
        self.require_local(profile)
        if not isinstance(data, bytes) or not data or audio_format not in {"wav", "mp3"}:
            raise ModelError("INVALID_AUDIO", "Provide a nonempty WAV or MP3 file.", 422)
        options = ASRParameters.model_validate({**profile.parameters,
            **request.model_dump(exclude_none=True, exclude={"timestamp_granularities"})})
        if request.timestamp_granularities is not None and options.response_format != "verbose_json":
            raise ModelError("INVALID_REQUEST", "Segment timestamps require verbose_json.", 422)
        async with self._lease(profile) as adapter:
            async with self.asr_inputs.stage(data, audio_format) as reference:
                return await adapter.transcribe(profile, reference, options)

    def voice_list(self, profile_id: str) -> list[dict]:
        from ai_workbench.workers.tts_catalog import voices
        from ai_workbench.core.models.runtimes.schema import model_path
        profile = self._resolve(self.profiles.get(profile_id))
        if profile.kind != "tts":
            raise ModelError("MODEL_KIND_MISMATCH", "Voice discovery requires a tts profile.")
        if local_engine(profile) != "kokoro":
            return []
        path = None
        if self.runtime_supervisor:
            try:
                path = model_path(self.runtime_supervisor.root, profile.model_ref)
            except ValueError:
                pass
        return [{**voice, "model": profile.alias} for voice in voices(path)]

    async def speech(self, profile_id: str, request: SpeechRequest, *, credential=None):
        from ai_workbench.workers.tts_catalog import LANGUAGES, VOICE_IDS, valid_voice
        from ai_workbench.core.models.runtimes.schema import model_path
        from ai_workbench.workers.audio import validate_audio
        profile = self.profile(profile_id, "tts")
        require_directory(profile)
        if local_engine(profile) in {"chatterbox", "qwen3tts"}:
            return await self._reference_speech(profile, request, credential)
        if request.tts.reference_audio is not None or request.tts.model_options is not None:
            raise ModelError("INVALID_REQUEST", "Reference audio and model_options require Chatterbox or Qwen3-TTS Base.")
        if request.voice not in VOICE_IDS:
            raise ModelError("VOICE_UNAVAILABLE", "Voice ID is not supported by this model.", 404)
        if request.tts.language is not None and request.tts.language != LANGUAGES[request.voice[0]]:
            raise ModelError("INVALID_REQUEST", "Language does not match the selected voice.")
        if isinstance(profile.source, LocalSource) and self.runtime_supervisor:
            try:
                path = model_path(self.runtime_supervisor.root, profile.model_ref)
            except (OSError, ValueError) as exc:
                raise ModelError("MODEL_NOT_FOUND", "The local model directory is missing or outside data/models.", 404) from exc
            if not await asyncio.to_thread(valid_voice, path, request.voice):
                raise ModelError("VOICE_UNAVAILABLE", "The local voice file is missing or invalid.", 404)
        response_format = request.response_format or profile.parameters["response_format"]
        speed = request.speed if request.speed is not None else profile.parameters["speed"]
        async with self._lease(profile) as adapter:
            result = await adapter.speech(profile, request.input, request.voice, speed, response_format, request.tts.language)
            try:
                if result.response_format != response_format:
                    raise ValueError("Unexpected audio format")
                validate_audio(result.data, response_format)
            except (ValueError, EOFError) as exc:
                raise ModelError("PROVIDER_PROTOCOL_ERROR", "Worker returned invalid audio.", 502) from exc
            return result

    def _voice_credential(self, credential):
        from ai_workbench.core.models.voice_references import credential_id
        settings = self.settings.get()
        if credential is not None and not settings.external_enabled:
            raise ModelError("SERVICE_DISABLED", "The inference service is disabled.", 503)
        current = credential_id(settings.external_api_key)
        if credential is not None and credential != current:
            raise ModelError("AUTH_INVALID", "The inference credential has changed.", 401)
        return current

    def _reference_profile(self, profile_id):
        profile = self.profile(profile_id, "tts")
        require_directory(profile)
        if local_engine(profile) not in {"chatterbox", "qwen3tts"}:
            raise ModelError("UNSUPPORTED_CAPABILITY", "Reference audio requires a managed Chatterbox or Qwen3-TTS Base profile.")
        return profile

    async def _validate_reference(self, profile, entry):
        async with self._lease(profile, autoload=False, load_trigger="reference") as adapter:
            return await adapter.validate_reference(profile, entry.path.name)

    async def _stage_reference(self, data, audio_format, reference_text=None):
        references = self.voice_references
        task = asyncio.create_task(asyncio.to_thread(references.stage, data, audio_format, reference_text))
        try:
            entry = await asyncio.shield(task)
        except asyncio.CancelledError:
            # A file write cannot be interrupted. Finish it before dropping its lease.
            try:
                entry = await task
            except Exception:
                pass
            else:
                await asyncio.to_thread(references.release, entry)
            raise
        if self._closed:
            await asyncio.to_thread(references.release, entry)
            raise ModelError("MODEL_UNAVAILABLE", "Model services are shutting down.", 503)
        return entry

    def _voice_admission(self, profile, binding, credential):
        self._voice_credential(credential)
        current = self._reference_profile(profile.id)
        if self.voice_binding(current) != binding or not current.external_enabled:
            raise ModelError("VOICE_UNAVAILABLE", "The model binding changed before admission.", 404)

    async def create_voice_reference(self, profile_id, data, audio_format, credential, *, reference_text=None):
        from ai_workbench.core.time import isoformat_utc
        from pydantic import ValidationError
        from ai_workbench.core.models.schema import ReferenceTranscript
        profile = self._reference_profile(profile_id)
        try:
            ReferenceTranscript(reference_text=reference_text)
        except ValidationError as exc:
            raise ModelError("INVALID_REQUEST", "Reference transcript must contain 1 to 4096 nonblank characters.") from exc
        if reference_text is not None and local_engine(profile) != "qwen3tts":
            raise ModelError("INVALID_REQUEST", "Reference transcripts require Qwen3-TTS Base.")
        credential = self._voice_credential(credential)
        binding = self.voice_binding(profile)
        entry = await self._stage_reference(data, audio_format, reference_text)
        published = False
        try:
            await self._validate_reference(profile, entry)
            self._voice_admission(profile, binding, credential)
            self.voice_references.publish(entry, profile.id, binding, credential)
            published = True
            return {"voice_id": entry.id, "model": profile.alias, "source": "temporary", "expires_at": isoformat_utc(entry.expires_at)}
        finally:
            if not published:
                await asyncio.to_thread(self.voice_references.release, entry)

    def temporary_voice_list(self, profile_id, credential):
        profile = self.profile(profile_id, "tts")
        credential = self._voice_credential(credential)
        if self._voice_references is None or local_engine(profile) not in {"chatterbox", "qwen3tts"}:
            return []
        language = None if local_engine(profile) == "qwen3tts" else "en-US"
        return [{**item, "model": profile.alias} for item in self._voice_references.list(
            profile.id, self.voice_binding(profile), credential, language=language)]

    def delete_voice_reference(self, identifier, credential):
        credential = self._voice_credential(credential)
        if self._voice_references is not None:
            for profile in self.profiles.list("tts"):
                self._resolve(profile)
                if not profile.enabled or not profile.external_enabled or local_engine(profile) not in {"chatterbox", "qwen3tts"}:
                    continue
                try:
                    self._voice_references.delete(identifier, profile.id, self.voice_binding(profile), credential)
                    return {"deleted": True, "voice_id": identifier}
                except ModelError as exc:
                    if exc.code != "VOICE_UNAVAILABLE":
                        raise
        raise ModelError("VOICE_UNAVAILABLE", "Voice ID is unavailable for this credential.", 404)

    def invalidate_voice_references(self, profile_id=None):
        if self._voice_references:
            self._voice_references.invalidate(profile_id)

    async def _reference_speech(self, profile, request, credential):
        from pydantic import ValidationError
        from ai_workbench.core.models.schema import AUDIO_REQUEST_OPTIONS
        from ai_workbench.workers.audio import validate_audio
        from ai_workbench.workers.audio_catalog import AUDIO_DEFAULTS, QWEN3TTS_LANGUAGES
        self._reference_profile(profile.id)
        credential = self._voice_credential(credential)
        architecture = local_engine(profile)
        languages = QWEN3TTS_LANGUAGES if architecture == "qwen3tts" else {"en-US"}
        if request.tts.language is not None and request.tts.language not in languages:
            raise ModelError("INVALID_REQUEST", "The selected TTS architecture does not support this language.")
        reference = request.tts.reference_audio
        if reference is not None and "reference_text" in reference.model_fields_set and architecture != "qwen3tts":
            raise ModelError("INVALID_REQUEST", "Reference transcripts require Qwen3-TTS Base.")
        options = {key: value for key, value in profile.parameters.items() if key in AUDIO_DEFAULTS[architecture]}
        if request.tts.model_options is not None:
            try:
                overrides = AUDIO_REQUEST_OPTIONS[architecture].model_validate(request.tts.model_options.model_dump(exclude_unset=True))
            except ValidationError as exc:
                raise ModelError("INVALID_REQUEST", "model_options do not match the selected TTS architecture.") from exc
            options.update(overrides.model_dump(exclude_none=True))
        binding = self.voice_binding(profile)
        entry = None
        staged = request.tts.reference_audio is not None
        if staged:
            entry = await self._stage_reference(base64.b64decode(reference.data_base64, validate=True), reference.format, reference.reference_text)
        else:
            self.voice_references.check(request.voice, profile.id, binding, credential)
        def admitted():
            nonlocal entry
            self._voice_admission(profile, binding, credential)
            if not staged:
                entry = self.voice_references.admit(request.voice, profile.id, binding, credential)
        try:
            if staged:
                await self._validate_reference(profile, entry)
            speed = request.speed if request.speed is not None else profile.parameters["speed"]
            response_format = request.response_format or profile.parameters["response_format"]
            async with self._lease(profile, on_admit=admitted) as adapter:
                result = await adapter.speech(profile, request.input, request.voice, speed, response_format, request.tts.language,
                    reference=entry.path.name, reference_text=entry.reference_text, model_options=options)
                try:
                    if result.response_format != response_format:
                        raise ValueError("Unexpected audio format")
                    validate_audio(result.data, response_format)
                except ValueError as exc:
                    raise ModelError("PROVIDER_PROTOCOL_ERROR", "Worker returned invalid audio.", 502) from exc
                return result
        finally:
            if entry is not None:
                await asyncio.to_thread(self.voice_references.release, entry)

    def _managed_changed(self, source_key):
        slot = self._slots.get(source_key)
        if slot:
            for profile in self.profiles.list():
                if self.execution_key(profile) == source_key:
                    self._notify(profile, slot.adapter.snapshot(profile))

    def runtime_changed(self):
        for profile in self.profiles.list():
            if isinstance(profile.source, LocalSource):
                self._publish(self._key(profile))

    def process_log(self, profile, *, tower: Tower | None = None):
        self.require_local(profile)
        self.validate_tower(profile, tower)
        slot = self._slots.get(self.execution_key(profile))
        path = getattr(slot.adapter, "log_path", None) if slot else None
        if slot:
            path = getattr(slot.adapter, "log_paths", {}).get(tower if profile.kind == "image_embedding" else profile.id, path)
        try:
            return path.read_text(encoding="utf-8", errors="replace") if path and path.is_file() else ""
        except OSError:
            return ""

    def require_local_idle(self):
        self.require_idle(("local",))
        for key in set(self._slots) | self._invalidating:
            if isinstance(key, tuple) and key[0] == "local":
                self.require_idle(key)

    async def invalidate_local(self):
        self.require_local_idle()
        self._invalidating.add(("local",))
        try:
            self.invalidate_voice_references()
            for key in list(self._slots):
                if isinstance(key, tuple) and key[0] == "local":
                    await self.invalidate(key)
        finally:
            self._invalidating.discard(("local",))

    def require_idle(self, source_key: tuple) -> None:
        slot = self._slots.get(source_key)
        if source_key in self._invalidating or slot and (slot.active or slot.queued):
            raise ModelError("MODEL_BUSY", "Wait for active and queued model requests before editing.", 409)

    async def invalidate(self, source_key: tuple) -> None:
        self.require_idle(source_key)
        self._invalidating.add(source_key)
        try:
            slot = self._slots.pop(source_key, None)
            for key in set(self._statuses) | set(self._idle) | set(self._load_locks):
                if key[0] == source_key:
                    self._statuses.pop(key, None)
                    self._load_locks.pop(key, None)
                    idle = self._idle.pop(key, None)
                    if idle:
                        idle.cancel()
            if slot:
                await slot.adapter.close()
        finally:
            self._invalidating.discard(source_key)

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
        if self._voice_references:
            await asyncio.to_thread(self._voice_references.close)
        if self._asr_inputs:
            await asyncio.to_thread(self._asr_inputs.close)
