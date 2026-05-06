# Agent Development

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

If an LLM model is not configured, Prompt Agent runs fail clearly. Set `AGENT_WORKBENCH_LLM_MODEL`, save an LLM Profile in Settings, or reference a profile in the Agent manifest:

```yaml
llm:
  profile: my_local_model
  allow_session_override: true
```

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

## Actions

Actions are Agent entry points:

```text
@my_script hello
@my_script:default hello
@translate:formal
```

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
- `rich_content`: ordered text, markdown, and image blocks.

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
