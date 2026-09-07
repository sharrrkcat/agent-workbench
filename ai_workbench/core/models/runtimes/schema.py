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


class LlamaOptions(Strict):
    threads: int = Field(default=4, ge=1, le=256)
    context_size: int = Field(default=4096, ge=512, le=1048576)
    batch_size: int = Field(default=512, ge=1, le=4096)
    gpu_layers: int = Field(default=0, ge=0, le=999, strict=True)


class LlamaCPUOptions(LlamaOptions):
    gpu_layers: Annotated[int, Field(strict=True, ge=0, le=0)] = 0


class LlamaCUDAOptions(LlamaOptions):
    gpu_layers: Literal["auto"] | Annotated[int, Field(strict=True, ge=1, le=999)] = "auto"


def llama_options(variant: str):
    return {"cpu": LlamaCPUOptions, "cuda": LlamaCUDAOptions, "vulkan": LlamaOptions}[variant]


class PythonOptions(Strict):
    device: Literal["cpu"] = "cpu"
    intraop_threads: int = Field(default=4, ge=1, le=256)
    max_batch_size: int = Field(default=32, ge=1, le=2048)


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


class CatalogEntry(Strict):
    runtime_id: Literal["llama-server", "python-worker"]
    variant: str
    version: str
    platform: str
    architecture: str = "x86_64"
    supported: bool = False
    reason: str | None = None
    url: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    size_bytes: int | None = Field(default=None, gt=0)
    additional_artifacts: list[RuntimeArtifact] = Field(default_factory=list)
    archive_format: Literal["zip", "tar.gz", "venv"]
    executable: str
    requirements: str | None = None
    python_version: str | None = None
    worker_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    kinds: list[str]
    options_schema: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_artifact(self):
        if self.url and (urlsplit(self.url).scheme != "https" or not urlsplit(self.url).hostname):
            raise ValueError("Runtime artifacts require HTTPS")
        if self.supported and self.archive_format != "venv" and not (self.url and self.sha256):
            raise ValueError("Installable archives require a pinned URL and SHA-256")
        if self.supported and self.archive_format == "venv" and not (self.requirements and self.python_version and self.sha256):
            raise ValueError("Installable workers require a hashed lock and Python version")
        if self.additional_artifacts and (self.runtime_id != "llama-server" or self.archive_format == "venv"):
            raise ValueError("Additional artifacts belong to managed llama-server archives")
        return self


InstallState = Literal["not_installed", "installing", "installed", "broken", "unsupported", "interrupted"]
JobState = Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class Installation(Strict):
    id: str
    runtime_id: str
    variant: str
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
    runtime_id: str | None = None
    variant: str | None = None
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
    runtime_id: str | None = None
    variant: str | None = None
    version: str | None = None
    operation: Literal["install", "uninstall", "cache_prune", "cache_clean"]
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
        identity = (self.runtime_id, self.variant, self.version)
        if self.operation in {"install", "uninstall"}:
            if not all(identity) or self.result is not None:
                raise ValueError("Installation jobs require a runtime identity and no cache result")
        elif any(value is not None for value in identity):
            raise ValueError("Cache jobs have no runtime identity")
        return self


class RuntimeStatus(Strict):
    runtime_id: str
    variant: str
    version: str
    install_state: InstallState
    process_state: Literal["stopped", "starting", "ready", "failed"] = "stopped"
    job_id: str | None = None
    device_name: str | None = None
    gpu_layers_loaded: int | None = Field(default=None, ge=0)
    gpu_layers_total: int | None = Field(default=None, ge=0)
