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
from ai_workbench.core.models.images import prepare_local_images, validate_local_image_options
from ai_workbench.core.models.runtimes.schema import is_transformers, local_engine
from ai_workbench.core.models.schema import (
    ChatChunk, ChatRequest, EmbeddingParameters, EmbeddingResult,
    ImagePart, LocalSource, ProviderSource, ModelProfile, ModelStatus, ExternalConnection, SpeechRequest,
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

    @property
    def voice_references(self):
        if self._voice_references is None:
            from ai_workbench.core.models.voice_references import VoiceReferences
            if not self.runtime_supervisor:
                raise ModelError("RUNTIME_UNSUPPORTED", "Managed Audio is not configured.", 503)
            self._voice_references = VoiceReferences(self.runtime_supervisor.root)
        return self._voice_references

    def voice_binding(self, profile):
        version = self.runtime_supervisor.release.version
        value = [profile.id, profile.model_ref, profile.source.type, local_engine(profile),
                 profile.parameters["architecture"], profile.source.execution_options, version]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

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
        engine = local_engine(profile)
        key = ("local", engine)
        if engine in {"chatterbox", "qwen3tts", "whisper"}:
            return key + (getattr(profile, "id", "draft"), profile.model_ref,
                          json.dumps(profile.source.execution_options, sort_keys=True, separators=(",", ":")))
        if engine in {"llama-server", "transformers"}:
            path = self.runtime_supervisor.root / "data" / "models" / profile.model_ref
            key += (profile.source.execution_options["device"], os.path.normcase(str(path)))
        if engine == "transformers":
            key += (json.dumps(profile.source.execution_options, sort_keys=True, separators=(",", ":")),)
        if engine == "llama-server":
            projector = profile.source.execution_options["mmproj_ref"]
            key += (os.path.normcase(str(self.runtime_supervisor.root / "data" / "models" / projector)) if projector else None,)
        return key

    def _key(self, profile: ModelProfile) -> tuple:
        source_key = self.execution_key(profile)
        engine = local_engine(profile)
        return source_key, source_key if engine in {"llama-server", "transformers"} else profile.id if engine else profile.model_ref

    def validate_binding(self, profile):
        if isinstance(profile.source, ProviderSource):
            self.providers.get(profile.source.provider_profile_id)
        if local_engine(profile) == "llama-server":
            for alias in self.profiles.list("llm"):
                if alias.id != getattr(profile, "id", None) and self.execution_key(alias) == self.execution_key(profile) and alias.source.execution_options != profile.source.execution_options:
                    raise ModelError("MODEL_CONFLICT", "Aliases of a managed GGUF must use identical execution options.", 409)

    def status(self, profile_id: str) -> ModelStatus:
        profile = self.profiles.get(profile_id)
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
            if installation.state != "installed":
                status.state = "unavailable"
                status.error_code = {"not_installed": "RUNTIME_NOT_INSTALLED", "installing": "RUNTIME_INSTALLING", "unsupported": "RUNTIME_UNSUPPORTED"}.get(installation.state, "RUNTIME_BROKEN")
            else:
                try:
                    path = model_path(self.runtime_supervisor.root, profile.model_ref)
                    if engine == "llama-server":
                        if not path.is_file():
                            raise ValueError()
                        projector = profile.source.execution_options["mmproj_ref"]
                        if projector and not model_path(self.runtime_supervisor.root, projector).is_file():
                            raise ValueError()
                    elif engine in {"chatterbox", "qwen3tts", "whisper"}:
                        from ai_workbench.workers.audio_catalog import audio_model
                        audio_model(self.runtime_supervisor.root / "data" / "models", profile.model_ref, profile.parameters["architecture"])
                    else:
                        from ai_workbench.workers.common import local_model
                        local_model(self.runtime_supervisor.root / "data" / "models", profile.model_ref, tts=engine == "kokoro")
                        if engine == "kokoro":
                            from ai_workbench.workers.tts_catalog import language_model
                            language_model(self.runtime_supervisor.root / "data" / "models")
                except (OSError, ValueError, WorkerError):
                    status.state = "unavailable"
                    status.error_code = "MODEL_NOT_FOUND"
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
            return ManagedQueue(), self._managed_slot(profile)
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
        key = self.execution_key(profile)
        if key not in self._slots:
            from ai_workbench.core.models.runtimes.adapters import AudioWorkerAdapter, LlamaServerAdapter, PythonWorkerAdapter, TransformersServerAdapter
            engine = local_engine(profile)
            cls = AudioWorkerAdapter if engine in {"chatterbox", "qwen3tts", "whisper"} else TransformersServerAdapter if engine == "transformers" else LlamaServerAdapter if engine == "llama-server" else PythonWorkerAdapter
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
    async def _lease(self, profile: ModelProfile, *, autoload: bool = True, release: bool = True, require_runtime=True, on_admit=None, load_trigger=None):
        if profile.source is None:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select a local runtime or provider for this model.", 503)
        local = isinstance(profile.source, LocalSource)
        executing = False
        key = self._key(profile)
        trace = None
        if local and self.runtime_supervisor and not self._closed and (
            load_trigger or autoload and self._statuses.get(key, ModelStatus()).state != "ready"
        ):
            trace = self._managed_slot(profile).adapter.begin_trace(profile, load_trigger or "autoload")
        def admitted():
            if on_admit:
                on_admit()
            idle = self._idle.pop(key, None)
            if idle and idle is not asyncio.current_task():
                idle.cancel()
        with tracing(trace):
            try:
                async with self._execution_lease(self.execution_key(profile), key, profile, require_runtime, admitted) as slot:
                    try:
                        if local and autoload:
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
                        if local and release and slot.model_active[key] == 1 and not slot.model_queued[key] and not self._closed:
                            await self._release_policy(profile, slot.adapter)
            except ModelError as exc:
                if (local and exc.code not in {"MODEL_BUSY", "UNLOAD_UNSUPPORTED", "INVALID_AUDIO", "AUDIO_TOO_LONG", "AUDIO_TOO_LARGE"}) or (
                    not local and executing and exc.code in {"MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "PROVIDER_ERROR", "PROVIDER_PROTOCOL_ERROR", "MODEL_REFUSAL", "EMBEDDING_DIMENSION_MISMATCH"}
                ):
                    self._notify(profile, ModelStatus(state="failed", error_code=exc.code))
                raise

    async def _release_policy(self, profile, adapter):
        key = self._key(profile)
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
            return result

    async def load(self, profile_id: str) -> ModelStatus:
        profile = self.profile(profile_id)
        self.require_local(profile)
        async with self._lease(profile, autoload=False, release=False, load_trigger="explicit") as adapter:
            result = await adapter.load(profile, explicit=True)
            self._notify(profile, result)
            return result

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

    def voice_list(self, profile_id: str) -> list[dict]:
        from ai_workbench.workers.tts_catalog import voices
        from ai_workbench.core.models.runtimes.schema import model_path
        profile = self.profiles.get(profile_id)
        if profile.kind != "tts":
            raise ModelError("MODEL_KIND_MISMATCH", "Voice discovery requires a tts profile.")
        if profile.parameters["architecture"] != "kokoro":
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
        if profile.parameters["architecture"] in {"chatterbox", "qwen3tts"}:
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
        if profile.parameters["architecture"] not in {"chatterbox", "qwen3tts"} or local_engine(profile) not in {"chatterbox", "qwen3tts"}:
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
        if reference_text is not None and profile.parameters["architecture"] != "qwen3tts":
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
        if self._voice_references is None or local_engine(profile) not in {"chatterbox", "qwen3tts"} or profile.parameters["architecture"] not in {"chatterbox", "qwen3tts"}:
            return []
        language = None if profile.parameters["architecture"] == "qwen3tts" else "en-US"
        return [{**item, "model": profile.alias} for item in self._voice_references.list(
            profile.id, self.voice_binding(profile), credential, language=language)]

    def delete_voice_reference(self, identifier, credential):
        credential = self._voice_credential(credential)
        if self._voice_references is not None:
            for profile in self.profiles.list("tts"):
                if not profile.enabled or not profile.external_enabled or local_engine(profile) not in {"chatterbox", "qwen3tts"} or profile.parameters["architecture"] not in {"chatterbox", "qwen3tts"}:
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
        architecture = profile.parameters["architecture"]
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

    def process_log(self, profile):
        self.require_local(profile)
        slot = self._slots.get(self.execution_key(profile))
        path = getattr(slot.adapter, "log_path", None) if slot else None
        if slot:
            path = getattr(slot.adapter, "log_paths", {}).get(profile.id, path)
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
