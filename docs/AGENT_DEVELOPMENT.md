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

Prompt Agents send core-built context plus a manifest prompt to an OpenAI-compatible LLM runtime. The model output is treated as markdown text assistant content.

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

LLM resolution is shared with Prompt Agents, Script `ctx.llm.*` calls, and model
diagnostics. See [contracts/runtime-llm-resolution.md](contracts/runtime-llm-resolution.md)
for the full priority order and Provider/Profile runtime semantics.

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
await ctx.reply_parts([
    {"type": "text", "format": "markdown", "text": "**markdown**"},
    {"type": "json", "data": {"ok": True}},
])
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

`reply_parts` is the Message Parts v2 base helper. The other reply helpers are
wrappers that write parts. Prefer `reply_parts` and typed helpers for new code.
`reply_blocks` is retained only as a legacy developer convenience and is
converted immediately to parts.

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

The core may run automatic session title generation immediately before the first real `ctx.llm.*` call in a pending default-titled session. This pre-hook uses only the triggering user message, does not create visible messages, and does not need any Agent code. Agent authors should not call title generation manually.

The built-in `comfyui_agent` is a Script Agent for ComfyUI workflow/preset recipes and generation. It uses the ComfyUI Capability workflow/preset library to create and edit a per-session recipe through a `form` part, switch `input_mode` between `llm` and `raw`, fill API-format workflow JSON from preset mappings, submit workflows, poll status, fetch formal output images, save local attachments, and return `image` or `media_group` parts.

ComfyUI preset YAML schema is documented in [COMFYUI_PRESET_SCHEMA.md](COMFYUI_PRESET_SCHEMA.md). Use that schema when creating or reviewing workflow preset files.

ComfyUI Agent action semantics:
- `default`: use the current session recipe `input_mode`; `llm` enhances the user request into `values.positive_prompt` using AgentConfig `llm_operation_default`, while `raw` writes the user text directly.
- `raw`: force raw for this invocation, keep the stored `input_mode` unchanged, write `values.positive_prompt`, then generation runs.
- `llm`: force LLM prompt enhancement for this invocation, use AgentConfig `llm_operation_default`, keep the stored `input_mode` unchanged, write `user_prompt` and generated `values.positive_prompt`, then generation runs only when `auto_run_after_llm_prompt=true`.
- `fresh`: one-shot LLM prompt generation that forces `input_mode=llm` and `llm_operation=fresh` for this request only. It uses only the user input to produce a complete new `values.positive_prompt`, does not modify the stored `input_mode`, and does not modify AgentConfig `llm_operation_default`.
- `refine`: one-shot LLM prompt generation that forces `input_mode=llm` and `llm_operation=refine` for this request only. It uses the current `values.positive_prompt` plus the user input to produce a complete new `values.positive_prompt`, does not modify the stored `input_mode`, and does not modify AgentConfig `llm_operation_default`.
- `run`: execute the current session recipe without changing prompt or parameters.
- `form`: show the session recipe editor expanded by default only; the form part does not expose `input_mode` or `user_prompt`, and form submit does not generate.
- `save_recipe_from_form`: internal form submit target that saves the session recipe editor without generating images. It is marked `callable: false` and is not intended for manual composer calls. Silent saves update the source `form` part with latest values and collapse that form to the minimal `Recipe saved. Click to expand.` state; expanding it shows the same editable recipe form again.
- `switch`, `presets`, `scan_workflows`, and `status`: update mode or inspect local state only; they do not generate.

Generation filters ComfyUI temporary, preview, and input images by default. Final chat galleries use saved local attachments for formal `output` images, and attachment metadata records ComfyUI source details including prompt id, preset id, workflow file name, and `comfyui_image_type=output`.

ComfyUI preset `parameter.ui.section` and `parameter.ui.span` metadata can shape the recipe editor layout. The Agent copies that metadata into the `form` part and copies top-level `ui.sections` when present; otherwise it applies compact defaults for prompts, sampling, image, model, and output fields. This layout metadata is static and the form still only edits the per-session recipe.

`input_mode` remains only `llm` or `raw`; `switch` controls only that stored recipe field and does not accept `fresh`, `refine`, or `unset`. `llm_operation_default` controls whether normal `default`/`llm` LLM-mode input uses `refine` or `fresh`, and defaults to `refine`; it does not accept `unset`.

The ComfyUI Agent prompt templates are `llm_refine_system_prompt`, `llm_refine_user_template`, `llm_fresh_system_prompt`, and `llm_fresh_user_template`. Alpha-era legacy `prompt_enhancer_system_prompt` and `prompt_enhancer_user_template` fields are not supported config fields.

`auto_run_after_llm_prompt=false` makes LLM mode save the generated positive prompt for inspection or form editing before the user runs `@comfyui_agent:run`; this applies to `default`, `llm`, `fresh`, and `refine` whenever they use LLM prompt generation.

`free_comfyui_memory_after_generation=false` by default. When enabled, the Agent requests ComfyUI to unload models and free execution memory after a submitted generation reaches a terminal state and output attachments have been saved when available. This is best-effort cleanup through the ComfyUI Capability `free_memory` method; failures are recorded as warnings/metadata and do not replace a successful image result. Enabling it can reduce VRAM usage for local LLMs, but the next ComfyUI generation may be slower because models need to reload.

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

## Message Parts Output

Supported visible message parts are:

- `text`: plain or Markdown text.
- `json`: structured objects and arrays.
- `file`: raw inline text or attachment references.
- `image`: one renderable image payload.
- `media_group`: a gallery of image items.
- `form`: validated interactive forms.
- `command_buttons`: send-message shortcut buttons.
- `notice` and `error`: simple status and error content.

Match the helper to the intended output. For example, use `reply_json` for structured data instead of a Markdown code block when downstream tools should inspect it.

Message Parts v2 is the backend storage path and visible content authority for
Agent and Script Agent assistant replies. New messages render from `parts[]`.

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
- Image output displayed as JSON: the Agent likely used `reply_json`; use `reply_image` or `reply_images`.
- LLM model not configured: set `AGENT_WORKBENCH_LLM_MODEL`, save an LLM Profile, or add an Agent `llm.profile`.

## Safety

Script Agents are trusted local Python code. They run in the backend process and can access local files and network through normal Python APIs. The current project does not sandbox Script Agents, enforce permissions, or isolate third-party code.
