from __future__ import annotations

from typing import Any

from ai_workbench.core.provider_inventory import is_internal_provider
from ai_workbench.core.schema.llm_profile import ProviderProfileSchema


LOCAL_RUNTIME_DEVICES = {"auto", "cpu", "cuda", "mps"}
DEFAULT_LOCAL_RUNTIME_DEVICE = "auto"
DEFAULT_LLAMA_CPP_GPU_LAYERS = 0
ONNX_EXECUTION_PROVIDERS = {"auto", "cuda", "cpu"}
DEFAULT_ONNX_EXECUTION_PROVIDER = "auto"


def normalize_local_runtime_device(value: Any, *, fallback: str = DEFAULT_LOCAL_RUNTIME_DEVICE) -> str:
    text = str(value or "").strip().lower()
    if text in LOCAL_RUNTIME_DEVICES:
        return text
    fallback_text = str(fallback or "").strip().lower()
    return fallback_text if fallback_text in LOCAL_RUNTIME_DEVICES else DEFAULT_LOCAL_RUNTIME_DEVICE


def normalize_llama_cpp_gpu_layers(value: Any, *, fallback: int = DEFAULT_LLAMA_CPP_GPU_LAYERS) -> int:
    if value in (None, ""):
        return fallback
    try:
        layers = int(value)
    except (TypeError, ValueError):
        return fallback
    if layers < -1:
        return fallback
    return layers


def normalize_onnx_execution_provider(value: Any, *, fallback: str = DEFAULT_ONNX_EXECUTION_PROVIDER) -> str:
    text = str(value or "").strip().lower()
    if text in ONNX_EXECUTION_PROVIDERS:
        return text
    fallback_text = str(fallback or "").strip().lower()
    return fallback_text if fallback_text in ONNX_EXECUTION_PROVIDERS else DEFAULT_ONNX_EXECUTION_PROVIDER


def provider_runtime_settings(provider: ProviderProfileSchema | None, *, legacy_device: str | None = None) -> dict[str, Any]:
    if provider is None or not is_internal_provider(getattr(provider, "provider", None)):
        return {
            "local_runtime_device": DEFAULT_LOCAL_RUNTIME_DEVICE,
            "llama_cpp_gpu_layers": DEFAULT_LLAMA_CPP_GPU_LAYERS,
            "onnx_execution_provider": DEFAULT_ONNX_EXECUTION_PROVIDER,
            "warnings": [],
        }
    metadata = provider.metadata if isinstance(provider.metadata, dict) else {}
    warnings: list[str] = []
    if provider.provider == "internal_transformers":
        configured = metadata.get("local_runtime_device")
        if configured in (None, "") and legacy_device:
            warnings.append("legacy_local_model_device_fallback")
            configured = legacy_device
        return {
            "local_runtime_device": normalize_local_runtime_device(configured),
            "llama_cpp_gpu_layers": DEFAULT_LLAMA_CPP_GPU_LAYERS,
            "onnx_execution_provider": DEFAULT_ONNX_EXECUTION_PROVIDER,
            "warnings": warnings,
        }
    if provider.provider == "internal_llama_cpp":
        return {
            "local_runtime_device": DEFAULT_LOCAL_RUNTIME_DEVICE,
            "llama_cpp_gpu_layers": normalize_llama_cpp_gpu_layers(metadata.get("llama_cpp_gpu_layers")),
            "onnx_execution_provider": DEFAULT_ONNX_EXECUTION_PROVIDER,
            "warnings": warnings,
        }
    if provider.provider == "internal_onnxruntime":
        return {
            "local_runtime_device": DEFAULT_LOCAL_RUNTIME_DEVICE,
            "llama_cpp_gpu_layers": DEFAULT_LLAMA_CPP_GPU_LAYERS,
            "onnx_execution_provider": normalize_onnx_execution_provider(metadata.get("onnx_execution_provider")),
            "warnings": warnings,
        }
    return {
        "local_runtime_device": DEFAULT_LOCAL_RUNTIME_DEVICE,
        "llama_cpp_gpu_layers": DEFAULT_LLAMA_CPP_GPU_LAYERS,
        "onnx_execution_provider": DEFAULT_ONNX_EXECUTION_PROVIDER,
        "warnings": warnings,
    }


def normalize_provider_runtime_metadata(provider: str, metadata: dict[str, Any] | None, *, legacy_device: str | None = None) -> dict[str, Any]:
    payload = dict(metadata or {})
    if provider == "internal_transformers":
        payload["local_runtime_device"] = normalize_local_runtime_device(
            payload.get("local_runtime_device"),
            fallback=normalize_local_runtime_device(legacy_device),
        )
        payload.pop("llama_cpp_gpu_layers", None)
        payload.pop("onnx_execution_provider", None)
    elif provider == "internal_llama_cpp":
        payload["llama_cpp_gpu_layers"] = normalize_llama_cpp_gpu_layers(payload.get("llama_cpp_gpu_layers"))
        payload.pop("local_runtime_device", None)
        payload.pop("onnx_execution_provider", None)
    elif provider == "internal_onnxruntime":
        payload["onnx_execution_provider"] = normalize_onnx_execution_provider(payload.get("onnx_execution_provider"))
        payload.pop("local_runtime_device", None)
        payload.pop("llama_cpp_gpu_layers", None)
    return payload
