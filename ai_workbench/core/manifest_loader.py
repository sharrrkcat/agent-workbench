from pathlib import Path
from typing import Any, Dict

import yaml

from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.capability import CapabilitySchema


def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"manifest must contain a YAML mapping: {manifest_path}")

    return data


def load_agent_manifest(path: str | Path) -> AgentSchema:
    return AgentSchema.model_validate(load_yaml_file(path))


def load_capability_manifest(path: str | Path) -> CapabilitySchema:
    return CapabilitySchema.model_validate(load_yaml_file(path))

