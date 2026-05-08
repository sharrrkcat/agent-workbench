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

## Agent Overrides

- Manifest values are package defaults.
- `AgentConfig` stores local overrides and enablement.
- Config tab writes `config_schema` values into `user_config`.
- Overrides tab edits display/runtime overrides.
- Display override fields include name, description, and avatar.
- Prompt override replaces the manifest prompt at runtime.
- LLM runtime override can set `llm_profile_id` and `allow_session_override`.
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

Reusable integration Capabilities should expose narrow protocol methods plus small helpers when that makes Agent code simpler. For example, the `comfyui` Capability exposes REST-only workflow submission, non-blocking prompt status, queue/history reads, blocking convenience polling, output extraction, image fetching, interrupt, upload, and object-info methods. It returns JSON contracts with image references or optional base64 image content; Script Agents remain responsible for attachments, user-visible progress, and final rendering.

The `comfyui` Capability also manages local workflow and preset library directories through CapabilityConfig. It can scan top-level API-format workflow JSON files, compute canonical workflow hashes, detect duplicate workflow content, load and validate preset YAML files, report per-workflow draft preset skip reasons, and create unmapped draft presets when configured. Preset files remain the durable user asset; session recipes are runtime state.

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
| `action_form` block | Declarative form inside `rich_content`. | `{"type": "action_form", "form_id": "demo", "title": "Demo", "fields": [{"name": "prompt", "type": "text"}], "submit": {"action_id": "run"}}` | Forms submit only to internal Agent actions. |

If a command returns a dict with no declared output, the runner may infer `json`, `image`, `image_gallery`, or `rich_content`.

### `action_form` rich content block

`action_form` is a declarative JSON block. It supports `text`, `textarea`, `integer`, `float`, `boolean`, `enum`, and `json` fields. It does not support HTML, frontend custom JavaScript, arbitrary URLs, file uploads, password/secret fields, remote options, or automatic execution.

Top-level fields:
- `type`: must be `action_form`.
- `form_id`: required string, unique within the message.
- `title`: required display title.
- `description`: optional help text.
- `fields`: required array of field declarations.
- `submit`: required object.

Field declarations use `name`, `type`, optional `label`, `description`/`help`, `required`, `value`, `default`, `placeholder`, numeric bounds/`step`, text length bounds, and enum `options: [{"value": "...", "label": "..."}]`.

Submit declarations use optional `label`, optional `agent_id`, required `action_id`, and optional `message`. If `agent_id` is omitted, the source message Agent is used.

On submit, the frontend sends only `source_message_id`, `form_id`, and `values`. The backend reads the original message, finds the matching `action_form`, resolves the submit target from that original block, validates values against the original fields, creates a `form_submission` user message with a short summary body, and invokes the target Agent action. Request body `agent_id` or `action_id` cannot override the original form target.

Forms may edit runtime state such as a session recipe. Preset selectors and other field groups are static for the rendered form; if a submitted preset change requires different fields, the target action should save the new state and return a fresh form. The ComfyUI Agent uses `action_form` as a recipe editor only; form submission does not submit generation.

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
