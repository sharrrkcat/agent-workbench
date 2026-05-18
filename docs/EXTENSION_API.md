# Extension API

This document is the compact contract for writing Agents, Capabilities, Script
Agent code, config schema fields, and output payloads. Runtime protocol details
live in [RUNTIME_PROTOCOLS.md](RUNTIME_PROTOCOLS.md) and focused contracts under
[contracts/](contracts/).

## Agent Manifest

| field | applies to | meaning | notes |
| --- | --- | --- | --- |
| `id` | all Agents | Global Agent id. | Must be unique and match the directory in strict checks. |
| `name` | all Agents | Display name. | Can be overridden locally. |
| `type` | all Agents | `prompt` or `script`. | Controls runtime path. |
| `description` | all Agents | Short display/help text. | Optional. |
| `avatar` | all Agents | Text or local image reference. | Optional. |
| `entry` | script | Python file entry point. | Required for script Agents; must stay inside Agent dir. |
| `actions` | all Agents | User-callable entry points. | Must include `default`; ids are unique per Agent. |
| `prompt` | prompt | System prompt base text. | Runtime appends action instruction when present. |
| `capabilities` | all Agents | Capability ids the Agent expects. | Prompt Agents that use LLM should declare `llm`. |
| `llm.profile` | prompt, LLM scripts | Model Profile id or alias. | Participates in LLM resolution. |
| `llm.allow_session_override` | prompt, LLM scripts | Whether session model override can win. | Defaults to true when `llm` exists. |
| `context_policy` | all Agents/actions | Core-built context scope. | Action policy can override Agent policy. |
| `model_lifecycle` | all Agents | Load/unload policy. | Unload is best effort. |
| `config_schema` | all Agents | User-editable local config fields. | Stored as AgentConfig `user_config`. |

### Action Fields

| field | meaning | notes |
| --- | --- | --- |
| `id` | Action id. | `default` is required. |
| `label` | Button/display label. | Strict checks require label or description. |
| `description` | Short help text. | Useful for generated registry and UI. |
| `instruction` | Prompt Agent action instruction. | Appended to the Agent prompt for that action. |
| `input_schema` | Action input metadata. | Not a model function-call schema. |
| `context_policy` | Action-specific context. | Overrides Agent context policy. |
| `llm` | Action-specific LLM settings. | Merged over Agent `llm`. |
| `attach_to` | UI attachment hint. | Used by message actions when present. |
| `callable` | Whether action is user-callable. | Defaults to true. |

Text routing supports:

- `@agent_id text` -> Agent `default`.
- `@agent_id:action args` -> explicit Agent action.
- `:action args` -> action on the current session default Agent only.

The `:action` shortcut does not infer from previous messages, recent Agent
calls, or other Agents. Use full `@agent_id:action` for buttons, saved
shortcuts, and cross-Agent calls.

Actions with `callable: false` are excluded from user-facing composer
autocomplete and direct text/API user invocation returns a not-callable error.
Trusted `action_form` submission may still target a non-callable action declared
by the original form block.

## Config Schema Fields

| field | meaning |
| --- | --- |
| `name` | Config key. |
| `type` | `string`, `text`, `integer`, `float`, `boolean`, `enum`, or `json`. |
| `label` | Settings display label. |
| `required` | Whether user config must provide a value when no default exists. |
| `default` | Manifest default value. |
| `description` | Settings help text. |
| `options` | Required for `enum`. |
| `secret` | Masks stored/displayed values. |
| `minimum` / `maximum` | Numeric bounds. |

Enum fields with manifest defaults render concrete enum values in Settings, not
an `unset` business option. Clearing an override is separate from choosing an
enum value; empty/null enum patches remove the override, while strings such as
`unset` are invalid unless explicitly listed in `options`.

## Agent Overrides

- Manifest values are package defaults.
- `AgentConfig` stores local overrides and enablement.
- Config tab writes `config_schema` values into `user_config`.
- Overrides tab edits display/runtime overrides.
- Display overrides include name, description, and avatar.
- Prompt override replaces the manifest prompt at runtime.
- LLM runtime override can set `llm_profile_id` and `allow_session_override`.
- Knowledge runtime override can set `knowledge_context_mode` to `use_default`,
  `enabled`, or `disabled`.
- Intent Routing runtime fields are edited under Agent detail -> Intent Routing.
- Reset overrides clears local AgentConfig values back to manifest behavior.
- Write overrides to manifest only when intentionally changing package defaults.

Knowledge overrides are summarized in [contracts/knowledge.md](contracts/knowledge.md).
Intent Routing overrides are summarized in
[contracts/intent-routing.md](contracts/intent-routing.md). Main LLM resolution
is owned by
[contracts/runtime-llm-resolution.md](contracts/runtime-llm-resolution.md).

## Prompt Agents

Prompt Agents let the core runtime build context and call the LLM. Model output
is treated as markdown text assistant content, not tool calls or structured
commands. Prompt Agent final messages persist a markdown `text` part in Message
Parts v2. Prompt Agents that call an LLM should declare `capabilities: [llm]`.

Core Memory, Worldbook, Knowledge, streaming, LLM resolution, and title
generation are runtime-owned. See the focused runtime, Memory/Worldbook,
Knowledge, and Utility LLM contracts under [contracts/](contracts/).

## Script Agents

Script Agents are trusted local Python imported into the backend process.
`entry` must export `async def run(ctx)`. Older scripts that return a final value
or reply once remain valid. Do not run untrusted Script Agent code; there is no
sandbox.

Script Agents are not Intent Routing router entries in the first alpha. They can
be called explicitly through `@agent`, `@agent:action`, `:action`, forms, or
trusted action invocation.

```python
async def run(ctx):
    async with ctx.step("Prepare input"):
        text = ctx.input.text.strip()
    await ctx.reply_markdown(f"Echo: {text}")
```

## Script Context API

### `ctx.input`

- `text`: routed argument text for this invocation.
- `action_id`: current Agent action id.
- `form_id`: submitted `action_form` id when applicable.
- `is_silent_submission`: true for silent `action_form` submissions.
- `attachments`: current message attachment metadata.
- `source_message_id`: source message for form/button/action invocations.
- `prefill`: structured action prefill data, including validated form values.

### `ctx.step` / `ctx.run`

- `ctx.step(name)` creates a visible run step.
- Script custom steps default under top-level `Running script`.
- Steps should describe user-meaningful progress.
- `ctx.run` exposes trusted lifecycle helpers such as starting, completing,
  failing, and updating steps.

Run lifecycle details:
[contracts/runtime-run-lifecycle.md](contracts/runtime-run-lifecycle.md).

### `ctx.session`

- `session_id`: current Session id.
- `default_agent_id`: current default Agent id.
- `context_mode`: current Session context projection mode.

Context modes are summarized in [RUNTIME_PROTOCOLS.md](RUNTIME_PROTOCOLS.md#conversation-context-modes).

### `ctx.state`

- `ctx.state.get(key, default=None)` reads per-session, per-agent JSON runtime
  state.
- `ctx.state.set(key, value)` writes per-session, per-agent JSON runtime state.
- State is scoped by `session_id + agent_id + key`.
- State is for runtime copies such as form-backed recipes, not user-owned source
  files, manifests, or Capability asset files.

### `ctx.llm`

- `ctx.llm.text(...)` returns final text.
- `ctx.llm.json(...)` parses and validates a JSON object from final text.
- `ctx.llm.generate(...)` performs a configured generation helper call.
- `ctx.llm.stream(...)` is internal and hidden from chat.
- `ctx.llm.stream_to_output(...)` is public output streaming.
- `ctx.output.write_delta(...)` appends visible public content.
- `ctx.output.finish(...)` completes the public streaming message.
- `ctx.llm.unload()` is legacy capability-runtime unload when supported.
- `ctx.llm.unload_model(...)` is trusted script-only provider/model-profile
  unload and returns structured outcome data.

The first real `ctx.llm.*` provider call in a pending default-titled session may
trigger the internal title pre-hook. Agent authors should not call title
generation manually.

Depending on runtime settings and Agent overrides, Core Memory, Worldbook, and
Knowledge may be appended to eligible `ctx.llm.*` calls. Script defaults are disabled unless opted in.

Runtime details live in the focused contracts for LLM resolution, streaming,
Memory/Worldbook, and Knowledge.

Development examples live in [AGENT_DEVELOPMENT.md](AGENT_DEVELOPMENT.md).

### Reply Helpers

- `reply_parts`: send ordered Message Parts v2 content.
- `reply_text`: send plain text.
- `reply_markdown`: send markdown-rendered content.
- `reply_json`: send a JSON object or array.
- `reply_image`: send one image payload with `url`.
- `reply_images`: send an ordered image gallery.
- `reply_audio` / `reply_video`: send one attachment-backed AudioPart or
  VideoPart from a saved attachment or validated part dict.
- `reply_blocks`: convenience helper that immediately converts block-like input
  to Message Parts. Prefer `reply_parts` and typed helpers.
- `reply_form` / `reply_action_form`: validate and send one `form` part.
- `reply_file_content`: send raw file text, not markdown-rendered content.

`reply_parts(parts, metadata=None)` is the v2 foundation; runtime sets
`content_version=2`. Existing helpers are parts wrappers. Reply helpers accept
optional compact metadata such as generated image recipe refs.

## Attachments In Script Agents

Script attachment helpers:

- `ctx.input.attachments`
- `ctx.read_attachment_text(attachment_or_id)`
- `ctx.read_attachment_bytes(attachment_or_id)`
- `ctx.attachment_as_data_url(attachment_or_id)`
- `ctx.save_attachment_bytes(...)`
- `ctx.save_attachment_base64(...)`
- `ctx.save_attachment_file(...)`

Generated files, images, audio, and video should be saved as attachments and
returned through local attachment URLs. Full contract:
[contracts/attachments-vision.md](contracts/attachments-vision.md).

## Capabilities

Capability manifests declare internal methods and optional global slash
commands.

| field | meaning | notes |
| --- | --- | --- |
| `id` | Global Capability id. | Must be unique and match directory in strict checks. |
| `name` | Display name. | Human-readable. |
| `methods` | Internal callable methods. | Method id must match runtime callable. |
| `input_schema` | Method input contract. | Lightweight manifest metadata. |
| `output.part_type` | Declared output part shape. | Used by commands and validation before persistence as Message Parts. |
| `commands` | User-facing slash commands. | Global namespace; names start with `/`. |
| `safe` | Command safety hint. | Documentation/UI hint, not a sandbox. |
| `config_schema` | Local CapabilityConfig fields. | Settings stores values by capability id. |

### Command Fields

| field | meaning | notes |
| --- | --- | --- |
| `name` | Global slash command name. | Must start with `/`. |
| `method` | Capability method to call. | Must reference a declared method. |
| `description` | Short command help text. | Used by UI and generated registry. |
| `safe` | Command safety hint. | Does not enforce sandbox behavior. |
| `confirm` | Optional confirmation text. | UI/runtime may use it before execution. |
| `argument_suggestions` | UI argument hints. | Optional list of `{ value, label?, description?, next_suggestions? }`; `value` must be non-empty. `next_suggestions.provider` is a core allowlist for second-argument UI hints; v1 supports only `pet_ids` for `/pet select <pet_id>`. It is not validation, a URL/import/runtime callback/shell hook, or passed to runtime methods. |

For a minimal manifest example, see [CAPABILITY_DEVELOPMENT.md](CAPABILITY_DEVELOPMENT.md).

Runtime call rules:

- Runtime can export `get_runtime()` or `CapabilityRuntime`.
- Strict checks import runtime code and require every manifest method id to exist
  as a callable.
- Command methods receive `(args, context)` or `(args)` depending on callable
  signature.
- Script Agents call capabilities through `await ctx.capability("id").method(...)`.
- If a runtime method accepts `context`, Script calls receive resolved
  CapabilityConfig, session id, capability id, and current attachments.
- Capability methods should return plain Python values matching declared output.

## Built-In Capability Summaries

`knowledge` is a thin wrapper over core Knowledge services and may expose
`list_bases`, `stats`, `search`, and `/kb-search`. It does not own retrieval,
indexing, embedding, reranking, local model backends, or automatic injection.
Full contract: [contracts/knowledge.md](contracts/knowledge.md).

`runtime` exposes `/free-memory <target>` and runtime memory APIs for best-effort release of `llm`, `comfyui`, `embedding`, `reranker`, or `all`; see [contracts/provider-status.md](contracts/provider-status.md#runtime-memory-release).

`comfyui` is a reusable external-service/local-asset Capability for workflow
submission, polling, fetching images, interrupts, upload, object info, memory
release, and workflow/preset library operations. Preset YAML is documented in
[COMFYUI_PRESET_SCHEMA.md](COMFYUI_PRESET_SCHEMA.md). User-facing generation
workflow belongs to the Script Agent.

Utility LLM, Intent Routing, General settings, and Knowledge settings are core-owned services; see `contracts/utility-llm.md`, `contracts/intent-routing.md`, and `contracts/settings-general.md`.

The built-in `file` Capability exposes only `/read-file <path>`, auto-detects text/image/audio/video into matching Message Parts, keeps one command toggle with per-kind limits, and does not support network reads or media analysis.

The built-in `codec` Capability exposes `/encode` and `/decode` for Base64 text, Base64URL tokens, URL component percent encoding, Unicode escapes, hex UTF-8 text, Base64 data URLs, image attachment encoding, and QR generation with `/encode qr <text>`. QR generation returns an attachment-backed PNG image part. QR decoding is not implemented. It does not fetch URLs, read local paths, transcode media, inspect JWTs, hash content, or inspect arbitrary binaries.

The built-in `http` Capability exposes only `/fetch-url <url>`, auto-detects text/HTML/JSON/image/direct audio/direct video into Message Parts, and keeps one command toggle with separate text/image limits. Direct audio and video use `source: url` and are not downloaded, cached, proxied, or saved locally.
Streaming media, OCR, ASR, TTS, transcription, and PDF parsing are unsupported.

## Capability Config

- `config_schema` declares Settings fields.
- Stored CapabilityConfig is local state, not package manifest data.
- Runtime command context receives `capability_config` after schema validation.
- Unknown config keys are rejected by API validation.

## Output Payloads

### Message Parts v2

New Agent, Script Agent, and Capability command replies persist visible content
as `content_version=2` plus ordered `parts`; supported part types and rules live
in [contracts/message-parts.md](contracts/message-parts.md). The frontend renders
normal messages only from `parts`.

Capability commands declare `output.part_type`: `text`, `json`, `file`,
`image`, `audio`, `video`, `media_group`, or `parts`. Text declarations may set
`format: plain|markdown`; file declarations may set `mode: inline_text`; media
groups may set `layout: gallery`. `output.type` is invalid.

`audio` outputs support local attachments and safe HTTP/HTTPS direct audio URLs:
`source: attachment` requires `attachment_id` plus local `/api/attachments/...`;
`source: url` requires HTTP/HTTPS and is not downloaded, cached, proxied, or
saved locally. Both require `audio/*` MIME type. `video` outputs support local
attachments and safe HTTP/HTTPS direct video URLs with the same source rules and
require `video/*` MIME type. HLS/DASH, `.m3u8`, `.mpd`, `.pls`, livestreams,
radio, podcast RSS, video page extraction, TTS, ASR/transcription, audio/video
understanding, thumbnails/posters, transcoding, and media input to LLMs are not
part of this API.

Markdown `text` parts keep render-time Knowledge citation enhancement.

### `action_form` Block

`action_form` is declarative JSON. It supports `text`, `textarea`, `integer`,
`float`, `boolean`, `enum`, and `json` fields. It does not support HTML,
JavaScript, arbitrary URLs, uploads, secret fields, remote options, or automatic
execution.

Supported UI metadata is static: `sections`, form `ui.default_collapsed`,
`ui.collapsed`, `ui.collapse_on_success`, `ui.collapsed_message`, and per-field
`ui.section` / `ui.span`. It shapes rendering only, not provider context,
target resolution, or validation.

On submit, the frontend sends only `source_message_id`, `form_id`, and `values`.
The backend reads the original message, resolves target/visibility from the
original block, and validates values against the original fields. Message
visibility creates a short `form_submission` user message. Silent visibility
invokes the target action without a visible user message and may refresh the
source form through trusted backend code.

### `command_buttons` Block

`command_buttons` renders trusted send-message shortcuts. On click, the frontend
sends the configured `message` through the same ordinary user-message path as
manual composer input. It does not send `prefill`, attachments, hidden action
payloads, arbitrary URLs, or executable frontend code.

Streaming and command-button runtime behavior:
[contracts/runtime-streaming.md](contracts/runtime-streaming.md#command-buttons).
