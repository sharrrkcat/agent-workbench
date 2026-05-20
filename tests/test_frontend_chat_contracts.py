from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_frontend(path: str) -> str:
    return (ROOT / "frontend" / "src" / path).read_text(encoding="utf-8")


def read_repo(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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


def test_chat_input_supports_static_command_argument_suggestions() -> None:
    input_source = read_frontend("components/ChatInput.tsx")
    palette_source = read_frontend("components/CommandPalette.tsx")
    client_source = read_frontend("api/client.ts")
    types_source = read_frontend("types.ts")
    en_chat = read_frontend("i18n/resources/en/chat.json")
    zh_chat = read_frontend("i18n/resources/zh-CN/chat.json")

    assert "commandArgumentAutocompleteMode(activeToken.token, commands)" in input_source
    assert "'command-arguments'" in palette_source
    assert "parseCommandArgumentToken" in palette_source
    assert "suggestion.value.toLowerCase().startsWith(argumentContext.prefix.toLowerCase())" in palette_source
    assert "value: `${argumentContext.command.name} ${suggestion.value} `" in palette_source
    assert "firstSuggestion?.next_suggestions" in palette_source
    assert "commandArgumentSuggestions" in palette_source
    assert "AbortController" in palette_source
    assert "requestSeqRef.current !== requestSeq" in palette_source
    assert "value: `${argumentContext.command.name} ${argumentContext.args[0]} ${suggestion.value} `" in palette_source
    assert "/api/commands/argument-suggestions" in client_source
    assert "argument_suggestions?: CommandArgumentSuggestion[]" in types_source
    assert "next_suggestions?: CommandArgumentNextSuggestions | null" in types_source
    assert "provider: 'pet_ids'" in types_source
    assert '"argumentSuggestions": "Arguments"' in en_chat
    assert '"argumentSuggestions": "参数"' in zh_chat


def test_command_palette_keeps_keyboard_selection_visible() -> None:
    palette_source = read_frontend("components/CommandPalette.tsx")

    assert "listRef" in palette_source
    assert "data-active" in palette_source
    assert "scrollIntoView({ block: 'nearest' })" in palette_source
    assert "[data-active=\"true\"]" in palette_source


def test_message_knowledge_snippets_modal_contract() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    client = read_frontend("api/client.ts")
    styles = read_frontend("styles.css")

    assert "BookOpen" in source
    assert "knowledgeSnippetRefs" in source
    assert "InjectedContextModal" in source
    assert "KnowledgeSnippetsTab" in source
    assert "WorldbookEntriesTab" in source
    assert "MemoryContextTab" in source
    assert "api.getKnowledgeChunk" in source
    assert "api.getWorldbookEntry" in source
    assert "snippet_refs" in source
    assert "entry_refs" in source
    assert "getKnowledgeChunk" in client
    assert "getWorldbookEntry" in client
    assert "/api/knowledge/chunks/" in client
    assert "/api/worldbook-entries/" in client
    assert ".knowledge-snippets-modal" in styles
    assert ".context-modal-body" in styles
    assert "white-space: pre-wrap" in styles


def test_message_type_exposes_message_parts_contract() -> None:
    source = read_frontend("types.ts")

    assert "content_version: 2" in source
    assert "parts: MessagePart[]" in source
    assert "export type TextMessagePart" in source
    assert "type: 'text'" in source
    assert "format: 'plain' | 'markdown'" in source
    assert "export type JsonMessagePart" in source
    assert "export type FileMessagePart" in source
    assert "mode: 'inline_text' | 'attachment_ref'" in source
    assert "export type ImageMessagePart" in source
    assert "export type AudioMessagePart" in source
    assert "export type AttachmentAudioMessagePart" in source
    assert "export type UrlAudioMessagePart" in source
    assert "type: 'audio'" in source
    assert "source: 'url'" in source
    assert "export type VideoMessagePart" in source
    assert "export type AttachmentVideoMessagePart" in source
    assert "export type UrlVideoMessagePart" in source
    assert "type: 'video'" in source
    assert "source: 'attachment'" in source
    assert "source: 'url'" in source
    assert "export type MediaGroupMessagePart" in source
    assert "layout: 'gallery'" in source
    assert "export type FormMessagePart" in source
    assert "export type CommandButtonsMessagePart" in source
    assert "export type NoticeMessagePart" in source
    assert "export type ErrorMessagePart" in source


def test_message_parts_renderer_is_only_normal_render_path() -> None:
    bubble = read_frontend("components/MessageBubble.tsx")
    renderer = read_frontend("components/messages/MessagePartsRenderer.tsx")

    assert "MessagePartsRenderer" in bubble
    assert "hasRenderableParts(message.parts)" in bubble
    assert "parts={message.parts}" in bubble
    assert "message.output_type" not in bubble
    assert "LegacyMessageFallback" not in bubble
    assert "export function MessagePartsRenderer" in renderer
    assert "parts.filter(isRenderableMessagePart)" in renderer
    assert "stablePartKey(part, index)" in renderer


def test_audio_message_parts_use_wide_layout_contract() -> None:
    bubble = read_frontend("components/MessageBubble.tsx")
    renderer = read_frontend("components/messages/MessagePartsRenderer.tsx")
    styles = read_frontend("styles.css")

    assert "hasWideMessageParts" in bubble
    assert "const hasWidePart = !isUser && hasWideMessageParts(message.parts)" in bubble
    assert "message-has-wide-part" in bubble
    assert "export function hasWideMessageParts" in renderer
    assert "isRenderableMessagePart(part) && isWideMessagePart(part)" in renderer
    assert "function isWideMessagePart(part: MessagePart)" in renderer
    assert "part.type === 'audio'" in renderer
    assert "part.type === 'video'" in renderer
    assert "message-content-wide" in renderer

    wide_stack_styles = styles[styles.index(".message-row.agent.message-has-wide-part .message-stack") : styles.index(".message {")]
    wide_message_styles = styles[styles.index(".message.agent.message-has-wide-part") : styles.index(".message.pending")]
    wide_content_styles = styles[styles.index(".message-content.parts-content.message-content-wide") : styles.index(".rich-content .message-content")]

    assert "width: min(720px, calc(100% - 48px))" in wide_stack_styles
    assert "max-width: min(720px, calc(100% - 48px))" in wide_stack_styles
    assert "width: 100%" in wide_message_styles
    assert "max-width: 100%" in wide_message_styles
    assert "width: 100%" in wide_content_styles
    assert "max-width: 100%" in wide_content_styles
    assert ".message-row.user .message-stack" in styles


def test_message_parts_renderer_routes_first_batch_part_types() -> None:
    renderer = read_frontend("components/messages/MessagePartsRenderer.tsx")

    assert "case 'text'" in renderer
    assert "TextPartRenderer" in renderer
    assert "case 'json'" in renderer
    assert "JsonPartRenderer" in renderer
    assert "case 'file'" in renderer
    assert "FilePartRenderer" in renderer
    assert "case 'image'" in renderer
    assert "ImagePartRenderer" in renderer
    assert "case 'audio'" in renderer
    assert "AudioPartRenderer" in renderer
    assert "case 'video'" in renderer
    assert "VideoPartRenderer" in renderer
    assert "case 'media_group'" in renderer
    assert "MediaGroupPartRenderer" in renderer
    assert "case 'form'" in renderer
    assert "FormPartRenderer" in renderer
    assert "case 'command_buttons'" in renderer
    assert "CommandButtonsPartRenderer" in renderer
    assert "case 'notice'" in renderer
    assert "NoticePartRenderer" in renderer
    assert "case 'error'" in renderer
    assert "ErrorPartRenderer" in renderer
    assert "default:" in renderer
    assert "message-part-notice warning" in renderer


def test_text_part_renderer_uses_markdown_or_plain_paths() -> None:
    source = read_frontend("components/messages/parts/TextPartRenderer.tsx")
    bubble = read_frontend("components/MessageBubble.tsx")

    assert "part.format === 'markdown'" in source
    assert "renderMarkdown(text)" in source
    assert "renderPlainText(text)" in source
    assert "knowledgeSnippetRefs={citationRefs}" in bubble
    assert "webSourceRefs={webCitationRefs}" in bubble
    assert "onOpenKnowledgeCitation={onOpenKnowledgeCitation}" in bubble
    assert "onOpenWebCitation={onOpenWebCitation}" in bubble
    assert "renderKnowledgeCitationChildren" in bubble
    assert "webCitationRefMap" in bubble
    assert "W\\d+" in bubble
    assert "['a', 'code', 'pre'].includes(node.type)" in bubble


def test_json_file_image_and_gallery_parts_delegate_to_legacy_renderers() -> None:
    json_source = read_frontend("components/messages/parts/JsonPartRenderer.tsx")
    file_source = read_frontend("components/messages/parts/FilePartRenderer.tsx")
    image_source = read_frontend("components/messages/parts/ImagePartRenderer.tsx")
    media_source = read_frontend("components/messages/parts/MediaGroupPartRenderer.tsx")
    bubble = read_frontend("components/MessageBubble.tsx")

    assert "renderJson(part.data)" in json_source
    assert "renderFile({" in file_source
    assert "part.mode === 'inline_text'" in file_source
    assert "renderPlainText(label)" in file_source
    assert "imagePayloadFromPart" in image_source
    assert "renderImage(image)" in image_source
    assert "part.layout !== 'gallery'" in media_source
    assert "renderImageGallery(images)" in media_source
    assert "renderJson={(data) => <JsonRenderer content={data} />}" in bubble
    assert "renderFile={(payload) => <FileContentRenderer payload={payload} />}" in bubble
    assert "renderImage={(image) => <ImageRenderer image={image} onPreviewImage={onPreviewImage} />}" in bubble
    assert "renderImageGallery={(images) => <ImageGalleryRenderer images={images} onPreviewImage={onPreviewImage} />}" in bubble


def test_audio_part_renderer_uses_custom_controls_for_local_attachments() -> None:
    source = read_frontend("components/messages/parts/AudioPartRenderer.tsx")
    update_metadata_body = source[source.index("function updateMetadata") : source.index("function updateTime")]
    update_time_body = source[source.index("function updateTime") : source.index("async function togglePlayback")]
    pointer_time_body = source[source.index("function timeFromPointerEvent") : source.index("function handleProgressPointerDown")]
    pointer_down_body = source[source.index("function handleProgressPointerDown") : source.index("function handleProgressPointerMove")]
    pointer_move_body = source[source.index("function handleProgressPointerMove") : source.index("function handleProgressPointerUp")]
    pointer_up_body = source[source.index("function handleProgressPointerUp") : source.index("function cancelProgressScrub")]
    keydown_body = source[source.index("function handleProgressKeyDown") : source.index("function commitSeek")]
    commit_seek_body = source[source.index("function commitSeek") : source.index("function completeSeek")]
    complete_seek_body = source[source.index("function completeSeek") : source.index("return (")]
    audio_tag = source[source.index("<audio") : source.index("/>", source.index("<audio"))]
    controls_markup = source[source.index('<div className="audio-part-controls">') : source.index('{failed ?')]

    assert "export function AudioPartRenderer" in source
    assert " controls" not in source
    assert "controls=" not in source
    assert "type=\"range\"" not in source
    assert "type='range'" not in source
    assert "<input" not in source
    assert "onInput" not in source
    assert "onChange" not in controls_markup
    assert "event.currentTarget.value" not in source
    assert "audioRef" in source
    assert "progressTrackRef" in source
    assert "window.localStorage.getItem('aw_audio_debug') === '1'" in source
    assert "function debugLog" in source
    assert "if (!audioDebugEnabled) return" in source
    assert "console.debug('[AudioPartRenderer]', label, data)" in source
    assert "togglePlayback" in source
    assert "isScrubbingRef" in source
    assert "isSeekingRef" in source
    assert "pendingSeekTimeRef" in source
    assert "beginScrub" not in source
    assert "finishScrub" not in source
    assert "if (isScrubbingRef.current) return" in update_time_body
    assert "if (isSeekingRef.current) return" in update_time_body
    assert "const displayedTime = isScrubbing ? scrubTime : currentTime" in source
    assert "const progressPercent = effectiveDuration > 0 ? clamp(displayedTime / effectiveDuration, 0, 1) * 100 : 0" in source
    assert "setScrubTime(nextTime)" in update_time_body
    assert "scrubTimeRef.current = nextTime" in update_time_body
    assert "getBoundingClientRect" in pointer_time_body
    assert "event.clientX" in pointer_time_body
    assert "rect.left" in pointer_time_body
    assert "rect.width" in pointer_time_body
    assert "clamp(rawRatio * effectiveDuration, 0, effectiveDuration)" in pointer_time_body
    assert "debugLog('timeFromPointerEvent'" in pointer_time_body
    assert "rawRatio" in pointer_time_body
    assert "clampedRatio" in pointer_time_body
    assert "computedTime" in pointer_time_body
    assert "setPointerCapture?.(event.pointerId)" in pointer_down_body
    assert "debugLog('handleProgressPointerDown'" in pointer_down_body
    assert "seekableRanges(audio)" in pointer_down_body
    assert "setIsScrubbing(true)" in pointer_down_body
    assert source.count("setIsScrubbing(true)") == 1
    assert "if (!isScrubbingRef.current) return" in pointer_move_body
    assert "debugLog('handleProgressPointerMove'" in pointer_move_body
    assert "if (!isScrubbingRef.current) return" in pointer_up_body
    assert "commitSeek(nextTime)" in pointer_up_body
    assert "debugLog('handleProgressPointerUp'" in pointer_up_body
    assert "releasePointerCapture?.(event.pointerId)" in pointer_up_body
    assert "onPointerDown={handleProgressPointerDown}" in source
    assert "onPointerMove={handleProgressPointerMove}" in source
    assert "onPointerUp={handleProgressPointerUp}" in source
    assert "onPointerCancel={cancelProgressScrub}" in source
    assert "onLostPointerCapture={cancelProgressScrub}" in source
    assert "role=\"slider\"" in source
    assert "aria-label={t('audio.seek')}" in source
    assert "aria-valuemin={0}" in source
    assert "aria-valuemax={Math.round(effectiveDuration)}" in source
    assert "aria-valuenow={Math.round(displayedTime)}" in source
    assert "onKeyDown={handleProgressKeyDown}" in source
    assert "ArrowLeft" in keydown_body
    assert "ArrowDown" in keydown_body
    assert "ArrowRight" in keydown_body
    assert "ArrowUp" in keydown_body
    assert "Home" in keydown_body
    assert "End" in keydown_body
    assert "Math.min(5, effectiveDuration * 0.05)" in keydown_body
    assert "function finitePositiveNumber" in source
    assert "function getAudioDuration" in source
    assert "const fallbackDuration = durationSeconds(part.duration_ms)" in source
    assert "const effectiveDuration = duration > 0 ? duration : fallbackDuration" in source
    assert "function commitSeek(targetSeconds: number)" in source
    assert "const targetTime = clamp(targetSeconds, 0, effectiveDuration)" in commit_seek_body
    assert "isSeekingRef.current = true" in commit_seek_body
    assert "pendingSeekTimeRef.current = targetTime" in commit_seek_body
    assert "debugLog('commitSeek'" in commit_seek_body
    assert "setterThrew: true" in commit_seek_body
    assert "setterThrew: false" in commit_seek_body
    assert "seekableRanges(audio)" in commit_seek_body
    assert "setCurrentTime(targetTime)" in commit_seek_body
    assert "setScrubTime(targetTime)" in commit_seek_body
    assert "audio.currentTime = targetTime" in commit_seek_body
    assert "onSeeked={completeSeek}" in source
    assert "debugLog('completeSeek'" in complete_seek_body
    assert "wasSeeking" in complete_seek_body
    assert "isSeekingAfter" in complete_seek_body
    assert "onPointerDown={beginScrub}" not in source
    assert "setCurrentTime(0)" not in update_metadata_body
    assert "setScrubTime(0)" not in update_metadata_body
    assert "scrubTimeRef.current = 0" not in update_metadata_body
    assert "key={currentTime}" not in audio_tag
    assert "key={scrubTime}" not in audio_tag
    assert "key={duration}" not in audio_tag
    assert "key={isPlaying}" not in audio_tag
    assert "audio-part-play" in source
    assert "audio-part-progress-track" in source
    assert "audio-part-progress-fill" in source
    assert "audio-part-progress-thumb" in source
    assert "part.source === 'attachment'" in source
    assert "part.source === 'url'" in source
    assert "function isRemoteHttpUrl" in source
    assert "^https?:\\/\\/" in source
    assert "function audioSourceUrl" in source
    assert "return isRemoteHttpUrl(part.url) ? part.url : ''" in source
    assert "^\\/api\\/attachments\\/" in source
    assert "part.source === 'attachment' ? part.attachment_id : part.url" in source
    assert "part.source, part.source === 'attachment' ? part.attachment_id : '', part.url" in source
    styles = read_frontend("styles.css")
    audio_part_styles = styles[styles.index(".audio-part {") : styles.index(".audio-part audio")]
    progress_track_styles = styles[styles.index(".audio-part-progress-track {") : styles.index(".audio-part-progress-track::before")]
    assert "width: min(100%, 720px)" not in audio_part_styles
    assert "width: 100%" in audio_part_styles
    assert "max-width: 100%" in audio_part_styles
    assert "fit-content" not in audio_part_styles
    assert "max-content" not in audio_part_styles
    assert "grid-template-columns: auto minmax(0, 1fr) auto" in styles
    assert "flex: 1 1 auto" in progress_track_styles
    assert ".audio-part-progress-track" in styles
    assert ".audio-part-progress-fill" in styles
    assert ".audio-part-progress-thumb" in styles


def test_video_part_renderer_uses_native_video_for_local_attachments() -> None:
    source = read_frontend("components/messages/parts/VideoPartRenderer.tsx")
    renderer = read_frontend("components/messages/MessagePartsRenderer.tsx")
    styles = read_frontend("styles.css")

    assert "export function VideoPartRenderer" in source
    assert "part.source === 'attachment'" in source
    assert "part.source === 'url'" in source
    assert "^\\/api\\/attachments\\/" in source
    assert "function isRemoteHttpUrl" in source
    assert "^https?:\\/\\/" in source
    assert "function videoSourceUrl" in source
    assert "return isRemoteHttpUrl(part.url) ? part.url : ''" in source
    assert '<video controls preload="metadata"' in source
    assert "autoplay" not in source.lower()
    assert "loop" not in source
    assert "muted" not in source
    assert "dangerouslySetInnerHTML" not in source
    assert "case 'video'" in renderer
    assert "part.type === 'video'" in renderer
    assert "if (part.source === 'url') return Boolean(part.url && part.mime_type)" in renderer
    assert "VideoPartRenderer" in renderer
    video_part_styles = styles[styles.index(".video-part {") : styles.index(".video-part video")]
    video_tag_styles = styles[styles.index(".video-part video") : styles.index(".video-part-header")]
    assert "width: 100%" in video_part_styles
    assert "max-width: 100%" in video_part_styles
    assert "width: 100%" in video_tag_styles
    assert "max-height: 70vh" in video_tag_styles


def test_script_lifecycle_audio_demo_duration_contract() -> None:
    source = read_repo("tests/test_script_agent.py")

    assert "test_script_lifecycle_lab_audio_demo_returns_audio_part" in source
    assert 'assert part["duration_ms"] == 5000' in source


def test_generated_registry_lists_single_file_read_command() -> None:
    registry = read_repo("docs/generated/REGISTRY.md")

    assert "| file | File Capability | read_file, read_text, read_image, read_audio | /read-file |  | parts, file, image, audio |" in registry
    assert "max_local_video_read_size_mb" in registry
    assert "/read-image" not in registry
    assert "/read-audio" not in registry
    assert "/read-video" not in registry
    assert "/file-audio" not in registry


def test_generated_registry_lists_single_http_fetch_url_command() -> None:
    registry = read_repo("docs/generated/REGISTRY.md")
    capability_detail = read_frontend("components/settings/CapabilityDetail.tsx")
    en_capabilities = read_frontend("i18n/resources/en/capabilities.json")
    zh_capabilities = read_frontend("i18n/resources/zh-CN/capabilities.json")

    assert "| http | HTTP Capability | fetch_url, get_text, fetch_page, fetch_image | /fetch-url |  | parts, text, text, image |" in registry
    assert "enable_fetch_url_command" in registry
    assert "/http-get" not in registry
    assert "/fetch-page" not in registry
    assert "/fetch-image" not in registry
    assert "enable_http_get" not in registry
    assert "enable_fetch_image" not in registry
    assert "enable_fetch_url_command" in capability_detail
    assert "enable_http_get" not in capability_detail
    assert "enable_fetch_image" not in capability_detail
    assert "/fetch-url" in en_capabilities
    assert "/fetch-url" in zh_capabilities


def test_form_and_command_button_parts_keep_existing_interactions() -> None:
    form_source = read_frontend("components/messages/parts/FormPartRenderer.tsx")
    buttons_source = read_frontend("components/messages/parts/CommandButtonsPartRenderer.tsx")
    bubble = read_frontend("components/MessageBubble.tsx")
    store = read_frontend("store/useWorkbenchStore.ts")

    assert "type: 'action_form'" in form_source
    assert "renderForm({ ...part, type: 'action_form' }, partIndex)" in form_source
    assert "type: 'command_buttons'" in buttons_source
    assert "renderCommandButtons({ type: 'command_buttons', buttons: part.buttons })" in buttons_source
    assert "renderForm={(form, blockIndex) => <ActionFormRenderer form={form} messageId={message.message_id} blockIndex={blockIndex} />}" in bubble
    assert "renderCommandButtons={(block) => <CommandButtonsRenderer block={block} />}" in bubble
    assert "submitForm(messageId, form.form_id, values, { silent })" in bubble
    assert "sendMessage(button.message)" in bubble
    assert "replaceFormPart(message.parts" in store


def test_copyable_and_renderable_message_content_are_parts_first() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    copyable_body = source[source.index("function copyableMessageContent") : source.index("function copyablePartsContent")]
    renderable_body = source[source.index("function hasRenderableMessage") : source.index("function hasVisibleRun")]

    assert "copyablePartsContent(message.parts)" in source
    assert "message.output_type" not in copyable_body
    assert "function copyablePartContent(part: MessagePart)" in source
    assert "if (part.type === 'json') return JSON.stringify(part.data, null, 2)" in source
    assert "if (part.type === 'form') return [part.title, part.description]" in source
    assert "if (part.type === 'command_buttons')" in source
    assert "if (hasRenderableParts(message.parts)) return true" in source
    assert "message.output_type" not in renderable_body


def test_markdown_knowledge_citations_still_skip_code_pre_and_links() -> None:
    source = read_frontend("components/MessageBubble.tsx")

    assert "parseKnowledgeCitationToken" in source
    assert "renderKnowledgeCitationChildren" in source
    assert "renderKnowledgeCitationNode" in source
    assert "['a', 'code', 'pre'].includes(node.type)" in source


def test_status_bar_only_shows_resolved_provider_and_model_target() -> None:
    source = read_frontend("components/StatusBar.tsx")

    assert "Default:" not in source
    assert "chat:statusBar.llmProviderModel" in source
    assert "chat:statusBar.llmMissingProviderProfile" in source
    assert "chat:statusBar.llmNoModelProfile" in source
    assert "chat:statusBar.llmNoLlm" in source


def test_default_model_menu_uses_agent_default_profile_not_effective_override() -> None:
    source = read_frontend("components/ChatInput.tsx")

    assert "resolveAgentDefaultLlmProfile" in source
    assert "const agentDefaultProfile = resolveAgentDefaultLlmProfile" in source
    assert "statusDotClass(agentDefaultProfile, llmProviderStatuses)" in source
    assert "statusDotClass(currentResolvedProfile" not in source


def test_composer_placeholder_mentions_current_agent_action_shortcut() -> None:
    source = read_frontend("components/ChatInput.tsx")

    assert "placeholder={t('placeholder')}" in source


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
    assert "chat:noCurrentAgent" in source
    assert "chat:noMatchingActions" in source
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

    assert "activeToken.token.startsWith('/')) return commandArgumentAutocompleteMode(activeToken.token, commands) ? 'command-arguments' : 'commands'" in source
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


def test_chat_header_has_context_sources_modal_contract() -> None:
    source = read_frontend("components/ChatHeader.tsx")
    client = read_frontend("api/client.ts")
    types = read_frontend("types.ts")

    assert "ContextSourcesButton" in source
    assert "ContextSourcesModal" in source
    assert "api.listKnowledgeBases()" in source
    assert "api.listSessionKnowledgeBases" in source
    assert "api.updateSessionKnowledgeBases" in source
    assert "api.getSessionWorldbooks" in source
    assert "api.updateSessionWorldbooks" in source
    assert "chat:contextSources.title" in source
    assert "buttonLabelCompact" in source
    assert "onReorder" in source
    assert "common:openSettings" in source
    assert "SessionKnowledgeBinding" in types
    assert "SessionWorldbookBinding" in types
    assert "sort_order: number" in types
    assert "listSessionKnowledgeBases" in client
    assert "updateSessionKnowledgeBases" in client
    assert "getSessionWorldbooks" in client
    assert "updateSessionWorldbooks" in client


def test_agent_overrides_has_knowledge_runtime_settings_contract() -> None:
    source = read_frontend("components/settings/AgentDetail.tsx")
    types = read_frontend("types.ts")

    assert "Knowledge Runtime Settings" in source
    assert "Use session knowledge bases" in source
    assert "Prompt Agents use Session KBs by default" in source
    assert "knowledge_context_mode" in source
    assert "knowledge_context_effective_mode" in source
    assert "'use_default' | 'enabled' | 'disabled'" in types


def test_agent_intent_routing_has_dedicated_tab_contract() -> None:
    source = read_frontend("components/settings/AgentDetail.tsx")
    types = read_frontend("types.ts")

    assert "['overview', 'overrides', 'actions', 'config', 'runtime', 'intentRouting', 'manifest']" in source
    assert "function IntentRoutingTab" in source
    assert "sections.intentRoutingEntry" in source
    assert "sections.intentRoutingTargetHints" in source
    assert "scriptIntentRoutingEntryUnsupported" in source
    assert "intent_routing_mode" in source
    assert "intent_routing_aliases_text" in source
    assert "intent_routing_examples_text" in source
    assert "'use_default' | 'enabled' | 'disabled'" in types
    overrides_body = source[source.index("function OverridesTab") : source.index("function IntentRoutingTab")]
    assert "sections.intentRoutingEntry" not in overrides_body
    assert "sections.intentRoutingTargetHints" not in overrides_body


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
    assert "ChatStatusPill" in source
    assert "api.getRuntimeResources()" in source
    assert "document.visibilityState === 'hidden'" in source
    assert source.index("<ChatStatusPill summary={tokenSummary} settings={generalSettings} />") < source.index("<ContextSourcesButton")


def test_failed_producer_messages_keep_identity_and_send_errors_are_local() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    store = read_frontend("store/useWorkbenchStore.ts")

    assert "hasProducerIdentity(message)" in source
    assert "message.speaker_type === 'capability'" in source
    assert "MessageErrorCard" in source
    assert "message.speaker_name" in source
    assert "createInlineErrorMessage(session.session_id, formatted.lastError, optimisticMessage.message_id)" in store
    assert "speaker_name: commandErrorTitle(error)" in store


def test_pet_auto_route_contracts_keep_original_user_message_and_readable_reasons() -> None:
    store = read_frontend("store/useWorkbenchStore.ts")
    settings_panel = read_frontend("components/settings/SettingsDetailPanel.tsx")
    en_settings = read_frontend("i18n/resources/en/settings.json")
    zh_settings = read_frontend("i18n/resources/zh-CN/settings.json")

    assert "hasFetchedReplacementUser(fetched, message)" in store
    assert "messageText(candidate) === messageText(message)" in store
    assert "generatedPetCommand" in settings_panel
    assert "targetIgnoredForAction" in settings_panel
    assert "notExecutedReason" in settings_panel
    assert "pet_target_ignored_for_action" in en_settings
    assert "pet_target_ignored_for_action" in zh_settings
    assert "ambiguous_pet_candidate" in en_settings


def test_popover_layer_uses_shared_z_index_above_composer() -> None:
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "--z-header: 100" in styles
    assert "--z-popover: 120" in styles
    assert "--z-composer: 4" in styles
    assert ".topbar {" in styles and "z-index: var(--z-header)" in styles
    assert ".popover-surface {" in styles and "z-index: var(--z-popover)" in styles
    assert ".session-menu {" in styles and "z-index: var(--z-popover)" in styles
    assert ".agent-menu {" in styles and "z-index: var(--z-popover)" in styles
    assert ".knowledge-picker-menu {" in styles and "z-index: var(--z-popover)" in styles
    assert ".model-selector-menu-portal {" in styles and "z-index: var(--z-popover)" in styles


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
    assert "const compactFailed = failed && !expanded && !hasManualExpanded && !forceExpanded" in source


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
    assert "parts: preserveStreamingContent ? message.parts : updatedMessage.parts" in source


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
    assert "replaceFormPart" in store
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
    assert "sendMessage(button.message)" in source
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
    assert "aria-label={t('chat:conversationMode')}" in source
    assert "{t('chat:mode')}</span>" in source
    assert "chat:modeSingle" in source
    assert "chat:modeGroup" in source
    assert "contextMode === 'group_transcript'" in source
    assert "changeContextMode('group_transcript')" in source
    assert "changeContextMode('single_assistant')" in source
    assert "chat:modeSingleTitle" in source
    assert "chat:modeGroupTitle" in source


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
    assert "settings:general.llmPrompts" in panel
    assert "general.autoGenerateTitles" in panel
    assert "general.sessionTitlePrompt" in panel
    assert "general.sessionTitleMaxChars" in panel
    assert "general.maxImageSize" in panel
    assert "general.sendTextFiles" in panel
    assert "general.contextRendering" in panel
    assert "general.groupTranscriptInstruction" in panel
    assert "general.commandResultInstruction" in panel
    assert "t('reset')" in panel
    assert "generalSettingsPatch(values)" in panel
    assert "group_transcript_system_instruction_default" not in panel[panel.index("function generalSettingsPatch") :]


def test_general_web_search_category_and_fields_are_exposed() -> None:
    types = read_frontend("types.ts")
    object_list = read_frontend("components/settings/SettingsObjectList.tsx")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")
    nav = read_frontend("components/settings/SettingsNav.tsx")

    assert "web_context_enabled: boolean" in types
    assert "web_context_max_results: number" in types
    assert "web_context_context_budget_chars: number" in types
    assert "web_context_prompt: string" in types
    assert "web_context_prompt_default: string" in types
    assert "web_context_plan_resolver_prompt: string" in types
    assert "web_context_candidate_judge_prompt: string" in types
    assert "web_context_page_excerpt_gate_prompt: string" in types
    assert "web_context_fetch_pages_enabled: boolean" in types
    assert "web_context_page_cleaning_enabled: boolean" in types
    assert "web_context_fetch_max_pages: number" in types
    assert "web_context_fetch_timeout_seconds: number" in types
    assert "web_context_fetch_max_bytes: number" in types
    assert "web_context_page_excerpt_chars: number" in types
    assert "web_context_total_page_excerpt_chars: number" in types
    assert "web_context_target_page_excerpts: number" in types
    assert "web_context_page_excerpt_gate_enabled: boolean" in types
    assert "web_context_page_excerpt_gate_backend: 'follow_agent_model_profile' | 'specific_model_profile' | 'utility_llm'" in types
    assert "web_context_page_excerpt_gate_model_profile_id: string | null" in types
    assert "web_context_page_excerpt_gate_min_quality: 'low' | 'medium' | 'high'" in types
    assert "web_context_candidate_judge_enabled: boolean" in types
    assert "web_context_candidate_judge_max_candidates: number" in types
    assert "web_context_candidate_judge_min_relevance: 'low' | 'medium' | 'high'" in types
    assert "web_context_candidate_judge_max_selected" not in types
    assert "'web_search'" in object_list
    assert "settings:general.webSearch" in object_list
    assert "settings:general.webSearchDescription" in object_list
    assert "icon: Globe" in object_list
    assert "category === 'web_search'" in panel
    assert "function GeneralWebSearchSettings" in panel
    assert "settings:general.enableWebSearchContext" in panel
    assert "settings:general.maxWebResults" in panel
    assert "settings:general.webContextBudget" in panel
    assert "settings:general.advancedPromptTemplates" in panel
    assert "settings:general.webContextInjectionPrompt" in panel
    assert "settings:general.webContextPlanResolverPrompt" in panel
    assert "settings:general.candidateRelevanceJudgePrompt" in panel
    assert "settings:general.pageExcerptGatePrompt" in panel
    assert "settings:general.resetToDefault" in panel
    assert "settings:general.pageFetching" in panel
    assert "settings:general.enhancedContentCleaning" in panel
    assert "settings:general.maxPagesToTry" in panel
    assert "settings:general.maxPagesToTryHelp" in panel
    assert "settings:general.targetAcceptedPageExcerpts" in panel
    assert "settings:general.targetAcceptedPageExcerptsHelp" in panel
    assert "settings:general.totalPageExcerptBudget" in panel
    assert "settings:general.pageExcerptGate" in panel
    assert "settings:general.pageExcerptGateBackend" in panel
    assert "settings:general.pageExcerptGateModelProfile" in panel
    assert "settings:general.minimumExcerptQuality" in panel
    assert "settings:general.candidateRelevanceJudge" in panel
    assert "settings:general.maxCandidatesToJudge" in panel
    assert "settings:general.minimumRelevance" in panel
    assert "settings:general.minimumRelevanceHelp" in panel
    assert "settings:general.maxSelectedSources" not in panel
    assert "conservative reject-only noise filter" in read_frontend("i18n/resources/en/settings.json")
    assert "does not choose the final source count" in read_frontend("i18n/resources/en/settings.json")
    assert "settings:general.searchProvider" in panel
    assert "capability_id === 'web_search'" in panel
    assert "web_context_enabled: values.web_context_enabled" in panel
    assert "web_context_prompt: values.web_context_prompt" in panel
    assert "web_context_plan_resolver_prompt: values.web_context_plan_resolver_prompt" in panel
    assert "web_context_candidate_judge_prompt: values.web_context_candidate_judge_prompt" in panel
    assert "web_context_page_excerpt_gate_prompt: values.web_context_page_excerpt_gate_prompt" in panel
    assert "web_context_fetch_pages_enabled: values.web_context_fetch_pages_enabled" in panel
    assert "web_context_page_cleaning_enabled: values.web_context_page_cleaning_enabled" in panel
    assert "web_context_total_page_excerpt_chars: values.web_context_total_page_excerpt_chars" in panel
    assert "web_context_target_page_excerpts: values.web_context_target_page_excerpts" in panel
    assert "web_context_page_excerpt_gate_enabled: values.web_context_page_excerpt_gate_enabled" in panel
    assert "web_context_page_excerpt_gate_backend: values.web_context_page_excerpt_gate_backend" in panel
    assert "web_context_candidate_judge_enabled: values.web_context_candidate_judge_enabled" in panel
    files_body = panel[panel.index("function GeneralFilesSettings"):panel.index("function GeneralMemorySettings")]
    web_search_body = panel[panel.index("function GeneralWebSearchSettings"):panel.index("function titleModelProfileOptionLabel")]
    base_card = web_search_body[web_search_body.index("settings:general.webSearchContext"):web_search_body.index("settings:general.candidateRelevanceJudge")]
    assert "web_context_fetch_pages_enabled" not in files_body
    assert "web_context_prompt" not in base_card
    assert "web_context_fetch_pages_enabled" in web_search_body
    assert "web_context_candidate_judge_enabled" in web_search_body
    assert "labelKey: 'sections.webSearch'" not in nav


def test_web_search_capability_settings_render_filtering_fields() -> None:
    detail = read_frontend("components/settings/CapabilityDetail.tsx")
    types = read_frontend("types.ts")
    en_capabilities = read_frontend("i18n/resources/en/capabilities.json")
    zh_capabilities = read_frontend("i18n/resources/zh-CN/capabilities.json")

    assert "capabilities:sections.resultQuality" in detail
    assert "result_filter_enabled" in detail
    assert "domain_blocklist" in detail
    assert "domain_allowlist" in detail
    assert "dedupe_results" in detail
    assert "dedupe_same_domain_title" in detail
    assert "filteredResults" in detail
    assert "deduplicatedResults" in detail
    assert "filtersApplied" in detail
    assert "export type WebSearchDiagnostics" in types
    assert '"resultQuality": "Result quality"' in en_capabilities
    assert '"resultQuality": "结果质量"' in zh_capabilities


def test_run_context_summary_includes_web_context_compact_metadata() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    runs_en = read_frontend("i18n/resources/en/runs.json")

    assert "type WebContextSummary" in source
    assert "record.web_context" in source
    assert "source_refs" in source
    assert "WebSourcesTab" in source
    assert "web-citation-badge" in source
    assert "function mergeWebContexts" in source
    assert "summary.web" in source
    assert "webSummaryLabel" in source
    assert "runs:contextSummary.web" in source
    assert "runs:contextSummary.webResultCount" in source
    assert "runs:contextSummary.searchQuery" in source
    assert "runs:contextSummary.webQuerySource" in source
    assert "runs:contextSummary.webResolverConfidence" in source
    assert "runs:stepMessages.intentUsedForWebContext" in source
    assert "metadata?.web_context_plan" in source
    assert "webSkipReasonLabel" in source
    assert "webQuerySourceLabel" in source
    assert "webContextPlanStepMessage" in source
    assert "searchDiagnostics" in source
    assert "pageFetchEnabled" in source
    assert "page_fetch_status" in source
    assert "page_excerpt_preview" in source
    assert "page_cleaning_status" in source
    assert "page_cleaning_cleaned_chars" in source
    assert "pageExcerptGate" in source
    assert "page_excerpt_gate_status" in source
    assert "page_excerpt_quality" in source
    assert "page_excerpt_confidence" in source
    assert "page_excerpt_coverage" in source
    assert "page_excerpt_gate_reason" in source
    assert "page_excerpt_gate_warning" in source
    assert "candidateJudge" in source
    assert "candidate_judge_relevance" in source
    assert "candidate_judge_role" in source
    assert "candidate_judge_confidence" in source
    assert "candidate_judge_state" in source
    assert "candidate_judge_reason" in source
    assert "selectedCount" not in source
    assert "filteredResults" in source
    assert "deduplicatedResults" in source
    assert "webCandidatesJudged" in source
    assert "pagesFetched" in source
    assert "pagesFailed" in source
    assert "pageExcerptGateStatus" in source
    assert '"web": "Web"' in runs_en
    assert '"webContextPlan": "Web context plan"' in runs_en
    assert '"intentUsedForWebContext": "{{intent}} - not executed as route · used for Web context"' in runs_en
    assert '"webResultCount": "{{count}} results · {{provider}}"' in runs_en
    assert '"webCandidatesJudged": "judged {{judged}} / retained {{retained}} / rejected {{rejected}} / unjudged {{unjudged}}"' in runs_en
    assert '"pagesFetched": "{{count}} pages fetched"' in runs_en
    assert '"pageExcerptGate": "pages attempted {{attempted}} · accepted {{accepted}} · rejected {{rejected}} · failed {{failed}}"' in runs_en
    assert '"accepted": "gate accepted"' in read_frontend("i18n/resources/en/chat.json")
    assert '"rejected": "gate rejected"' in read_frontend("i18n/resources/en/chat.json")
    assert '"knowledge_query_candidate_blocked": "knowledge query candidate blocked"' in runs_en
    assert '"web_results_filtered_empty": "all web results were filtered"' in runs_en
    assert '"webSkipReasons"' in runs_en


def test_web_sources_modal_card_removes_duplicate_low_value_fields() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    body = source[source.index("function WebSourcesTab"):source.index("function judgeStateLabel")]

    assert "web-source-card" in body
    assert "ref_id" in body
    assert "ref.domain || t('chat:contextModal.domain')" in body
    assert "sourceUrl" not in body
    assert "{ref.domain ? <span>{t('chat:contextModal.domain')}" not in body
    assert "{ref.page_title ? <span>{t('chat:contextModal.pageTitle')}" not in body
    assert "const searchSnippet = ref.snippet_preview || ref.snippet" in body
    assert "fetchedExcerptPreview" in body
    assert "chat:contextModal.searchSnippet" in body
    assert "chat:contextModal.fetchedPageExcerpt" in body
    assert "pageCleaningStatusLabel(ref, t)" in body
    assert "context-content-block" in body
    assert "showNotInjected" in body
    assert "chat:contextModal.notInjected" in body
    assert "href={ref.url}" in body
    assert "chat:contextModal.openSource" in body
    assert "const confidence = ref.page_excerpt_gate_status ? ref.page_excerpt_confidence : ref.candidate_judge_confidence" in body
    assert body.count("chat:contextModal.confidence") == 1
    assert "candidate_judge_confidence ? <Chip" not in body
    assert "ref.page_excerpt_gate_reason ? <span>" not in body
    assert "pageFetchWarningLabel(ref.page_excerpt_gate_warning, t)" in body
    assert "chat:contextModal.unknownWarning" in source
    chat_en = read_frontend("i18n/resources/en/chat.json")
    assert '"searchSnippet": "Search snippet"' in chat_en
    assert '"fetchedPageExcerpt": "Fetched page excerpt"' in chat_en
    assert '"cleaned": "cleaned"' in chat_en
    assert '"notInjected": "not injected"' in chat_en
    assert '"page_excerpt_gate_invalid_json": "Invalid Gate JSON."' in chat_en
    assert '"page_excerpt_gate_repaired_json_string_controls": "Gate JSON string controls were repaired."' in chat_en
    assert "setContextModalInitial({ tab: 'web', targetRef: refId })" in source
    assert "targetRefElement.current.scrollIntoView" in source
    assert "KnowledgeSnippetsTab" in source
    assert "WorldbookEntriesTab" in source


def test_running_run_steps_default_to_active_only_until_manually_expanded() -> None:
    source = read_frontend("components/MessageBubble.tsx")
    styles = read_frontend("styles.css")

    assert "const compactActive = active && !expanded && !hasManualExpanded && !forceExpanded" in source
    assert "const compactFailed = failed && !expanded && !hasManualExpanded && !forceExpanded" in source
    assert "activeRunStep(stepTree)" in source
    assert "failedRunStep(stepTree, run, getRunStatusLabel(run?.status, t))" in source
    assert "run-step-active-list" in source
    assert "compact" in source
    assert "function activeRunStep" in source
    assert "function failedRunStep" in source
    assert "step.status === 'running'" in source
    assert "step.status === 'pending'" in source
    assert "step.status === 'failed'" in source
    assert "`${run.run_id}:failed-summary`" in source
    assert "function mostSpecificRecentStep" in source
    assert "function defaultRunStepsExpanded" in source
    assert "return false" in source
    assert ".run-step-active-list" in styles


def test_chat_input_web_search_toggle_patches_general_settings_and_reuses_intent_motion() -> None:
    input_source = read_frontend("components/ChatInput.tsx")
    styles = read_frontend("styles.css")

    assert "const [webSearchSaving, setWebSearchSaving]" in input_source
    assert "const [webSearchPendingValue, setWebSearchPendingValue]" in input_source
    assert "async function toggleWebSearch()" in input_source
    assert "await updateGeneralSettings({ web_context_enabled: nextEnabled })" in input_source
    assert "'composer-intent-toggle'" in input_source
    assert "'composer-web-search-toggle'" in input_source
    assert "webSearchSaving ? 'pending' : ''" in input_source
    assert "disabled={!webSearchReady}" in input_source
    assert "disabled={webSearchSaving}" not in input_source
    assert "aria-label={webSearchEnabled ? t('webSearch.disable') : t('webSearch.enable')}" in input_source
    assert "<Globe size={15}" in input_source
    controls = input_source[input_source.index("composer-actions") : input_source.index("<div ref={modelSelectorRef}")]
    assert controls.index("intentRoutingVisualEnabled") < controls.index("webSearchVisualEnabled")
    assert ".composer-intent-toggle.pending {\n  border-color: rgba(255, 255, 255, 0.18);" in styles
    pending_start = styles.index(".composer-intent-toggle.pending {")
    pending_block = styles[pending_start : styles.index("}", pending_start)]
    assert "cursor: wait" in pending_block
    assert "not-allowed" not in pending_block


def test_general_intent_routing_auto_mode_contract() -> None:
    types = read_frontend("types.ts")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")

    assert "intent_routing_mode: 'shadow' | 'auto';" in types
    assert '<option value="auto">{t(\'settings:general.autoMode\')}</option>' in panel
    assert "settings:general.autoModeHelp" in panel
    assert "settings:general.autoModeSafeRoutingOff" in panel
    assert "settings:general.intentRoutingExplicitBypass" in panel
    assert "settings:general.intentRoutingShadowRecords" in panel
    assert "settings:general.intentRoutingAutoSafeOnly" in panel
    assert "intent_routing_semantic_intent_min_score: number;" in types
    assert "settings:general.semanticThresholds" in panel
    assert "settings:general.openUtilityLlmSettings" not in panel
    assert "legacyEmbeddingPathConfigured" not in panel


def test_general_settings_uses_middle_category_list() -> None:
    console = read_frontend("components/settings/SettingsConsole.tsx")
    object_list = read_frontend("components/settings/SettingsObjectList.tsx")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")

    assert "type GeneralSettingsCategory = 'files' | 'llm_prompts'" in object_list
    assert "{ id: 'files', name: t('settings:general.files'), description: t('settings:general.filesDescription'), icon: SlidersHorizontal }" in object_list
    assert "{ id: 'llm_prompts', name: t('settings:general.llmPrompts'), description: t('settings:general.llmPromptsDescription'), icon: SlidersHorizontal }" in object_list
    assert "if (section === 'general')" in object_list
    general_branch = object_list[object_list.index("if (section === 'general')") : object_list.index("if (section === 'agents')")]
    assert "<ObjectListHeader title={t('settings:objectList.category')} count={generalCategories.length} />" in general_branch
    assert "No objects in this section." not in general_branch
    assert "generalCategory === category.id ? 'active' : ''" in general_branch
    assert "onSelectGeneralCategory?.(category.id)" in general_branch

    assert "useState<GeneralSettingsCategory>('files')" in console
    assert "setGeneralCategory('files')" in console
    assert "generalCategory={generalCategory}" in console
    assert "onSelectGeneralCategory={setGeneralCategory}" in console

    assert "generalCategory = 'files'" in panel
    assert "<GeneralDetail category={generalCategory} llmProfiles={llmProfiles} onDirtyChange={onDirtyChange} onSelectGeneralCategory={onSelectGeneralCategory} />" in panel
    assert "function GeneralFilesSettings" in panel
    assert "function GeneralPromptSettings" in panel
    assert "category === 'files' ? (" in panel
    assert "DetailTabs" not in panel
    assert "generalTab" not in panel


def test_appearance_settings_has_chat_status_panel_category() -> None:
    console = read_frontend("components/settings/SettingsConsole.tsx")
    object_list = read_frontend("components/settings/SettingsObjectList.tsx")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")
    types = read_frontend("types.ts")

    assert "type AppearanceSettingsCategory = 'pet' | 'fonts' | 'chat_status_panel'" in object_list
    assert "settings:appearance.chatStatusPanel" in object_list
    assert "appearanceCategory={appearanceCategory}" in console
    assert "onSelectAppearanceCategory={setAppearanceCategory}" in console
    assert "appearanceCategory === 'pet'" in panel
    assert "ChatStatusPanelDetail" in panel
    assert "resource_status_panel_enabled: boolean" in types
    assert "resource_status_show_tokens: boolean" in types


def test_knowledge_settings_uses_three_column_console_and_api_wiring() -> None:
    nav = read_frontend("components/settings/SettingsNav.tsx")
    console = read_frontend("components/settings/SettingsConsole.tsx")
    object_list = read_frontend("components/settings/SettingsObjectList.tsx")
    panel = read_frontend("components/settings/SettingsDetailPanel.tsx")
    knowledge = read_frontend("components/settings/KnowledgeSettingsPanel.tsx")
    client = read_frontend("api/client.ts")

    assert "'knowledge'" in nav
    assert "labelKey: 'sections.knowledge'" in nav
    assert "export type KnowledgeSettingsCategory = KnowledgeSettingsSubsection" in object_list
    assert "export type KnowledgeSettingsCategory = 'defaults' | 'embedding_models' | 'knowledge_bases'" in read_frontend("types.ts")
    assert "settings:subsections.defaults" in object_list
    assert "settings:subsections.embeddingModels" in object_list
    assert "settings:subsections.knowledgeBases" in object_list
    assert "if (section === 'knowledge')" in object_list
    assert "knowledgeSubsection === 'defaults'" in object_list
    assert "useState<KnowledgeSettingsSubsection>('defaults')" in console
    assert "setSelectedKnowledgeSubsection('defaults')" in console
    assert "knowledgeSubsection={selectedKnowledgeSubsection}" in console
    assert "onKnowledgeSubsectionChange={changeKnowledgeSubsection}" in console
    assert "<KnowledgeSettingsDetail" in panel

    assert "knowledge:sections.localModels" in knowledge
    assert "knowledge:sections.embedding" in knowledge
    assert "knowledge:sections.reranker" in knowledge
    assert "t('sections.retrieval')" in knowledge
    assert "t('sections.chunking')" in knowledge
    assert "t('sections.indexLimits')" in knowledge
    assert "t('sections.contextInjection')" in knowledge
    assert "knowledge:actions.scanLocalModels" in knowledge
    assert "knowledge:actions.testReranker" in knowledge
    assert "knowledge:actions.test" in knowledge
    assert "empty.noEmbeddingProfiles" in knowledge
    assert "empty.noKnowledgeBases" in knowledge
    assert "empty.noKnowledgeBases" in knowledge
    assert "empty.noSources" in knowledge
    assert "knowledge:actions.pasteText" in knowledge
    assert "api.listKnowledgeSources" in knowledge
    assert "api.createPastedKnowledgeSource" in knowledge
    assert "api.deleteKnowledgeSource" in knowledge
    assert "api.reindexKnowledgeSource" in knowledge
    assert "api.scanKnowledgeModels()" in knowledge
    assert "api.updateKnowledgeSettings" in knowledge
    assert "api.testEmbeddingModel" in knowledge
    assert "api.rerankKnowledge" in knowledge
    assert "backendLabel(scan?.backend, t)" in knowledge
    assert "knowledge:backend.unavailableOptionalDeps" in knowledge

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

    assert "message.metadata?.event_type" in source
    assert "SystemEventSeparator" in source
    assert "system-event-separator" in source
    assert ".system-event-separator" in styles
    assert ".mode-switcher" in styles
