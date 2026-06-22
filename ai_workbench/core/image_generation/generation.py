from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import inspect
import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ai_workbench.core.image_generation.profiles import ImageModelProfile, normalize_lora_ref
from ai_workbench.core.time import isoformat_utc, utc_now


ImageGenerationSampler = Literal["euler", "euler_a", "dpmpp_2m", "dpmpp_sde", "ddim"]
ImageGenerationScheduler = Literal["normal", "karras", "exponential", "simple"]
ImageGenerationJobStatus = Literal["queued", "running", "cancelling", "completed", "failed", "cancelled"]

SUPPORTED_SAMPLERS: tuple[ImageGenerationSampler, ...] = ("euler", "euler_a", "dpmpp_2m", "dpmpp_sde", "ddim")
SUPPORTED_SCHEDULERS: tuple[ImageGenerationScheduler, ...] = ("normal", "karras", "exponential", "simple")
MAX_IMAGE_GENERATION_SEED = 2**32 - 1
TERMINAL_IMAGE_GENERATION_JOB_STATUSES = {"completed", "failed", "cancelled"}


class ImageGenerationError(ValueError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class Txt2ImgLora(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    weight: float = Field(default=1.0, ge=-4.0, le=4.0)

    @field_validator("ref", mode="before")
    @classmethod
    def _ref(cls, value: Any) -> str:
        return normalize_lora_ref(value)


class Txt2ImgRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id_or_alias: str = Field(min_length=1)
    positive_prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str = Field(default="", max_length=8000)
    width: int = Field(default=1024, ge=64, le=2048)
    height: int = Field(default=1024, ge=64, le=2048)
    steps: int = Field(default=30, ge=1, le=150)
    cfg: float = Field(default=7.0, ge=0.0, le=30.0)
    sampler: ImageGenerationSampler = "euler"
    scheduler: ImageGenerationScheduler = "normal"
    seed: int | None = Field(default=None, ge=0, le=MAX_IMAGE_GENERATION_SEED)
    batch_size: int = Field(default=1, ge=1, le=4)
    loras: list[Txt2ImgLora] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_prompt_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "positive_prompt" not in data and "prompt" in data:
            data = dict(data)
            data["positive_prompt"] = data.pop("prompt")
        return data

    @field_validator("profile_id_or_alias", "positive_prompt", "negative_prompt", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("width", "height")
    @classmethod
    def _multiple_of_eight(cls, value: int) -> int:
        if value % 8 != 0:
            raise ValueError("must be a multiple of 8")
        return value

    @field_validator("cfg")
    @classmethod
    def _cfg(cls, value: float) -> float:
        return round(float(value), 3)

    def normalized(self) -> "Txt2ImgRequest":
        seed = self.seed if self.seed is not None else deterministic_seed(self)
        return self.model_copy(update={"seed": seed})

    def public_summary(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "task": "txt2img",
            "profile_id_or_alias": normalized.profile_id_or_alias,
            "width": normalized.width,
            "height": normalized.height,
            "steps": normalized.steps,
            "cfg": normalized.cfg,
            "sampler": normalized.sampler,
            "scheduler": normalized.scheduler,
            "seed": normalized.seed,
            "batch_size": normalized.batch_size,
            "lora_count": len(normalized.loras),
            "positive_prompt_chars": len(normalized.positive_prompt),
            "negative_prompt_chars": len(normalized.negative_prompt),
            "positive_prompt_sha256": _short_hash(normalized.positive_prompt),
            "negative_prompt_sha256": _short_hash(normalized.negative_prompt) if normalized.negative_prompt else "",
        }


class GeneratedImagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    filename: str
    mime_type: str = "image/png"
    width: int
    height: int
    seed: int
    size_bytes: int
    data_base64: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Txt2ImgResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: f"img_{uuid4().hex}")
    backend: str = "fake"
    real_generation: bool = False
    profile: dict[str, Any]
    request: dict[str, Any]
    images: list[GeneratedImagePayload]
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ImageGenerationJob:
    request_id: str
    run_id: str
    profile_id: str
    profile_alias: str | None
    task: str
    request: dict[str, Any]
    status: ImageGenerationJobStatus = "queued"
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=utc_now)
    queued_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    def public_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id or None,
            "profile_id": self.profile_id,
            "profile_alias": self.profile_alias,
            "task": self.task,
            "status": self.status,
            "cancel_requested": self.cancel_requested,
            "created_at": isoformat_utc(self.created_at),
            "queued_at": isoformat_utc(self.queued_at),
            "started_at": isoformat_utc(self.started_at) if self.started_at else None,
            "finished_at": isoformat_utc(self.finished_at) if self.finished_at else None,
            "queue_wait_ms": _duration_ms(self.queued_at, self.started_at or self.finished_at),
            "execution_ms": _duration_ms(self.started_at, self.finished_at),
            "request": dict(self.request),
            "error_code": self.error_code,
        }

    def queue_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id or None,
            "status": self.status,
            "queued_at": isoformat_utc(self.queued_at),
            "started_at": isoformat_utc(self.started_at) if self.started_at else None,
            "finished_at": isoformat_utc(self.finished_at) if self.finished_at else None,
            "queue_wait_ms": _duration_ms(self.queued_at, self.started_at or self.finished_at),
            "execution_ms": _duration_ms(self.started_at, self.finished_at),
            "cancel_requested": self.cancel_requested,
        }


def deterministic_seed(request: Txt2ImgRequest) -> int:
    data = "|".join(
        [
            request.profile_id_or_alias,
            request.positive_prompt,
            request.negative_prompt,
            str(request.width),
            str(request.height),
            str(request.steps),
            str(request.cfg),
            request.sampler,
            request.scheduler,
            str(request.batch_size),
            repr([lora.model_dump() for lora in request.loras]),
        ]
    )
    return int(hashlib.sha256(data.encode("utf-8")).hexdigest()[:8], 16)


class FakeTxt2ImgRuntime:
    backend = "fake"
    real_generation = False

    def request_id(self, profile: ImageModelProfile, request: Txt2ImgRequest) -> str:
        return "img_" + uuid4().hex

    def generate(self, profile: ImageModelProfile, request: Txt2ImgRequest, request_id: str | None = None) -> Txt2ImgResult:
        normalized = request.normalized()
        request_summary = normalized.public_summary()
        profile_summary = _public_profile(profile)
        request_id = request_id or self.request_id(profile, normalized)
        images: list[GeneratedImagePayload] = []
        for index in range(normalized.batch_size):
            image_seed = (int(normalized.seed or 0) + index) % (MAX_IMAGE_GENERATION_SEED + 1)
            png = _fake_png(normalized.width, normalized.height, profile, normalized, image_seed)
            images.append(
                GeneratedImagePayload(
                    index=index,
                    filename=f"image-generation-{request_id}-{index + 1}.png",
                    width=normalized.width,
                    height=normalized.height,
                    seed=image_seed,
                    size_bytes=len(png),
                    data_base64=base64.b64encode(png).decode("ascii"),
                    metadata={
                        "source": "image_generation",
                        "backend": self.backend,
                        "request_id": request_id,
                        "profile_id": profile.id,
                        "profile_alias": profile.alias,
                        "seed": image_seed,
                    },
                )
            )
        return Txt2ImgResult(
            request_id=request_id,
            backend=self.backend,
            real_generation=self.real_generation,
            profile=profile_summary,
            request=request_summary,
            images=images,
            metadata={
                "kind": "image_generation_txt2img",
                "backend": self.backend,
                "real_generation": self.real_generation,
                "request_id": request_id,
                "output_count": len(images),
            },
        )


class ImageGenerationService:
    def __init__(
        self,
        profile_store: Any = None,
        repo_root: Any = None,
        runtime: FakeTxt2ImgRuntime | None = None,
        max_concurrent: int = 1,
    ) -> None:
        self.profile_store = profile_store
        self.repo_root = repo_root
        self.runtime = runtime or FakeTxt2ImgRuntime()
        self.max_concurrent = max(1, int(max_concurrent or 1))
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._jobs: dict[str, ImageGenerationJob] = {}
        self._recent_job_ids: list[str] = []
        self._cache: dict[str, dict[str, Any]] = {}

    def configure(
        self,
        profile_store: Any = None,
        repo_root: Any = None,
        runtime: FakeTxt2ImgRuntime | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        if profile_store is not None:
            self.profile_store = profile_store
        if repo_root is not None:
            self.repo_root = repo_root
        if runtime is not None:
            self.runtime = runtime
        if max_concurrent is not None and int(max_concurrent) != self.max_concurrent:
            self.max_concurrent = max(1, int(max_concurrent))
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

    def status(self) -> dict[str, Any]:
        profiles = self._profiles()
        queue = self.queue_status()
        return {
            "ok": True,
            "service": "internal",
            "profiles_total": len(profiles),
            "profiles_enabled": sum(1 for profile in profiles if profile.enabled),
            "supported_tasks": ["txt2img"],
            "supported_architectures": ["sd15", "sdxl", "z_image"],
            "runtime": {
                "available": True,
                "status": "ready",
                "backend": self.runtime.backend,
                "real_generation": self.runtime.real_generation,
                "supports_queue": True,
                "supports_cancel": True,
                "supports_unload": True,
            },
            "queue": {
                "max_concurrent": queue["max_concurrent"],
                "active_count": queue["active_count"],
                "queued_count": queue["queued_count"],
            },
            "cache": queue["cache"],
        }

    def list_model_profiles(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        profiles = self._profiles()
        if enabled_only:
            profiles = [profile for profile in profiles if profile.enabled]
        return [profile.model_dump() for profile in profiles]

    def validate_txt2img(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request, profile = self._resolve_txt2img_request(payload, **kwargs)
        normalized = request.normalized()
        return {
            "valid": True,
            "profile": _public_profile(profile),
            "request": normalized.public_summary(),
            "runtime": {
                "backend": self.runtime.backend,
                "real_generation": self.runtime.real_generation,
            },
        }

    async def txt2img(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request, profile = self._resolve_txt2img_request(payload, **kwargs)
        normalized = request.normalized()
        job = self._create_job(profile, normalized, context=context)
        self._remember_job(job)
        try:
            return await self._run_job(job, profile, normalized)
        except asyncio.CancelledError:
            self._mark_job_cancelled(job, "Run was cancelled.")
            raise
        except ImageGenerationError:
            raise
        except Exception as exc:
            self._mark_job_failed(job, "IMAGE_GENERATION_FAILED", str(exc) or "Image generation failed.")
            raise

    def queue_status(self) -> dict[str, Any]:
        active = [job for job in self._jobs.values() if job.status in {"running", "cancelling"}]
        queued = [job for job in self._jobs.values() if job.status == "queued"]
        visible = sorted([*active, *queued], key=lambda job: job.created_at)
        return {
            "backend": self.runtime.backend,
            "real_generation": self.runtime.real_generation,
            "max_concurrent": self.max_concurrent,
            "active_count": len(active),
            "queued_count": len(queued),
            "active_requests": [job.public_summary() for job in visible],
            "cache": self.cache_status(),
        }

    def cache_status(self) -> dict[str, Any]:
        return {
            "backend": self.runtime.backend,
            "real_generation": self.runtime.real_generation,
            "cached_profiles": len(self._cache),
            "profile_ids": sorted(self._cache),
        }

    def cancel(self, request_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        request_id = str(request_id or "").strip()
        run_id = str(run_id or "").strip()
        if not request_id and not run_id:
            raise ImageGenerationError("INVALID_IMAGE_GENERATION_CANCEL_REQUEST", "request_id or run_id is required.")
        matches = [
            job
            for job in self._jobs.values()
            if (request_id and job.request_id == request_id) or (run_id and job.run_id == run_id)
        ]
        if not matches:
            return {"ok": False, "status": "not_found", "request_id": request_id or None, "run_id": run_id or None}
        changed = 0
        for job in matches:
            job.cancel_requested = True
            if job.status in {"queued", "running"}:
                job.status = "cancelling"
                changed += 1
        return {
            "ok": True,
            "status": "cancel_requested" if changed else "already_terminal",
            "request_id": request_id or None,
            "run_id": run_id or None,
            "matched": len(matches),
            "changed": changed,
        }

    def unload(self, profile_id_or_alias: str | None = None) -> dict[str, Any]:
        profile_id = ""
        profile_alias = ""
        if profile_id_or_alias:
            try:
                profile = self._get_profile(str(profile_id_or_alias))
                profile_id = profile.id
                profile_alias = profile.alias
            except ImageGenerationError:
                return {
                    "ok": False,
                    "target": "image_generation",
                    "status": "not_found",
                    "profile_id_or_alias": str(profile_id_or_alias),
                    "removed": 0,
                    "message": "Image generation model profile not found.",
                }
        busy = [
            job
            for job in self._jobs.values()
            if job.status not in TERMINAL_IMAGE_GENERATION_JOB_STATUSES
            and (not profile_id or job.profile_id == profile_id)
        ]
        if busy:
            return {
                "ok": False,
                "target": "image_generation",
                "status": "busy",
                "profile_id": profile_id or None,
                "profile_alias": profile_alias or None,
                "active_count": len(busy),
                "removed": 0,
                "message": "Image generation is busy.",
            }
        keys = [key for key in self._cache if not profile_id or key == profile_id]
        for key in keys:
            self._cache.pop(key, None)
        return {
            "ok": True,
            "target": "image_generation",
            "status": "freed" if keys else "skipped",
            "profile_id": profile_id or None,
            "profile_alias": profile_alias or None,
            "removed": len(keys),
            "message": "Freed." if keys else "No image generation runtime cache loaded.",
        }

    def _resolve_txt2img_request(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> tuple[Txt2ImgRequest, ImageModelProfile]:
        if self.profile_store is None:
            raise ImageGenerationError("IMAGE_GENERATION_NOT_CONFIGURED", "Image generation service is not configured.")
        values = dict(payload or {})
        values.update({key: value for key, value in kwargs.items() if key != "context"})
        request = _parse_request(values)
        profile = self._get_profile(request.profile_id_or_alias)
        if not profile.enabled:
            raise ImageGenerationError("IMAGE_GENERATION_MODEL_DISABLED", f"Image generation model profile is disabled: {profile.alias}")
        if "txt2img" not in profile.supported_tasks:
            raise ImageGenerationError(
                "IMAGE_GENERATION_TASK_UNSUPPORTED",
                f"Image generation model profile does not support txt2img: {profile.alias}",
            )
        return request, profile

    def _get_profile(self, profile_id_or_alias: str) -> ImageModelProfile:
        try:
            return self.profile_store.get_by_id_or_alias(profile_id_or_alias)
        except KeyError as exc:
            raise ImageGenerationError(
                "IMAGE_GENERATION_MODEL_NOT_FOUND",
                f"Image generation model profile not found: {profile_id_or_alias}",
            ) from exc

    def _profiles(self) -> list[ImageModelProfile]:
        if self.profile_store is None:
            return []
        return list(self.profile_store.list())

    def _create_job(
        self,
        profile: ImageModelProfile,
        request: Txt2ImgRequest,
        context: dict[str, Any] | None = None,
    ) -> ImageGenerationJob:
        request_id = self._new_request_id(profile, request)
        return ImageGenerationJob(
            request_id=request_id,
            run_id=str((context or {}).get("run_id") or ""),
            profile_id=profile.id,
            profile_alias=profile.alias,
            task="txt2img",
            request=request.public_summary(),
        )

    def _new_request_id(self, profile: ImageModelProfile, request: Txt2ImgRequest) -> str:
        make_request_id = getattr(self.runtime, "request_id", None)
        if callable(make_request_id):
            value = make_request_id(profile, request)
            if value:
                return str(value)
        return "img_" + uuid4().hex

    def _remember_job(self, job: ImageGenerationJob) -> None:
        self._jobs[job.request_id] = job
        self._recent_job_ids.append(job.request_id)
        self._prune_jobs()

    def _prune_jobs(self, keep: int = 40) -> None:
        self._recent_job_ids = [request_id for request_id in self._recent_job_ids if request_id in self._jobs]
        while len(self._recent_job_ids) > keep:
            removable = next(
                (
                    request_id
                    for request_id in self._recent_job_ids
                    if self._jobs[request_id].status in TERMINAL_IMAGE_GENERATION_JOB_STATUSES
                ),
                None,
            )
            if removable is None:
                return
            self._recent_job_ids.remove(removable)
            self._jobs.pop(removable, None)

    async def _run_job(self, job: ImageGenerationJob, profile: ImageModelProfile, request: Txt2ImgRequest) -> dict[str, Any]:
        if job.cancel_requested:
            self._mark_job_cancelled(job, "Image generation was cancelled before start.")
            raise ImageGenerationError("IMAGE_GENERATION_CANCELLED", "Image generation was cancelled.", {"request_id": job.request_id})
        async with self._semaphore:
            if job.cancel_requested or job.status == "cancelling":
                self._mark_job_cancelled(job, "Image generation was cancelled before start.")
                raise ImageGenerationError("IMAGE_GENERATION_CANCELLED", "Image generation was cancelled.", {"request_id": job.request_id})
            job.status = "running"
            job.started_at = utc_now()
            self._touch_cache(profile)
            try:
                result = self._call_generate(profile, request, job.request_id)
                if inspect.isawaitable(result):
                    result = await result
                if job.cancel_requested or job.status == "cancelling":
                    self._mark_job_cancelled(job, "Image generation was cancelled.")
                    raise ImageGenerationError("IMAGE_GENERATION_CANCELLED", "Image generation was cancelled.", {"request_id": job.request_id})
            except asyncio.CancelledError:
                self._mark_job_cancelled(job, "Run was cancelled.")
                raise
            except ImageGenerationError as exc:
                if job.status not in TERMINAL_IMAGE_GENERATION_JOB_STATUSES:
                    self._mark_job_failed(job, exc.code, exc.message)
                raise
            except Exception as exc:
                self._mark_job_failed(job, "IMAGE_GENERATION_FAILED", str(exc) or "Image generation failed.")
                raise
            job.status = "completed"
            job.finished_at = utc_now()
            payload = result.model_dump() if isinstance(result, BaseModel) else dict(result)
            queue_metadata = job.queue_metadata()
            payload["queue"] = queue_metadata
            metadata = dict(payload.get("metadata") or {})
            metadata["queue"] = queue_metadata
            payload["metadata"] = metadata
            return payload

    def _call_generate(self, profile: ImageModelProfile, request: Txt2ImgRequest, request_id: str) -> Any:
        generate = getattr(self.runtime, "generate")
        try:
            parameters = inspect.signature(generate).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "request_id" in parameters:
            return generate(profile, request, request_id=request_id)
        return generate(profile, request)

    def _touch_cache(self, profile: ImageModelProfile) -> None:
        now = utc_now()
        existing = dict(self._cache.get(profile.id) or {})
        self._cache[profile.id] = {
            "profile_id": profile.id,
            "profile_alias": profile.alias,
            "backend": self.runtime.backend,
            "real_generation": self.runtime.real_generation,
            "loaded_at": existing.get("loaded_at") or isoformat_utc(now),
            "last_used_at": isoformat_utc(now),
            "use_count": int(existing.get("use_count") or 0) + 1,
        }

    def _mark_job_cancelled(self, job: ImageGenerationJob, message: str) -> None:
        job.status = "cancelled"
        job.cancel_requested = True
        job.finished_at = utc_now()
        job.error_code = "IMAGE_GENERATION_CANCELLED"
        job.error_message = message

    def _mark_job_failed(self, job: ImageGenerationJob, code: str, message: str) -> None:
        job.status = "failed"
        job.finished_at = utc_now()
        job.error_code = code
        job.error_message = message


def _parse_request(values: dict[str, Any]) -> Txt2ImgRequest:
    try:
        return Txt2ImgRequest.model_validate(values)
    except ValidationError as exc:
        error = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(item) for item in error.get("loc", []))
        message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
        raise ImageGenerationError("INVALID_IMAGE_GENERATION_REQUEST", message, {"errors": exc.errors()}) from exc


def _public_profile(profile: ImageModelProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "alias": profile.alias,
        "name": profile.name,
        "architecture": profile.architecture,
        "variant": profile.variant,
        "checkpoint_ref": profile.checkpoint_ref,
        "vae_ref": profile.vae_ref,
        "dtype": profile.dtype,
        "device": profile.device,
        "clip_skip": profile.clip_skip,
    }


def _fake_png(width: int, height: int, profile: ImageModelProfile, request: Txt2ImgRequest, seed: int) -> bytes:
    digest = hashlib.sha256(
        repr(
            {
                "profile": profile.alias,
                "prompt": request.positive_prompt,
                "negative": request.negative_prompt,
                "seed": seed,
                "width": width,
                "height": height,
            }
        ).encode("utf-8")
    ).digest()
    color = bytes([digest[0], digest[7], digest[14]])
    row = b"\x00" + color * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _short_hash(value: Any, length: int = 12) -> str:
    if isinstance(value, str):
        data = value
    else:
        data = repr(value)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:length]


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))
