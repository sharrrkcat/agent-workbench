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


def test_status_bar_only_shows_resolved_provider_and_model_target() -> None:
    source = read_frontend("components/StatusBar.tsx")

    assert "Default:" not in source
    assert "return `LLM - ${provider.name} - ${profile.model_id || 'No model ID'}`;" in source
    assert "LLM - Missing provider profile" in source
    assert "LLM - No model profile selected" in source
    assert "LLM - No LLM" in source


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


def test_chat_renders_run_steps_panel_and_step_statuses() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "RunStepsPanel" in source
    assert "completed" in source
    assert "failed" in source
    assert "running" in source
    assert "skipped" in source


def test_store_merges_run_step_updates_by_step_id() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "run_step_created" in source
    assert "run_step_updated" in source
    assert "stepsByRunId" in source
    assert "runsById" in source
    assert "byId.set(step.step_id" in source
    assert "mergeRunStepIntoState" in source
    assert "mergeRunsIntoState" in source
    assert "parseRunStepPayload" in source


def test_run_steps_expansion_is_scoped_by_run_id() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    store = read_frontend("store/useWorkbenchStore.ts")

    assert "runStepsExpandedByRunId" in store
    assert "setRunStepsExpanded" in store
    assert "Object.prototype.hasOwnProperty.call(expandedByRunId, runId)" in source
    assert "defaultRunStepsExpanded" in source
    assert "'FAILED', 'CANCELLED'" in source


def test_run_steps_duration_and_running_tick_are_rendered() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    time = read_frontend("utils/time.ts")

    assert "stepDurationLabel" in source
    assert "formatDurationMs" in source
    assert "parseServerTime" in source
    assert "Date.parse" not in source
    assert "window.setInterval" in source
    assert "window.clearInterval" in source
    assert "hasRunningStep" in source
    assert "stepsByRunId[message.run_id]" in source
    assert "`${value}Z`" in time


def test_empty_running_script_placeholder_remains_visible() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "hasVisibleRun(messageRun)" in source
    assert "isActiveRunStatus(run.status)" in source


def test_non_draft_streaming_placeholder_accepts_deltas() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "message.client_status !== 'streaming'" in source
    assert "message_id: typeof event.message_id === 'string'" in source
