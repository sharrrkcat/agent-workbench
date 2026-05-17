import argparse
import inspect
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.core.manifest_loader import load_agent_manifest, load_capability_manifest
from ai_workbench.core.script import _load_module


ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PROFILE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")
ALLOWED_AGENT_TYPES = {"prompt", "script"}
ALLOWED_OUTPUT_PART_TYPES = {"text", "json", "file", "image", "audio", "video", "media_group", "parts"}


@dataclass
class CheckResult:
    agents: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.agents)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "agents": self.agents,
            "capabilities": self.capabilities,
            "commands": self.commands,
            "errors": self.errors,
            "warnings": self.warnings,
        }


AgentCheckResult = CheckResult


def check_agents(
    agents_root: str | Path = ROOT / "agents",
    capabilities_root: str | Path = ROOT / "capabilities",
    strict: bool = False,
) -> CheckResult:
    return check_workbench(agents_root=agents_root, capabilities_root=capabilities_root, strict=strict)


def check_workbench(
    agents_root: str | Path = ROOT / "agents",
    capabilities_root: str | Path = ROOT / "capabilities",
    strict: bool = False,
) -> CheckResult:
    result = CheckResult()
    agents_path = Path(agents_root)
    capabilities_path = Path(capabilities_root)

    capabilities = _check_capabilities(capabilities_path, result, strict=strict)
    _check_agents(agents_path, result, strict=strict, capability_ids=set(capabilities))

    if not result.agents:
        result.errors.append(f"{agents_path}: no agents found")
    if not result.capabilities:
        result.errors.append(f"{capabilities_path}: no capabilities found")
    return result


def print_result(result: CheckResult, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(result.as_json(), ensure_ascii=False, indent=2))
        return
    for warning in result.warnings:
        print(f"[WARN] {warning}")
    for error in result.errors:
        print(f"[FAIL] {error}")
    if result.ok:
        print(
            "[OK] Agent checks passed: "
            f"{len(result.agents)} agent(s), {len(result.capabilities)} capability(ies), {len(result.commands)} command(s)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Agent and Capability manifests.")
    parser.add_argument("--strict", action="store_true", help="run runtime and developer ergonomics checks")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--agents-root", default=str(ROOT / "agents"), help=argparse.SUPPRESS)
    parser.add_argument("--capabilities-root", default=str(ROOT / "capabilities"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    result = check_workbench(args.agents_root, args.capabilities_root, strict=args.strict)
    print_result(result, json_output=args.json)
    return 0 if result.ok else 1


def _check_agents(agents_path: Path, result: CheckResult, strict: bool, capability_ids: set[str]) -> None:
    seen_agent_ids: dict[str, Path] = {}
    for manifest_path in sorted(agents_path.glob("*/agent.yaml")):
        raw = _load_raw_yaml(manifest_path, result)
        if raw is None:
            continue

        try:
            agent = load_agent_manifest(manifest_path)
        except Exception as exc:
            result.errors.append(f"{manifest_path}: invalid agent manifest: {exc}")
            continue

        result.agents.append({"id": agent.id, "type": agent.type, "path": str(manifest_path)})

        if agent.id in seen_agent_ids:
            result.errors.append(
                f"{manifest_path}: agent '{agent.id}' duplicates id from {seen_agent_ids[agent.id]}"
            )
        else:
            seen_agent_ids[agent.id] = manifest_path

        for capability_id in agent.capabilities:
            if capability_id not in capability_ids:
                result.errors.append(f"{manifest_path}: agent '{agent.id}' references unknown capability '{capability_id}'")

        if not strict:
            if agent.type == "script":
                _check_script_agent(agent.id, agent.entry or "", manifest_path.parent, manifest_path, result)
            continue

        _require_fields(manifest_path, raw, ["id", "name", "type", "actions"], result)
        if agent.id != manifest_path.parent.name:
            result.errors.append(f"{manifest_path}: agent id '{agent.id}' must match directory '{manifest_path.parent.name}'")
        if not ID_RE.fullmatch(agent.id):
            result.errors.append(f"{manifest_path}: agent id '{agent.id}' must be lowercase snake_case")
        if agent.type not in ALLOWED_AGENT_TYPES:
            result.errors.append(f"{manifest_path}: agent '{agent.id}' has unsupported type '{agent.type}'")
        _check_actions(manifest_path, agent.id, agent.actions, result)
        _check_llm_profile(manifest_path, agent.id, raw, result)
        if agent.type == "prompt" and "llm" not in agent.capabilities:
            result.warnings.append(f"{manifest_path}: prompt agent '{agent.id}' should declare llm capability")

        if agent.type == "script":
            _check_script_agent(agent.id, agent.entry or "", manifest_path.parent, manifest_path, result)


def _check_capabilities(capabilities_path: Path, result: CheckResult, strict: bool) -> dict[str, Any]:
    capabilities: dict[str, Any] = {}
    command_names: dict[str, tuple[str, Path]] = {}

    for manifest_path in sorted(capabilities_path.glob("*/capability.yaml")):
        raw = _load_raw_yaml(manifest_path, result)
        if raw is None:
            continue
        if strict:
            _check_raw_command_argument_suggestions(manifest_path, raw, result)

        try:
            capability = load_capability_manifest(manifest_path)
        except Exception as exc:
            result.errors.append(f"{manifest_path}: invalid capability manifest: {exc}")
            continue

        result.capabilities.append({"id": capability.id, "path": str(manifest_path)})
        if capability.id in capabilities:
            result.errors.append(f"{manifest_path}: capability '{capability.id}' duplicates an earlier manifest")
        capabilities[capability.id] = capability

        method_ids = {method.id for method in capability.methods}
        runtime = None
        if strict:
            _require_fields(manifest_path, raw, ["id", "name", "methods"], result)
            if capability.id != manifest_path.parent.name:
                result.errors.append(
                    f"{manifest_path}: capability id '{capability.id}' must match directory '{manifest_path.parent.name}'"
                )
            if not ID_RE.fullmatch(capability.id):
                result.errors.append(f"{manifest_path}: capability id '{capability.id}' must be lowercase snake_case")
            runtime = _load_capability_runtime(capability.id, manifest_path.parent, manifest_path, result)

        for method in capability.methods:
            legacy_type = method.output.get("type") if isinstance(method.output, dict) else None
            if strict and legacy_type:
                result.errors.append(
                    f"{manifest_path}: capability '{capability.id}' method '{method.id}' uses unsupported output.type; use output.part_type"
                )
            part_type = method.output.get("part_type") if isinstance(method.output, dict) else None
            if strict and part_type and part_type not in ALLOWED_OUTPUT_PART_TYPES:
                result.errors.append(
                    f"{manifest_path}: capability '{capability.id}' method '{method.id}' has unsupported output.part_type '{part_type}'"
                )
            if strict and runtime is not None:
                runtime_method = getattr(runtime, method.id, None)
                if runtime_method is None or not callable(runtime_method):
                    result.errors.append(
                        f"{manifest_path}: capability '{capability.id}' method '{method.id}' is missing callable runtime method"
                    )

        for command in capability.commands:
            result.commands.append(
                {
                    "name": command.name,
                    "capability_id": capability.id,
                    "method": command.method,
                    "path": str(manifest_path),
                }
            )
            if command.name in command_names:
                existing_id, existing_path = command_names[command.name]
                result.errors.append(
                    f"{manifest_path}: command '{command.name}' from capability '{capability.id}' duplicates "
                    f"command from capability '{existing_id}' in {existing_path}"
                )
            else:
                command_names[command.name] = (capability.id, manifest_path)
            if strict and not command.name.startswith("/"):
                result.errors.append(f"{manifest_path}: command '{command.name}' must start with '/'")
            if strict and command.method not in method_ids:
                result.errors.append(
                    f"{manifest_path}: command '{command.name}' references missing method '{command.method}'"
                )

    return capabilities


def _check_raw_command_argument_suggestions(manifest_path: Path, raw: dict[str, Any], result: CheckResult) -> None:
    capability_id = str(raw.get("id") or "<unknown>")
    commands = raw.get("commands")
    if not isinstance(commands, list):
        return
    for index, raw_command in enumerate(commands):
        if not isinstance(raw_command, dict):
            continue
        command_name = str(raw_command.get("name") or f"<command {index}>")
        _check_argument_suggestions(manifest_path, capability_id, command_name, raw_command, result)


def _check_argument_suggestions(
    manifest_path: Path,
    capability_id: str,
    command_name: str,
    raw_command: dict[str, Any],
    result: CheckResult,
) -> None:
    field_name = "argument_suggestions"
    if field_name not in raw_command:
        return
    suggestions = raw_command.get(field_name)
    if not isinstance(suggestions, list):
        result.errors.append(
            f"{manifest_path}: capability '{capability_id}' command '{command_name}' field '{field_name}' must be an array"
        )
        return
    for index, suggestion in enumerate(suggestions):
        item_field = f"{field_name}[{index}]"
        if not isinstance(suggestion, dict):
            result.errors.append(
                f"{manifest_path}: capability '{capability_id}' command '{command_name}' field '{item_field}' must be an object"
            )
            continue
        value = suggestion.get("value")
        if "value" not in suggestion:
            result.errors.append(
                f"{manifest_path}: capability '{capability_id}' command '{command_name}' field '{item_field}.value' is required"
            )
        elif not isinstance(value, str) or not value.strip():
            result.errors.append(
                f"{manifest_path}: capability '{capability_id}' command '{command_name}' field '{item_field}.value' must be a non-empty string"
            )
        for optional_field in ("label", "description"):
            optional_value = suggestion.get(optional_field)
            if optional_value is not None and not isinstance(optional_value, str):
                result.errors.append(
                    f"{manifest_path}: capability '{capability_id}' command '{command_name}' field '{item_field}.{optional_field}' must be a string"
                )


def _check_actions(manifest_path: Path, agent_id: str, actions: list[Any], result: CheckResult) -> None:
    seen: set[str] = set()
    for action in actions:
        if action.id in seen:
            result.errors.append(f"{manifest_path}: agent '{agent_id}' has duplicate action id '{action.id}'")
        seen.add(action.id)
        if not ID_RE.fullmatch(action.id):
            result.errors.append(f"{manifest_path}: agent '{agent_id}' action '{action.id}' must be lowercase snake_case")
        if not (action.label or action.description):
            result.errors.append(
                f"{manifest_path}: agent '{agent_id}' action '{action.id}' must provide label or description"
            )


def _check_llm_profile(manifest_path: Path, agent_id: str, raw: dict[str, Any], result: CheckResult) -> None:
    llm = raw.get("llm")
    if not isinstance(llm, dict) or "profile" not in llm:
        return
    profile = llm.get("profile")
    if not isinstance(profile, str) or not profile.strip() or not PROFILE_RE.fullmatch(profile.strip()):
        result.errors.append(f"{manifest_path}: agent '{agent_id}' llm.profile must be a non-empty profile id or alias")


def _check_script_agent(
    agent_id: str,
    entry: str,
    agent_dir: Path,
    manifest_path: Path,
    result: CheckResult,
) -> None:
    if not entry:
        result.errors.append(f"{manifest_path}: script agent '{agent_id}' requires an entry field")
        return

    resolved_agent_dir = agent_dir.resolve()
    entry_path = (resolved_agent_dir / entry).resolve()
    try:
        entry_path.relative_to(resolved_agent_dir)
    except ValueError:
        result.errors.append(f"{manifest_path}: script entry must stay inside the agent directory for agent '{agent_id}'")
        return

    if not entry_path.is_file():
        result.errors.append(f"{manifest_path}: script agent '{agent_id}' entry not found: {entry}")
        return

    module_name = f"agent_workbench_check_agent_{agent_id}"
    try:
        module = _load_module(entry_path, module_name)
    except Exception as exc:
        result.errors.append(f"{manifest_path}: script agent '{agent_id}' import failed: {exc}")
        return

    run = getattr(module, "run", None)
    if run is None:
        result.errors.append(f"{manifest_path}: script agent '{agent_id}' entry must export run(ctx)")
        return
    if not callable(run) or not inspect.iscoroutinefunction(run):
        result.errors.append(f"{manifest_path}: script agent '{agent_id}' run(ctx) must be async")
        return

    signature = inspect.signature(run)
    parameters = list(signature.parameters.values())
    if not parameters or parameters[0].name != "ctx":
        result.errors.append(f"{manifest_path}: script agent '{agent_id}' run function must accept ctx as first argument")


def _load_capability_runtime(
    capability_id: str,
    capability_dir: Path,
    manifest_path: Path,
    result: CheckResult,
) -> Any:
    runtime_path = capability_dir / "__init__.py"
    if not runtime_path.is_file():
        result.errors.append(f"{manifest_path}: capability '{capability_id}' runtime file not found: __init__.py")
        return None

    module_name = f"agent_workbench_check_capability_{capability_id}"
    try:
        module = _load_module(runtime_path, module_name)
    except Exception as exc:
        result.errors.append(f"{manifest_path}: capability '{capability_id}' runtime import failed: {exc}")
        return None

    factory = getattr(module, "get_runtime", None)
    runtime_class = getattr(module, "CapabilityRuntime", None)
    if not callable(factory) and runtime_class is None:
        result.errors.append(f"{manifest_path}: capability '{capability_id}' must export get_runtime() or CapabilityRuntime")
        return None

    try:
        if callable(factory):
            return factory()
        return runtime_class()
    except Exception as exc:
        result.errors.append(f"{manifest_path}: capability '{capability_id}' runtime construction failed: {exc}")
        return None


def _load_raw_yaml(path: Path, result: CheckResult) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except Exception as exc:
        result.errors.append(f"{path}: could not read YAML: {exc}")
        return None
    if not isinstance(data, dict):
        result.errors.append(f"{path}: manifest must contain a YAML mapping")
        return None
    return data


def _require_fields(path: Path, raw: dict[str, Any], fields: list[str], result: CheckResult) -> None:
    for field_name in fields:
        if field_name not in raw:
            result.errors.append(f"{path}: missing required field '{field_name}'")


if __name__ == "__main__":
    raise SystemExit(main())
