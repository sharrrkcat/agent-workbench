# Agent Workbench

Technical Alpha for a lightweight personal AI workbench.

The app looks like a small chat client, but messages can route to callable Agents and slash Commands:

- Plain text goes to the current session default Agent.
- `@translate 你好` invokes a specific Agent.
- `@translate:formal` invokes a specific Agent action.
- `/base64 hello` invokes a global Command exposed by a Capability.

Round 11 focuses on alpha polish: schema-aware configuration, API/UI secret masking, LLM connection diagnostics, SQLite persistence checks, and basic operator scripts.

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

- Explicit environment overrides: `AGENT_WORKBENCH_LLM_BASE_URL`, `AGENT_WORKBENCH_LLM_API_KEY`, `AGENT_WORKBENCH_LLM_MODEL`, `AGENT_WORKBENCH_LLM_TIMEOUT`
- Agent manifest `model` fields
- persisted `llm` CapabilityConfig from Settings
- `llm` capability manifest defaults

Environment variables intentionally win so local development and CI can temporarily override UI-saved settings without editing SQLite.

## Basic Usage

Create a session, then try:

```text
hello
@translate 你好
@translate:formal
/base64 hello
```

Message action buttons use the same Agent action system as text calls.

## Local LM Studio

Start LM Studio or another OpenAI-compatible local service with an API endpoint like:

```text
http://localhost:1234/v1
```

Set `AGENT_WORKBENCH_LLM_MODEL` in `.env`, or configure the `llm` capability in Settings. Local LM Studio setups often do not require an API key; an empty key is allowed.

In Settings, use the `llm` capability `Test connection` button. It calls `/api/capability-configs/llm/test`, checks `/models`, and returns a success or failure message with the configured base URL.

After a successful test, available models are shown in the LLM settings area. Select one, then click Save to persist it as `CapabilityConfig.user_config.model`. Prompt Agents without their own manifest model use that saved model by default. Agents that declare a model in their manifest keep using the manifest model unless an environment override is present.

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

Run:

```powershell
uv run python scripts/check.py
```

It checks Python version, manifest loading, Agent/Capability/Command registries, SQLite initialization, and `schema_version`.

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
