# Agent Workbench

v0.1.0-alpha Technical Alpha for a lightweight personal AI workbench.

The app looks like a small chat client, but messages can route to callable Agents and slash Commands:

- Plain text goes to the current session default Agent.
- `@translate 你好` invokes a specific Agent.
- `@translate:formal` invokes a specific Agent action.
- `/base64 hello` invokes a global Command exposed by a Capability.

The current alpha focuses on local-first chat routing, schema-aware settings, LLM diagnostics, run timelines, health checks, SQLite persistence, and basic operator scripts.

## Quick Start

Requirements:

- Python 3.10.11 or any Python 3.10+
- uv
- Node.js and npm for the frontend

Create a local env file:

```powershell
Copy-Item .env.example .env
```

Install backend dependencies:

```powershell
uv sync
```

Start the backend:

```powershell
uv run uvicorn ai_workbench.api.main:app --reload
```

Start the frontend in another shell:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL, usually `http://localhost:5173`.

## Environment

`.env.example` contains the local defaults:

```text
AGENT_WORKBENCH_DATABASE_URL=sqlite:///./data/agent_workbench.db
AGENT_WORKBENCH_LLM_BASE_URL=http://localhost:1234/v1
AGENT_WORKBENCH_LLM_API_KEY=
AGENT_WORKBENCH_LLM_MODEL=
AGENT_WORKBENCH_LLM_TIMEOUT=60
```

LLM config resolution now uses one shared path for Prompt Agents, Script Agent `ctx.llm.generate`, diagnostics, and model listing.

Priority, highest first:

- per-invocation explicit override
- session LLM Profile override, when the Agent allows it
- Agent manifest `llm.profile`
- Agent manifest legacy `model` fields
- persisted `llm` CapabilityConfig `default_profile`
- persisted direct `llm` CapabilityConfig from Settings
- `.env` / process environment fallback: `AGENT_WORKBENCH_LLM_BASE_URL`, `AGENT_WORKBENCH_LLM_API_KEY`, `AGENT_WORKBENCH_LLM_MODEL`, `AGENT_WORKBENCH_LLM_TIMEOUT`
- `llm` capability manifest defaults

The Chat composer has a custom dark session model selector beside Send. `Default` means the current Agent manifest or global fallback resolves the model. Selecting an enabled saved LLM Profile stores `session.llm_profile_id` and overrides LLM Agents in that session unless the Agent opts out. The dropdown hides disabled profiles and highlights the selected item.

When the session model changes, the app inserts a centered `model_changed` separator before the next user message. This separator is persisted for UI history but is filtered out of LLM context.

## Basic Usage

Create a session, then try:

```text
hello
@translate 你好
@translate:formal
/base64 hello
```

Message action buttons use the same Agent action system as text calls.

Message hover actions are available in Chat:

- User messages: Copy, Edit, Delete.
- Agent messages: Copy, Retry, Delete.

Copy uses the raw message content. Markdown replies copy Markdown source, and JSON messages copy pretty JSON.

Delete only removes the selected message. It does not remove later messages and does not cascade-delete runs.

Agent Retry deletes the selected Agent message and all later messages, then regenerates from the source user message. User Edit updates the selected user message, deletes all later messages, then submits the edited content again. Retry and Edit both use the current session model resolution rules, so switching the composer model before retrying or editing affects the regenerated Agent reply and still records `llm_resolution` metadata.

Sessions can be deleted from the sidebar. Deleting a session is a hard delete in this alpha: its messages, runs, and run events are removed from SQLite.

## Agent Avatars

Agent image avatars can live beside the Agent manifest. Directory avatars take priority over `agent.yaml`:

```text
agents/my_agent/avatar.png
agents/my_agent/avatar.jpg
agents/my_agent/avatar.jpeg
agents/my_agent/avatar.webp
agents/my_agent/avatar.svg
agents/my_agent/agent.png
agents/my_agent/agent.jpg
```

If no directory avatar exists, `avatar` in `agent.yaml` can be an emoji, an `http`/`https` image URL, a local path inside the Agent directory such as `./avatar.png`, or text such as `TA`. Local avatar paths must stay inside the Agent directory.

## Local LM Studio

Start LM Studio or another OpenAI-compatible local service with an API endpoint like:

```text
http://localhost:1234/v1
```

Set `AGENT_WORKBENCH_LLM_MODEL` in `.env`, or configure the `llm` capability in Settings. Local LM Studio setups often do not require an API key; an empty key is allowed.

In Settings, use the `llm` capability `Test connection` button. It calls `/api/capability-configs/llm/test`, checks `/models`, and returns a success or failure message with the configured base URL.

After a successful test, available models are shown in the LLM settings area. Select one, then click Save to persist it as `CapabilityConfig.user_config.model`. Prompt Agents without their own manifest model use that saved model by default. Agents that declare a model in their manifest keep using the manifest model unless an environment override is present.

## LLM Profiles

Saved LLM Profiles are reusable model connection configs. The user-facing fields are:

- Name: the display name shown in Settings, such as `My Qwen3 Local`.
- Model ID: the real provider model id, such as `ascat/Ministral-3-3b-it-ad`.
- Profile key: the stable key used by Agent manifests. In the current API this maps to the stored `alias` field.

Supported provider labels in this alpha:

- `openai_compatible`
- `lm_studio`
- `llama_cpp`
- `custom`

All provider labels currently use the same OpenAI-compatible runtime path.

Settings -> LLM follows the Settings Console three-column structure. The middle object list contains:

- Global fallback, backed by the existing `llm` CapabilityConfig.
- LLM Profiles, backed by the `llm_profiles` SQLite table.

The profile editor can create, edit, delete, test, and refresh models for saved profiles. New profiles generate a Profile key from Name by lowercasing, replacing whitespace with underscores, removing invalid characters, and appending a numeric suffix if needed. API/UI responses mask `api_key` as `********`; PATCHing `api_key: "********"` preserves the stored secret. Secrets are still stored as plaintext in SQLite in this alpha and are not encrypted yet.

Profile capability flags are available for display and future behavior:

- Vision
- Tools
- Reasoning
- Streaming
- JSON mode

These flags do not change runtime behavior yet.

Agent manifests can reference a profile by Profile key or id:

```yaml
llm:
  profile: myqwen3
  allow_session_override: false
  temperature: 0.2
  top_p: 0.9
  top_k: 40
  max_tokens: 2048
```

`allow_session_override` defaults to `true`. If it is `false`, the session model selector does not override that Agent; the Agent keeps using its manifest profile/model or fallback. The Agent dropdown marks these Agents as locked.

Agent replies store resolved model metadata in run metadata and assistant message metadata under `llm_resolution`. The Chat UI displays the model used for that specific reply, preferring profile name, then profile key, then model id. The API never returns plaintext API keys in this metadata.

The old manifest `model` field remains compatible:

```yaml
model:
  provider: openai_compatible
  base_url: http://localhost:1234/v1
  model: qwen2.5-3b-instruct
```

`model` is legacy. New Agents should prefer `llm.profile`.

Profile resolution errors are structured:

- `LLM_PROFILE_NOT_FOUND`
- `LLM_PROFILE_DISABLED`
- `LLM_PROFILE_INVALID`

## Settings

AgentConfig and CapabilityConfig now use manifest-declared `config_schema` fields. Unknown user config fields are rejected by the API.

Supported schema field types:

- `string`
- `text`
- `integer`
- `float`
- `boolean`
- `enum`
- `json`

If a manifest has no `config_schema`, Settings shows `No configurable fields` and does not allow arbitrary JSON edits.

The `llm` Settings card also shows resolved non-secret status:

- `base_url`
- `model`
- `timeout`
- whether an API key is set

The resolved status endpoint does not return API key plaintext.

Secret fields render as password inputs. API responses return the fixed mask `********` for set secrets. Sending `********` back in a PATCH keeps the stored value unchanged. Sending an empty string clears the secret because empty strings are omitted from the saved form payload in the current UI; API callers can send `""` explicitly if they want to persist an empty value.

Secret masking is API/UI masking only. Secrets are still stored as plaintext JSON in SQLite and are not encrypted yet.

## SQLite Data

Default database path:

```text
data/agent_workbench.db
```

Override it with:

```text
AGENT_WORKBENCH_DATABASE_URL=sqlite:///./data/agent_workbench.db
```

The current schema version is stored in app metadata as `schema_version`.

This project still uses a lightweight schema version guard plus `SQLModel.metadata.create_all`. New tables can be created during startup, but there is no Alembic migration system yet.

Reset local data with a dry run:

```powershell
uv run python scripts/reset_data.py
```

Actually delete the default SQLite file:

```powershell
uv run python scripts/reset_data.py --yes
```

The reset script only deletes file-backed SQLite databases in safe project or temp paths.

## Diagnostics

Health endpoints:

```text
GET /api/health
GET /api/health/details
```

`/api/health` returns version, database status, and schema version. `/api/health/details` adds registry counts and a non-secret LLM config summary. It reports whether an API key is set, but never returns the plaintext key.

Runs also have a lightweight event timeline:

```text
GET /api/runs/{run_id}/events
```

The timeline records events such as `run_started`, `run_step`, `action_invoked`, `message_done`, `run_done`, `run_failed`, and `run_cancelled`. The frontend Runs panel can expand a run to show this timeline.

API errors use a structured shape:

```json
{
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "Run not found: example",
    "details": {}
  }
}
```

The frontend shows API failures in a visible error banner/status area instead of only logging them.

Run:

```powershell
uv run python scripts/check.py
```

It checks Python version, manifest loading, Agent/Capability/Command registries, SQLite initialization, `schema_version`, `create_app(use_memory=True)`, health endpoints, registry counts, and that health details do not leak API key plaintext.

## Development Checks

```powershell
uv run pytest
cd frontend
npm run build
cd ..
uv run python scripts/check.py
```

## Script Agents

Script Agents are local trusted Python code. They can call core helpers through `AgentContext`, including LLM helpers and Capabilities, but they are not sandboxed as untrusted code.

See [docs/AGENT_DEVELOPMENT.md](docs/AGENT_DEVELOPMENT.md) for Prompt Agent and Script Agent templates, the recommended `ctx.llm` and reply SDKs, `scripts/check_agents.py`, and command-line Agent testing with `scripts/run_agent.py`.

The same guide covers frontend output rendering for `text`, `markdown`, and `json`, LLM JSON reliability patterns for small local models, and a practical Script Agent debug workflow.

## Current Limitations

- Technical Alpha, local-first only.
- No auth, users, roles, or permissions.
- No Alembic migrations.
- No secret encryption.
- No external app integrations.
- No function calling, MCP, or LLM automatic tool selection.
- No file upload.
- No model pool, GPU scheduling, or advanced model lifecycle management.
- Run cancellation is API-level state hardening; it does not kill every underlying Python task.
