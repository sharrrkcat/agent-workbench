"""Settings and cached diagnostics without unstructured business payloads."""

from typing import Literal

from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, patch_model
from ai_workbench.core.models.schema import ModelStatus
from ai_workbench.core.settings import AppSettings, PetSettingsPatch


GeneralSettingsRequest = patch_model("GeneralSettingsRequest", AppSettings, fields={
    "pet": (PetSettingsPatch | None, Field(default_factory=lambda: None,
        description="Deep-merges position when supplied; omission or null leaves Pet settings unchanged.")),
})


class GeneralSettingsResponse(AppSettings):
    session_title_prompt_default: str = Field(description="Built-in title prompt.", json_schema_extra={"readOnly": True})
    group_transcript_system_instruction_default: str = Field(json_schema_extra={"readOnly": True})
    group_transcript_system_instruction_effective: str = Field(json_schema_extra={"readOnly": True})


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "degraded"]
    schema_revision: str


class ComponentHealth(ApiModel):
    status: Literal["ok", "degraded"]
    error: str | None = None


class LlmHealth(ModelStatus):
    status: Literal["ok"]
    model_profile_id: str
    alias: str


class ActiveRuns(ApiModel):
    active_count: int


class HealthDetails(ApiModel):
    status: Literal["ok", "degraded"]
    version: str
    database: ComponentHealth
    schema_revision: str
    llm: LlmHealth | ComponentHealth
    runs: ActiveRuns


class CpuResources(ApiModel):
    available: bool
    percent: float | None
    reason: str | None = None


class MemoryResources(CpuResources):
    used_bytes: int | None
    total_bytes: int | None


class GpuResources(ApiModel):
    index: int
    name: str
    available: bool
    utilization_percent: float | None
    memory_used_bytes: int | None
    memory_total_bytes: int | None
    memory_percent: float | None
    backend: Literal["nvml", "unavailable"]
    reason: str | None = None


class ProcessResources(ApiModel):
    backend_memory_bytes: int | None
    reason: str | None = None


class RuntimeResources(ApiModel):
    cpu: CpuResources
    memory: MemoryResources
    gpus: list[GpuResources]
    process: ProcessResources
    updated_at: ApiTimestamp | None
    error: str | None = None


class DatabaseStorage(ApiModel):
    status: Literal["ok", "warning"]
    path: str
    size_bytes: int
    schema_revision: str


class AttachmentStorage(ApiModel):
    directory: str
    count: int
    total_size_bytes: int
    orphan_count: int
    orphan_size_bytes: int
    last_scan_time: ApiTimestamp


class StorageStats(ApiModel):
    database: DatabaseStorage
    attachments: AttachmentStorage
    warnings: list[str] = Field(default_factory=list)


class OrphanAttachment(ApiModel):
    id: str
    path: str
    size_bytes: int


class OrphanScan(ApiModel):
    orphan_count: int
    orphan_size_bytes: int
    orphans: list[OrphanAttachment]


class CleanupError(ApiModel):
    path: str
    error: str


class OrphanCleanup(ApiModel):
    deleted_count: int
    deleted_size_bytes: int
    errors: list[CleanupError]
