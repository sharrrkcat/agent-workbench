from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_frontend(path: str) -> str:
    return (ROOT / "frontend" / "src" / path).read_text(encoding="utf-8")


def test_status_bar_does_not_render_global_error_text() -> None:
    source = read_frontend("components/StatusBar.tsx")

    assert "CircleAlert" not in source
    assert "lastError" not in source
    assert "error," not in source
    assert "{error}" not in source


def test_default_model_menu_uses_agent_default_profile_not_effective_override() -> None:
    source = read_frontend("components/ChatInput.tsx")

    assert "resolveAgentDefaultLlmProfile" in source
    assert "const agentDefaultProfile = resolveAgentDefaultLlmProfile" in source
    assert "statusDotClass(agentDefaultProfile, llmProviderStatuses)" in source
    assert "statusDotClass(currentResolvedProfile" not in source


def test_model_status_helper_has_four_ui_tones_and_unloaded_yellow() -> None:
    source = read_frontend("utils/modelStatus.ts")

    assert "ModelProfileStatusTone = 'green' | 'yellow' | 'red' | 'gray'" in source
    assert "NO_MODEL_PROFILE', tone: 'gray'" in source
    assert "MODEL_NOT_LOADED', tone: 'yellow'" in source
    assert "PROVIDER_UNREACHABLE', tone: 'red'" in source
    assert "READY', tone: 'green'" in source
