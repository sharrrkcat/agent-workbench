from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_workbench.core.manifest_loader import load_agent_manifest, load_capability_manifest
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.capability import CapabilitySchema
from scripts.check_agents import CheckResult, _check_capabilities


ROOT = Path(__file__).resolve().parents[1]


def test_agent_manifests_load() -> None:
    chat = load_agent_manifest(ROOT / "agents" / "chat" / "agent.yaml")
    translate = load_agent_manifest(ROOT / "agents" / "translate" / "agent.yaml")
    script_lifecycle_lab = load_agent_manifest(ROOT / "agents" / "script_lifecycle_lab" / "agent.yaml")

    assert isinstance(chat, AgentSchema)
    assert chat.id == "chat"
    assert chat.context_policy.mode == "session"
    assert {action.id for action in translate.actions} == {"default", "formal", "casual", "retry"}
    assert script_lifecycle_lab.type == "script"
    assert script_lifecycle_lab.entry == "agent.py"
    assert "llm" in script_lifecycle_lab.capabilities
    assert {action.id for action in script_lifecycle_lab.actions} == {
        "default",
        "steps",
        "hidden_json",
        "public_stream",
        "audio_demo",
    }


def test_comfyui_form_save_action_is_internal_not_user_callable() -> None:
    comfyui = load_agent_manifest(ROOT / "agents" / "comfyui_agent" / "agent.yaml")

    action = next(item for item in comfyui.actions if item.id == "save_recipe_from_form")

    assert action.callable is False


def test_capability_manifest_loads() -> None:
    capability = load_capability_manifest(ROOT / "capabilities" / "codec" / "capability.yaml")

    assert isinstance(capability, CapabilitySchema)
    assert capability.id == "codec"
    assert {method.id for method in capability.methods} == {"encode", "decode"}
    assert {command.name for command in capability.commands} == {"/encode", "/decode"}
    assert all(method.output == {"part_type": "parts"} for method in capability.methods)


def test_command_argument_suggestions_load() -> None:
    capability = CapabilitySchema.model_validate(
        {
            "id": "demo_capability",
            "name": "Demo Capability",
            "methods": [{"id": "encode"}],
            "commands": [
                {
                    "name": "/encode",
                    "method": "encode",
                    "argument_suggestions": [
                        {"value": "base64", "description": "Standard Base64"},
                        {
                            "value": "url",
                            "label": "URL",
                            "description": "URL component percent encoding",
                            "next_suggestions": {"provider": "pet_ids"},
                        },
                    ],
                }
            ],
        }
    )

    command = capability.commands[0]
    assert command.argument_suggestions[0].value == "base64"
    assert command.argument_suggestions[1].label == "URL"
    assert command.argument_suggestions[1].next_suggestions
    assert command.argument_suggestions[1].next_suggestions.provider == "pet_ids"


def test_command_without_argument_suggestions_loads() -> None:
    capability = CapabilitySchema.model_validate(
        {
            "id": "demo_capability",
            "name": "Demo Capability",
            "methods": [{"id": "echo"}],
            "commands": [{"name": "/echo", "method": "echo"}],
        }
    )

    assert capability.commands[0].argument_suggestions == []


def test_builtin_command_argument_suggestions_load() -> None:
    codec = load_capability_manifest(ROOT / "capabilities" / "codec" / "capability.yaml")
    pet = load_capability_manifest(ROOT / "capabilities" / "pet" / "capability.yaml")

    encode = next(command for command in codec.commands if command.name == "/encode")
    decode = next(command for command in codec.commands if command.name == "/decode")
    pet_command = pet.commands[0]

    assert [item.value for item in encode.argument_suggestions] == ["base64", "base64url", "url", "unicode", "hex", "qr"]
    assert [item.value for item in decode.argument_suggestions] == ["base64", "base64url", "url", "unicode", "hex"]
    assert "qr" not in [item.value for item in decode.argument_suggestions]
    assert [item.value for item in pet_command.argument_suggestions] == ["status", "wake", "tuck", "reload", "select"]
    select = next(item for item in pet_command.argument_suggestions if item.value == "select")
    assert select.next_suggestions
    assert select.next_suggestions.provider == "pet_ids"


@pytest.mark.parametrize(
    ("argument_suggestions", "expected"),
    [
        ("bad", "field 'argument_suggestions' must be an array"),
        ([{"description": "Missing value"}], "field 'argument_suggestions[0].value' is required"),
        ([{"value": ""}], "field 'argument_suggestions[0].value' must be a non-empty string"),
        ([{"value": "base64", "description": 123}], "field 'argument_suggestions[0].description' must be a string"),
        ([{"value": "base64", "next_suggestions": "bad"}], "suggestion value 'base64' field 'argument_suggestions[0].next_suggestions' must be an object"),
        ([{"value": "base64", "next_suggestions": {}}], "suggestion value 'base64' field 'argument_suggestions[0].next_suggestions.provider' is required"),
        ([{"value": "base64", "next_suggestions": {"provider": ""}}], "suggestion value 'base64' field 'argument_suggestions[0].next_suggestions.provider' must be a non-empty string"),
        ([{"value": "base64", "next_suggestions": {"provider": "paths"}}], "suggestion value 'base64' field 'argument_suggestions[0].next_suggestions.provider' has unsupported provider 'paths'"),
    ],
)
def test_strict_check_reports_invalid_argument_suggestions_shape(tmp_path: Path, argument_suggestions, expected: str) -> None:
    capability_dir = tmp_path / "bad_capability"
    capability_dir.mkdir()
    capability_dir.joinpath("__init__.py").write_text(
        "class CapabilityRuntime:\n    def echo(self, args=''):\n        return args\n",
        encoding="utf-8",
    )
    capability_dir.joinpath("capability.yaml").write_text(
        f"""
id: bad_capability
name: Bad Capability
methods:
  - id: echo
commands:
  - name: /bad
    method: echo
    argument_suggestions: {argument_suggestions!r}
""",
        encoding="utf-8",
    )
    result = CheckResult()

    _check_capabilities(tmp_path, result, strict=True)

    assert any("capability 'bad_capability'" in error and "command '/bad'" in error and expected in error for error in result.errors)


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
