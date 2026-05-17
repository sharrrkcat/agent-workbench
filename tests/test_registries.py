from pathlib import Path

import pytest

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.manifest_loader import load_agent_manifest
from ai_workbench.core.schema.capability import CapabilitySchema


ROOT = Path(__file__).resolve().parents[1]


def test_command_registry_exposes_codec_commands() -> None:
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(ROOT / "capabilities")

    commands = CommandRegistry.from_capability_registry(capabilities)

    names = {command.name for command in commands.list()}
    assert {"/encode", "/decode"}.issubset(names)
    assert "/base64" not in names
    assert "/base64-decode" not in names
    assert "/base64-image" not in names
    assert "/base64-to-image" not in names
    assert "/image-base64" not in names
    assert "/base64-encode-image" not in names
    assert commands.get("/encode").capability_id == "codec"
    assert commands.get("/encode").method == "encode"
    assert commands.get("/decode").capability_id == "codec"
    assert commands.get("/decode").method == "decode"
    assert [item.value for item in commands.get("/encode").argument_suggestions] == [
        "base64",
        "base64url",
        "url",
        "unicode",
        "hex",
        "qr",
    ]
    assert [item.value for item in commands.get("/decode").argument_suggestions] == [
        "base64",
        "base64url",
        "url",
        "unicode",
        "hex",
    ]


def test_command_registry_exposes_pet_command() -> None:
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(ROOT / "capabilities")

    commands = CommandRegistry.from_capability_registry(capabilities)

    assert commands.get("/pet").capability_id == "pet"
    assert commands.get("/pet").method == "command"
    assert [item.value for item in commands.get("/pet").argument_suggestions] == [
        "status",
        "wake",
        "tuck",
        "reload",
        "select",
    ]


def test_command_registry_exposes_single_read_file_command() -> None:
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(ROOT / "capabilities")

    commands = CommandRegistry.from_capability_registry(capabilities)
    names = {command.name for command in commands.list()}

    assert "/read-file" in names
    assert "/read-image" not in names
    assert "/read-audio" not in names
    assert "/file-audio" not in names
    assert commands.get("/read-file").capability_id == "file"
    assert commands.get("/read-file").method == "read_file"


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
