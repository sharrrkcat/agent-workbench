from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import os
from pathlib import Path
import secrets
import socket
from uuid import uuid4

import httpx
from pydantic import ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.runtimes.cuda import LlamaCudaLog, confirmed_offload, cuda_arguments, llama_environment, probe_cuda_device
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
from ai_workbench.core.models.runtimes.schema import RuntimeStatus, is_transformers, model_path
from ai_workbench.core.models.runtimes.supervisor import remove_owned
from ai_workbench.core.models.schema import AudioOutput, EmbeddingResult, ModelStatus, ProviderProfile, RerankResult, VisionResult
from ai_workbench.workers.tts_catalog import FORMATS, MAX_AUDIO_BYTES
from ai_workbench.workers.audio import validate_audio
from ai_workbench.workers.timing import LoadTrace, TRACE_ENV, TRACE_HEADER, current_trace, stage, tracing


class ManagedAdapter:
    def __init__(self, supervisor, profile, changed):
        self.supervisor, self.profile, self.changed = supervisor, profile, changed
        self.entry = supervisor.entry(profile.runtime_id, profile.runtime_variant)
        self.process: ManagedProcess | None = None
        self.monitor: asyncio.Task | None = None
        self.client: httpx.AsyncClient | None = None
        self.openai: OpenAIAdapter | None = None
        self.loaded: set[str] = set()
        self.failed = False
        self.state = "stopped"
        self.run_dir: Path | None = None
        self.lock = asyncio.Lock()
        self.token = ""
        self.log_path: Path | None = None
        self.log_paths: dict[str, Path] = {}
        self._trace_logs: dict[str, RuntimeLog] = {}
        self.error_code: str | None = None
        self.device_name: str | None = None
        self.gpu_layers_loaded: int | None = None
        self.gpu_layers_total: int | None = None
        self.tool_calls_supported = False

    def begin_trace(self, profile, trigger):
        load_id = str(uuid4())
        path = self.supervisor.logs / f"process-{profile.runtime_id}-{load_id}.log"
        log_type = LlamaCudaLog if self.entry.runtime_id == "llama-server" and self.entry.variant == "cuda" else RuntimeLog
        log = log_type(path, self.supervisor.root, (self.token,) if self.token else ())
        self.log_path = self.log_paths[profile.id] = path
        self._trace_logs[load_id] = log
        self._prune_logs()

        def finished():
            self._trace_logs.pop(load_id, None)
            self._prune_logs()

        operation = {"health": "health", "reference": "reference_prepare"}.get(trigger, "load")
        return LoadTrace({"load_id": load_id, "model_profile_id": profile.id,
                          "runtime_id": self.entry.runtime_id, "variant": self.entry.variant,
                          "version": self.entry.version, "device": profile.runtime_options.get("device", self.entry.variant),
                          "trigger": trigger, "operation": operation},
                         log.write, total_stage=operation + "_total", on_finish=finished)

    def _prune_logs(self):
        try:
            active = {log.path for log in self._trace_logs.values()}
            manager = self.supervisor.manager
            for slot in manager._slots.values() if manager else ():
                adapter = slot.adapter
                if isinstance(adapter, ManagedAdapter):
                    active.update(log.path for log in adapter._trace_logs.values())
                    if adapter.process:
                        log = getattr(adapter.process, "log", None)
                        if log:
                            active.add(log.path)
            terminal = sorted((path for path in self.supervisor.logs.glob(f"process-{self.entry.runtime_id}-*.log")
                               if path not in active), key=lambda path: path.stat().st_mtime_ns, reverse=True)
            for path in terminal[20:]:
                path.unlink()
        except OSError:
            pass

    def _trace(self, profile, trigger):
        trace = current_trace()
        return trace if trace and trace.metadata["load_id"] in self._trace_logs else self.begin_trace(profile, trigger)

    def _activate_trace(self, trace):
        log = self._trace_logs[trace.metadata["load_id"]]
        if self.token:
            log.secrets = (self.token,)
        if self.process:
            self.process.log = log
        return log

    @property
    def single_model(self):
        return self.entry.runtime_id == "llama-server" or self.entry.variant == "transformers-cuda"

    def runtime_status(self):
        value = self.supervisor.installation(self.entry.runtime_id, self.entry.variant)
        return RuntimeStatus(runtime_id=value.runtime_id, variant=value.variant, version=value.version,
            install_state=value.state, process_state=self.state, job_id=value.job_id,
            device_name=self.device_name, gpu_layers_loaded=self.gpu_layers_loaded,
            gpu_layers_total=self.gpu_layers_total).model_dump()

    def snapshot(self, profile):
        loaded = bool(self.loaded) if self.single_model else profile.id in self.loaded
        return ModelStatus(state="failed" if self.failed else "ready" if loaded else "unloaded",
            residency="loaded" if loaded else "unloaded", unload_supported=True,
            error_code=(self.error_code or "MODEL_UNAVAILABLE") if self.failed else None, runtime=self.runtime_status())

    def _model_path(self, profile):
        try:
            path = model_path(self.supervisor.root, profile.model_ref)
            if not path.exists() or profile.runtime_id == "llama-server" and not path.is_file() or profile.runtime_id == "python-worker" and not path.is_dir():
                raise FileNotFoundError()
            if profile.runtime_id == "python-worker":
                from ai_workbench.workers.common import WorkerError, local_model
                try:
                    if self.entry.variant == "audio-cuda":
                        from ai_workbench.workers.audio_catalog import audio_model
                        return audio_model(self.supervisor.root / "data" / "models", profile.model_ref, profile.parameters["architecture"])
                    return local_model(self.supervisor.root / "data" / "models", profile.model_ref,
                        wd14=profile.kind == "vision" and profile.parameters["architecture"] == "wd14", tts=profile.kind == "tts")
                except WorkerError as exc:
                    raise ModelError(exc.code, "The local model directory is incomplete or outside data/models.", exc.status) from exc
            return path
        except (OSError, ValueError) as exc:
            raise ModelError("MODEL_NOT_FOUND", "The local model file or directory is missing or outside data/models.", 404) from exc

    async def health(self, profile):
        with tracing(self._trace(profile, "health")) as trace:
            self._activate_trace(trace)
            with stage("execution_entry"):
                self.supervisor.executable(self.entry)
            with stage("model_resources"):
                self._model_path(profile)
            if self.client and self.process and self.process.process.returncode is None:
                with stage("health_rpc"):
                    await self._rpc("GET", "/health")
            return self.snapshot(profile)

    async def load(self, profile, *, explicit=False):
        with tracing(self._trace(profile, "explicit" if explicit else "autoload")) as trace:
            async with self.lock:
                self._activate_trace(trace)
                trace.reused.update(process_reused=self.process is not None,
                                    model_reused=bool(self.loaded) if self.single_model else profile.id in self.loaded)
                if self.failed and not explicit:
                    raise ModelError("MODEL_UNAVAILABLE", "The managed process failed. Load the model again from Models settings.", 503)
                with stage("execution_entry"):
                    executable = self.supervisor.executable(self.entry)
                with stage("model_resources"):
                    path = self._model_path(profile)
                if self.failed:
                    with stage("failure_cleanup"):
                        await self._stop()
                    self.failed = False
                try:
                    if not self.process:
                        await self._start(profile, path, executable)
                    if not self.single_model and profile.id not in self.loaded:
                        with stage("worker_load_rpc"):
                            metadata = await self._rpc("POST", "/load", {"profile_id": profile.id, "kind": profile.kind,
                                "model_ref": profile.model_ref, "parameters": profile.parameters, "options": profile.runtime_options})
                            if self.entry.variant == "audio-cuda":
                                if not isinstance(metadata.get("device_name"), str):
                                    raise ModelError("RUNTIME_BROKEN", "Audio worker did not report its execution device.", 503)
                                self.device_name = metadata["device_name"]
                    self.loaded.add(profile.id)
                    return self.snapshot(profile)
                except BaseException as exc:
                    if self.process or self.run_dir:
                        with stage("failure_cleanup"):
                            await self._stop()
                    self.failed, self.state = True, "failed"
                    self.error_code = exc.code if isinstance(exc, ModelError) else "MODEL_UNAVAILABLE"
                    self.changed()
                    raise

    async def _start(self, profile, path, executable):
        self.state = "starting"
        self.changed()
        run_id = str(uuid4())
        self.run_dir = self.supervisor.base / ".processes" / run_id
        self.run_dir.mkdir(parents=True)
        self.token = secrets.token_urlsafe(32)
        cuda = self.entry.runtime_id == "llama-server" and self.entry.variant == "cuda"
        trace = current_trace()
        log = self._activate_trace(trace)
        env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "VIRTUAL_ENV", "LLAMA_ARG_")) and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
        target = self.supervisor.directory(self.entry)
        if profile.runtime_id == "python-worker":
            ready = self.run_dir / "ready.json"
            env.update(WORKBENCH_WORKER_TOKEN=self.token, WORKBENCH_WORKER_READY=str(ready),
                       WORKBENCH_MODELS_ROOT=str(self.supervisor.root / "data" / "models"))
            env[TRACE_ENV] = trace.transport_value()
            if self.entry.variant == "audio-cuda":
                env.update(WORKBENCH_AUDIO_REFERENCES_ROOT=str(self.supervisor.manager.voice_references.base))
                if getattr(self, "validation", False):
                    env["WORKBENCH_AUDIO_VALIDATION"] = "1"
            if is_transformers(profile) or self.entry.variant == "audio-cuda":
                cache = self.run_dir / "cache"
                env.update(WORKBENCH_MODEL_REF=profile.model_ref,
                           WORKBENCH_RUNTIME_OPTIONS=json.dumps(profile.runtime_options),
                           HF_HOME=str(cache), HF_HUB_CACHE=str(cache / "hub"), TORCH_HOME=str(cache / "torch"))
            args = [executable, "-I", "-B", "-X", "utf8", target / "worker" / self.entry.worker_entrypoint]
            port = None
        else:
            if cuda:
                env = llama_environment(executable.parent)
                with stage("cuda_probe"):
                    device_id, self.device_name = await probe_cuda_device(executable, env, log)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            key_file = self.run_dir / "api-key"
            key_file.write_text(self.token, encoding="utf-8")
            key_file.chmod(0o600)
            options = profile.runtime_options
            # b10809 exposes core llama INFO records, including offload, at trace verbosity.
            args = [executable, "--host", "127.0.0.1", "--port", port, "--model", path, "--alias", "managed",
                    "--api-key-file", key_file, "--threads", options["threads"], "--ctx-size", options["context_size"],
                    "--batch-size", options["batch_size"], "--parallel", 1,
                    "--reasoning-format", "none", "--log-verbosity", 4 if cuda else 1]
            if cuda:
                args.extend(["--log-colors", "off"])
            args.extend(cuda_arguments(options, device_id) if cuda else ["--n-gpu-layers", options["gpu_layers"]])
        with stage("process_spawn"):
            self.process = await ManagedProcess.start(args, env=env, cwd=executable.parent, log=log)
        with stage("ready_wait"):
            await self._wait_ready(profile, port, ready if profile.runtime_id == "python-worker" else None)
        if self.single_model:
            if cuda:
                with stage("cuda_offload_confirmation"):
                    self.gpu_layers_loaded, self.gpu_layers_total = await confirmed_offload(log)
            with stage("model_advertisement"):
                provider = ProviderProfile(name="managed", base_url=str(self.client.base_url).rstrip("/") + "/v1", api_key=self.token, timeout_seconds=300)
                self.openai = OpenAIAdapter(provider)
                if "managed" not in await self.openai.models():
                    raise ModelError("RUNTIME_BROKEN", "The managed server did not advertise the configured model.", 503)
        self.state = "ready"
        self.monitor = asyncio.create_task(self._watch(self.process))
        self.changed()

    async def _wait_ready(self, profile, port, ready):
        for _ in range(1200):
            if port is None and ready.exists():
                try:
                    data = json.loads(ready.read_text(encoding="utf-8"))
                    if data.get("error_code"):
                        allowed = {"MODEL_UNAVAILABLE", "MODEL_NOT_FOUND", "RUNTIME_DEVICE_UNAVAILABLE", "RUNTIME_BROKEN", "UNSUPPORTED_CAPABILITY"}
                        code = data["error_code"] if data["error_code"] in allowed else "RUNTIME_BROKEN"
                        raise ModelError(code, "The managed worker could not load the configured local model.", 503)
                    if data["protocol_version"] != 1 or type(data["port"]) is not int or not 1 <= data["port"] <= 65535:
                        raise ValueError()
                    port = data["port"]
                    if is_transformers(profile):
                        if not isinstance(data.get("device_name"), str) or type(data.get("tool_calls")) is not bool:
                            raise ValueError()
                        self.device_name = data["device_name"]
                        self.tool_calls_supported = data["tool_calls"]
                except (ValueError, KeyError):
                    raise ModelError("RUNTIME_BROKEN", "Worker readiness response was invalid.", 503)
            if self.process.process.returncode is not None:
                raise ModelError("MODEL_UNAVAILABLE", "The managed process exited during startup.", 503)
            if port is not None:
                if not self.client:
                    headers = {"Authorization": f"Bearer {self.token}"} if self.single_model else {"X-Worker-Token": self.token}
                    self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers, timeout=300, trust_env=False)
                try:
                    response = await self.client.get("/health", timeout=1)
                    if response.status_code == 200:
                        if profile.runtime_id == "python-worker" and response.json().get("protocol_version") != 1:
                            raise ModelError("RUNTIME_BROKEN", "Worker protocol version mismatch.", 503)
                        break
                except (httpx.RequestError, ValueError):
                    pass
            await asyncio.sleep(0.25)
        else:
            raise ModelError("MODEL_TIMEOUT", "The managed process did not become healthy in five minutes.", 504)

    async def _watch(self, process):
        await process.process.wait()
        if not process.stopping:
            await process.stop()
            self.failed, self.state = True, "failed"
            self.error_code = "MODEL_UNAVAILABLE"
            self.device_name = self.gpu_layers_loaded = self.gpu_layers_total = None
            self.tool_calls_supported = False
            self.loaded.clear()
            self.changed()

    async def _rpc(self, method, operation, body=None, *, audio_format=None):
        if self.failed or not self.client:
            raise ModelError("MODEL_UNAVAILABLE", "The managed worker is not running.", 503)
        try:
            trace = current_trace()
            headers = {TRACE_HEADER: trace.transport_value()} if trace and operation in {"/load", "/reference"} else None
            if audio_format:
                async with self.client.stream(method, operation, json=body) as stream:
                    chunks = bytearray()
                    async for chunk in stream.aiter_bytes():
                        if len(chunks) + len(chunk) > MAX_AUDIO_BYTES:
                            raise ValueError("Audio response exceeds limit")
                        chunks.extend(chunk)
                    response = httpx.Response(stream.status_code, headers=stream.headers, content=bytes(chunks))
            else:
                response = await self.client.request(method, operation, json=body, headers=headers)
            if audio_format and response.is_success:
                if response.headers.get("content-type") != FORMATS[audio_format]:
                    raise ValueError("Unexpected audio MIME type")
                validate_audio(response.content, audio_format)
                return AudioOutput(data=response.content, response_format=audio_format)
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("Invalid worker response")
            if not response.is_success:
                error = value.get("error", {})
                if not isinstance(error, dict) or not isinstance(error.get("code", "MODEL_UNAVAILABLE"), str):
                    raise ValueError("Invalid worker error")
                code = error.get("code", "MODEL_UNAVAILABLE")
                allowed = {"INVALID_REQUEST", "MODEL_BUSY", "MODEL_NOT_FOUND", "MODEL_UNAVAILABLE", "MODEL_KIND_MISMATCH", "UNSUPPORTED_CAPABILITY", "EMBEDDING_DIMENSION_MISMATCH", "REQUEST_TOO_LARGE", "VOICE_UNAVAILABLE", "AUDIO_TOO_LARGE", "AUDIO_TOO_LONG", "INVALID_AUDIO", "RUNTIME_BROKEN", "RUNTIME_DEVICE_UNAVAILABLE"}
                raise ModelError(code if code in allowed else "MODEL_UNAVAILABLE", "The managed worker could not complete this operation.", response.status_code)
            return value
        except asyncio.CancelledError:
            # A synchronous CPU call cannot be cancelled safely within its thread.
            # Stop the shared worker before the manager releases its queue slot.
            with stage("failure_cleanup"):
                await self._stop()
            self.changed()
            raise
        except httpx.TimeoutException as exc:
            with stage("failure_cleanup"):
                await self._stop()
            self.failed, self.state = True, "failed"
            self.changed()
            raise ModelError("MODEL_TIMEOUT", "The managed worker timed out and was stopped.", 504) from exc
        except (httpx.HTTPError, ValueError) as exc:
            with stage("failure_cleanup"):
                await self._stop()
            self.failed, self.state = True, "failed"
            self.changed()
            raise ModelError("MODEL_UNAVAILABLE", "The managed worker disconnected or returned an invalid response.", 503) from exc

    async def unload(self, profile):
        async with self.lock:
            if not self.single_model:
                if profile.id in self.loaded and not self.failed:
                    await self._rpc("POST", "/unload", {"profile_id": profile.id})
                    self.loaded.discard(profile.id)
                elif self.failed:
                    self.loaded.clear()
            else:
                self.loaded.clear()
            if not self.loaded or self.single_model:
                await self._stop()
                self.failed = False
            return self.snapshot(profile)

    async def _stop(self):
        if self.process:
            await self.process.stop()
            self.process = None
        if self.monitor:
            await self.monitor
            self.monitor = None
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.openai:
            await self.openai.close()
            self.openai = None
        self.loaded.clear()
        self.state = "stopped"
        self.error_code = None
        self.device_name = self.gpu_layers_loaded = self.gpu_layers_total = None
        self.tool_calls_supported = False
        if self.run_dir and self.run_dir.exists():
            remove_owned(self.supervisor.base, self.run_dir)
        self.run_dir = None

    async def close(self):
        await self._stop()


class LlamaServerAdapter(ManagedAdapter):
    async def chat(self, profile, request):
        if not self.openai or self.failed:
            raise ModelError("MODEL_UNAVAILABLE", "The managed model is not running.", 503)
        return await self.openai.chat(profile.model_copy(update={"model_ref": "managed"}), request)

    async def chat_stream(self, profile, request):
        if not self.openai or self.failed:
            raise ModelError("MODEL_UNAVAILABLE", "The managed model is not running.", 503)
        async with aclosing(self.openai.chat_stream(profile.model_copy(update={"model_ref": "managed"}), request)) as stream:
            async for chunk in stream:
                yield chunk


class TransformersServerAdapter(LlamaServerAdapter):
    def _require_tools(self, request):
        if (request.tools or any(message.tool_calls or message.role == "tool" for message in request.messages)) and not self.tool_calls_supported:
            raise ModelError("UNSUPPORTED_CAPABILITY", "The local checkpoint has no supported Transformers tool response template.", 422)

    async def _abort(self, error=None):
        await self._stop()
        if error is not None:
            self.failed, self.state = True, "failed"
            self.error_code = error.code if isinstance(error, ModelError) else "MODEL_UNAVAILABLE"
        self.changed()

    async def chat(self, profile, request):
        self._require_tools(request)
        try:
            return await super().chat(profile, request)
        except asyncio.CancelledError:
            await self._abort()
            raise
        except ModelError as exc:
            await self._abort(exc)
            raise

    async def chat_stream(self, profile, request):
        self._require_tools(request)
        completed, error = False, None
        try:
            async with aclosing(super().chat_stream(profile, request)) as stream:
                async for chunk in stream:
                    yield chunk
            completed = True
        except ModelError as exc:
            error = exc
            raise
        finally:
            if not completed:
                # Closing HTTP alone cannot prove a synchronous generation thread
                # stopped. Terminate this model's process before releasing its lease.
                await self._abort(error)


class PythonWorkerAdapter(ManagedAdapter):
    async def speech(self, profile, text, voice, speed, response_format, language):
        return await self._rpc("POST", "/speech", {"profile_id": profile.id, "input": text, "voice": voice,
            "speed": speed, "response_format": response_format, "language": language}, audio_format=response_format)

    async def _batches(self, profile, operation, items, input_key, output_key, schema, extra=None):
        results = []
        size = min(profile.parameters.get("batch_size", 1), profile.runtime_options["max_batch_size"])
        for offset in range(0, len(items), size):
            batch = items[offset:offset + size]
            value = await self._rpc("POST", operation, {"profile_id": profile.id, input_key: batch, **(extra or {})})
            try:
                result = schema.model_validate(value)
            except ValidationError as exc:
                raise ModelError("PROVIDER_PROTOCOL_ERROR", "Worker returned an invalid result.", 502) from exc
            rows = getattr(result, output_key)
            if len(rows) != len(batch):
                raise ModelError("PROVIDER_PROTOCOL_ERROR", "Worker result count did not match input.", 502)
            results.extend(rows)
        return schema(**{output_key: results})

    async def embed(self, profile, texts, dimensions):
        return await self._batches(profile, "/embed", texts, "texts", "vectors", EmbeddingResult, {"dimensions": dimensions})

    async def rerank(self, profile, query, documents):
        return await self._batches(profile, "/rerank", documents, "documents", "scores", RerankResult, {"query": query})

    async def image_embed(self, profile, images):
        return await self._batches(profile, "/image-embed", images, "images", "vectors", EmbeddingResult)

    async def vision(self, profile, images):
        return await self._batches(profile, "/vision", images, "images", "outputs", VisionResult)


class AudioWorkerAdapter(ManagedAdapter):
    async def validate_reference(self, profile, reference):
        with tracing(self._trace(profile, "reference")) as trace:
            async with self.lock:
                self._activate_trace(trace)
                trace.reused.update(process_reused=self.process is not None, model_reused=profile.id in self.loaded)
                if self.failed:
                    raise ModelError("MODEL_UNAVAILABLE", "Load the Audio model again after its process failure.", 503)
                if not self.process:
                    try:
                        with stage("execution_entry"):
                            executable = self.supervisor.executable(self.entry)
                        with stage("model_resources"):
                            path = self._model_path(profile)
                        await self._start(profile, path, executable)
                    except BaseException:
                        if self.process or self.run_dir:
                            with stage("failure_cleanup"):
                                await self._stop()
                        self.changed()
                        raise
            with stage("reference_rpc"):
                value = await self._rpc("POST", "/reference", {"reference": reference})
                if type(value.get("frames")) is not int or value["frames"] < 1 or type(value.get("sample_rate")) is not int or not 8000 <= value["sample_rate"] <= 192000:
                    raise ModelError("PROVIDER_PROTOCOL_ERROR", "Audio worker returned invalid reference metadata.", 502)
            return value

    async def speech(self, profile, text, voice, speed, response_format, language, *, reference, reference_text=None, model_options):
        return await self._rpc("POST", "/speech", {"profile_id": profile.id, "input": text, "reference": reference,
            "reference_text": reference_text, "speed": speed, "response_format": response_format,
            "language": language, "model_options": model_options}, audio_format=response_format)

    async def transcribe(self, profile, reference):
        return await self._rpc("POST", "/transcribe", {"profile_id": profile.id, "reference": reference})
