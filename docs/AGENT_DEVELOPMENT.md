# Agent Development

Agents live under `agents/<agent_id>/` with an `agent.yaml` manifest. Agent ids are global and must be unique. Every Agent must define a `default` action.

## Prompt Agents

A Prompt Agent sends core-built context plus the manifest prompt to the configured OpenAI-compatible LLM runtime.

Minimal `agents/my_prompt/agent.yaml`:

```yaml
id: my_prompt
name: My Prompt Agent
type: prompt
prompt: You are concise and helpful.
actions:
  - id: default
context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 4000
model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

Prompt Agents do not declare slash commands. Commands belong to Capability manifests.

## Agent Avatars

Place image avatars in the Agent directory when possible:

```text
agents/my_agent/avatar.png
```

The backend checks these files first, in order: `avatar.png`, `avatar.jpg`, `avatar.jpeg`, `avatar.webp`, `avatar.svg`, `agent.png`, `agent.jpg`. A directory avatar overrides `avatar` in `agent.yaml`.

If no directory avatar exists, `avatar` in `agent.yaml` supports emoji, `http`/`https` image URLs, local paths inside the Agent directory such as `./avatar.png` or `avatar.png`, and short text fallbacks. Local paths using `../` or absolute paths are ignored.

## Script Agents

Script Agents are trusted local Python code. They are imported and run inside the backend process with no sandbox. Do not treat Script Agents as a boundary for untrusted code.

Minimal `agents/my_script/agent.yaml`:

```yaml
id: my_script
name: My Script Agent
type: script
entry: agent.py
actions:
  - id: default
context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 4000
model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

Minimal `agents/my_script/agent.py`:

```python
async def run(ctx):
    await ctx.reply_text(f"Input: {ctx.input.text}")
```

The script entry path must stay inside the Agent directory. The module must export `async def run(ctx)`.

## LLM SDK

Recommended Script Agent LLM methods:

```python
text = await ctx.llm.text(system="You are concise.", user=ctx.input.text)
data = await ctx.llm.json(system="Return a JSON object.", user=ctx.input.text)
reply = await ctx.llm.chat([
    {"role": "system", "content": "You are concise."},
    {"role": "user", "content": ctx.input.text},
])
```

`ctx.llm.text(...)` returns `str`. `ctx.llm.json(...)` extracts a raw or fenced JSON object and returns `dict`; invalid JSON raises a clear error. `ctx.llm.chat(...)` returns text.

`ctx.llm.generate(...)` remains for compatibility and supports old calls such as `await ctx.llm.generate(prompt=...)` plus `await ctx.llm.generate(system=..., user=...)`. New Script Agents should prefer `text`, `json`, and `chat`.

Manual unload is available:

```python
await ctx.llm.unload()
```

Do not depend on LLM function calling, MCP, or automatic tool selection. Script Agents should call Capabilities and parse/validate LLM output explicitly.

## Reply SDK

Recommended reply methods:

```python
await ctx.reply_text("plain text")
await ctx.reply_markdown("**markdown**")
await ctx.reply_json({"ok": True})
```

`reply_json` stores structured JSON content with `output_type=json`. It does not stringify the object for the backend API.

Compatibility forms still work:

```python
await ctx.reply("markdown body", type="markdown")
await ctx.reply("markdown body", output_type="markdown")
```

## Output Rendering

The frontend renders messages by `output_type`:

- `text`: plain text with line breaks preserved.
- `markdown`: Markdown rendered with headings, lists, tables, and code blocks. Raw HTML is not enabled.
- `json`: objects and arrays are pretty-printed as JSON.

Match content type to output type:

```python
await ctx.reply_text("plain text")
await ctx.reply_markdown("# Title\n\n- item")
await ctx.reply_json({"summary": "ok", "items": [1, 2]})
```

Avoid returning JSON as a Markdown string unless the user should read it as prose. Prefer `reply_json` when downstream UI or tools should inspect structured data.

## LLM JSON Reliability

Small local models often produce invalid JSON, comments around JSON, or Markdown fences with broken content. `ctx.llm.json(...)` is strict: it extracts a raw or fenced JSON object and calls `json.loads`. It does not repair invalid JSON.

For complex Agents, use an explicit fallback path:

```python
import json


async def run(ctx):
    raw = await ctx.llm.text(
        system="Return only a JSON object with keys summary and tasks.",
        user=ctx.input.text,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = await ctx.llm.text(
            system="Rewrite this as valid JSON only. No prose.",
            user=raw,
        )
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model did not produce valid JSON: {exc}") from exc

    await ctx.reply_json(data)
```

Use stricter prompts, smaller schemas, and clear errors when repair fails. Do not rely on LLM tool calling, MCP, or automatic tool choice.

## Capabilities

Script Agents call internal Capabilities through `ctx.capability(...)`:

```python
async def run(ctx):
    cap = ctx.capability("base64")
    encoded = await cap.encode(text="hello")
    if not encoded.success:
        raise RuntimeError(encoded.error or "base64 failed")
    await ctx.reply_text(encoded.data)
```

Declare capability dependencies in `agent.yaml`:

```yaml
capabilities:
  - base64
```

## Local Checks

Validate all Agent manifests and Script Agent imports:

```powershell
uv run python scripts/check_agents.py
```

This checks unique Agent ids, `default` actions, script entry paths, `run(ctx)`, async `run`, and declared Capability references. It imports Script Agent modules but does not execute `run(ctx)`, connect to an LLM, touch the frontend, or modify the database.

Run an Agent from the command line:

```powershell
uv run python scripts/run_agent.py echo_script "hello"
uv run python scripts/run_agent.py project_planner:json_only "plan a local release"
uv run python scripts/run_agent.py meeting_digest "今天讨论了..."
uv run python scripts/run_agent.py meeting_digest:json_only "今天讨论了..."
uv run python scripts/run_agent.py echo_script "hello" --json
uv run python scripts/run_agent.py echo_script "hello" --show-trace
```

The command prints run id, run status, events, messages, and errors. It defaults to an in-memory runtime so quick Agent tests do not pollute local SQLite.

## Debug Workflow

1. Run manifest/import checks:

```powershell
uv run python scripts/check_agents.py
```

2. Run the Agent without opening the frontend:

```powershell
uv run python scripts/run_agent.py echo_script "hello"
uv run python scripts/run_agent.py project_planner:json_only "plan a local release"
```

3. Use machine-readable output when comparing runs:

```powershell
uv run python scripts/run_agent.py echo_script "hello" --json
```

4. Use traceback output only when debugging local code:

```powershell
uv run python scripts/run_agent.py echo_script "hello" --show-trace
```

If an LLM model is missing, set `AGENT_WORKBENCH_LLM_MODEL`, save a model in Settings, or set the Agent manifest `model` field. The default CLI memory runtime may not read saved SQLite Settings; use `--use-sqlite` when testing persisted Settings.

## Common Mistakes

- Missing `default` action in `agent.yaml`.
- Typo in `capabilities` such as `base_64` instead of `base64`.
- LLM model not configured for an Agent that calls `ctx.llm`.
- Invalid JSON from a small model passed directly to `reply_json`.
- Mismatch between `output_type` and content, such as `output_type=json` with a prose string.
- Using `ctx.reply(...)` with the wrong keyword; prefer `reply_text`, `reply_markdown`, and `reply_json`.

## Migration Note

Existing Script Agents such as a local `meeting_digest` can continue using:

```python
generated = await ctx.llm.generate(system="...", user="...")
```

For new code, prefer:

```python
text = await ctx.llm.text(system="...", user="...")
data = await ctx.llm.json(system="...", user="...")
```
