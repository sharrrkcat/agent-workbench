import importlib
from pathlib import Path
from typing import Any, Callable, Dict


class CapabilityRuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: Dict[str, Any] = {}

    def load_from_directory(self, root: str | Path) -> None:
        path = Path(root)
        for manifest_path in sorted(path.glob("*/capability.yaml")):
            capability_id = manifest_path.parent.name
            self.register(capability_id, load_capability_runtime(capability_id))

    def register(self, capability_id: str, runtime: Any) -> None:
        if capability_id in self._runtimes:
            raise ValueError(f"duplicate capability runtime id: {capability_id}")
        self._runtimes[capability_id] = runtime

    def replace(self, capability_id: str, runtime: Any) -> None:
        self._runtimes[capability_id] = runtime

    def get_runtime(self, capability_id: str) -> Any:
        try:
            return self._runtimes[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability runtime id: {capability_id}") from exc

    def get_method(self, capability_id: str, method_id: str) -> Callable[[str], Any]:
        runtime = self.get_runtime(capability_id)

        method = getattr(runtime, method_id, None)
        if method is None or not callable(method):
            raise KeyError(f"unknown runtime method: {capability_id}.{method_id}")
        return method


def load_capability_runtime(capability_id: str) -> Any:
    module = importlib.import_module(f"capabilities.{capability_id}")

    factory = getattr(module, "get_runtime", None)
    if callable(factory):
        return factory()

    runtime_class = getattr(module, "CapabilityRuntime", None)
    if runtime_class is not None:
        return runtime_class()

    return module
