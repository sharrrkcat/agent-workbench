from pathlib import Path
from typing import Dict, Iterable, List

from ai_workbench.core.manifest_loader import load_agent_manifest
from ai_workbench.core.schema.agent import AgentSchema


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentSchema] = {}
        self._agent_dirs: Dict[str, Path] = {}

    def register(self, agent: AgentSchema, agent_dir: str | Path | None = None) -> None:
        if agent.id in self._agents:
            raise ValueError(f"duplicate agent id: {agent.id}")
        self._agents[agent.id] = agent
        if agent_dir is not None:
            self._agent_dirs[agent.id] = Path(agent_dir)

    def load_from_directory(self, root: str | Path) -> None:
        for manifest_path in _iter_agent_manifests(root):
            self.register(load_agent_manifest(manifest_path), agent_dir=manifest_path.parent)

    def get(self, agent_id: str) -> AgentSchema:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent id: {agent_id}") from exc

    def list(self) -> List[AgentSchema]:
        return list(self._agents.values())

    def get_agent_dir(self, agent_id: str) -> Path:
        try:
            return self._agent_dirs[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent directory for id: {agent_id}") from exc


def _iter_agent_manifests(root: str | Path) -> Iterable[Path]:
    path = Path(root)
    if path.is_file():
        yield path
        return

    yield from sorted(path.glob("*/agent.yaml"))
