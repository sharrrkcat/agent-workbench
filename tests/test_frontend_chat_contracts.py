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


def test_pet_sprite_uses_codex_animation_durations() -> None:
    source = read_frontend("components/PetSprite.tsx")

    assert "CODEX_PET_ATLAS" in source
    assert "columns: 8" in source
    assert "rows: 9" in source
    assert "durations: [560, 220, 220, 280, 280, 640]" in source
    assert "durations: [120, 120, 120, 120, 120, 120, 120, 220]" in source
    assert "durations: [140, 140, 140, 280]" in source
    assert "durations: [140, 140, 140, 140, 280]" in source
    assert "durations: [140, 140, 140, 140, 140, 140, 140, 240]" in source
    assert "durations: [150, 150, 150, 150, 150, 260]" in source
    assert "durations: [120, 120, 120, 120, 120, 220]" in source
    assert "durations: [150, 150, 150, 150, 150, 280]" in source
    assert "currentSpec.durations.length" in source
    assert "frameCount" not in source
    assert "frameDurationMs" not in source
    assert "setInterval" not in source
    assert "% CODEX_PET_ATLAS.columns" not in source
    assert "% 8" not in source


def test_pet_overlay_repeats_jump_and_keeps_drag_position_local() -> None:
    source = read_frontend("components/PetOverlay.tsx")

    assert "DEFAULT_PET_SCALE = 0.5" in source
    assert "pet_scale: DEFAULT_PET_SCALE" in source
    assert "onPlaybackComplete={handlePlaybackComplete}" in source
    assert "setHoverActive(false)" in source
    assert "const [localPosition, setLocalPosition]" in source
    assert "pendingSavedPositionRef" in source
    assert "positionsMatch(settings.position, pendingPosition)" in source
    assert "setLocalPosition(finalPosition)" in source
    assert "api.updatePetSettings({ position: { mode: 'custom', ...savedPosition } })" in source
    assert "repeatCount === undefined" in read_frontend("components/PetSprite.tsx")
    assert "if (animationState === 'jumping') return 3" in source
    assert "if (animationState === 'running' && runningTask) return 2" in source
    assert "commandFeedbackForAction" in source
    assert "setComposerWaitPhase((phase) => (phase === 'waiting' ? 'idle' : 'waiting'))" in source


def test_composer_draft_text_drives_pet_waiting_state() -> None:
    input_source = read_frontend("components/ChatInput.tsx")
    store_source = read_frontend("store/useWorkbenchStore.ts")
    overlay_source = read_frontend("components/PetOverlay.tsx")

    assert "composerDraftText: string" in store_source
    assert "setComposerDraftText: (text: string) => void" in store_source
    assert "setComposerDraftText(value)" in input_source
    assert "composerDraftText.trim().length > 0" in overlay_source


def test_message_knowledge_snippets_modal_contract() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    client = read_frontend("api/client.ts")
    styles = read_frontend("styles.css")

    assert "BookOpen" in source
    assert "knowledgeSnippetRefs" in source
    assert "KnowledgeSnippetsModal" in source
    assert "api.getKnowledgeChunk" in source
    assert "snippet_refs" in source
    assert "getKnowledgeChunk" in client
    assert "/api/knowledge/chunks/" in client
    assert ".knowledge-snippets-modal" in styles
    assert "white-space: pre-wrap" in styles


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


def test_composer_placeholder_mentions_current_agent_action_shortcut() -> None:
    source = read_frontend("components/ChatInput.tsx")

    assert "Ask anything, use @agent, :action, or /command" in source


def test_composer_current_agent_action_autocomplete_trigger_contract() -> None:
    source = read_frontend("components/ChatInput.tsx")

    assert "current-actions" in source
    assert r"^:([A-Za-z0-9_-]*)$" in source
    assert "activeToken.token.startsWith(':')" in source


def test_command_palette_current_agent_action_autocomplete_contract() -> None:
    source = read_frontend("components/CommandPalette.tsx")

    assert "currentSession?.default_agent_id" in source
    assert "currentAgent.actions" in source
    assert ".filter((action) => action.callable !== false)" in source
    assert "label: `:${action.id}`" in source
    assert "value: `:${action.id} `" in source
    assert "No current agent selected." in source
    assert "No matching actions for current agent." in source
    assert "save_recipe_from_form" not in source
    assert "value: `@${agent.id}:${action.id} `" in source
    assert "commands" in source


def test_settings_config_enum_does_not_render_unset_option() -> None:
    source = read_frontend("components/settings/ConfigForm.tsx")
    utils = read_frontend("components/settings/configUtils.ts")

    assert '<option value="">Unset</option>' not in source
    assert "field.options.map((option)" in source
    assert "optionValues.has(value)" in source
    assert "effectiveConfigValue" in utils
    assert "field.options.includes(value)" in utils


def test_composer_colon_autocomplete_does_not_replace_existing_namespaces() -> None:
    source = read_frontend("components/ChatInput.tsx")

    assert "activeToken.token.startsWith('/')) return 'commands'" in source
    assert "activeToken.token.startsWith('@') && activeToken.token.includes(':')) return 'actions'" in source
    assert "activeToken.token.startsWith('@')) return 'agents'" in source
    assert source.index("activeToken.token.startsWith('@') && activeToken.token.includes(':')") < source.index("activeToken.token.startsWith(':')")


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


def test_chat_header_has_session_knowledge_picker_contract() -> None:
    source = read_frontend("components/ChatHeader.tsx")
    client = read_frontend("api/client.ts")
    types = read_frontend("types.ts")

    assert "SessionKnowledgePicker" in source
    assert "api.listKnowledgeBases()" in source
    assert "api.listSessionKnowledgeBases" in source
    assert "api.updateSessionKnowledgeBases" in source
    assert "KB: {selectedIds.size}" in source
    assert "Settings &gt; Knowledge" in source
    assert "SessionKnowledgeBinding" in types
    assert "listSessionKnowledgeBases" in client
    assert "updateSessionKnowledgeBases" in client


def test_agent_overrides_has_knowledge_runtime_settings_contract() -> None:
    source = read_frontend("components/settings/AgentDetail.tsx")
    types = read_frontend("types.ts")

    assert "Knowledge Runtime Settings" in source
    assert "Use session knowledge bases" in source
    assert "Prompt Agents use Session KBs by default" in source
    assert "knowledge_context_mode" in source
    assert "knowledge_context_effective_mode" in source
    assert "'use_default' | 'enabled' | 'disabled'" in types


def test_chat_renders_run_steps_panel_and_step_statuses() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "RunStepsPanel" in source
    assert "completed" in source
    assert "failed" in source
    assert "running" in source
    assert "skipped" in source


def test_message_metrics_label_distinguishes_input_and_output_tokens() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "metrics.prompt_tokens" in source
    assert "runs:metrics.inputTokens" in source
    assert "runs:metrics.outputTokens" in source
    assert "runs:metrics.estimatedOutputTokens" in source
    assert "parts.join(' · ')" in source
    assert "metrics.total_tokens" not in source[source.index("function formatMetrics") : source.index("function numberValue")]
    assert source.index("runs:metrics.inputTokens") < source.index("runs:metrics.outputTokens")


def test_chat_header_renders_session_token_summary_before_knowledge_picker() -> None:
    source = read_frontend("components/ChatHeader.tsx")

    assert "summarizeSessionTokens(state.messages)" in source
    assert "metadata?.llm_metrics" in source
    assert "metrics.prompt_tokens" in source
    assert "metrics.completion_tokens" in source
    assert "metrics.estimated_completion_tokens" in source
    assert "chat:tokens.tooltip" in source
    assert source.index("<SessionTokenPill summary={tokenSummary} />") < source.index("<SessionKnowledgePicker")


def test_failed_producer_messages_keep_identity_and_send_errors_are_local() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    store = read_frontend("store/useWorkbenchStore.ts")

    assert "hasProducerIdentity(message)" in source
    assert "message.speaker_type === 'capability'" in source
    assert "MessageErrorCard" in source
    assert "message.speaker_name" in source
    assert "createInlineErrorMessage(session.session_id, formatted.lastError, optimisticMessage.message_id)" in store
    assert "speaker_name: commandErrorTitle(error)" in store


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


def test_message_badge_prefers_profile_name_before_model_ids() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "resolveMessageModelBadge" in source
    assert "llm?.model_profile_name" in source
    assert "resolution?.profile_name" in source
    assert "llm?.requested_model_id" in source
    assert "llm?.actual_model_id" in source
    assert source.index("llm?.model_profile_name") < source.index("llm?.requested_model_id")
    assert source.index("llm?.requested_model_id") < source.index("llm?.actual_model_id")


def test_message_badge_tooltip_keeps_actual_model_debug_details() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "Model profile ID:" in source
    assert "Provider profile ID:" in source
    assert "Requested model:" in source
    assert "Actual model:" in source
    assert "Provider:" in source
    assert "Status:" in source


def test_session_type_includes_context_mode_and_speaker_fields() -> None:
    source = read_frontend("types.ts")

    assert "ContextMode = 'single_assistant' | 'group_transcript'" in source
    assert "context_mode?: ContextMode" in source
    assert "title_generation_state?: 'pending' | 'done' | 'skipped' | 'failed' | 'manual'" in source
    assert "speaker_type?: 'user' | 'agent' | 'capability' | 'system' | null" in source
    assert "speaker_id?: string | null" in source
    assert "speaker_name?: string | null" in source
    assert "origin?: string | null" in source


def test_action_form_block_renderer_and_submission_contract_are_present() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    store = read_frontend("store/useWorkbenchStore.ts")
    client = read_frontend("api/client.ts")
    types = read_frontend("types.ts")
    styles = read_frontend("styles.css")

    assert "type: 'action_form'" in types
    assert "visibility?: 'message' | 'silent' | null" in types
    assert "success_message?: string | null" in types
    assert "ui?: {" in types
    assert "default_collapsed?: boolean | null" in types
    assert "collapsed?: boolean | null" in types
    assert "collapse_on_success?: boolean | null" in types
    assert "collapsed_message?: string | null" in types
    assert "span?: number | null" in types
    assert "updated_form?: {" in types
    assert "sections?: ActionFormSection[] | null" in types
    assert "ActionFormRenderer" in source
    assert "ActionFormFieldControl" in source
    assert "initialActionFormCollapsed(form)" in source
    assert "form.ui?.collapsed_message || 'Click to expand.'" in source
    assert "className=\"action-form-collapse-toggle\"" in source
    assert "aria-expanded={false}" in source
    assert "setExpanded(true)" in source
    assert "className=\"action-form-header-toggle\"" in source
    assert "setExpanded(false)" in source
    assert "groupActionFormFields(form)" in source
    assert "field.ui?.section" in source
    assert "resolveActionFormFieldSpan(field)" in source
    assert "sections.map((section)" in source
    assert "section.fields.map((field)" in source
    assert "key={`${formDomKey}-${field.name}`}" in source
    assert "const id = `action-form-${formDomKey}-${field.name}`" in source
    assert "htmlFor={id}" in source
    assert "name: field.name" in source
    assert "textarea" in source
    assert "type=\"number\"" in source
    assert "type=\"checkbox\"" in source
    assert "<select" in source
    assert "action-form-json" in source
    assert "initialFormValues(form)" in source
    assert "form.submit.visibility === 'silent'" in source
    assert "submitForm(messageId, form.form_id, values, { silent })" in source
    assert "throw new Error(result.message || result.error || 'Form submission failed')" in source
    assert "setNotice(result?.message || form.submit.success_message || 'Saved')" in source
    assert "submitForm: (sourceMessageId: string, formId: string, values: Record<string, unknown>, options?: { silent?: boolean })" in store
    assert "options?.silent" in store
    assert "applyUpdatedFormBlock(get().messages, result.updated_form)" in store
    assert "replaceActionFormBlock" in store
    assert "/forms/submit" in client
    assert ".action-form-card" in styles
    assert ".action-form-card.collapsed" in styles
    assert ".action-form-collapse-toggle" in styles
    assert ".action-form-header-toggle" in styles
    assert "grid-template-columns: repeat(12" in styles
    assert ".action-form-section" in styles
    assert ".action-form-field.span-12" in styles
    assert ".action-form-field.span-6" in styles
    assert ".action-form-field.span-4" in styles
    assert "@media (max-width: 560px)" in styles
    assert ".action-form-error" in styles
    assert ".action-form-notice" in styles
    assert ".action-form-field select option" in styles


def test_command_buttons_render_as_send_message_shortcuts() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    store = read_frontend("store/useWorkbenchStore.ts")
    client = read_frontend("api/client.ts")
    types = read_frontend("types.ts")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "CommandButtonsBlock" in types
    assert "type: 'command_buttons'" in types
    assert "buttons: { label: string; message: string }[]" in types
    assert "CommandButtonsRenderer" in source
    assert "block.type === 'command_buttons'" in source
    assert "useWorkbenchStore((state) => state.sendMessage)" in source
    assert "sendMessage(button.message)" in source
    assert "useWorkbenchStore((state) => state.sending)" in source
    assert "title={button.message}" in source
    assert "submitForm(" not in source[source.index("function CommandButtonsRenderer") : source.index("function ActionFormRenderer")]
    assert "invokeAction(" not in source[source.index("function CommandButtonsRenderer") : source.index("function ActionFormRenderer")]
    assert "api.sendMessage(session.session_id, content, attachments)" in store
    assert "/forms/submit" in client
    assert ".command-buttons" in styles
    assert ".command-buttons button" in styles


def test_chat_header_displays_and_switches_conversation_mode() -> None:
    source = read_frontend("components/ChatHeader.tsx")

    assert "mode-switcher" in source
    assert "aria-label=\"Conversation mode\"" in source
    assert ">Mode</span>" in source
    assert "Single" in source
    assert "Group" in source
    assert "contextMode === 'group_transcript'" in source
    assert "changeContextMode('group_transcript')" in source
    assert "changeContextMode('single_assistant')" in source
    assert "Single assistant: Treat agent history like a normal assistant conversation." in source
    assert "Group transcript: Label user, agents, and command results in context so agents can distinguish speakers." in source


def test_store_patches_and_normalizes_session_context_mode() -> None:
    source = read_frontend("store/useWorkbenchStore.ts")
    client = read_frontend("api/client.ts")

    assert "updateSessionContextMode: (contextMode: ContextMode) => Promise<void>" in source
    assert "if (normalizeContextMode(session.context_mode) === contextMode) return" in source
    assert "api.updateSession(session.session_id, { context_mode: contextMode })" in source
    assert "await get().refreshCurrent()" in source
    assert "Failed to update conversation mode" in source
    assert "normalizeSession" in source
    assert "context_mode: normalizeContextMode(session.context_mode)" in source
    assert "contextMode === 'group_transcript' ? 'group_transcript' : 'single_assistant'" in source
    assert "'title' | 'default_agent_id' | 'llm_profile_id' | 'context_mode'" in client


def test_general_settings_context_rendering_fields_are_exposed() -> None:
    types = read_frontend("types.ts")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")

    assert "group_transcript_system_instruction: string | null" in types
    assert "group_transcript_system_instruction_default: string" in types
    assert "group_transcript_system_instruction_effective: string" in types
    assert "command_result_context_instruction: string | null" in types
    assert "command_result_context_instruction_default: string" in types
    assert "command_result_context_instruction_effective: string" in types
    assert "auto_generate_session_titles: boolean" in types
    assert "session_title_prompt: string" in types
    assert "session_title_max_input_chars: number" in types
    assert "Files" in panel
    assert "LLM & Prompts" in panel
    assert "Auto-generate session titles" in panel
    assert "Session title prompt" in panel
    assert "Session title max input chars" in panel
    assert "Max image size (MB)" in panel
    assert "Send text file attachments to LLM" in panel
    assert "Context Rendering" in panel
    assert "Group transcript system instruction" in panel
    assert "Command result context instruction" in panel
    assert "Reset to default" in panel
    assert "generalSettingsPatch(values)" in panel
    assert "group_transcript_system_instruction_default" not in panel[panel.index("function generalSettingsPatch") :]


def test_general_settings_uses_middle_category_list() -> None:
    console = read_frontend("components/settings/SettingsConsole.tsx")
    object_list = read_frontend("components/settings/SettingsObjectList.tsx")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")

    assert "type GeneralSettingsCategory = 'files' | 'llm_prompts'" in object_list
    assert "{ id: 'files', name: 'Files', description: 'Upload limits and file context.' }" in object_list
    assert "{ id: 'llm_prompts', name: 'LLM & Prompts', description: 'Title generation and context prompts.' }" in object_list
    assert "if (section === 'general')" in object_list
    general_branch = object_list[object_list.index("if (section === 'general')") : object_list.index("if (section === 'agents')")]
    assert '<ObjectListHeader title="Category" count={generalCategories.length} />' in general_branch
    assert "No objects in this section." not in general_branch
    assert "generalCategory === category.id ? 'active' : ''" in general_branch
    assert "onSelectGeneralCategory?.(category.id)" in general_branch

    assert "useState<GeneralSettingsCategory>('files')" in console
    assert "setGeneralCategory('files')" in console
    assert "generalCategory={generalCategory}" in console
    assert "onSelectGeneralCategory={setGeneralCategory}" in console

    assert "generalCategory = 'files'" in panel
    assert "<GeneralDetail category={generalCategory} onDirtyChange={onDirtyChange} />" in panel
    assert "function GeneralFilesSettings" in panel
    assert "function GeneralPromptSettings" in panel
    assert "category === 'files' ? (" in panel
    assert "DetailTabs" not in panel
    assert "generalTab" not in panel


def test_knowledge_settings_uses_three_column_console_and_api_wiring() -> None:
    nav = read_frontend("components/settings/SettingsNav.tsx")
    console = read_frontend("components/settings/SettingsConsole.tsx")
    object_list = read_frontend("components/settings/SettingsObjectList.tsx")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")
    knowledge = read_frontend("components/settings/KnowledgeSettingsPanel.tsx")
    client = read_frontend("api/client.ts")

    assert "'knowledge'" in nav
    assert "label: 'Knowledge'" in nav
    assert "export type KnowledgeSettingsCategory = KnowledgeSettingsSubsection" in object_list
    assert "export type KnowledgeSettingsCategory = 'defaults' | 'embedding_models' | 'knowledge_bases'" in read_frontend("types.ts")
    assert "Defaults" in object_list
    assert "EMBEDDING MODELS" in object_list
    assert "KNOWLEDGE BASES" in object_list
    assert "if (section === 'knowledge')" in object_list
    assert "knowledgeSubsection === 'defaults'" in object_list
    assert "useState<KnowledgeSettingsSubsection>('defaults')" in console
    assert "setSelectedKnowledgeSubsection('defaults')" in console
    assert "knowledgeSubsection={selectedKnowledgeSubsection}" in console
    assert "onKnowledgeSubsectionChange={changeKnowledgeSubsection}" in console
    assert "<KnowledgeSettingsDetail" in panel

    assert "Local Models" in knowledge
    assert "Embedding" in knowledge
    assert "Reranker" in knowledge
    assert "Retrieval" in knowledge
    assert "Chunking" in knowledge
    assert "Index limits" in knowledge
    assert "Context Injection" in knowledge
    assert "Scan local models" in knowledge
    assert "Test reranker" in knowledge
    assert "Test" in knowledge
    assert "No embedding model profiles yet." in knowledge
    assert "No knowledge bases yet." in knowledge
    assert "Knowledge base configuration, sources, and local indexes." in knowledge
    assert "No sources have been indexed for this knowledge base." in knowledge
    assert "Index pasted text" in knowledge
    assert "api.listKnowledgeSources" in knowledge
    assert "api.createPastedKnowledgeSource" in knowledge
    assert "api.deleteKnowledgeSource" in knowledge
    assert "api.reindexKnowledgeSource" in knowledge
    assert "api.scanKnowledgeModels()" in knowledge
    assert "api.updateKnowledgeSettings" in knowledge
    assert "api.testEmbeddingModel" in knowledge
    assert "api.rerankKnowledge" in knowledge
    assert "backendLabel(scan?.backend)" in knowledge
    assert "Unavailable: optional dependencies missing" in knowledge

    assert "/api/knowledge/settings" in client
    assert "/api/knowledge/models/scan" in client
    assert "/api/knowledge/embedding-models" in client
    assert "/api/knowledge/bases" in client
    assert "/api/knowledge/bases/${knowledgeBaseId}/sources" in client
    assert "/api/knowledge/sources/${sourceId}/reindex" in client
    assert "/api/knowledge/rerank" in client


def test_mode_changed_separator_renders_like_model_changed_separator() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "message.output_type === 'event'" in source
    assert "SystemEventSeparator" in source
    assert "system-event-separator" in source
    assert ".system-event-separator" in styles
    assert ".mode-switcher" in styles
