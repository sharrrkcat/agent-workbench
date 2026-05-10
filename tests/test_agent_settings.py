from pathlib import Path

import yaml

from ai_workbench.core.agent_settings import resolved_agent_settings, resolved_knowledge_context_mode, write_overrides_to_manifest
from ai_workbench.core.schema.agent import AgentSchema


def test_agent_missing_runtime_fields_resolves_system_defaults() -> None:
    agent = AgentSchema.model_validate(
        {
            "id": "minimal",
            "name": "Minimal",
            "type": "prompt",
            "actions": [{"id": "default", "description": "Default"}],
        }
    )

    resolved = resolved_agent_settings(agent, {})

    assert resolved["runtime"]["context_policy"]["mode"] == "recent_messages"
    assert resolved["runtime"]["context_policy"]["max_messages"] == 8
    assert resolved["runtime"]["model_lifecycle"]["unload"] == "never"
    assert resolved["runtime"]["timeout_seconds"] == 120
    assert resolved["field_sources"]["runtime.timeout_seconds"] == "default"
    assert resolved["runtime"]["knowledge_context_mode"] == "use_default"
    assert resolved["runtime"]["knowledge_context_effective_mode"] == "enabled"


def test_write_overrides_to_manifest_writes_only_display_runtime_not_user_config(tmp_path: Path) -> None:
    agent_dir = tmp_path / "chat"
    agent_dir.mkdir()
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "id": "chat",
                "name": "Chat Agent",
                "type": "prompt",
                "description": "Default chat",
                "prompt": "Original prompt",
                "actions": [{"id": "default", "description": "Default"}],
                "capabilities": ["llm"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    agent = AgentSchema.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")))

    write_overrides_to_manifest(
        agent,
        agent_dir,
        {
            "display": {"name": "Custom Chat"},
            "runtime": {"timeout_seconds": 88, "llm_profile_id": "local", "allow_session_override": False, "prompt": "Custom prompt", "knowledge_context_mode": "disabled"},
            "user_config": {"temperature": 0.1},
        },
    )

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert raw["name"] == "Custom Chat"
    assert raw["timeout_seconds"] == 88
    assert raw["prompt"] == "Custom prompt"
    assert raw["llm"] == {"profile": "local", "allow_session_override": False}
    assert "knowledge_context_mode" not in raw
    assert "user_config" not in raw
    assert "config" not in raw


def test_knowledge_context_mode_defaults_by_agent_type() -> None:
    prompt_agent = AgentSchema.model_validate(
        {"id": "chat", "name": "Chat", "type": "prompt", "actions": [{"id": "default"}]}
    )
    script_llm_agent = AgentSchema.model_validate(
        {"id": "script", "name": "Script", "type": "script", "entry": "agent.py", "capabilities": ["llm"], "actions": [{"id": "default"}]}
    )
    script_plain_agent = AgentSchema.model_validate(
        {"id": "plain", "name": "Plain", "type": "script", "entry": "agent.py", "actions": [{"id": "default"}]}
    )

    assert resolved_knowledge_context_mode(prompt_agent, {})["effective_mode"] == "enabled"
    assert resolved_knowledge_context_mode(script_llm_agent, {})["effective_mode"] == "disabled"
    assert resolved_knowledge_context_mode(script_plain_agent, {})["available"] is False
    assert resolved_knowledge_context_mode(script_llm_agent, {"runtime": {"knowledge_context_mode": "enabled"}})["effective_mode"] == "enabled"
