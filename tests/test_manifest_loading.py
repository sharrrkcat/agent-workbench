from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_workbench.core.manifest_loader import load_agent_manifest, load_capability_manifest
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.capability import CapabilitySchema


ROOT = Path(__file__).resolve().parents[1]


def test_agent_manifests_load() -> None:
    chat = load_agent_manifest(ROOT / "agents" / "chat" / "agent.yaml")
    translate = load_agent_manifest(ROOT / "agents" / "translate" / "agent.yaml")

    assert isinstance(chat, AgentSchema)
    assert chat.id == "chat"
    assert chat.context_policy.mode == "session"
    assert {action.id for action in translate.actions} == {"default", "formal", "casual", "retry"}


def test_capability_manifest_loads() -> None:
    capability = load_capability_manifest(ROOT / "capabilities" / "base64" / "capability.yaml")

    assert isinstance(capability, CapabilitySchema)
    assert capability.id == "base64"
    assert {method.id for method in capability.methods} == {"encode", "decode", "decode_image"}
    assert {command.name for command in capability.commands} == {
        "/base64",
        "/base64-decode",
        "/base64-image",
        "/base64-to-image",
    }
    decode_image = next(method for method in capability.methods if method.id == "decode_image")
    assert decode_image.output == {"type": "image"}


def test_agent_without_default_action_fails() -> None:
    with pytest.raises(ValidationError, match="default"):
        AgentSchema.model_validate(
            {
                "id": "missing_default",
                "name": "Missing Default",
                "type": "prompt",
                "actions": [{"id": "other"}],
                "context_policy": {"mode": "current_message"},
                "model_lifecycle": {"load": "on_demand", "unload": "never", "unload_failure": "warn"},
            }
        )


def test_command_referencing_missing_method_fails() -> None:
    with pytest.raises(ValidationError, match="missing method ids: decode"):
        CapabilitySchema.model_validate(
            {
                "id": "bad_capability",
                "name": "Bad Capability",
                "methods": [{"id": "encode"}],
                "commands": [{"name": "/decode", "method": "decode"}],
            }
        )


def test_agent_manifest_with_slash_command_alias_field_fails() -> None:
    with pytest.raises(ValidationError, match="Commands belong in Capability manifests"):
        AgentSchema.model_validate(
            {
                "id": "bad_agent",
                "name": "Bad Agent",
                "type": "prompt",
                "actions": [{"id": "default"}],
                "commands": ["/bad"],
                "context_policy": {"mode": "current_message"},
                "model_lifecycle": {"load": "on_demand", "unload": "never", "unload_failure": "warn"},
            }
        )


def test_agent_manifest_llm_profile_defaults_allow_session_override_true() -> None:
    agent = AgentSchema.model_validate(
        {
            "id": "profile_agent",
            "name": "Profile Agent",
            "type": "prompt",
            "actions": [{"id": "default"}],
            "llm": {"profile": "myqwen3", "temperature": 0.2},
            "context_policy": {"mode": "current_message"},
            "model_lifecycle": {"load": "on_demand", "unload": "never", "unload_failure": "warn"},
        }
    )

    assert agent.llm["profile"] == "myqwen3"
    assert agent.llm["allow_session_override"] is True
    assert agent.llm["temperature"] == 0.2


def test_agent_manifest_llm_allow_session_override_false_loads() -> None:
    agent = AgentSchema.model_validate(
        {
            "id": "locked_agent",
            "name": "Locked Agent",
            "type": "prompt",
            "actions": [{"id": "default"}],
            "llm": {"profile": "myqwen3", "allow_session_override": False},
            "context_policy": {"mode": "current_message"},
            "model_lifecycle": {"load": "on_demand", "unload": "never", "unload_failure": "warn"},
        }
    )

    assert agent.llm["allow_session_override"] is False
