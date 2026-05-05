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
uv run python scripts/run_agent.py meeting_digest "今天讨论了..."
uv run python scripts/run_agent.py meeting_digest:json_only "今天讨论了..."
```

The command prints run id, run status, events, messages, and errors. It defaults to an in-memory runtime so quick Agent tests do not pollute local SQLite.

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
