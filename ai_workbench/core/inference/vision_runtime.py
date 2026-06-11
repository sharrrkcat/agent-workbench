from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import threading
from typing import Any, Callable, Literal, Protocol


@dataclass(frozen=True)
class VisionRuntimeInput:
    input_type: Literal["image"] = "image"
    image_base64: str = ""


@dataclass(frozen=True)
class VisionTextData:
    type: Literal["text"]
    text: str


@dataclass(frozen=True)
class VisionObjectBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class VisionDetectedObject:
    label: str
    score: float
    box: VisionObjectBox


@dataclass(frozen=True)
class VisionObjectsData:
    type: Literal["objects"]
    objects: list[VisionDetectedObject]


VisionResultData = VisionTextData | VisionObjectsData


@dataclass(frozen=True)
class VisionRuntimeResult:
    data: VisionResultData | dict[str, Any]


class VisionRuntimeUnavailable(Exception):
    pass


class VisionRuntimeError(Exception):
    pass


class VisionRuntimeInvalidRequest(VisionRuntimeError):
    pass


class VisionRuntime(Protocol):
    def run(
        self,
        *,
        profile: Any,
        task: str,
        input: VisionRuntimeInput,
        options: dict[str, Any],
    ) -> VisionRuntimeResult:
        ...


RuntimeFactory = Callable[[Any], VisionRuntime]
_FACTORIES: dict[str, RuntimeFactory] = {}


class VisionRuntimeCache:
    def __init__(self) -> None:
        self._runtimes: dict[tuple[str, str], VisionRuntime] = {}
        self._architectures: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    def get_or_create(self, profile: Any, factory: RuntimeFactory) -> VisionRuntime:
        key = _cache_key(profile)
        with self._lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = factory(profile)
                self._runtimes[key] = runtime
                self._architectures[key] = str(getattr(profile, "architecture", "unknown"))
            return runtime

    def clear(self) -> int:
        with self._lock:
            removed = len(self._runtimes)
            for runtime in self._runtimes.values():
                _best_effort_unload(runtime)
            self._runtimes.clear()
            self._architectures.clear()
            return removed

    def clear_profile(self, profile_id: str) -> int:
        with self._lock:
            keys = [key for key in self._runtimes if key[0] == profile_id]
            for key in keys:
                _best_effort_unload(self._runtimes[key])
                del self._runtimes[key]
                self._architectures.pop(key, None)
            return len(keys)

    def status(self) -> dict[str, Any]:
        with self._lock:
            architecture_counts: dict[str, int] = {}
            for architecture in self._architectures.values():
                architecture_counts[architecture] = architecture_counts.get(architecture, 0) + 1
            return {
                "runtime_count": len(self._runtimes),
                "profile_count": len({key[0] for key in self._runtimes}),
                "architecture_counts": dict(sorted(architecture_counts.items())),
            }


DEFAULT_VISION_RUNTIME_CACHE = VisionRuntimeCache()


def register_vision_runtime_factory(architecture: str, factory: RuntimeFactory) -> None:
    _FACTORIES[str(architecture)] = factory


def unregister_vision_runtime_factory(architecture: str) -> None:
    _FACTORIES.pop(str(architecture), None)


def clear_vision_runtime_factories() -> None:
    _FACTORIES.clear()


def has_vision_runtime_factory() -> bool:
    return bool(_FACTORIES)


def get_vision_runtime(
    profile: Any,
    *,
    cache: VisionRuntimeCache = DEFAULT_VISION_RUNTIME_CACHE,
) -> VisionRuntime:
    architecture = str(getattr(profile, "architecture", ""))
    factory = _FACTORIES.get(architecture)
    if factory is None:
        raise VisionRuntimeUnavailable("Vision runtime is not available.")
    return cache.get_or_create(profile, factory)


def run_vision_task(
    profile: Any,
    *,
    task: str,
    input: VisionRuntimeInput,
    options: dict[str, Any],
    cache: VisionRuntimeCache = DEFAULT_VISION_RUNTIME_CACHE,
) -> VisionRuntimeResult:
    try:
        runtime = get_vision_runtime(profile, cache=cache)
        result = runtime.run(profile=profile, task=task, input=input, options=options)
    except VisionRuntimeUnavailable:
        raise
    except VisionRuntimeInvalidRequest:
        raise
    except VisionRuntimeError:
        raise
    except Exception as exc:
        raise VisionRuntimeError("Vision runtime failed.") from exc
    try:
        data = _validate_result_data(task, result.data)
    except VisionRuntimeError:
        raise
    except Exception as exc:
        raise VisionRuntimeError("Vision runtime returned invalid output.") from exc
    return VisionRuntimeResult(data=data)


def vision_runtime_cache_status() -> dict[str, Any]:
    return DEFAULT_VISION_RUNTIME_CACHE.status()


def clear_vision_runtime_cache(profile_id: str | None = None) -> int:
    if profile_id:
        return DEFAULT_VISION_RUNTIME_CACHE.clear_profile(profile_id)
    return DEFAULT_VISION_RUNTIME_CACHE.clear()


def profile_fingerprint(profile: Any) -> str:
    data = {
        "id": getattr(profile, "id", ""),
        "provider_profile_id": getattr(profile, "provider_profile_id", None),
        "provider_model_id": getattr(profile, "provider_model_id", ""),
        "architecture": getattr(profile, "architecture", ""),
        "backend": getattr(profile, "backend", ""),
        "supported_tasks": list(getattr(profile, "supported_tasks", []) or []),
        "max_batch_size": getattr(profile, "max_batch_size", None),
        "metadata": getattr(profile, "metadata", {}) or {},
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_key(profile: Any) -> tuple[str, str]:
    return (str(getattr(profile, "id", "")), profile_fingerprint(profile))


def _best_effort_unload(runtime: VisionRuntime) -> None:
    unload = getattr(runtime, "unload", None)
    if callable(unload):
        try:
            unload()
        except Exception:
            return


def _validate_result_data(task: str, value: Any) -> VisionResultData:
    raw = _dataclass_to_dict(value)
    if task in {"caption", "detailed_caption", "ocr"}:
        if not isinstance(raw, dict) or raw.get("type") != "text" or not isinstance(raw.get("text"), str):
            raise VisionRuntimeError("Vision runtime returned invalid text output.")
        return VisionTextData(type="text", text=raw["text"])
    if task == "object_detection":
        if not isinstance(raw, dict) or raw.get("type") != "objects" or not isinstance(raw.get("objects"), list):
            raise VisionRuntimeError("Vision runtime returned invalid object output.")
        objects: list[VisionDetectedObject] = []
        for item in raw["objects"]:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                raise VisionRuntimeError("Vision runtime returned invalid object output.")
            score = _finite_float(item.get("score"))
            if score < 0 or score > 1:
                raise VisionRuntimeError("Vision runtime returned invalid object score.")
            box = item.get("box")
            if not isinstance(box, dict):
                raise VisionRuntimeError("Vision runtime returned invalid object box.")
            parsed_box = VisionObjectBox(
                x_min=_normalized_float(box.get("x_min")),
                y_min=_normalized_float(box.get("y_min")),
                x_max=_normalized_float(box.get("x_max")),
                y_max=_normalized_float(box.get("y_max")),
            )
            if parsed_box.x_max < parsed_box.x_min or parsed_box.y_max < parsed_box.y_min:
                raise VisionRuntimeError("Vision runtime returned invalid object box.")
            objects.append(VisionDetectedObject(label=item["label"], score=score, box=parsed_box))
        return VisionObjectsData(type="objects", objects=objects)
    raise VisionRuntimeError("Vision task is not supported.")


def _dataclass_to_dict(value: Any) -> Any:
    if isinstance(value, VisionTextData):
        return {"type": value.type, "text": value.text}
    if isinstance(value, VisionObjectsData):
        return {
            "type": value.type,
            "objects": [
                {
                    "label": item.label,
                    "score": item.score,
                    "box": {
                        "x_min": item.box.x_min,
                        "y_min": item.box.y_min,
                        "x_max": item.box.x_max,
                        "y_max": item.box.y_max,
                    },
                }
                for item in value.objects
            ],
        }
    return value


def _finite_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite value")
    return result


def _normalized_float(value: Any) -> float:
    result = _finite_float(value)
    if result < 0 or result > 1:
        raise ValueError("coordinate out of range")
    return result
