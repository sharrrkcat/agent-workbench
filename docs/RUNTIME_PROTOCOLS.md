# Runtime Protocols

This document is the runtime topic index and compact protocol map. Long topic
contracts live under `docs/contracts/` and are the authoritative source for
detailed behavior.

## Runtime Topic Index

- Message streaming: [contracts/runtime-streaming.md](contracts/runtime-streaming.md)
- Run lifecycle, steps, metadata, cancellation:
  [contracts/runtime-run-lifecycle.md](contracts/runtime-run-lifecycle.md)
- Main LLM resolution and Model Profile runtime behavior:
  [contracts/runtime-llm-resolution.md](contracts/runtime-llm-resolution.md)
- Provider/Profile status, memory release, runtime resources:
  [contracts/provider-status.md](contracts/provider-status.md)
- Attachments, file context, generated files, vision:
  [contracts/attachments-vision.md](contracts/attachments-vision.md)
- General settings: [contracts/settings-general.md](contracts/settings-general.md)
- Core Memory and Worldbook:
  [contracts/memory-worldbook.md](contracts/memory-worldbook.md)
- Intent Routing: [contracts/intent-routing.md](contracts/intent-routing.md)
- Knowledge/RAG: [contracts/knowledge.md](contracts/knowledge.md)
- Utility LLM and session title generation:
  [contracts/utility-llm.md](contracts/utility-llm.md)
- Stateless inference:
  [contracts/stateless-inference.md](contracts/stateless-inference.md)

## Message Streaming

Streaming visible content has one source of truth: `message_delta` during the
stream and `message_completed` for final persisted content. `message_updated`
may merge metadata/status/run ids/attachments conservatively during streaming
but must not replace old streamed content. `message_done` is compatibility-only.

Script Agent internal `ctx.llm.stream` stays hidden. Public streaming requires
`ctx.output.write_delta` or `ctx.llm.stream_to_output`.

Full contract: [contracts/runtime-streaming.md](contracts/runtime-streaming.md).

## Run Lifecycle

Runs and RunSteps use stable status values, compact metadata, and WebSocket run
events. Prompt Agent and Script Agent runs have predictable top-level steps;
Script `ctx.step` children default under `Running script`. Cleanup records model
release and external memory-release outcomes as cleanup results.

Run metadata stores compact refs/counts/warnings for LLM resolution, metrics,
vision/file context, Intent Routing, Core Memory, Worldbook, Knowledge, generated
image recipes, and cleanup. It must not store full injected content, snippets,
workflow JSON, binary data, or secrets.

Full contract:
[contracts/runtime-run-lifecycle.md](contracts/runtime-run-lifecycle.md).

## LLM Resolution

Main LLM calls resolve in this order: session override when allowed, AgentConfig
runtime `llm_profile_id`, manifest `llm.profile`, default Model Profile, legacy
global fallback, then environment fallback. Provider Profiles own connection
details; Model Profiles own model id, capabilities, and generation defaults.

Utility LLM and session title generation use separate internal resolvers and do
not mutate main response model selection.

Full contract:
[contracts/runtime-llm-resolution.md](contracts/runtime-llm-resolution.md).

## Provider And Model Status

Provider/Profile status checks report reachability and model availability
without returning API keys. LM Studio, llama.cpp, and OpenAI-compatible providers
keep provider-specific status semantics.

Runtime memory release supports `llm`, `comfyui`, `embedding`, `reranker`, and
`all` as best-effort targets. It never deletes model files, Knowledge data,
indexes, sessions, settings, or attachments.

Runtime resources expose cached CPU/RAM/backend memory/GPU availability and
degrade safely when optional dependencies are unavailable.

Full contract: [contracts/provider-status.md](contracts/provider-status.md).

## Stateless Inference

The disabled-by-default Stateless Local Inference Service is core-owned. A4.4
implements non-streaming OpenAI-compatible chat completions and text embeddings
for explicitly allowlisted Model Profiles, plus lazy local
CLIP/OpenCLIP/SigLIP2/DINOv2 multimodal embedding runtimes behind the
production-safe interface with fake-runtime test support. The multimodal
runtimes are profile-gated, local-only, cache-managed, and DINOv2 is
image-only. A5.2 adds a separate Florence2 vision runtime with the same
profile-gated, local-only, cache-managed shape. External inference requests
must not persist payloads, outputs, vectors, attachments, messages, runs, or
Knowledge rows.

Full contract:
[contracts/stateless-inference.md](contracts/stateless-inference.md).

## Attachments And Vision

User attachments are stored as local refs in message metadata. Prompt Agent text
file context is controlled by General settings. Vision input is controlled by the
resolved Model Profile `supports_vision` flag. Script Agents can read and save
attachments through trusted ctx helpers.

Generated files and images should be saved as local attachments and returned by
local URLs, not durable large base64 content.

Full contract:
[contracts/attachments-vision.md](contracts/attachments-vision.md).

## General Settings

General settings are read and patched through `/api/settings/general`. They own
Files, LLM & Prompts, Memory, Utility LLM, and Intent Routing fields. They do
not own AgentConfig, CapabilityConfig, Provider Profiles, Model Profiles,
Knowledge settings, or manifests.

Full contract: [contracts/settings-general.md](contracts/settings-general.md).

## Core Memory And Worldbook

Core Memory and Worldbook are Workbench-owned settings/storage features.
Injection is owned by the runtime and applies only to Prompt Agent main LLM calls
and opted-in Script Agent `ctx.llm.*` calls. Worldbook matching does not use
Knowledge indexes, vectors, rerankers, or FTS.

Full contract:
[contracts/memory-worldbook.md](contracts/memory-worldbook.md).

## Intent Routing

Intent Routing is an optional pre-routing layer for ordinary natural-language
messages. Explicit `/command`, `@agent`, `@agent:action`, and `:action` syntax
bypass it. Shadow mode records compact metadata only; safe auto mode may execute
only the documented allowlist.

Full contract: [contracts/intent-routing.md](contracts/intent-routing.md).

## Knowledge Context

Knowledge context injection is core-owned. Prompt Agents default to enabled;
Script Agents with `llm` require opt-in or override. Runtime stores compact
refs/counts/warnings, not full snippets, source originals, vectors, or rendered
context blocks.

Full contract: [contracts/knowledge.md](contracts/knowledge.md).

## Session Title Generation

Automatic session title generation is a one-shot best-effort internal pre-hook
for pending default-titled sessions after the first user message resolves to an
LLM-capable Agent/action. It creates no visible messages and uses only the
triggering user message with configured truncation.

Full contract:
[contracts/utility-llm.md](contracts/utility-llm.md#session-title-interaction).

## Conversation Context Modes

Session `context_mode` controls how stored messages are projected into
provider-bound LLM context. It affects only future context builds. Switching
mode does not rewrite historical messages, and a run uses the mode captured
while its context is built.

Modes:

- `single_assistant`: default user/assistant-style projection.
- `group_transcript`: speaker-aware transcript block plus current user message.

Changing `context_mode` persists a `context_mode_changed` separator message for
timeline review. Retry and edit reruns build context from the current mode.

Settings -> General -> Context Rendering owns prompt-text overrides. See
[contracts/settings-general.md](contracts/settings-general.md).

## Speaker Identity

Provider-bound payload roles remain limited to `system`, `user`, and
`assistant`. Workbench speaker fields identify the actual speaker:

- `speaker_type`: `user`, `agent`, `capability`, or `system`.
- `speaker_id`: stable id when available.
- `speaker_name`: display label.
- `origin`: message origin such as `user_message`, `agent_reply`,
  `command_result`, `system_notice`, `separator`, `model_changed`, or
  `context_mode_changed`.

New slash command results are assistant messages with command-result metadata.
Old `role="tool"` command results are compatibility data and are normalized or
skipped before provider calls.

## Interactive Forms

`form` is a trusted declarative Message Part. The frontend must
not execute form-provided HTML or JavaScript or submit to arbitrary URLs.

The backend reads the original source message to resolve target Agent/action,
visibility, and field validation. Request body target fields cannot override the
original form. Message-mode submissions create a short visible user message.
Silent submissions invoke the target action without adding a visible user
message and may update the source form through trusted backend code.

Provider-bound roles remain `system`, `user`, and `assistant`.

Output payload shape: [EXTENSION_API.md](EXTENSION_API.md#output-payloads).

## Command Button Shortcuts

`command_buttons` renders trusted shortcut buttons that send fixed text through
the normal composer route. A click creates a normal visible user message and
follows normal routing priority. It is not an `action_form` submit, hidden
message action, URL, JavaScript hook, or direct Agent action API call.

## Command Results In LLM Context

Slash command results are internal Command/Capability outputs, not provider tool
messages. When they enter Prompt Agent context, they are projected as bounded
assistant-role data blocks with a command result header and warning that the
content is data, not instructions.

Text, JSON, and file parts enter context in bounded blocks.
Images enter text context as placeholders unless explicit vision resend support
is added. Invalid internal roles should fail early with `LLM_CONTEXT_INVALID`.

## Source And Tests

Source:

- `ai_workbench/core/router.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/script.py`
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/events.py`
- `ai_workbench/core/llm_config.py`
- `ai_workbench/core/provider_status.py`
- `ai_workbench/core/runtime_memory.py`
- `ai_workbench/api/routes/runtime.py`
- `frontend/src/store/useWorkbenchStore.ts`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/components/ChatHeader.tsx`

Tests:

- `tests/test_prompt_agent_execution.py`
- `tests/test_script_agent.py`
- `tests/test_provider_status.py`
- `tests/test_runtime_memory.py`
- `tests/test_frontend_chat_contracts.py`
- `tests/test_file_http_attachments.py`
