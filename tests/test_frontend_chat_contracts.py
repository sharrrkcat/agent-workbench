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


def test_store_applies_provider_status_update_events_to_status_cache() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "llm_provider_status_updated" in source
    assert "parseLlmProviderStatusPayload(event.payload.provider)" in source
    assert "[provider.provider_profile_id]: provider" in source


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
    assert "parent_step_id" in read_frontend("types.ts")


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
    assert "formatDurationSeconds" in source
    assert "seconds.toFixed(2)" in source
    assert "parseServerTime" in source
    assert "Date.parse" not in source
    assert "window.setInterval" in source
    assert "window.clearInterval" in source
    assert "hasRunningStep" in source
    assert "stepsByRunId[message.run_id]" in source
    assert "`${value}Z`" in time


def test_run_steps_builds_nested_tree_and_renders_children() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "buildRunStepTree" in source
    assert "parent_step_id" in source
    assert "RunStepTreeItem" in source
    assert "run-step-children" in source
    assert "byId.get(parentId)" in source
    assert ".run-step-children" in styles
    assert "margin: 5px 0 0 23px" in styles


def test_empty_running_script_placeholder_remains_visible() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "hasVisibleRun(messageRun)" in source
    assert "isActiveRunStatus(run.status)" in source


def test_non_draft_streaming_placeholder_accepts_deltas() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "message.client_status !== 'streaming'" in source
    assert "message_id: typeof event.message_id === 'string'" in source
    assert "message_updated" in source
    assert "mergeUpdatedMessage" in source


def test_streaming_store_tracks_message_seq_and_completion() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "lastMessageSeqById" in source
    assert "completedMessageIds" in source
    assert "eventSeq(event)" in source
    assert "seq <= lastSeq" in source
    assert "markCompletedMessages" in source
    assert "markMessageSeq" in source


def test_streaming_store_ignores_message_updated_content_while_streaming() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "preserveStreamingContent" in source
    assert "message.client_status === 'streaming'" in source
    assert "completedMessageIds[updatedMessage.message_id]" in source
    assert "content: preserveStreamingContent ? message.content : updatedMessage.content" in source


def test_streaming_store_replaces_final_and_dedupes_by_run_or_draft() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")

    assert "replaceDraftWithFinal(get().messages, finalMessage, draftMessageId)" in source
    assert "message.message_id.startsWith('draft-') && message.run_id && message.run_id === finalMessage.run_id" in source
    assert "resolveMessageSeqKey" in source
