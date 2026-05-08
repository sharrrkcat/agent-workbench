# Extension API

## Purpose

This document is the compact contract for writing Agents, Capabilities, Script Agent code, and output payloads.

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
- `attachments`: current message attachment metadata.
- `source_message_id`: source message for message-button/action invocations when available.
- `prefill`: structured action prefill data when available.

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
- `reply_file_content`: send raw file text, not markdown-rendered content.

## Attachments in Script Agents

- `ctx.input.attachments` contains current input attachment metadata.
- `ctx.read_attachment_text(attachment_or_id)` reads trusted local text attachment content.
- `ctx.read_attachment_bytes(attachment_or_id)` reads trusted local bytes.
- `ctx.attachment_as_data_url(attachment_or_id)` returns a data URL for image/file handoff.
- Image attachments can be read by scripts regardless of Prompt Agent vision support.
- Text/code/config files can be read by scripts through helpers; Prompt Agent file context is controlled separately by General settings.

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
- Script Agents call capabilities through `await ctx.capability("id").method(...)`.
- Capability methods should return plain Python values matching declared output.

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
| `rich_content` | Ordered mixed blocks. | `{"blocks": [{"type": "markdown", "content": "..."}]}` | Keep block order explicit. |

If a command returns a dict with no declared output, the runner may infer `json`, `image`, `image_gallery`, or `rich_content`.

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
