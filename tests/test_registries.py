from pathlib import Path

import pytest

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.manifest_loader import load_agent_manifest
from ai_workbench.core.schema.capability import CapabilitySchema


ROOT = Path(__file__).resolve().parents[1]


def test_command_registry_exposes_base64_commands() -> None:
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(ROOT / "capabilities")

    commands = CommandRegistry.from_capability_registry(capabilities)

    assert {command.name for command in commands.list()} == {"/base64", "/base64-decode"}
    assert commands.get("/base64").capability_id == "base64"
    assert commands.get("/base64").method == "encode"
    assert commands.get("/base64-decode").method == "decode"


def test_duplicate_agent_id_fails() -> None:
    registry = AgentRegistry()
    agent = load_agent_manifest(ROOT / "agents" / "chat" / "agent.yaml")

    registry.register(agent)

    with pytest.raises(ValueError, match="duplicate agent id: chat"):
        registry.register(agent)


def test_duplicate_command_name_fails() -> None:
    first = CapabilitySchema.model_validate(
        {
            "id": "first",
            "name": "First",
            "methods": [{"id": "encode"}],
            "commands": [{"name": "/same", "method": "encode"}],
        }
    )
    second = CapabilitySchema.model_validate(
        {
            "id": "second",
            "name": "Second",
            "methods": [{"id": "decode"}],
            "commands": [{"name": "/same", "method": "decode"}],
        }
    )

    registry = CommandRegistry()
    registry.register_capability(first)

    with pytest.raises(ValueError, match="duplicate command name: /same"):
        registry.register_capability(second)

