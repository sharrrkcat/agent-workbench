"""Prepared model identity and a concrete, independently owned SigLIP tower client."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Callable, Literal
from uuid import uuid4

import httpx
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog, prune_process_logs
from ai_workbench.core.models.runtimes.schema import SiglipOptions
from ai_workbench.core.models.runtimes.supervisor import remove_owned
from ai_workbench.core.models.schema import SiglipResult, SiglipTowerInfo, Tower
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.siglip_catalog import model_directory, model_file, model_files
from ai_workbench.workers.timing import TRACE_ENV, current_trace

class SiglipHealth(SiglipTowerInfo):
    protocol_version: Literal[1]


def model_revision(path: Path) -> str:
    """Content identity, not verification against an expected checkpoint or file list."""
    digest = hashlib.sha256(b"workbench-siglip-model-v1\0")
    for name in model_files(path):
        relative = name.encode("utf-8")
        source = model_file(path, name)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        # Actual length frames the content; it is never compared with a preset size.
        digest.update(source.stat().st_size.to_bytes(8, "big"))
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class SiglipModelUse:
    """Share this object between towers; prepare a new one after releasing the whole model."""
    models_root: Path
    model_ref: str
    path: Path
    model_revision: str

    @classmethod
    async def prepare(cls, repo_root: Path, model_ref: str) -> SiglipModelUse:
        def read():
            root = (repo_root / "data" / "models").resolve()
            path = model_directory(root, model_ref)
            return cls(root, model_ref, path, model_revision(path))
        try:
            return await asyncio.to_thread(read)
        except WorkerError as exc:
            raise ModelError(exc.code, "The local SigLIP directory is incomplete or outside data/models.", exc.status) from exc
        except OSError as exc:
            raise ModelError("MODEL_NOT_FOUND", "Cannot read the local SigLIP model files.", 404) from exc


class SiglipTowerClient:
    """One tower/process. Callers prepare inputs and own serialization and model-use lifetime."""
    _active_logs: set[Path] = set()
    _trace_logs: set[Path] = set()

    def __init__(self, supervisor, model: SiglipModelUse, tower: Tower, options: SiglipOptions | None = None,
                 *, log: RuntimeLog | None = None, on_exit: Callable[[], None] | None = None):
        self.supervisor, self.model, self.tower = supervisor, model, tower
        self.options = options or SiglipOptions()
        self.process: ManagedProcess | None = None
        self.client: httpx.AsyncClient | None = None
        self.run_dir: Path | None = None
        self.info: SiglipTowerInfo | None = None
        self.log = log
        self.on_exit = on_exit
        self.monitor: asyncio.Task | None = None

    def use_log(self, log: RuntimeLog):
        if self.log:
            self._active_logs.discard(self.log.path)
            log.secrets = self.log.secrets
        self.log = log
        if self.process:
            self._active_logs.add(log.path)
            self.process.log = log

    @classmethod
    def prune_logs(cls, directory):
        prune_process_logs(directory, "siglip2", cls._active_logs | cls._trace_logs)

    async def load(self) -> SiglipTowerInfo:
        if self.process is not None:
            return await self.health()
        executable = self.supervisor.executable("siglip2", self.options.device)
        entrypoint = self.supervisor.worker_entrypoint("siglip2")
        run_id, token = str(uuid4()), secrets.token_urlsafe(32)
        self.run_dir = self.supervisor.base / ".processes" / run_id
        self.run_dir.mkdir(parents=True)
        ready, cache = self.run_dir / "ready.json", self.run_dir / "cache"
        if self.log is None:
            self.log = RuntimeLog(self.supervisor.logs / f"process-siglip2-{run_id}.log", self.supervisor.root)
        self.log.secrets = (token,)
        self._active_logs.add(self.log.path)
        self.prune_logs(self.supervisor.logs)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "VIRTUAL_ENV")) and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
        env.update(COGITA_WORKER_TOKEN=token, COGITA_WORKER_READY=str(ready),
            COGITA_MODELS_ROOT=str(self.model.models_root), COGITA_MODEL_REF=self.model.model_ref,
            COGITA_SIGLIP_TOWER=self.tower, COGITA_MODEL_REVISION=self.model.model_revision,
            COGITA_RUNTIME_OPTIONS=self.options.model_dump_json(), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
            HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false", HF_HOME=str(cache),
            HF_HUB_CACHE=str(cache / "hub"), TORCH_HOME=str(cache / "torch"))
        trace = current_trace()
        if trace:
            env[TRACE_ENV] = trace.transport_value()
        self.log.write(f"Starting SigLIP {self.tower} tower on {self.options.device}")
        try:
            self.process = await ManagedProcess.start([executable, "-I", "-B", "-X", "utf8", entrypoint],
                env=env, cwd=executable.parent, log=self.log)
            self.info = await asyncio.wait_for(self._connect(ready, token), 300)
            self.monitor = asyncio.create_task(self._watch(self.process))
            self.log.write("SigLIP tower ready")
            return self.info
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            await self.close()
            raise ModelError("MODEL_TIMEOUT", "The SigLIP tower did not become ready in five minutes.", 504) from exc
        except (OSError, ValueError, httpx.HTTPError) as exc:
            await self.close()
            raise ModelError("MODEL_UNAVAILABLE", "The SigLIP worker could not become ready.", 503) from exc
        except BaseException:
            await self.close()
            raise

    async def _connect(self, ready, token):
        while not ready.exists():
            if self.process.process.returncode is not None:
                raise ModelError("MODEL_UNAVAILABLE", "The SigLIP worker exited during loading.", 503)
            await asyncio.sleep(0.1)
        data = json.loads(ready.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid readiness response")
        if "error_code" in data:
            code = data["error_code"]
            if not isinstance(code, str) or code not in {"MODEL_NOT_FOUND", "MODEL_UNAVAILABLE", "RUNTIME_DEVICE_UNAVAILABLE", "UNSUPPORTED_CAPABILITY", "INVALID_REQUEST"}:
                code = "MODEL_UNAVAILABLE"
            raise ModelError(code, "The SigLIP worker could not load this tower.", 503)
        if data.get("protocol_version") != 1 or type(data.get("port")) is not int or not 1 <= data["port"] <= 65535:
            raise ValueError("Invalid readiness response")
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{data['port']}",
            headers={"X-Worker-Token": token}, timeout=300, trust_env=False)
        return await self.health()

    async def _watch(self, process):
        await process.process.wait()
        if not process.stopping:
            await process.stop()
            await self._clear_transport()
            self.process = self.monitor = None
            if self.on_exit:
                self.on_exit()

    async def _rpc(self, method, operation, body=None):
        if not self.client:
            raise ModelError("MODEL_UNAVAILABLE", "The SigLIP tower is not loaded.", 503)
        response = await self.client.request(method, operation, json=body)
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid worker response")
        if not response.is_success:
            error = value.get("error", {})
            if not isinstance(error, dict) or not isinstance(error.get("code"), str):
                raise ValueError("Invalid worker error")
            code = error["code"]
            if code not in {"INVALID_REQUEST", "MODEL_BUSY", "MODEL_UNAVAILABLE", "UNSUPPORTED_CAPABILITY", "REQUEST_TOO_LARGE"}:
                code = "MODEL_UNAVAILABLE"
            raise ModelError(code, "The SigLIP worker could not complete this operation.", response.status_code)
        return value

    def _check_info(self, info):
        if (info.tower, info.device, info.dtype, info.model_revision) != (
                self.tower, self.options.device, "float16" if self.options.device == "cuda" else "float32", self.model.model_revision):
            raise ValueError("Unexpected tower execution identity")

    async def health(self) -> SiglipTowerInfo:
        try:
            health = SiglipHealth.model_validate(await self._rpc("GET", "/health"), strict=True)
            self._check_info(health)
            return SiglipTowerInfo.model_validate(health.model_dump(exclude={"protocol_version"}))
        except (httpx.HTTPError, ValueError) as exc:
            await self.close()
            raise ModelError("MODEL_UNAVAILABLE", "The SigLIP worker returned invalid health information.", 503) from exc
        except (ModelError, asyncio.CancelledError):
            await self.close()
            raise

    async def embed(self, inputs: list[str]) -> SiglipResult:
        try:
            if self.process is None:
                await self.load()
            loaded_info = self.info
            result = SiglipResult.model_validate(await self._rpc("POST", "/embed", {"inputs": inputs}), strict=True)
            self._check_info(result)
            if len(result.vectors) != len(inputs) or result.model_dump(include=set(SiglipTowerInfo.model_fields)) != loaded_info.model_dump():
                raise ValueError("Embedding results do not match the request and loaded tower")
            return result
        except asyncio.CancelledError:
            await self.close()
            raise
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            await self.close()
            raise ModelError("MODEL_TIMEOUT", "The SigLIP tower timed out and was stopped.", 504) from exc
        except (httpx.HTTPError, ValueError) as exc:
            await self.close()
            raise ModelError("MODEL_UNAVAILABLE", "The SigLIP worker returned an invalid response or disconnected.", 503) from exc
        except ModelError:
            await self.close()
            raise

    async def close(self):
        if self.process:
            await self.process.stop()
            self.process = None
        if self.monitor:
            await self.monitor
            self.monitor = None
        await self._clear_transport()

    async def _clear_transport(self):
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.run_dir:
            remove_owned(self.supervisor.base, self.run_dir)
            self.run_dir = None
        if self.log:
            self._active_logs.discard(self.log.path)
            self.prune_logs(self.supervisor.logs)
        self.info = None
