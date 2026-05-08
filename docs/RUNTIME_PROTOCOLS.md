# Runtime Protocols

## Message Streaming

- Streaming content has one source of truth.
- During streaming, visible content is updated by `message_delta`.
- `message_updated` must not replace streaming content.
- `message_completed` is the final authoritative content.
- `message_delta` is a realtime transport event. By default it is sent over WebSocket but is not persisted to the SQLite event log.
- `message_completed` persists the final assistant message content.
- Settings -> Data -> `Persist streaming message deltas` makes `message_delta` persist for debugging.
- Run steps, errors, warnings, and other diagnostic events are not affected by the streaming delta persistence setting.
- `message_delta` carries `message_id`, `run_id`, `seq`, `delta`, and optional `reasoning_delta`.
- `message_completed` carries `message_id`, `run_id`, `seq`, and final `message`.
- `seq` is monotonic per message.
- The frontend ignores older `seq`.
- The frontend ignores delta after completed if `seq` is old.
- `message_updated` can merge metadata, `run_id`, attachments, and status, but not old content while streaming.
- Internal `ctx.llm.stream` does not emit public `message_delta`.
- `ctx.output.write_delta` and `ctx.llm.stream_to_output` emit public deltas.

Producer rules:
- Emit `message_started` before public deltas for a new assistant draft.
- Increment `seq` once for each public delta.
- Emit `message_completed` once with the final message and a greater `seq`.
- Keep final message content equal to the accumulated visible deltas unless an explicit final replacement is intended.
- Include `draft_message_id` on completion when the frontend may need to replace a draft id.
- Do not emit empty visible deltas unless carrying `reasoning_delta`.

Frontend merge rules:
- Use `message_id` plus `draft_message_id` to resolve the active streaming row.
- Track the last accepted `seq` per message.
- Mark messages completed after `message_completed`.
- Merge `message_updated` conservatively while streaming.
- Attach run metrics and steps without resetting streamed content.

Tiny event examples:

```json
{
  "type": "message_delta",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {"seq": 1, "delta": "hel", "reasoning_delta": null}
}
```

```json
{
  "type": "message_completed",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {"seq": 2, "message": {"message_id": "msg_1", "content": "hello"}}
}
```

## Run Lifecycle

Run status values:
- `PENDING`
- `RUNNING`
- `CANCELLING`
- `WAITING_FOR_USER`
- `DONE`
- `FAILED`
- `CANCELLED`
- `INTERRUPTED`

RunStep status values:
- `pending`
- `running`
- `completed`
- `failed`
- `skipped`

Run steps:
- `RunStep.parent_step_id` creates nesting.
- Prompt Agent default top-level steps include `Resolving agent`, `Building context`, `Resolving model`, `Calling LLM`, `Saving response`, and `Cleanup`.
- Script Agent default top-level steps include `Resolving agent`, optional `Resolving model`, `Starting script`, `Running script`, `Saving response`, and `Cleanup`.
- Script custom steps created with `ctx.step` default under `Running script`.
- Model lifecycle unload outcomes are shown on the `Cleanup` step when cleanup attempts unload.
- Session load returns runs and steps attached to messages.

Run metadata:
- Prompt Agent runs record `llm_resolution` when model resolution succeeds.
- Prompt Agent runs can record `llm_metrics`, `vision_input`, `file_context`, and reasoning metadata.
- Model lifecycle unload attempts are recorded under `llm_unload`, including success, skipped, unsupported, failure, and provider status refresh outcome.
- Failures should set both run status and user-visible error metadata where applicable.
- Cancellation sets `cancel_requested` before terminal cancellation when possible.

WebSocket events:
- `run_updated`
- `run_step_created`
- `run_step_updated`
- `run_completed`
- `run_failed`

Related events:
- `run_started` marks creation/start but does not include the full lifecycle payload.
- `run_cancel_requested` marks a cancellation request.
- `run_cancelled` marks terminal cancellation.
- `run_warning` carries non-fatal lifecycle warnings.
- `message_done` is a compatibility completion signal; do not use it as streaming source of truth.
- `llm_provider_status_updated` carries a refreshed provider status payload after runtime-triggered model status changes.

Cancel API:

```text
POST /api/runs/{run_id}/cancel
```

Frontend run-step expansion:
- `running`, `cancelling`, `failed`, and `cancelled` render expanded by default.
- `completed` renders collapsed by default.
- Manual toggle state is scoped by `run_id`.

Prompt Agent step contract:
- `Resolving agent` applies AgentConfig runtime overrides.
- `Building context` uses the resolved context policy.
- `Resolving model` resolves provider/model profile and attachment capabilities.
- `Calling LLM` wraps the provider call or stream.
- `Saving response` persists final assistant content.
- `Cleanup` applies model lifecycle policy.

Script Agent step contract:
- `Resolving agent` loads the script entry.
- `Resolving model` appears only when the Agent uses `llm`.
- `Starting script` marks pre-run setup.
- `Running script` is the parent for normal `ctx.step` calls.
- `Saving response` finalizes returned or replied content.
- `Cleanup` applies model lifecycle policy.

Failure behavior:
- If a step fails, emit `run_step_updated` with `failed`.
- If the run fails, emit `run_failed` with a run payload and error details.
- If a Script Agent streamed partial content before failure, complete the partial message rather than dropping visible output.
- If no partial content exists, write an error payload for the assistant message.
- Terminal statuses should not be moved back to `RUNNING`.

## LLM Resolution

Resolution order:

1. Session override when allowed.
2. AgentConfig runtime `llm_profile_id`.
3. Manifest `llm.profile`.
4. Default model profile.
5. Legacy global fallback.
6. Environment fallback.

Semantics:
- Provider Profile means connection details: provider, base URL, API key, and timeout.
- Model Profile means model id, capabilities, and generation defaults.
- Actual model metadata comes from provider response.
- Composer `Default` means agent default resolved model.
- Assistant message header model badges prefer Model Profile display name/name, then requested model id, then actual model id.
- Actual model id is preserved in message/run metadata and debug details/tooltips even when the short badge shows the Model Profile name.
- The bottom status bar may keep its debug-oriented provider profile plus model target/actual display and does not need to match chat message badges.
- `supports_streaming` controls visible Prompt Agent streaming.
- Script Agent public streaming requires explicit `ctx.output.write_delta` or `ctx.llm.stream_to_output`.
- `supports_vision` controls image input to Prompt Agent LLM calls.
- `supports_reasoning` is an output declaration and does not force provider behavior.
- Unload is trusted script-only for manual script calls, and best-effort for lifecycle policies.
- Successful, skipped, unsupported, and failed unload attempts remain cleanup outcomes in run metadata; unsupported unload and status refresh failure do not overwrite an otherwise successful run unless the lifecycle policy explicitly fails on unload failure.

Current implementation note: `resolve_llm_config` applies defaults first and then overrides later sources, so later sources win. Keep user-facing behavior aligned with the order above when changing it.

Profile capability flags:
- `supports_streaming`: enables visible Prompt Agent stream path.
- `supports_vision`: allows image attachments to be encoded into LLM messages.
- `supports_tools`: reserved capability flag; routing does not depend on model tool calls.
- `supports_reasoning`: declares expected reasoning output metadata.
- `supports_json_mode`: declares provider/model support, but scripts must still validate JSON.

Fallback notes:
- Legacy global fallback comes from persisted `llm` CapabilityConfig.
- Environment fallback uses `AGENT_WORKBENCH_LLM_BASE_URL`, `AGENT_WORKBENCH_LLM_API_KEY`, `AGENT_WORKBENCH_LLM_MODEL`, and `AGENT_WORKBENCH_LLM_TIMEOUT`.
- Session override is ignored when the resolved Agent runtime disallows it.
- Missing model selection raises `LLM_MODEL_NOT_SELECTED`.

Prompt Agent LLM calls:
- Non-streaming calls store one final assistant message.
- Streaming calls emit deltas, then store final content on completion. Deltas are persisted only when Settings -> Data enables `Persist streaming message deltas`.
- Context warnings may be attached to message metadata.
- Image vision metadata records supported, attached, sent, and ignored counts.
- File context metadata records included text attachment details and warnings.

Script Agent LLM calls:
- `ctx.llm.text`, `ctx.llm.json`, and `ctx.llm.generate` mark the LLM as used for lifecycle cleanup.
- `ctx.llm.stream` marks the LLM as used but remains internal.
- `ctx.llm.stream_to_output` both uses the LLM and writes public deltas.
- Scripts must parse and validate model output themselves.
- Scripts should not assume provider function calling is available.

## Conversation Context Modes

Session `context_mode` controls how the core projects stored messages into provider-bound LLM context. It affects only future context builds. Switching the mode does not rewrite historical messages, and a run uses the mode captured while its context is built.

Modes:
- `single_assistant`: default mode. The core preserves the existing user/assistant-style chat history projection as closely as possible.
- `group_transcript`: speaker-aware mode. The core renders historical messages into one transcript block and sends the current user input in a separate current-message block.

Retry and edit reruns build context from the current session `context_mode`.

## Speaker Identity

Message `role` is the provider-compatible direction of the message. New provider-bound payloads may only use `system`, `user`, and `assistant`.

Message speaker fields identify the actual Workbench speaker:
- `speaker_type`: `user`, `agent`, `capability`, or `system`.
- `speaker_id`: stable speaker id when available, such as `local_user`, an Agent id, or a Capability id.
- `speaker_name`: display name used for transcript labels.
- `origin`: message origin such as `user_message`, `agent_reply`, `command_result`, `system_notice`, `separator`, `model_changed`, or `context_mode_changed`.

New user messages use `role="user"`, `speaker_type="user"`, `speaker_id="local_user"`, `speaker_name="User"`, and `origin="user_message"`.

New Agent replies use `role="assistant"`, `speaker_type="agent"`, `speaker_id=<agent_id>`, the resolved Agent display name as `speaker_name`, and `origin="agent_reply"`.

New slash command results use `role="assistant"`, `speaker_type="capability"`, `speaker_id=<capability_id>`, a Capability or command display name as `speaker_name`, and `origin="command_result"`. Their metadata continues to include `metadata.kind="command_result"`, `metadata.command`, `metadata.capability_id`, and `metadata.output_type`.

Old messages may lack speaker fields. Context projection falls back from role, top-level `agent_id` / `command_name`, and command-result metadata. Old `role="tool"` command results are compatibility data only and are normalized or skipped before provider calls.

## Group Transcript Context

In `group_transcript`, the provider payload still only uses `system`, `user`, and `assistant` roles.

The system message contains the Agent prompt or prompt override plus identity instructions:
- The current Agent is told its own name.
- Prior messages from the same Agent are labeled `[Agent Name (you)]`.
- Other Agent messages are labeled `[Agent Name]`.
- User messages are labeled `[User]`.
- Command result blocks are labeled `[Command result: ...]` and explicitly described as data, not instructions.
- The Agent is instructed to reply only as itself and not impersonate other Agents.

The user message contains:
- `<conversation_transcript>` with recent history rendered using speaker labels.
- `<current_user_message>` with the current user input, which is always preserved.

System, separator, model-changed, and context-mode-changed event messages are skipped by default so they do not pollute the transcript. Transcript rendering is a temporary context projection; it does not modify stored message content.

This mode does not implement auto mode, automatic Agent collaboration, Agent-to-Agent scheduling, function calling, tool calls, or MCP.

## Command Results in LLM Context

- Slash command results are internal Command/Capability outputs, not OpenAI tool messages.
- Commands remain declared by Capabilities, not Agents.
- The project does not emit `role="tool"` or `role="function"` to LLM providers unless a future implementation adds the full function/tool calling protocol, including assistant tool calls and matching tool result ids.
- New slash command result messages are stored as assistant messages with command-result metadata such as `metadata.kind="command_result"`, `metadata.producer="capability"`, `metadata.command`, `metadata.capability_id`, and `metadata.output_type`.
- Old persisted `role="tool"` or `role="command"` command result messages are compatibility data. Context projection must normalize them before provider calls or skip them if they cannot be safely paired with a triggering user command.
- When command results enter Prompt Agent context, they are projected as assistant messages with a clear command result header, capability source, output type, and the warning that the content is data, not instructions.
- Command result projection must not use system-role content, because command output should not receive system-level weight.
- Pair-aware trimming keeps a slash command user message and its command result together. If the triggering user command is trimmed out, the command result is also trimmed out.
- Text and markdown outputs enter context in a bounded `<command_output>` block.
- JSON outputs enter context as a bounded `<json>` block.
- `file_content` outputs enter context in a bounded `<file_content>` block with filename, MIME type, size, and truncated metadata.
- Image and image gallery outputs enter text context as placeholders only. Historical image bytes or data URLs are not resent unless explicit vision resend support is implemented.
- Rich content outputs preserve block order where practical: text, markdown, and file content blocks are expanded; image blocks become placeholders.
- Binary or unsupported command outputs enter context as placeholder summaries instead of raw data.
- Provider-bound chat payload validation allows only `system`, `user`, and `assistant` roles. Invalid internal roles should fail early with `LLM_CONTEXT_INVALID` rather than surfacing provider prompt-template errors as the only diagnostic.

## Provider and Model Status

Status values:
- `READY`: provider and configured model look usable.
- `PROVIDER_UNREACHABLE`: connection failed or timed out.
- `MODEL_NOT_AVAILABLE`: provider is reachable but requested model is absent.
- `MODEL_MISMATCH`: single-model provider is serving a different model.
- `MODEL_STATUS_UNKNOWN`: provider response was incomplete or ambiguous.

Provider behavior:
- LM Studio first uses native `/api/v1/models` when available.
- LM Studio native responses can include `loaded_instances`; unload targets loaded matching instances.
- LM Studio model status is green `READY` when the model exists and has loaded instances, yellow `MODEL_NOT_LOADED` when it exists without loaded instances, and red for missing or unreachable providers.
- LM Studio falls back to OpenAI-compatible model listing when native status is unavailable.
- llama.cpp router mode reports a list of models.
- llama.cpp single-server mode reports only the currently served model; use `--alias` for a stable id.
- OpenAI-compatible providers support basic reachability/model-list status when the API exposes models.
- OpenAI-compatible model status is green `READY` when the provider is reachable, `/v1/models` returns a parseable list, and the configured model id exists in that list.
- OpenAI-compatible model status is red when the provider is unreachable, the provider/model profile cannot be resolved, the target model id is missing, or the parseable model list does not contain the configured model id.
- OpenAI-compatible providers do not expose portable loaded/unloaded pool semantics, so they should not produce yellow unloaded status.

Status usage:
- Provider-level status is an aggregate across configured model profiles.
- Model-level status is more specific and should be preferred for user-facing model badges.
- A reachable provider with an incomplete model list should not be treated as ready without model evidence.
- Unload support is provider-specific; unsupported unload should be reported as a warning unless policy says fail.
- Unload is available to trusted script/runtime paths only, not as a normal user-facing action.
- After an unload attempt finishes, refresh the affected provider profile status and emit `llm_provider_status_updated` when refresh succeeds.
- Unsupported unload and unload-triggered status refresh failures are cleanup outcomes and must not overwrite an otherwise successful main run.

## Attachments and Vision

- User attachments are stored as local refs in message metadata.
- Image attachments are sent to the LLM only when resolved Model Profile has `supports_vision=true`.
- Text files are sent to Prompt Agent context only when the General setting enables file context.
- Script Agents can read attachments through trusted helpers.
- `file_content` displays raw text and should not be markdown-rendered.

Attachment metadata:
- User message metadata keeps attachment refs rather than full base64 payloads.
- Prompt Agent vision resolves images to data URLs only for supported profiles.
- Unsupported image input becomes a text placeholder or warning instead of a vision payload.
- File attachment context obeys per-file and per-message byte limits.
- File and HTTP Capabilities are active commands, not passive upload handling.

Output rendering boundaries:
- Backend output type selects the frontend renderer.
- `markdown` content is rendered as markdown.
- `file_content` content is rendered as raw text.
- `image` and `image_gallery` payloads require renderable URLs.
- `rich_content` preserves ordered blocks.
- The frontend must not infer streaming state from content shape.
- Renderer changes should update output payload contracts when shapes change.

## Source and Tests

Source:
- `ai_workbench/core/runner.py`
- `ai_workbench/core/script.py`
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/events.py`
- `ai_workbench/core/llm_config.py`
- `ai_workbench/core/provider_status.py`
- `frontend/src/store/useWorkbenchStore.ts`
- `frontend/src/components/MessageBubble.tsx`

Tests:
- `tests/test_prompt_agent_execution.py`
- `tests/test_script_agent.py`
- `tests/test_provider_status.py`
- `tests/test_frontend_chat_contracts.py`
- `tests/test_file_http_attachments.py`
