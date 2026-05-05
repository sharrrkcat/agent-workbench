import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.manifest_loader import load_agent_manifest
from ai_workbench.core.script import _load_module


@dataclass
class AgentCheckResult:
    checked: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_agents(
    agents_root: str | Path = ROOT / "agents",
    capabilities_root: str | Path = ROOT / "capabilities",
) -> AgentCheckResult:
    result = AgentCheckResult()
    agents_path = Path(agents_root)
    capability_ids = _load_capability_ids(Path(capabilities_root), result)
    seen_agent_ids: dict[str, Path] = {}

    for manifest_path in sorted(agents_path.glob("*/agent.yaml")):
        result.checked += 1
        try:
            agent = load_agent_manifest(manifest_path)
        except Exception as exc:
            result.errors.append(f"{manifest_path}: invalid manifest: {exc}")
            continue

        if agent.id in seen_agent_ids:
            result.errors.append(
                f"{manifest_path}: duplicate agent id '{agent.id}' also declared in {seen_agent_ids[agent.id]}"
            )
        else:
            seen_agent_ids[agent.id] = manifest_path

        for capability_id in agent.capabilities:
            if capability_id not in capability_ids:
                result.errors.append(f"{manifest_path}: unknown capability reference '{capability_id}'")

        if agent.type == "script":
            _check_script_agent(agent.id, agent.entry or "", manifest_path.parent, manifest_path, result)

    if result.checked == 0:
        result.errors.append(f"{agents_path}: no agents found")
    return result


def print_result(result: AgentCheckResult) -> None:
    for warning in result.warnings:
        print(f"[WARN] {warning}")
    for error in result.errors:
        print(f"[FAIL] {error}")
    if result.ok:
        print(f"[OK] Agent checks passed: {result.checked} manifest(s)")


def main() -> int:
    result = check_agents()
    print_result(result)
    return 0 if result.ok else 1


def _load_capability_ids(capabilities_root: Path, result: AgentCheckResult) -> set[str]:
    registry = CapabilityRegistry()
    try:
        registry.load_from_directory(capabilities_root)
    except Exception as exc:
        result.errors.append(f"{capabilities_root}: capability manifests failed to load: {exc}")
        return set()
    return {capability.id for capability in registry.list()}


def _check_script_agent(
    agent_id: str,
    entry: str,
    agent_dir: Path,
    manifest_path: Path,
    result: AgentCheckResult,
) -> None:
    if not entry:
        result.errors.append(f"{manifest_path}: script agent requires an entry field")
        return

    resolved_agent_dir = agent_dir.resolve()
    entry_path = (resolved_agent_dir / entry).resolve()
    try:
        entry_path.relative_to(resolved_agent_dir)
    except ValueError:
        result.errors.append(f"{manifest_path}: script entry must stay inside the agent directory")
        return

    if not entry_path.is_file():
        result.errors.append(f"{manifest_path}: script entry not found: {entry}")
        return

    module_name = f"agent_workbench_check_agent_{agent_id}"
    try:
        module = _load_module(entry_path, module_name)
    except Exception as exc:
        result.errors.append(f"{manifest_path}: script import failed: {exc}")
        return

    run = getattr(module, "run", None)
    if run is None:
        result.errors.append(f"{manifest_path}: script entry must export run(ctx)")
        return
    if not inspect.iscoroutinefunction(run):
        result.errors.append(f"{manifest_path}: script run(ctx) must be async")
        return

    signature = inspect.signature(run)
    parameters = list(signature.parameters.values())
    if not parameters or parameters[0].name != "ctx":
        result.errors.append(f"{manifest_path}: script run function must accept ctx as its first argument")


if __name__ == "__main__":
    raise SystemExit(main())
