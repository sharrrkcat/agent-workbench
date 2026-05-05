from pathlib import Path
from typing import Dict, Iterable, List

from ai_workbench.core.manifest_loader import load_capability_manifest
from ai_workbench.core.schema.capability import CapabilitySchema


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: Dict[str, CapabilitySchema] = {}

    def register(self, capability: CapabilitySchema) -> None:
        if capability.id in self._capabilities:
            raise ValueError(f"duplicate capability id: {capability.id}")
        self._capabilities[capability.id] = capability

    def load_from_directory(self, root: str | Path) -> None:
        for manifest_path in _iter_capability_manifests(root):
            self.register(load_capability_manifest(manifest_path))

    def get(self, capability_id: str) -> CapabilitySchema:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability id: {capability_id}") from exc

    def list(self) -> List[CapabilitySchema]:
        return list(self._capabilities.values())


def _iter_capability_manifests(root: str | Path) -> Iterable[Path]:
    path = Path(root)
    if path.is_file():
        yield path
        return

    yield from sorted(path.glob("*/capability.yaml"))

