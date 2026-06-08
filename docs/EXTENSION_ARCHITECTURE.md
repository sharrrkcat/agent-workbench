# Extension Architecture

This is the design guide for complex Agent Workbench extensions. It complements:

- [EXTENSION_API.md](EXTENSION_API.md): concrete Agent, Capability, ctx, config,
  and output APIs.
- [RUNTIME_PROTOCOLS.md](RUNTIME_PROTOCOLS.md): runtime topic index.
- [docs/generated/REGISTRY.md](generated/REGISTRY.md): installed Agents and
  Capabilities.

Use this document before writing code for an external integration, local
workspace tool, knowledge bridge, long task Agent, or LLM-assisted tool workflow.
It is not a tutorial or product-specific recipe.

## Extension Categories

### Pure Agent

Use when the extension interprets user input, calls an LLM, orchestrates a
workflow, and returns text, JSON, images, or rich content without reusable
low-level tools.

Typical components:

- `agents/<agent_id>/agent.yaml`
- optional `agents/<agent_id>/agent.py`
- prompt, action definitions, context policy, and output rendering

Avoid creating a Capability only for prompt formatting or trusting raw LLM output
as structured data without validation.

### Tool Capability

Use when behavior is reusable, has stable method contracts, can back slash
commands, or can be unit tested without chat UI.

Typical components:

- `capabilities/<capability_id>/capability.yaml`
- `capabilities/<capability_id>/__init__.py`
- optional slash commands in the Capability manifest

Avoid letting a Capability decide conversational style or adding slash commands
to an Agent.

### External Service Integration

Use a Capability for protocol, auth, retries, timeouts, and normalized errors.
Use a Script Agent for user-facing workflow, LLM planning, progress, and final
output. Tests should use a fake runtime or mock HTTP server.

Avoid storing API keys in `agent.yaml`, calling the service directly from Agent
workflow code when it is reusable, or relying on temporary remote URLs as the
only durable output.

### Local Workspace Integration

Use a Capability for path validation, read/write operations, conflict handling,
size limits, and allowlists. Use a Script Agent for intent, preview/write
decisions, LLM transforms, and summaries. Tests should use temporary
directories.

Avoid paths outside configured roots, unconditional writes, and raw LLM output
overwriting files directly.

### Long-Running Workflow

Use when work has phases such as validate, submit, poll, fetch, save, and
render. Capabilities expose submit/status/fetch/cancel when supported. Script
Agents expose progress through run steps and handle timeout/cancellation.

Runtime lifecycle details:
[contracts/runtime-run-lifecycle.md](contracts/runtime-run-lifecycle.md).

### Knowledge Bridge

Knowledge v1 is core-owned: local model settings, indexing, vector/FTS storage,
retrieval, session bindings, and automatic context injection live in core
services. The `knowledge` Capability is a thin wrapper over core retrieval and
status.

Full contract: [contracts/knowledge.md](contracts/knowledge.md).

### Stateless Inference

The Stateless Local Inference Service is core-owned because it touches
Provider/Model Profiles, runtime caches, settings, OpenAI-compatible routes,
status, unload, and the external privacy boundary. A future Capability may wrap
trusted Script Agent helpers only.

Full contract:
[contracts/stateless-inference.md](contracts/stateless-inference.md).

### LLM-Assisted Tool Orchestration

Use `ctx.llm.text`, `ctx.llm.json`, or `ctx.llm.stream` when the LLM drafts
intermediate data that script code validates before a Capability executes
effects. Public output should happen only after validation and execution
decisions.

Never trust raw LLM JSON for file writes, network calls, or destructive actions.
Do not rely on provider function calling unless the project explicitly supports
it.

## Agent Vs Capability Decision Table

Use an Agent when code owns:

- user interaction.
- intent interpretation.
- workflow/action selection.
- LLM calls and validation.
- orchestration across steps.
- progress through `ctx.step`.
- final chat output.

Use a Capability when code owns:

- reusable tool behavior.
- external service protocol.
- local file/workspace operations.
- stable method inputs and outputs.
- slash commands.
- functionality reusable by multiple Agents.
- unit testing without chat UI.

Recommended split:

```text
External API / protocol / file operation -> Capability
User-facing workflow / LLM planning / progress / final response -> Agent
```

Rules:

- Do not hide reusable protocol or file code inside one `agent.py` unless it is
  truly one-off.
- Do not create a Capability for pure prompt formatting.
- Do not let a Capability decide user-facing conversation style.
- Keep Agent actions user-callable and workflow-oriented.
- Keep Capability methods narrow, named, and reusable.
- Put slash commands only in Capability manifests.

## Example Split: ComfyUI

- `capabilities/comfyui`: connection tests, workflow submission, polling,
  queue/history reads, image fetches, interrupt, upload, object info, `/free`
  memory request, and workflow/preset library operations.
- `agents/comfyui_agent`: recipe form, input mode, LLM prompt operation,
  workflow filling, progress, output attachment saving, optional memory-release
  request, and final image gallery.

Workflow files and preset YAML are local user assets managed by ComfyUI
Capability configuration. Session recipes are per-session, per-agent runtime
state. Preset YAML is specified in
[COMFYUI_PRESET_SCHEMA.md](COMFYUI_PRESET_SCHEMA.md).

Generated images should be saved as local attachments and rendered as
attachment-backed image outputs. Attachment rules:
[contracts/attachments-vision.md](contracts/attachments-vision.md).

ComfyUI memory release is best-effort cleanup and should not turn an already
successful generation into a failed run. Runtime memory rules:
[contracts/provider-status.md](contracts/provider-status.md#runtime-memory-release).

## Configuration Ownership

`CapabilityConfig` stores connection and tool behavior such as URLs, API keys,
allowed directories, write toggles, timeouts, polling, file-size limits,
redirect/network limits, and provider or service-specific transport settings.

`AgentConfig` stores workflow and user experience defaults such as templates,
output format, target folders, prompt style, preview/write mode, tags,
generation defaults, seed policy, and Agent-specific behavior toggles.

Rules:

- Connection and protocol config belongs to `CapabilityConfig`.
- User-facing behavior and workflow defaults belong to `AgentConfig`.
- Secrets belong to `CapabilityConfig` or Provider Profile, not `agent.yaml`.
- Package defaults can live in manifests.
- Local user values live in AgentConfig or CapabilityConfig records.
- If multiple Agents can use the same connection, do not store it only in one
  AgentConfig.

Core-owned configuration:

- General settings: [contracts/settings-general.md](contracts/settings-general.md)
- Provider/Model Profiles and LLM resolution:
  [contracts/runtime-llm-resolution.md](contracts/runtime-llm-resolution.md)
- Knowledge: [contracts/knowledge.md](contracts/knowledge.md)
- Intent Routing: [contracts/intent-routing.md](contracts/intent-routing.md)
- Utility LLM and titles: [contracts/utility-llm.md](contracts/utility-llm.md)
- Core Memory and Worldbook:
  [contracts/memory-worldbook.md](contracts/memory-worldbook.md)
- Stateless inference:
  [contracts/stateless-inference.md](contracts/stateless-inference.md)

## Data Ownership And Output Rules

Choose output payloads by returned data:

- short plain text: `text` part with `format: plain`.
- rendered prose: `text` part with `format: markdown`.
- structured data for inspection: `json` part.
- raw source/config/log/note text: `file` part.
- one image: `image` part.
- multiple images: `media_group` part.
- ordered mixed result: `parts`.
- long-term file/image result: save as local attachment or stable local
  reference where possible.

Rules:

- Do not return raw workflow logs as markdown when a `file` part fits better.
- Do not use large data URLs for durable outputs when attachment storage exists.
- Do not return remote temporary service URLs as the only final result.
- Keep raw debug data in metadata or `file` parts, not primary prose.
- Prefer local attachment-backed image outputs for generated images.
- Use `json` for plans, validation reports, and structured downstream data.
- Use `parts` only when ordered mixed content matters.

Output shape contract: [EXTENSION_API.md](EXTENSION_API.md#output-payloads).
Attachment contract:
[contracts/attachments-vision.md](contracts/attachments-vision.md).

## Long-Running Workflow Pattern

Recommended step structure:

```text
Running script
  Prepare input
  Validate configuration
  Build request/workflow
  Submit or start task
  Wait for completion
  Fetch or build outputs
  Save artifacts
  Render result
Cleanup
```

Rules:

- Use `ctx.step` for user-meaningful progress.
- Poll non-blocking status methods at configured intervals.
- Stop polling on cancellation.
- Fetch outputs only after completion.
- Cancellation is best effort and should not corrupt already saved outputs.
- Do not block the event loop with long synchronous loops.

## LLM Usage Patterns

- Final LLM output: use Prompt Agents or `ctx.llm.stream_to_output`.
- Internal transform: use `ctx.llm.text`, `ctx.llm.json`, or hidden
  `ctx.llm.stream`, then validate.
- Utility LLM: core-only service for titles and Intent Routing JSON slots. Full
  contract: [contracts/utility-llm.md](contracts/utility-llm.md).
- Public streaming: only use `ctx.llm.stream_to_output` or
  `ctx.output.write_delta` for user-facing text. Full contract:
  [contracts/runtime-streaming.md](contracts/runtime-streaming.md).

## External Writes And Safety

- Prefer preview before destructive or persistent writes.
- Make write behavior configurable.
- Validate paths and stay inside allowed directories.
- Do not let raw LLM output directly overwrite files.
- Consider backup or conflict handling before overwriting.
- Return a clear summary of changes.
- Keep secrets out of logs, markdown replies, metadata, and generated files.
- Tests must cover denied paths and disabled write mode.

## Cancellation And Timeout Rules

- Long tasks should accept cancellation if possible.
- Capabilities should expose cancel/interrupt when the service supports it.
- Unsupported external cancellation should stop local polling and mark the local
  run cancelled.
- Timeout should fail the relevant step with a clear message.
- Partial outputs should be intentionally kept or discarded based on safety and
  usefulness.

Run lifecycle and cancellation:
[contracts/runtime-run-lifecycle.md](contracts/runtime-run-lifecycle.md).

## Testing Strategy

General rules:

- Do not require real external services in automated tests.
- External service integrations use fake runtime or mock HTTP server.
- Local workspace integrations use temp directories.
- LLM behavior uses mock text, JSON, or stream chunks.
- Images use small fake bytes.
- Tests should cover success, unreachable, invalid response, timeout,
  cancellation, and output validation.
- Run `check_agents.py --strict` for manifest validation.
- Update generated registry when manifests change.
- Keep tests focused on contracts and failure behavior, not personal environment
  state.

## Example Mappings

ComfyUI:

- Category: External Service Integration plus Long-Running Workflow.
- Capability: service protocol and workflow/preset assets.
- Agent: workflow fill, progress, output rendering.
- Output: `media_group` plus markdown summary.
- Tests: fake ComfyUI server or runtime.

Obsidian / LLM Wiki:

- Category: Local Workspace Integration plus Knowledge Bridge.
- Capability: vault read/search/write.
- Agent: note generation, backlinks, preview/write.
- Output: markdown summary plus `file` note preview.
- Tests: temp vault plus mock LLM JSON.

GitHub issue triage:

- Category: External Service Integration plus LLM-assisted Tool Orchestration.
- Capability: GitHub API.
- Agent: summarize, label suggestions, draft comments.
- Output: markdown plus JSON plan.
- Tests: mock API responses.

## Non-Goals

This document does not define product-specific workflow details, UI workflow
editors, plugin marketplace behavior, permission system design, external service
installation instructions, provider-specific authentication docs, full
diagnostics implementation, or frontend styling rules.
