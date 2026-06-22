from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from ai_workbench.core.profile_aliases import validate_profile_alias
from ai_workbench.core.time import utc_now


ImageGenerationArchitecture = Literal["sd15", "sdxl", "z_image"]
ImageGenerationVariant = Literal["base", "pony", "illustrious", "noobai", "custom"]
ImageGenerationDtype = Literal["auto", "fp16", "bf16", "fp32"]
ImageGenerationDevice = Literal["auto", "cuda", "cpu"]
ImageGenerationTask = Literal["txt2img"]

DEFAULT_IMAGE_GENERATION_TASKS: tuple[ImageGenerationTask, ...] = ("txt2img",)
SDXL_ONLY_VARIANTS = {"pony", "illustrious", "noobai"}


def normalize_image_generation_ref(value: Any, *, kind: Literal["checkpoints", "vae", "loras"]) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{kind} ref must not be empty.")
    if "\\" in raw:
        raise ValueError(f"{kind} ref must use POSIX-style forward slashes.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{kind} ref must be a safe relative ref.")
    expected_prefix = ("image_generation", kind)
    if len(path.parts) < 3 or tuple(path.parts[:2]) != expected_prefix:
        raise ValueError(f"{kind} ref must start with image_generation/{kind}/ and include a model name.")
    return path.as_posix()


def normalize_checkpoint_ref(value: Any) -> str:
    return normalize_image_generation_ref(value, kind="checkpoints")


def normalize_vae_ref(value: Any) -> str:
    return normalize_image_generation_ref(value, kind="vae")


def normalize_lora_ref(value: Any) -> str:
    return normalize_image_generation_ref(value, kind="loras")


def image_generation_profile_updates(patch: BaseModel) -> dict[str, Any]:
    return patch.model_dump(exclude_unset=True)


class ImageModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    alias: str
    name: str
    description: str = ""
    notes: str = ""
    enabled: StrictBool = True
    architecture: ImageGenerationArchitecture = "sdxl"
    variant: ImageGenerationVariant = "base"
    checkpoint_ref: str
    vae_ref: str | None = None
    dtype: ImageGenerationDtype = "auto"
    device: ImageGenerationDevice = "auto"
    clip_skip: int | None = Field(default=None, ge=1)
    supported_tasks: list[ImageGenerationTask] = Field(default_factory=lambda: list(DEFAULT_IMAGE_GENERATION_TASKS))
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

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

    @field_validator("checkpoint_ref", mode="before")
    @classmethod
    def _checkpoint_ref(cls, value: Any) -> str:
        return normalize_checkpoint_ref(value)

    @field_validator("vae_ref", mode="before")
    @classmethod
    def _vae_ref(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return normalize_vae_ref(text) if text else None

    @field_validator("supported_tasks", mode="before")
    @classmethod
    def _supported_tasks(cls, value: Any) -> list[str]:
        if value is None:
            return list(DEFAULT_IMAGE_GENERATION_TASKS)
        if not isinstance(value, list):
            raise ValueError("supported_tasks must be an array.")
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text != "txt2img":
                raise ValueError("supported_tasks may contain only txt2img.")
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
    def _model_rules(self) -> "ImageModelProfile":
        if self.supported_tasks != ["txt2img"]:
            raise ValueError("supported_tasks must be exactly ['txt2img'].")
        if self.variant in SDXL_ONLY_VARIANTS and self.architecture != "sdxl":
            raise ValueError("pony, illustrious, and noobai variants require architecture=sdxl.")
        return self


class ImageModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    alias: str | None = None
    description: str = ""
    notes: str = ""
    enabled: StrictBool = True
    architecture: ImageGenerationArchitecture = "sdxl"
    variant: ImageGenerationVariant = "base"
    checkpoint_ref: str
    vae_ref: str | None = None
    dtype: ImageGenerationDtype = "auto"
    device: ImageGenerationDevice = "auto"
    clip_skip: int | None = Field(default=None, ge=1)
    supported_tasks: list[ImageGenerationTask] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str | None) -> str | None:
        return validate_profile_alias(value) if value is not None else None


class ImageModelProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    alias: str | None = None
    description: str | None = None
    notes: str | None = None
    enabled: StrictBool | None = None
    architecture: ImageGenerationArchitecture | None = None
    variant: ImageGenerationVariant | None = None
    checkpoint_ref: str | None = None
    vae_ref: str | None = None
    dtype: ImageGenerationDtype | None = None
    device: ImageGenerationDevice | None = None
    clip_skip: int | None = Field(default=None, ge=1)
    supported_tasks: list[ImageGenerationTask] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str | None) -> str | None:
        return validate_profile_alias(value) if value is not None else None
