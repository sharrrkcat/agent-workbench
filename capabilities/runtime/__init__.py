from __future__ import annotations

from ai_workbench.core.runtime_memory import expand_targets, format_memory_result


class CapabilityRuntime:
    def __init__(self) -> None:
        self._service = None

    def configure(self, service) -> None:
        self._service = service

    def free_memory(self, args: str = "", context: dict | None = None) -> str:
        target = (args or "").strip().lower()
        if not target:
            return "/free-memory [llm|comfyui|embedding|reranker|all]"
        targets = expand_targets([target])
        if self._service is None:
            raise RuntimeError("Runtime memory service is not configured.")
        return format_memory_result(self._service.free_memory(targets, context=context or {}))


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()
