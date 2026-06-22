from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from ai_workbench.core.profile_aliases import validate_profile_alias
from ai_workbench.core.time import utc_now


VisionArchitecture = Literal["florence2", "florence2_promptgen", "wd14"]
VisionBackend = Literal["transformers", "onnxruntime"]
VisionTask = Literal[
    "caption",
    "detailed_caption",
    "more_detailed_caption",
    "ocr",
    "object_detection",
    "generate_tags",
    "analyze",
    "mixed_caption",
    "mixed_caption_plus",
]

MAX_VISION_BATCH_SIZE = 64
FLORENCE2_VISION_TASKS: tuple[VisionTask, ...] = ("caption", "detailed_caption", "more_detailed_caption", "ocr", "object_detection")
FLORENCE2_PROMPTGEN_VISION_TASKS: tuple[VisionTask, ...] = (
    "caption",
    "detailed_caption",
    "more_detailed_caption",
    "generate_tags",
    "analyze",
    "mixed_caption",
    "mixed_caption_plus",
)
WD14_VISION_TASKS: tuple[VisionTask, ...] = ("generate_tags",)
DEFAULT_VISION_TASKS: tuple[VisionTask, ...] = FLORENCE2_VISION_TASKS
VISION_TASKS_BY_ARCHITECTURE: dict[str, tuple[VisionTask, ...]] = {
    "florence2": FLORENCE2_VISION_TASKS,
    "florence2_promptgen": FLORENCE2_PROMPTGEN_VISION_TASKS,
    "wd14": WD14_VISION_TASKS,
}
VISION_BACKENDS_BY_ARCHITECTURE: dict[str, VisionBackend] = {
    "florence2": "transformers",
    "florence2_promptgen": "transformers",
    "wd14": "onnxruntime",
}
VISION_PROVIDERS_BY_ARCHITECTURE: dict[str, str] = {
    "florence2": "internal_transformers",
    "florence2_promptgen": "internal_transformers",
    "wd14": "internal_onnxruntime",
}
VISION_TASKS: set[str] = {task for tasks in VISION_TASKS_BY_ARCHITECTURE.values() for task in tasks}


def default_vision_tasks_for_architecture(architecture: Any) -> list[VisionTask]:
    return list(VISION_TASKS_BY_ARCHITECTURE.get(str(architecture or "florence2"), DEFAULT_VISION_TASKS))


def vision_backend_for_architecture(architecture: Any) -> VisionBackend:
    return VISION_BACKENDS_BY_ARCHITECTURE.get(str(architecture or "florence2"), "transformers")


def vision_provider_for_architecture(architecture: Any) -> str:
    return VISION_PROVIDERS_BY_ARCHITECTURE.get(str(architecture or "florence2"), "internal_transformers")


def vision_provider_compatibility_error(profile: Any, provider_profile_store: Any) -> str | None:
    architecture = str(getattr(profile, "architecture", "") or "florence2")
    expected_provider = vision_provider_for_architecture(architecture)
    provider_profile_id = getattr(profile, "provider_profile_id", None)
    if not provider_profile_id:
        return f"Vision architecture {architecture} requires a {expected_provider} provider profile."
    if provider_profile_store is None:
        return "Vision provider profile store is not available."
    try:
        provider = provider_profile_store.get(str(provider_profile_id))
    except Exception:
        return f"Vision provider profile is missing: {provider_profile_id}."
    actual_provider = str(getattr(provider, "provider", ""))
    if actual_provider != expected_provider:
        return f"Vision architecture {architecture} requires a {expected_provider} provider profile."
    return None


def normalize_vision_model_ref(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("provider_model_id must not be empty.")
    if "\\" in raw:
        raise ValueError("provider_model_id must use POSIX-style forward slashes.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("provider_model_id must be a safe relative ref.")
    if not path.parts or path.parts[0] != "vision":
        raise ValueError("provider_model_id must start with vision/.")
    if len(path.parts) < 2:
        raise ValueError("provider_model_id must include a model name.")
    return path.as_posix()


def vision_profile_updates(patch: BaseModel) -> dict[str, Any]:
    values = patch.model_dump(exclude_unset=True)
    if "architecture" in values:
        architecture = values["architecture"]
        values.setdefault("backend", vision_backend_for_architecture(architecture))
        values.setdefault("supported_tasks", default_vision_tasks_for_architecture(architecture))
    return values


class VisionModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    alias: str
    name: str
    description: str = ""
    notes: str = ""
    enabled: StrictBool = True
    external_inference_enabled: StrictBool = False
    provider_profile_id: str | None = None
    provider_model_id: str
    architecture: VisionArchitecture = "florence2"
    backend: VisionBackend = "transformers"
    supported_tasks: list[VisionTask] = Field(default_factory=lambda: list(DEFAULT_VISION_TASKS))
    max_batch_size: int | None = Field(default=1, ge=1, le=MAX_VISION_BATCH_SIZE)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _fill_architecture_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            values = dict(data)
            architecture = values.get("architecture", "florence2")
            if values.get("backend") is None:
                values["backend"] = vision_backend_for_architecture(architecture)
            if values.get("supported_tasks") is None:
                values["supported_tasks"] = default_vision_tasks_for_architecture(architecture)
            return values
        return data

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Name must not be empty.")
        return text

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str) -> str:
        return validate_profile_alias(value)

    @field_validator("description", "notes", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("provider_profile_id", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("provider_model_id", mode="before")
    @classmethod
    def _provider_model_id(cls, value: Any) -> str:
        return normalize_vision_model_ref(value)

    @field_validator("supported_tasks", mode="before")
    @classmethod
    def _supported_tasks(cls, value: Any) -> list[str]:
        if value is None:
            return list(DEFAULT_VISION_TASKS)
        if not isinstance(value, list):
            raise ValueError("supported_tasks must be an array.")
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text not in VISION_TASKS:
                raise ValueError("supported_tasks contains an unsupported task.")
            if text not in result:
                result.append(text)
        return result

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object.")
        if len(str(value)) > 4000:
            raise ValueError("metadata must be compact.")
        return value

    @model_validator(mode="after")
    def _model_rules(self) -> "VisionModelProfile":
        if not self.supported_tasks:
            raise ValueError("supported_tasks must not be empty.")
        expected_backend = vision_backend_for_architecture(self.architecture)
        if self.backend != expected_backend:
            raise ValueError("backend is unsupported by the selected architecture.")
        allowed = set(default_vision_tasks_for_architecture(self.architecture))
        if any(task not in allowed for task in self.supported_tasks):
            raise ValueError("supported_tasks contains a task unsupported by the selected architecture.")
        return self


class VisionModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    alias: str | None = None
    description: str = ""
    notes: str = ""
    enabled: StrictBool = True
    external_inference_enabled: StrictBool = False
    provider_profile_id: str | None = None
    provider_model_id: str
    architecture: VisionArchitecture = "florence2"
    backend: VisionBackend | None = None
    supported_tasks: list[VisionTask] | None = None
    max_batch_size: int | None = Field(default=1, ge=1, le=MAX_VISION_BATCH_SIZE)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str | None) -> str | None:
        return validate_profile_alias(value) if value is not None else None


class VisionModelProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    alias: str | None = None
    description: str | None = None
    notes: str | None = None
    enabled: StrictBool | None = None
    external_inference_enabled: StrictBool | None = None
    provider_profile_id: str | None = None
    provider_model_id: str | None = None
    architecture: VisionArchitecture | None = None
    backend: VisionBackend | None = None
    supported_tasks: list[VisionTask] | None = None
    max_batch_size: int | None = Field(default=None, ge=1, le=MAX_VISION_BATCH_SIZE)
    metadata: dict[str, Any] | None = None

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str | None) -> str | None:
        return validate_profile_alias(value) if value is not None else None
