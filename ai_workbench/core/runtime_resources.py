from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import timezone
from typing import Any

from ai_workbench.core.time import utc_now


RESOURCE_CACHE_TTL_SECONDS = 3.0


@dataclass
class RuntimeResourcesService:
    cache_ttl_seconds: float = RESOURCE_CACHE_TTL_SECONDS
    _cached: dict[str, Any] | None = field(default=None, init=False)
    _cached_at: float = field(default=0.0, init=False)

    def resources(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_ttl_seconds:
            return self._cached
        payload = self._sample_resources()
        self._cached = payload
        self._cached_at = now
        return payload

    def _sample_resources(self) -> dict[str, Any]:
        psutil = _import_psutil()
        return {
            "cpu": _cpu_status(psutil),
            "memory": _memory_status(psutil),
            "gpus": _gpu_statuses(),
            "process": _process_status(psutil),
            "updated_at": utc_now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def _cpu_status(psutil: Any) -> dict[str, Any]:
    if psutil is None:
        return {"available": False, "percent": None, "reason": "psutil unavailable"}
    try:
        return {"available": True, "percent": float(psutil.cpu_percent(interval=None))}
    except Exception as exc:
        return {"available": False, "percent": None, "reason": str(exc) or "CPU unavailable"}


def _memory_status(psutil: Any) -> dict[str, Any]:
    if psutil is None:
        return {"available": False, "used_bytes": None, "total_bytes": None, "percent": None, "reason": "psutil unavailable"}
    try:
        memory = psutil.virtual_memory()
        return {
            "available": True,
            "used_bytes": int(memory.used),
            "total_bytes": int(memory.total),
            "percent": float(memory.percent),
        }
    except Exception as exc:
        return {"available": False, "used_bytes": None, "total_bytes": None, "percent": None, "reason": str(exc) or "RAM unavailable"}


def _process_status(psutil: Any) -> dict[str, Any]:
    if psutil is None:
        return {"backend_memory_bytes": None, "reason": "psutil unavailable"}
    try:
        process = psutil.Process(os.getpid())
        return {"backend_memory_bytes": int(process.memory_info().rss)}
    except Exception as exc:
        return {"backend_memory_bytes": None, "reason": str(exc) or "Process memory unavailable"}


def _gpu_statuses() -> list[dict[str, Any]]:
    nvml = _import_nvml()
    if nvml is None:
        return [_unavailable_gpu()]
    try:
        nvml.nvmlInit()
        count = int(nvml.nvmlDeviceGetCount())
        gpus: list[dict[str, Any]] = []
        for index in range(count):
            handle = nvml.nvmlDeviceGetHandleByIndex(index)
            name = nvml.nvmlDeviceGetName(handle)
            utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
            memory = nvml.nvmlDeviceGetMemoryInfo(handle)
            total = int(memory.total)
            used = int(memory.used)
            gpus.append(
                {
                    "index": index,
                    "name": name.decode("utf-8", errors="replace") if isinstance(name, bytes) else str(name),
                    "available": True,
                    "utilization_percent": float(utilization.gpu),
                    "memory_used_bytes": used,
                    "memory_total_bytes": total,
                    "memory_percent": (used / total * 100.0) if total else None,
                    "backend": "nvml",
                }
            )
        return gpus or [_unavailable_gpu("No GPU devices reported by NVML.")]
    except Exception as exc:
        return [_unavailable_gpu(str(exc) or "NVML unavailable.")]
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:
            pass


def _unavailable_gpu(reason: str = "NVML unavailable.") -> dict[str, Any]:
    return {
        "index": 0,
        "name": "",
        "available": False,
        "utilization_percent": None,
        "memory_used_bytes": None,
        "memory_total_bytes": None,
        "memory_percent": None,
        "backend": "unavailable",
        "reason": reason,
    }


def _import_psutil() -> Any:
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _import_nvml() -> Any:
    for module_name in ("pynvml", "nvidia_smi"):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        if hasattr(module, "nvmlInit"):
            return module
    return None
