# Extension API

## Purpose

This document is the compact contract for writing Agents, Capabilities, Script Agent code, and output payloads.

For architecture decisions about whether to build an Agent, a Capability, or both, read `docs/EXTENSION_ARCHITECTURE.md` first.

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

Minimal Prompt Agent:

```yaml
id: demo_prompt
name: Demo Prompt
type: prompt
actions:
  - id: default
    label: Chat
prompt: |
  Reply concisely.
capabilities:
  - llm
llm:
  profile: local-default
context_policy:
  mode: current_message
model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

Minimal Script Agent:

```yaml
id: demo_script
name: Demo Script
type: script
entry: agent.py
actions:
  - id: default
    label: Run
context_policy:
  mode: current_message
model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

### Action fields

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

Text routing supports two Agent action forms:

- `@agent_id:action args` explicitly invokes `action` on `agent_id`.
- `:action args` invokes `action` only on the current session default Agent.

The `:action` shortcut does not infer from previous messages, recent Agent calls, or other Agents. If the current session default Agent lacks the named action, routing returns a structured error instead of treating the input as ordinary text. Use full `@agent_id:action` messages for buttons, saved shortcuts, and cross-Agent calls.

Actions with `callable: false` are internal Agent entry points. They are excluded from user-facing composer autocomplete and direct text/API user invocation returns a clear not-callable error. Trusted internal `action_form` submission may still target a non-callable action declared by the original form block.

### Config schema fields

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

Enum config fields with manifest defaults should render concrete enum values in Settings, not an `unset` business option. Clearing a local config override is separate from choosing an enum value; empty/null enum patches are treated as removing the override and returning to the manifest default, while strings such as `unset` are invalid unless explicitly listed in `options`.

## Agent Overrides

- Manifest values are package defaults.
- `AgentConfig` stores local overrides and enablement.
- Config tab writes `config_schema` values into `user_config`.
- Overrides tab edits display/runtime overrides.
- Display override fields include name, description, and avatar.
- Prompt override replaces the manifest prompt at runtime.
- LLM runtime override can set `llm_profile_id` and `allow_session_override`.
- Knowledge runtime override can set `knowledge_context_mode` to `use_default`, `enabled`, or `disabled`. Prompt Agents default to effective `enabled`; Script Agents that declare `llm` default to effective `disabled`; Script Agents without `llm` do not show the override. This override is stored only in `AgentConfig.runtime` and is not written into `agent.yaml`.
- Reset overrides clears local AgentConfig values back to manifest behavior.
- Write overrides to manifest only when intentionally changing the package default.

## Prompt Agents

- Prompt Agents let the core runtime build context and call the LLM.
- Model output is treated as assistant content, not tool calls or structured commands.
- Prompt Agents that call an LLM should declare `capabilities: [llm]`.
- Visible streaming is controlled by the resolved Model Profile `supports_streaming`.
- Prompt Agent run steps, streaming, and LLM resolution follow `docs/RUNTIME_PROTOCOLS.md`.

## Script Agents

- Script Agents are trusted local Python imported into the backend process.
- `entry` must export `async def run(ctx)`.
- Older scripts that return a final value or reply once remain valid.
- Do not run untrusted Script Agent code; there is no sandbox.

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
- `form_id`: submitted `action_form` id when the invocation came from a form submission.
- `is_silent_submission`: true when the invocation came from an `action_form` with `submit.visibility="silent"`.
- `attachments`: current message attachment metadata.
- `source_message_id`: source message for message-button/action invocations when available.
- `prefill`: structured action prefill data when available. Form submissions place validated field values here.

### `ctx.step` / `ctx.run`

- `ctx.step(name)` creates a visible run step.
- In Script Agents, custom steps default under the top-level `Running script` step.
- Steps are visible in chat and should describe user-meaningful progress.
- Do not use `ctx.step` for every tiny internal function.
- `ctx.run` exposes trusted lifecycle helpers such as `start_step`, `complete_step`, `fail_step`, and progress updates.

```python
async with ctx.step("Parse JSON"):
    ...
```

### `ctx.session`

- `session_id`: current Session id.
- `default_agent_id`: current default Agent id.
- `context_mode`: current Session context projection mode. See `docs/RUNTIME_PROTOCOLS.md#conversation-context-modes` and `docs/RUNTIME_PROTOCOLS.md#group-transcript-context`.

### `ctx.state`

- `ctx.state.get(key, default=None)` reads per-session, per-agent JSON runtime state.
- `ctx.state.set(key, value)` writes per-session, per-agent JSON runtime state.
- State is intended for runtime copies such as a form-backed recipe. It should not replace user-owned source files such as Capability asset files or Agent manifests.
- State is scoped by `session_id + agent_id + key`, so different sessions and Agents do not share values.

### `ctx.llm`

- `ctx.llm.text(...)` returns final text as a string.
- `ctx.llm.json(...)` parses and validates a JSON object from final text.
- `ctx.llm.stream(...)` is internal streaming. It does not write to chat.
- `ctx.llm.stream_to_output(...)` is public output streaming.
- `ctx.output.write_delta(...)` explicitly appends visible public content.
- `ctx.output.finish(...)` completes the public streaming message.
- `ctx.llm.unload_model(...)` is trusted script-only model unload through provider/model profiles and returns a structured `CapabilityCallResult` with unload outcome data.
- The first real `ctx.llm.*` provider call in a pending default-titled session may trigger the core automatic session-title pre-hook. Agent authors should not call title generation manually; the pre-hook is internal, non-streaming, and creates no visible messages.
- Depending on the Agent Knowledge override and active Session KB bindings, the core may append a `Retrieved Knowledge` system-context block before `ctx.llm.*` provider calls. This is automatic, best-effort, and does not change script method signatures. Retrieval warnings are recorded in run metadata without storing full snippet content.
- `ctx.llm.unload()` is legacy capability-runtime unload if the LLM runtime supports it and also returns structured outcome data when available.
- Script manual unload records run metadata, refreshes affected provider status when possible, and should surface success through the current run step rather than creating another assistant message.

Internal JSON streaming, hidden from chat:

```python
import json

chunks = []
async for chunk in ctx.llm.stream(system="Return JSON.", user=ctx.input.text):
    chunks.append(chunk.text)
data = json.loads("".join(chunks))
await ctx.reply_markdown(render_report(data))
```

Public streaming:

```python
await ctx.llm.stream_to_output(system="Reply in markdown.", user=ctx.input.text)
```

Or:

```python
async for chunk in ctx.llm.stream(system="Reply.", user=ctx.input.text):
    await ctx.output.write_delta(chunk.text)
await ctx.output.finish()
```

### Reply helpers

- `reply_text`: send plain text.
- `reply_markdown`: send markdown-rendered content.
- `reply_json`: send a JSON object or array.
- `reply_image`: send one image payload with `url`.
- `reply_images`: send an ordered image gallery.
- `reply_blocks`: send ordered rich content blocks.
- `reply_form` / `reply_action_form`: validate and send one `action_form` block as `rich_content`.
- `reply_file_content`: send raw file text, not markdown-rendered content.
- Reply helpers accept optional message metadata for durable structured details such as generated image recipe metadata.

## Attachments in Script Agents

- `ctx.input.attachments` contains current input attachment metadata.
- `ctx.read_attachment_text(attachment_or_id)` reads trusted local text attachment content.
- `ctx.read_attachment_bytes(attachment_or_id)` reads trusted local bytes.
- `ctx.attachment_as_data_url(attachment_or_id)` returns a data URL for image/file handoff.
- `await ctx.save_attachment_bytes(data, filename, mime_type, kind="file", metadata=None)` stores generated bytes as a local attachment and links it to the current output message/run.
- `await ctx.save_attachment_base64(data_base64, filename, mime_type, kind="file", metadata=None)` decodes base64 or a data URL, stores it as a local attachment, and links it to the current output message/run.
- Image attachments can be read by scripts regardless of Prompt Agent vision support.
- Text/code/config files can be read by scripts through helpers; Prompt Agent file context is controlled separately by General settings.
- Generated files and images should be saved as attachments and returned through `reply_image` / `reply_images` using the local attachment `url`; do not put large base64 data URLs in message content.

Generated attachment helpers return local attachment metadata:

```json
{
  "id": "uuid",
  "type": "image",
  "mime_type": "image/png",
  "name": "result.png",
  "size": 12345,
  "uri": "local://attachments/<id>.png",
  "url": "/api/attachments/<id>.png",
  "created_at": "2026-05-08T12:00:00Z",
  "metadata": {"source": "optional"}
}
```

## Capabilities

Capability manifests declare internal methods and optional global slash commands.

| field | meaning | notes |
| --- | --- | --- |
| `id` | Global Capability id. | Must be unique and match directory in strict checks. |
| `name` | Display name. | Human-readable. |
| `methods` | Internal callable methods. | Method id must match runtime callable. |
| `input_schema` | Method input contract. | Lightweight manifest metadata. |
| `output.type` | Declared output renderer. | Used by commands and validation. |
| `commands` | User-facing slash commands. | Global namespace; names start with `/`. |
| `safe` | Command safety hint. | Documentation/UI hint, not a sandbox. |
| `config_schema` | Local CapabilityConfig fields. | Settings stores values by capability id. |

Minimal `capability.yaml`:

```yaml
id: demo_tool
name: Demo Tool
methods:
  - id: echo
    input_schema:
      text:
        type: string
        required: true
    output:
      type: text
commands:
  - name: /demo
    method: echo
    description: Echo text.
    safe: true
```

Minimal runtime:

```python
class CapabilityRuntime:
    def echo(self, text: str, context: dict | None = None) -> str:
        return text


def get_runtime():
    return CapabilityRuntime()
```

Runtime call rules:
- Runtime can export `get_runtime()` or `CapabilityRuntime`.
- Strict checks import runtime code and require every manifest method id to exist as a callable.
- Command methods receive `(args, context)` when the runtime callable accepts two parameters.
- Command methods receive only `(args)` when the runtime callable accepts one parameter.
- Script Agents call capabilities through `await ctx.capability("id").method(...)`. When the runtime method accepts a `context` keyword, Script Agent calls receive resolved CapabilityConfig, session id, capability id, and current attachments.
- Capability methods should return plain Python values matching declared output.

Built-in `knowledge` Capability:
- `search(query, knowledge_base_ids=None, session_id=None, top_k=None, max_context_chars=None, debug=True)` returns the core Knowledge search JSON shape, using explicit KB ids when provided or the current Script/command context `session_id` otherwise.
- `list_bases(enabled_only=False)` returns compact KB records with id, name, enabled state, index status, source count, and chunk count.
- `stats(knowledge_base_id=None)` returns compact source/chunk/embedding counts globally or for one KB. It does not read full source originals or return vectors.
- `/kb-search <query>` passes the remaining text as `query`, searches current session active KBs, returns JSON, and does not call an LLM or create an Agent run. Empty input fails clearly; no active KBs returns an empty result with a `No active knowledge bases for this session.` warning.

Reusable integration Capabilities should expose narrow protocol methods plus small helpers when that makes Agent code simpler. For example, the `comfyui` Capability exposes REST-only workflow submission, non-blocking prompt status, queue/history reads, blocking convenience polling, output extraction, image fetching, interrupt, upload, object-info, and `free_memory` methods. `free_memory` posts to ComfyUI `/free` with `unload_models` and `free_memory` booleans and returns a structured JSON outcome; it is not a slash command or user-facing Agent action. The Capability returns JSON contracts with image references or optional base64 image content; Script Agents remain responsible for attachments, user-visible progress, memory-release workflow choices, and final rendering.

The `comfyui` Capability also manages local workflow and preset library directories through CapabilityConfig. It can scan top-level API-format workflow JSON files, compute canonical workflow hashes, detect duplicate workflow content, load and validate preset YAML files, report per-workflow draft preset skip reasons, and create unmapped draft presets when configured. Preset files remain the durable user asset; session recipes are runtime state.

The built-in `comfyui_agent` Script Agent exposes user-callable `fresh` and `refine` actions as one-shot LLM prompt operations. Its AgentConfig `llm_operation_default` controls whether normal `default`/`llm` LLM-mode input uses `refine` or `fresh`; the stored recipe `input_mode` remains only `llm` or `raw`. Template config keys are `llm_refine_system_prompt`, `llm_refine_user_template`, `llm_fresh_system_prompt`, and `llm_fresh_user_template`.

General settings include `auto_generate_session_titles`, `session_title_prompt`, and `session_title_max_input_chars`. These control the core automatic title pre-hook before first real LLM use and are read through `GET /api/settings/general` / `PATCH /api/settings/general`.

## Knowledge Settings, Local Model APIs, Indexing, And Search

Knowledge RAG v1 adds Workbench-owned settings, local model APIs, and source indexing APIs. These are internal Workbench JSON APIs, not provider function calling, tool calling, or OpenAI-compatible embedding endpoints.

Settings:

- `GET /api/knowledge/settings`
- `PATCH /api/knowledge/settings`

Knowledge Defaults store local model device, embedding batch/timeout defaults, the single global reranker configuration, retrieval/chunking/index limits, and Knowledge context prompt templates. `models_root` is read-only in v1 and defaults to `data/models`.

Local model directories:

- `data/models/embeddings/<model-folder>`
- `data/models/rerankers/<model-folder>`
- `data/knowledge/sources`

Model paths must be relative to `data/models`, use POSIX-style storage, and match either `embeddings/<folder>` for embedding profiles or `rerankers/<folder>` for the global reranker. Absolute paths and `..` segments are rejected.

Embedding model profile APIs:

- `GET /api/knowledge/embedding-models`
- `POST /api/knowledge/embedding-models`
- `GET /api/knowledge/embedding-models/{id}`
- `PATCH /api/knowledge/embedding-models/{id}`
- `DELETE /api/knowledge/embedding-models/{id}`
- `POST /api/knowledge/embedding-models/{id}/test`

Embedding generation:

- `POST /api/knowledge/embeddings`

Request shape is `{model_profile_id, purpose, inputs}` where `purpose` is `query` or `document`. The API applies the profile instruction for that purpose, validates batch size against Knowledge Defaults, and returns `{model_profile_id, model_path, purpose, dimension, vectors}`.

Reranking:

- `POST /api/knowledge/rerank`

The reranker uses Knowledge Defaults `reranker_enabled` and `reranker_model_path`. It returns sorted `{id, score}` results or structured errors such as `KNOWLEDGE_RERANKER_DISABLED`, `KNOWLEDGE_RERANKER_MODEL_NOT_CONFIGURED`, `KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE`, or `KNOWLEDGE_MODEL_NOT_FOUND`.

Knowledge base APIs:

- `GET /api/knowledge/bases`
- `POST /api/knowledge/bases`
- `GET /api/knowledge/bases/{id}`
- `PATCH /api/knowledge/bases/{id}`
- `DELETE /api/knowledge/bases/{id}`

Knowledge source indexing APIs:

- `GET /api/knowledge/bases/{id}/sources`
- `POST /api/knowledge/bases/{id}/sources`
- `GET /api/knowledge/sources/{source_id}`
- `DELETE /api/knowledge/sources/{source_id}`
- `POST /api/knowledge/sources/{source_id}/reindex`
- `POST /api/knowledge/bases/{id}/reindex`

`POST /api/knowledge/bases/{id}/sources` supports pasted text:

```json
{"source_type": "pasted_text", "title": "Notes", "text": "..."}
```

and text attachments:

```json
{"source_type": "attachment_text", "attachment_id": "local://attachments/<id>.txt"}
```

The indexer validates source size and chunk limits, chunks text, embeds chunks with the KB embedding model profile using `purpose=document`, stores vectors as float32 SQLite BLOBs, and writes FTS5 rows. Pasted source originals are saved under `data/knowledge/sources/<source_id>.txt`; full pasted source text is not stored in `kb_sources`. Attachment indexing reads existing local text attachments and does not delete or modify the original attachment.

Index responses include `source_id`, `status`, `chunks`, `embedding_model_profile_id`, `embedding_dimension`, `indexed_at`, and `error`.

Knowledge search:

- `POST /api/knowledge/search`

Request shape:

```json
{"query": "...", "knowledge_base_ids": ["kb_id"], "session_id": null, "top_k": 6, "max_context_chars": 10000, "debug": true}
```

`query` is required and non-empty. Provide either explicit `knowledge_base_ids` or `session_id`; explicit KB ids win. Search uses only enabled KBs. Vector search is grouped by embedding model profile and never compares scores across different embedding models directly. Keyword search uses FTS5/BM25 across selected KBs. Candidates are deduped by `chunk_id`, merged with RRF, optionally reranked once globally, then trimmed by `top_k` and `max_context_chars`.

Response shape:

```json
{"query": "...", "results": [{"rank": 1, "chunk_id": "...", "content": "...", "rrf_score": 0.031, "rerank_score": null}], "debug": {"warnings": []}}
```

Phase 4 adds automatic Prompt Agent and Script Agent Knowledge context injection plus a chat session KB picker. Phase 5 adds a thin `knowledge` Capability and `/kb-search` command that wrap the same core retrieval path for explicit debugging/manual search. Current non-goals: `local_file` sources, automatic model download, and changes to retrieval/indexing/model backends.

Session bindings:

- `GET /api/sessions/{session_id}/knowledge-bases`
- `PATCH /api/sessions/{session_id}/knowledge-bases`

Phase 2 bindings are configuration only. They do not alter Prompt Agent or Script Agent context.

## Capability Config

- `config_schema` declares Settings fields.
- Stored CapabilityConfig is local state, not part of the package manifest.
- Runtime command context receives `capability_config` after schema validation.
- Unknown config keys are rejected by API validation.

## Output Payloads

| output type | use when | minimal shape | common pitfall |
| --- | --- | --- | --- |
| `text` | Plain text. | `"hello"` | Markdown is not rendered as markdown. |
| `markdown` | Rendered markdown. | `"**hello**"` | Do not use for raw file dumps. |
| `json` | Structured data display. | `{"ok": true}` | Lists are valid command output but `reply_json` expects object or array. |
| `image` | One renderable image. | `{"url": "data:image/png;base64,..."}` | Missing `url` fails validation. |
| `image_gallery` | Multiple images. | `{"images": [{"url": "..."}]}` | Each image must satisfy image payload shape. |
| `file_content` | Raw text file display. | `{"content": "...", "filename": "a.txt"}` | It is raw text and does not go through markdown rendering. |
| `rich_content` | Ordered mixed blocks. | `{"blocks": [{"type": "markdown", "text": "..."}]}` | Keep block order explicit. |
| `action_form` block | Declarative form inside `rich_content`. | `{"type": "action_form", "form_id": "demo", "title": "Demo", "fields": [{"name": "prompt", "type": "text"}], "submit": {"action_id": "run", "visibility": "silent"}}` | Forms submit only to internal Agent actions. |
| `command_buttons` block | Send-message shortcut buttons inside `rich_content`. | `{"type": "command_buttons", "buttons": [{"label": "Run recipe", "message": "@comfyui_agent:run"}]}` | Buttons send ordinary user messages only. |

If a command returns a dict with no declared output, the runner may infer `json`, `image`, `image_gallery`, or `rich_content`.

### `action_form` rich content block

`action_form` is a declarative JSON block. It supports `text`, `textarea`, `integer`, `float`, `boolean`, `enum`, and `json` fields. It does not support HTML, frontend custom JavaScript, arbitrary URLs, file uploads, password/secret fields, remote options, or automatic execution.

Top-level fields:
- `type`: must be `action_form`.
- `form_id`: required string, unique within the message.
- `title`: required display title.
- `description`: optional help text.
- `ui`: optional form-level UI metadata. Supported keys are `default_collapsed`, `collapsed`, `collapse_on_success`, and `collapsed_message`.
- `fields`: required array of field declarations.
- `sections`: optional array of static layout section declarations shaped as `{key, title?}`.
- `submit`: required object.

Form-level `ui` fields:
- `default_collapsed`: optional boolean, used only for first render when `collapsed` is absent. Missing means expanded.
- `collapsed`: optional boolean persisted form state. When present, it takes precedence over `default_collapsed`.
- `collapse_on_success`: optional boolean. Trusted backend code may use this after a successful silent save to return an `updated_form` or emit `message_updated` with the source form collapsed.
- `collapsed_message`: optional short text shown in collapsed state, such as `Recipe saved. Click to expand.`

Collapsed state is frontend UI state on the same `action_form` block. It does not change the form submission protocol, submit target resolution, field values, provider-bound context, or the rule that the frontend submits only `source_message_id`, `form_id`, and `values`. Field `name` values remain submission keys; they are not DOM ids, and renderers should derive globally unique DOM ids per rendered form instance.

Field declarations use `name`, `type`, optional `label`, `description`/`help`, `required`, `value`, `default`, `placeholder`, numeric bounds/`step`, text length bounds, enum `options: [{"value": "...", "label": "..."}]`, and optional static UI metadata:

- `ui.section`: optional section key. Fields with the same section render in one section container.
- `ui.span`: optional integer from 1 to 12 for the frontend 12-column form grid.

Section order comes from the first occurrence of each `field.ui.section` in the `fields` array. Field order within a section is exactly the `fields` array order. If a field has no `ui.section`, it belongs to the default section. If `field.ui.section` has no matching top-level `sections` entry, the frontend may derive a title from the key. `ui.order` is not supported; reorder the `fields` array instead. The first version supports only static section grouping and grid span metadata. It does not support nested layout, collapsible sections, row layout DSL, or dynamic onchange refresh.

Grid rendering is frontend behavior. Typical spans are `12` for long fields such as `textarea`, `json`, and prompt text, `6` for medium text/select fields, and `4` or `3` for compact numeric, boolean, and enum fields. Small screens may collapse to one column.

Submit declarations use optional `label`, optional `agent_id`, required `action_id`, optional `message`, optional `visibility`, optional `success_message`, and optional `failure_message`. If `agent_id` is omitted, the source message Agent is used. `visibility` defaults to `"message"` and may be `"message"` or `"silent"`.

On submit, the frontend sends only `source_message_id`, `form_id`, and `values`. The backend reads the original message, finds the matching `action_form`, resolves the submit target and visibility from that original block, and validates values against the original fields. Request body `agent_id`, `action_id`, or `visibility` cannot override the original form target or visibility.

With `visibility="message"`, the backend creates a `form_submission` user message with a short summary body and invokes the target Agent action. This is the default and preserves older form behavior.

With `visibility="silent"`, the backend invokes the target Agent action without creating a visible user message and suppresses normal assistant output from reply helpers or public output streaming. The target Script Agent still receives validated values in `ctx.input.prefill`, `ctx.input.form_id`, `ctx.input.source_message_id`, and `ctx.input.is_silent_submission=true`, so it can save state, save a recipe, or update settings. Successful silent submissions return a structured response with `silent=true` and a user-facing message from `submit.success_message` or `"Saved"`. A Script Agent may return `{"updated_form": {"source_message_id": "...", "form_id": "...", "block": {...}}}` after it has rebuilt and persisted a replacement source `action_form`; the frontend can use that payload, or the corresponding `message_updated` event, to refresh the existing form without adding chat messages. The replacement block may set `ui.collapsed=true` to collapse the same source form after a successful silent save while retaining all fields and values for later expansion. Failed silent submissions return a structured error; `submit.failure_message` may be used as an error prefix.

Forms may edit runtime state such as a session recipe. Preset selectors and other field groups are static while the user edits a rendered form; there is no dynamic onchange refresh. If a silent submit changes the saved state enough to require different fields, the target action can save the state and replace the source message form block from trusted backend code. The frontend still submits only `source_message_id`, `form_id`, and values; it must not submit a replacement form block. The ComfyUI Agent uses `action_form` as a recipe editor only; form submission does not submit generation, choose input mode, or collect the LLM user request.

### `command_buttons` rich content block

`command_buttons` renders trusted send-message shortcut buttons. It is not a message action, hidden Agent action, URL, JavaScript hook, or form submit.

Top-level fields:
- `type`: must be `command_buttons`.
- `buttons`: required array of button declarations.

Button declarations use:
- `label`: required display text.
- `message`: required user message text to send through the normal composer route.

On click, the frontend sends `message` through the same ordinary user-message path as manual composer input. It creates a normal user message, uses normal routing, and does not send `prefill`, attachments, hidden action payloads, arbitrary URLs, or executable frontend code.

## Validation and CLI

```powershell
uv run python scripts/check_agents.py --strict
uv run python scripts/run_agent.py demo "hello"
uv run python scripts/run_command.py "/demo hello"
```

## Source and Tests

Source:
- `ai_workbench/core/script.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/capability_registry.py`
- `ai_workbench/core/capability_runtime.py`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/store/useWorkbenchStore.ts`

Tests:
- `tests/test_script_agent.py`
- `tests/test_prompt_agent_execution.py`
- `tests/test_frontend_chat_contracts.py`
- `tests/test_api.py`
