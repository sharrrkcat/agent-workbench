# Agent Development

For compact API contracts and AI-oriented routing, see:

- [AI_CONTEXT.md](AI_CONTEXT.md)
- [EXTENSION_API.md](EXTENSION_API.md)
- [RUNTIME_PROTOCOLS.md](RUNTIME_PROTOCOLS.md)

Agents live under `agents/<agent_id>/` with an `agent.yaml` manifest. Agent ids are global, lowercase snake_case, and unique. Every Agent must define a `default` action.

Use the template generator for new Agents:

```powershell
uv run python scripts/create_agent.py demo --type script
uv run python scripts/create_agent.py translator --type prompt
uv run python scripts/create_agent.py image_helper --type script --name "Image Helper Agent"
```

Add `--dry-run` to preview files and `--force` only when intentionally overwriting a local template directory.

## Agent Types

Prompt Agents send core-built context plus a manifest prompt to an OpenAI-compatible LLM runtime. The model output is treated as plain text.

Script Agents are trusted local Python code imported and run inside the backend process. They can call Capabilities and LLM helpers through `AgentContext`. There is no sandbox, so do not run Agents from untrusted sources.

## Prompt Agent Manifest

Minimal `agents/my_prompt/agent.yaml`:

```yaml
id: my_prompt
name: My Prompt Agent
type: prompt
description: Reply with a concise answer.
avatar: ""

actions:
  - id: default
    label: Chat
    description: Reply to the current user message.

prompt: |
  You are concise, practical, and helpful.

context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 4000

model_lifecycle:
  load: on_demand
  unload: never
  unload_failure: warn
```

If an LLM model is not configured, Prompt Agent runs fail clearly. Set `AGENT_WORKBENCH_LLM_MODEL`, save a Model Profile in Settings, set the Default model profile, or reference a profile in the Agent manifest:

```yaml
llm:
  profile: my_local_model
  allow_session_override: true
```

Declare the `llm` capability for agents that use the LLM runtime. Settings uses the capability declaration to decide whether to show LLM Runtime Settings in the Overrides tab:

```yaml
capabilities:
  - llm
```

## Agent Overrides

Agent manifests are package defaults. `AgentConfig` stores local user overrides and normal saves do not modify `agent.yaml`.

Settings > Agents has two separate surfaces:

- `Config` is for agent-defined business fields from `config_schema`.
- `Overrides` is for Workbench display and runtime settings shared across agents.

Every agent can override display name, avatar, and description. Capability-declared sections appear when the agent manifest declares that capability. The first built-in section is `LLM Runtime Settings`, shown only for agents that declare `llm`.

Prompt Agents also get a `Prompt` override section. The prompt override is stored in `AgentConfig.runtime.prompt`, affects runtime execution immediately after saving, and is not part of `user_config`.

Display resolution:

```text
AgentConfig display override > manifest/package avatar > generated fallback
```

LLM resolution:

```text
session override, when allowed > AgentConfig runtime llm_profile_id > manifest llm.profile > default model profile > legacy global fallback > environment fallback
```

Context and lifecycle resolution:

```text
action context_policy, where present > AgentConfig runtime > manifest > system default
```

System defaults are centralized in `ai_workbench/core/agent_defaults.py`. If a manifest omits context policy, model lifecycle, timeout, or session override fields, the Settings UI and runtime resolver still return complete defaults.

`Reset overrides` clears display/runtime overrides only; it keeps `user_config` from the Config tab. `Write overrides to manifest` physically edits `agents/<id>/agent.yaml` and is intended for local agent development. It writes only overridden display/runtime fields, not `user_config` or untouched defaults, and may rewrite YAML formatting/comments.

Script Agents remain trusted local Python code. Writing overrides to a manifest modifies local package files.

## Script Agent Manifest

Minimal `agents/my_script/agent.yaml`:

```yaml
id: my_script
name: My Script Agent
type: script
description: Run local Python logic.
entry: agent.py

actions:
  - id: default
    label: Run
    description: Run the script agent.

context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 4000

model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

The script entry path must stay inside the Agent directory. The module must export `async def run(ctx)`.

## Script Agent SDK

Minimal `agents/my_script/agent.py`:

```python
async def run(ctx):
    async with ctx.step("prepare"):
        text = ctx.input.text.strip()

    await ctx.reply_text(f"Input: {text}")
```

Useful reply helpers:

```python
await ctx.reply_text("plain text")
await ctx.reply_markdown("**markdown**")
await ctx.reply_json({"ok": True})
await ctx.reply_image("https://example.test/image.png", alt="Example")
await ctx.reply_blocks([
    {"type": "markdown", "text": "## Result"},
    {"type": "text", "text": "Plain text block"},
])
await ctx.reply_form({
    "type": "action_form",
    "form_id": "demo",
    "title": "Demo Form",
    "fields": [{"name": "prompt", "type": "textarea", "required": True}],
    "submit": {"label": "Run", "action_id": "form_submit"},
})
await ctx.reply_images([
    {"url": "https://example.test/a.png", "alt": "A"},
    {"url": "https://example.test/b.png", "alt": "B"},
])
```

Optional LLM helper:

```python
summary = await ctx.llm.text(system="Summarize briefly.", user=ctx.input.text)
await ctx.reply_text(summary)
```

Manual unload is available to Script Agents:

```python
await ctx.llm.unload()
```

Script Agents should parse and validate LLM output explicitly. Do not depend on model function-calling or automatic tool selection.

The built-in `comfyui_agent` is a Script Agent for ComfyUI workflow/preset recipes and generation. It uses the ComfyUI Capability workflow/preset library to create and edit a per-session recipe through an `action_form`, switch `input_mode` between `llm` and `raw`, fill API-format workflow JSON from preset mappings, submit workflows, poll status, fetch images, save local attachments, and return an `image_gallery`.

ComfyUI preset YAML schema is documented in [COMFYUI_PRESET_SCHEMA.md](COMFYUI_PRESET_SCHEMA.md). Use that schema when creating or reviewing workflow preset files.

ComfyUI Agent action semantics:
- `default`: use the current session recipe `input_mode`; `llm` enhances the user request into `values.positive_prompt`, while `raw` writes the user text directly.
- `raw`: force raw for this invocation, keep the stored `input_mode` unchanged, write `values.positive_prompt`, then generation runs.
- `llm`: force LLM prompt enhancement for this invocation, keep the stored `input_mode` unchanged, write `user_prompt` and generated `values.positive_prompt`, then generation runs only when `auto_run_after_llm_prompt=true`.
- `run`: execute the current session recipe without changing prompt or parameters.
- `form`: show the session recipe editor only; the form does not expose `input_mode` or `user_prompt`, and form submit does not generate.
- `save_recipe_from_form`: internal form submit target that saves the session recipe editor without generating images. It is marked `callable: false` and is not intended for manual composer calls.
- `switch`, `presets`, `scan_workflows`, and `status`: update mode or inspect local state only; they do not generate.

`switch` controls the stored recipe `input_mode`; `raw` and `llm` are one-shot modes for a single invocation. `auto_run_after_llm_prompt=false` makes LLM mode save the generated positive prompt for inspection or form editing before the user runs `@comfyui_agent:run`.

When LLM prompt inspection stops before generation, the reply may include `command_buttons` that send `@comfyui_agent:form` and `@comfyui_agent:run` as normal user messages.

Minimal interactive form Script Agent:

```python
async def run(ctx):
    if ctx.action_id == "form_submit":
        await ctx.reply_json({
            "received_prefill": ctx.input.prefill,
            "source_message_id": ctx.input.source_message_id,
            "form_id": ctx.input.form_id,
        })
        return

    await ctx.reply_form({
        "type": "action_form",
        "form_id": "demo",
        "title": "Demo Form",
        "description": "Collect a few values and invoke another action.",
        "fields": [
            {"name": "prompt", "type": "textarea", "label": "Prompt", "required": True},
            {"name": "count", "type": "integer", "label": "Count", "minimum": 1, "maximum": 10, "value": 2},
            {"name": "mode", "type": "enum", "options": [{"value": "fast", "label": "Fast"}, {"value": "quality", "label": "Quality"}]},
        ],
        "submit": {"label": "Run", "action_id": "form_submit"},
    })
```

## Actions

Actions are Agent entry points:

```text
@my_script hello
@my_script:default hello
@translate:formal
:formal
```

Use `@agent_id:action args` when the call must target a specific Agent. Use `:action args` only as a shortcut for the current session default Agent's action; it does not infer an Agent from previous messages, recent calls, or other Agents. If the current default Agent does not define that action, routing returns a clear error instead of falling back to `default`.

The composer autocompletes current-Agent action shortcuts when the input is only `:` plus an optional action prefix, such as `:` or `:fo`. The list is built only from the current session default Agent and only includes actions where `callable` is true or omitted.

Set `callable: false` for internal form actions that should not be manually called by users. They do not appear in user-facing autocomplete, and direct user invocation is rejected, but trusted `action_form` submit targets may still call them.

Buttons, saved shortcuts, and cross-Agent links should continue to use the full `@agent_id:action` form because the user's current default Agent may be different when the button is clicked. `@agent_id:action` also remains the right form for explicit cross-Agent calls.

CLI action calls:

```powershell
uv run python scripts/run_agent.py render_test:image "1"
uv run python scripts/run_agent.py render_test "1" --action image
```

## Output Types

Supported rendered output types are:

- `text`: plain text with line breaks preserved.
- `markdown`: Markdown prose, headings, lists, tables, and code blocks.
- `json`: structured objects and arrays.
- `image`: one renderable image payload.
- `image_gallery`: a list of image payloads.
- `file_content`: raw file text shown without Markdown rendering.
- `rich_content`: ordered text, markdown, image, file content, and `action_form` blocks.

Match the helper to the intended output. For example, use `reply_json` for structured data instead of a Markdown code block when downstream tools should inspect it.

## CLI Workflow

Create and test a Script Agent:

```powershell
uv run python scripts/create_agent.py demo --type script
uv run python scripts/check_agents.py --strict
uv run python scripts/run_agent.py demo "hello"
```

Create and test a Prompt Agent:

```powershell
uv run python scripts/create_agent.py translator --type prompt
uv run python scripts/check_agents.py --strict
uv run python scripts/run_agent.py translator "Translate this"
```

Use JSON output for automation:

```powershell
uv run python scripts/check_agents.py --strict --json
uv run python scripts/run_agent.py demo "hello" --json
```

## Common Errors

- Missing manifest fields: check that `id`, `name`, `type`, `actions`, `context_policy`, and `model_lifecycle` are present.
- Script import error: run `uv run python scripts/check_agents.py --strict` and inspect the file path in the error.
- Missing script entry: ensure `entry: agent.py` points to an existing file inside the Agent directory.
- Duplicate action id: every action under one Agent must be unique.
- Unknown capability reference: add the Capability under `capabilities/<id>/` or remove the reference.
- Image output displayed as JSON: the Agent likely used `reply_json` or returned a dict with `output_type=json`; use `reply_image` or `reply_images`.
- LLM model not configured: set `AGENT_WORKBENCH_LLM_MODEL`, save an LLM Profile, or add an Agent `llm.profile`.

## Safety

Script Agents are trusted local Python code. They run in the backend process and can access local files and network through normal Python APIs. The current project does not sandbox Script Agents, enforce permissions, or isolate third-party code.
