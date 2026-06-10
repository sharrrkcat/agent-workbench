from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import threading
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class MultimodalEmbeddingInput:
    input_type: str
    image_base64: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class MultimodalEmbeddingResult:
    vectors: list[list[float]]
    dimensions: int | None = None


class MultimodalRuntimeUnavailable(Exception):
    pass


class MultimodalRuntimeError(Exception):
    pass


class MultimodalEmbeddingRuntime(Protocol):
    def embed(
        self,
        *,
        profile: Any,
        inputs: list[MultimodalEmbeddingInput],
        normalize: bool,
    ) -> MultimodalEmbeddingResult:
        ...


RuntimeFactory = Callable[[Any], MultimodalEmbeddingRuntime]
_FACTORIES: dict[str, RuntimeFactory] = {}


class MultimodalRuntimeCache:
    def __init__(self) -> None:
        self._runtimes: dict[tuple[str, str], MultimodalEmbeddingRuntime] = {}
        self._architectures: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    def get_or_create(self, profile: Any, factory: RuntimeFactory) -> MultimodalEmbeddingRuntime:
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


DEFAULT_MULTIMODAL_RUNTIME_CACHE = MultimodalRuntimeCache()


def register_multimodal_embedding_runtime_factory(architecture: str, factory: RuntimeFactory) -> None:
    _FACTORIES[str(architecture)] = factory


def unregister_multimodal_embedding_runtime_factory(architecture: str) -> None:
    _FACTORIES.pop(str(architecture), None)


def clear_multimodal_embedding_runtime_factories() -> None:
    _FACTORIES.clear()


def has_multimodal_embedding_runtime_factory() -> bool:
    return bool(_FACTORIES)


def get_multimodal_embedding_runtime(
    profile: Any,
    *,
    cache: MultimodalRuntimeCache = DEFAULT_MULTIMODAL_RUNTIME_CACHE,
) -> MultimodalEmbeddingRuntime:
    architecture = str(getattr(profile, "architecture", ""))
    factory = _FACTORIES.get(architecture)
    if factory is None:
        raise MultimodalRuntimeUnavailable("Multimodal embedding runtime is not available.")
    return cache.get_or_create(profile, factory)


def embed_multimodal_inputs(
    profile: Any,
    inputs: list[MultimodalEmbeddingInput],
    *,
    normalize: bool,
    cache: MultimodalRuntimeCache = DEFAULT_MULTIMODAL_RUNTIME_CACHE,
) -> MultimodalEmbeddingResult:
    try:
        runtime = get_multimodal_embedding_runtime(profile, cache=cache)
        result = runtime.embed(profile=profile, inputs=inputs, normalize=normalize)
    except MultimodalRuntimeUnavailable:
        raise
    except MultimodalRuntimeError:
        raise
    except Exception as exc:
        raise MultimodalRuntimeError("Multimodal embedding runtime failed.") from exc
    try:
        vectors = [[float(value) for value in vector] for vector in result.vectors]
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise ValueError("non-finite vector value")
    except Exception as exc:
        raise MultimodalRuntimeError("Multimodal embedding runtime returned invalid vectors.") from exc
    try:
        if len(vectors) != len(inputs):
            raise MultimodalRuntimeError("Multimodal embedding runtime returned the wrong number of vectors.")
        dimensions = len(vectors[0]) if vectors else 0
        if dimensions <= 0 or any(len(vector) != dimensions for vector in vectors):
            raise MultimodalRuntimeError("Multimodal embedding runtime returned invalid vector dimensions.")
        profile_dimensions = getattr(profile, "dimensions", None)
        if profile_dimensions is not None and int(profile_dimensions) != dimensions:
            raise MultimodalRuntimeError("Multimodal embedding runtime returned unexpected vector dimensions.")
    except MultimodalRuntimeError:
        raise
    except Exception as exc:
        raise MultimodalRuntimeError("Multimodal embedding runtime returned invalid vector dimensions.") from exc
    return MultimodalEmbeddingResult(vectors=vectors, dimensions=dimensions)


def multimodal_runtime_cache_status() -> dict[str, Any]:
    return DEFAULT_MULTIMODAL_RUNTIME_CACHE.status()


def clear_multimodal_runtime_cache(profile_id: str | None = None) -> int:
    if profile_id:
        return DEFAULT_MULTIMODAL_RUNTIME_CACHE.clear_profile(profile_id)
    return DEFAULT_MULTIMODAL_RUNTIME_CACHE.clear()


def profile_fingerprint(profile: Any) -> str:
    data = {
        "id": getattr(profile, "id", ""),
        "provider_profile_id": getattr(profile, "provider_profile_id", None),
        "provider_model_id": getattr(profile, "provider_model_id", ""),
        "architecture": getattr(profile, "architecture", ""),
        "backend": getattr(profile, "backend", ""),
        "embedding_space": getattr(profile, "embedding_space", None),
        "dimensions": getattr(profile, "dimensions", None),
        "normalize_default": getattr(profile, "normalize_default", None),
        "supported_input_types": list(getattr(profile, "supported_input_types", []) or []),
        "preprocessing_signature": getattr(profile, "preprocessing_signature", None),
        "pooling_strategy": getattr(profile, "pooling_strategy", None),
        "max_batch_size": getattr(profile, "max_batch_size", None),
        "metadata": getattr(profile, "metadata", {}) or {},
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_key(profile: Any) -> tuple[str, str]:
    return (str(getattr(profile, "id", "")), profile_fingerprint(profile))


def _best_effort_unload(runtime: MultimodalEmbeddingRuntime) -> None:
    unload = getattr(runtime, "unload", None)
    if callable(unload):
        try:
            unload()
        except Exception:
            return
