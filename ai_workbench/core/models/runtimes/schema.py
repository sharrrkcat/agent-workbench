from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_workbench.core.time import utc_now


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def relative_ref(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or ":" in value or path.is_absolute() or any(
        part in {"", ".", ".."} or part.rstrip(" .") != part for part in value.split("/")
    ):
        raise ValueError("Use a safe relative path below data/models")
    return value


def model_path(root: Path, ref: str) -> Path:
    relative_ref(ref)
    base = (root / "data" / "models").resolve()
    path = (base / ref).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Model path escapes data/models")
    return path


LocalEngine = Literal["llama-server", "transformers", "kokoro", "chatterbox", "qwen3tts", "whisper"]


class LlamaOptions(Strict):
    device: Literal["cpu", "cuda"] = "cuda"
    threads: int = Field(default=4, ge=1, le=256)
    context_size: int = Field(default=4096, ge=512, le=1048576)
    batch_size: int = Field(default=512, ge=1, le=4096)
    gpu_layers: int = Field(default=0, ge=0, le=999, strict=True)


class LlamaCPUOptions(LlamaOptions):
    device: Literal["cpu"] = "cpu"
    gpu_layers: Annotated[int, Field(strict=True, ge=0, le=0)] = 0


class LlamaCUDAOptions(LlamaOptions):
    device: Literal["cuda"] = "cuda"
    gpu_layers: Literal["auto"] | Annotated[int, Field(strict=True, ge=1, le=999)] = "auto"


def llama_options(device: str):
    return {"cpu": LlamaCPUOptions, "cuda": LlamaCUDAOptions}[device]


class OnnxCPUOptions(Strict):
    device: Literal["cpu"] = "cpu"
    intraop_threads: int = Field(default=4, ge=1, le=256)
    max_batch_size: int = Field(default=1, ge=1, le=1, strict=True)


class PythonOptions(Strict):
    device: Literal["cpu", "cuda"] = "cuda"
    intraop_threads: int = Field(default=4, ge=1, le=256, strict=True)


def local_engine(profile) -> LocalEngine | None:
    if profile.backend_profile_id != "local":
        return None
    if profile.kind == "llm":
        return "llama-server" if profile.model_ref.endswith(".gguf") else "transformers"
    if profile.kind in {"tts", "asr"}:
        return profile.parameters["architecture"]
    return None


def is_transformers(profile) -> bool:
    return local_engine(profile) == "transformers"


class DownloadSettings(Strict):
    http_proxy: str | None = None
    pypi_index_url: str | None = None
    pytorch_index_url: str | None = None
    github_release_proxy_url: str | None = None

    @field_validator("http_proxy", "pypi_index_url", "pytorch_index_url", "github_release_proxy_url")
    @classmethod
    def valid_url(cls, value, info):
        if value is None or value == "":
            return None
        url = urlsplit(value)
        schemes = {"http", "https"} if info.field_name == "http_proxy" else {"https"}
        if url.scheme not in schemes or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTPS URL without credentials, query or fragment (HTTP is allowed for the proxy)")
        return value.rstrip("/")


class RuntimeArtifact(Strict):
    url: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_format: Literal["zip", "tar.gz"]
    size_bytes: int | None = Field(default=None, gt=0)

    @field_validator("url")
    @classmethod
    def https_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Runtime artifacts require HTTPS without credentials")
        return value


class NativeRuntime(Strict):
    artifact: RuntimeArtifact
    dependencies: list[RuntimeArtifact] = Field(default_factory=list)
    executable: str = "llama-server.exe"


class LocalRelease(Strict):
    version: str
    platform: str
    architecture: str = "x86_64"
    supported: bool = False
    reason: str | None = None
    requirements: str | None = None
    lock_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    python_version: str
    python_artifact: RuntimeArtifact | None = None
    python_executable: str = "env/python.exe"
    pytorch_index_url: str = "https://download.pytorch.org/whl/cu128"
    worker_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    worker_files: list[str] = Field(default_factory=list)
    native_cpu: NativeRuntime | None = None
    native_cuda: NativeRuntime | None = None

    @model_validator(mode="after")
    def valid_release(self):
        if self.supported and not all((self.requirements, self.lock_sha256,
                self.python_artifact, self.worker_sha256, self.worker_files, self.native_cpu, self.native_cuda)):
            raise ValueError("An installable local release requires pinned Python, packages, workers and native components")
        if len(set(self.worker_files)) != len(self.worker_files) or any(
            relative_ref(name) != name or "/" in name or not name.endswith(".py") for name in self.worker_files
        ):
            raise ValueError("Worker sources must be unique Python filenames")
        return self


class InstallationExecutables(Strict):
    python: str
    cpu: str
    cuda: str

    @field_validator("python", "cpu", "cuda")
    @classmethod
    def relative_entry(cls, value):
        return relative_ref(value)


class InstallationManifest(Strict):
    release: LocalRelease
    executables: InstallationExecutables


InstallState = Literal["not_installed", "installing", "installed", "broken", "unsupported", "interrupted"]
JobState = Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class Installation(Strict):
    backend_profile_id: Literal["local"] = "local"
    version: str
    state: InstallState = "not_installed"
    job_id: str | None = None
    error_code: str | None = None
    manifest_sha256: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class StorageUsage(Strict):
    complete: bool = True
    file_count: int | None = Field(default=0, ge=0)
    logical_bytes: int | None = Field(default=0, ge=0)
    unique_bytes: int | None = Field(default=0, ge=0)
    shared_bytes: int | None = Field(default=0, ge=0)
    exclusive_bytes: int | None = Field(default=0, ge=0)


class StorageGroup(StorageUsage):
    id: str
    category: Literal["runtime", "python", "cache", "staging", "processes", "other"]
    relative_path: str
    backend_profile_id: Literal["local"] | None = None
    version: str | None = None


class StorageWarning(Strict):
    code: Literal["STORAGE_UNREADABLE", "STORAGE_CHANGED", "STORAGE_ID_UNAVAILABLE", "STORAGE_LINK_ROOT"]
    relative_path: str


class RuntimeStorage(Strict):
    scanned_at: datetime = Field(default_factory=utc_now)
    complete: bool = True
    totals: StorageUsage = Field(default_factory=StorageUsage)
    groups: list[StorageGroup] = Field(default_factory=list)
    warnings: list[StorageWarning] = Field(default_factory=list)
    skipped_links: int = 0


class CacheCleanupRequest(Strict):
    mode: Literal["prune", "clean"]


class CacheCleanupResult(Strict):
    before: StorageUsage | None = None
    after: StorageUsage | None = None


class RuntimeJob(Strict):
    id: str = Field(default_factory=lambda: str(uuid4()))
    backend_profile_id: Literal["local"] | None = None
    version: str | None = None
    operation: Literal["install", "repair", "uninstall", "cache_prune", "cache_clean"]
    result: CacheCleanupResult | None = None
    state: JobState = "queued"
    stage: str = "queued"
    progress_current: int = 0
    progress_total: int | None = None
    error_code: str | None = None
    cancel_requested: bool = False
    log_path: str = ""
    revision: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def valid_target(self):
        identity = (self.backend_profile_id, self.version)
        if self.operation in {"install", "repair", "uninstall"}:
            if not all(identity) or self.result is not None:
                raise ValueError("Installation jobs require a local backend release and no cache result")
        elif any(value is not None for value in identity):
            raise ValueError("Cache jobs have no installation identity")
        return self


class RuntimeStatus(Strict):
    backend_profile_id: Literal["local"] = "local"
    engine: LocalEngine
    version: str
    install_state: InstallState
    process_state: Literal["stopped", "starting", "ready", "failed"] = "stopped"
    job_id: str | None = None
    device_name: str | None = None
    gpu_layers_loaded: int | None = Field(default=None, ge=0)
    gpu_layers_total: int | None = Field(default=None, ge=0)
