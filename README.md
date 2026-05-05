# Agent Workbench

A lightweight local AI workbench where users can chat with a default Agent, call specific Agents with `@agent_id`, call Agent actions with `@agent_id:action`, and run slash Commands such as `/base64`.

## Current Scope

This repository currently implements the first two core layers:

- Pydantic v2 schemas for Agents, Actions, Capabilities, Commands, context policy, model lifecycle, runs, and messages.
- YAML manifest loading for Agent and Capability manifests.
- Registries for globally unique Agents, Capabilities, and Commands.
- Example `chat` and `translate` Agent manifests.
- Example `base64` Capability manifest exposing `/base64` and `/base64-decode`.
- In-memory stores for sessions, messages, and runs.
- Deterministic routing for `/command`, `@agent`, `@agent:action`, plain text fallback, and waiting-run resume.
- Executable Base64 Commands through `/base64` and `/base64-decode`.
- Command runs with `RUNNING`, `DONE`, and `FAILED` status transitions.
- Command output messages and a minimal in-memory EventBus.
- OpenAI-compatible LLM Capability runtime for Prompt Agents.
- Prompt Agent execution for `@chat`, `@translate`, and plain text to the session default Agent.
- Core-controlled context building for `none`, `current_message`, `recent_messages`, and `session`.
- Full selected-message context for Agent actions, including source Agent messages and parent user messages when available.
- Structured action invocation for future message buttons through `runtime.invoke_action(...)`.
- Agent output message parent linkage, action-linked messages, and generated `available_actions`.
- Action events through the in-memory EventBus.
- Best-effort `after_run` model unload handling with warning events.
- Minimal Script Agent SDK and runner for local trusted Python scripts.
- Script Agent helpers for `ctx.reply`, `ctx.step`, `ctx.capability`, `ctx.llm.generate`, and `ctx.llm.unload`.
- `ctx.ask` skeleton that marks a run as `WAITING_FOR_USER` and sets `session.waiting_run_id`.
- FastAPI app factory with in-memory runtime wiring.
- REST API routes for Agents, Commands, Sessions, Messages, Actions, and Runs.
- Minimal WebSocket endpoint with ping/pong and first-pass EventBus delivery.
- React/Vite frontend MVP with sessions, chat input, message actions, run panel, and basic settings.
- SQLite persistence for sessions, messages, runs, AgentConfig, CapabilityConfig, and lightweight app metadata.
- AgentConfig and CapabilityConfig APIs for enabling/disabling runtime surfaces and storing JSON `user_config`.
- Hardened run cancellation semantics for `PENDING`, `RUNNING`, and `WAITING_FOR_USER` runs.
- Lightweight `schema_version` metadata record for future migration checks.

No external integrations, function calling, model pool, automatic tool selection, script sandbox, auth, formal migration system, or cross-restart task resume are implemented yet.

## Supported Routing Syntax

- `/base64 hello` routes to Command `/base64` with args `hello`.
- `/base64-decode aGVsbG8=` routes to Command `/base64-decode` and returns `hello`.
- `@translate hello` routes to Agent `translate`, action `default`, with args `hello`.
- `@translate:formal more formal please` routes to Agent `translate`, action `formal`, preserving args.
- Message-button style action calls can use `runtime.invoke_action(...)` with `source_message_id`.
- `@echo_script hello` runs the demo Script Agent and calls the Base64 Capability through `ctx.capability`.
- Plain text routes to the session default Agent with action `default`.
- If a session has `waiting_run_id`, input routes to resume before parsing `/` or `@`.

## LLM Configuration

Prompt Agents use OpenAI-compatible `/chat/completions`.

Configuration comes from Agent manifests and can be overridden with environment variables:

- `AGENT_WORKBENCH_LLM_BASE_URL`
- `AGENT_WORKBENCH_LLM_API_KEY`
- `AGENT_WORKBENCH_LLM_MODEL`

Do not commit API tokens or local temporary tokens.

## Script Agents

Script Agents are local trusted Python code loaded from an Agent directory. Entry files must stay inside that directory and export `async def run(ctx)`.

The current SDK supports:

- `ctx.reply(...)`
- `ctx.step(...)`
- `ctx.capability(...)`
- `ctx.llm.generate(...)`
- `ctx.llm.unload(...)`
- `ctx.ask(...)` as a waiting-state skeleton

There is no script sandbox, external app integration, durable persistence, or true multi-turn resume yet.

## API

The API is available through an app factory; importing it does not start a server.

```python
from ai_workbench.api import create_app

app = create_app()
```

Implemented routes include:

- `GET /api/agents`
- `GET /api/commands`
- `GET /api/agent-configs`
- `PATCH /api/agent-configs/{agent_id}`
- `GET /api/capability-configs`
- `PATCH /api/capability-configs/{capability_id}`
- `POST /api/sessions`
- `POST /api/sessions/{session_id}/messages`
- `POST /api/sessions/{session_id}/actions`
- `GET /api/sessions/{session_id}/messages`
- `GET /api/sessions/{session_id}/runs`
- `POST /api/runs/{run_id}/cancel`
- `WS /api/ws/{session_id}`

Runtime events and WebSocket subscribers are still in-memory. WebSocket event delivery is an initial single-process implementation.

## Frontend

Round 8 adds a minimal browser MVP built with React, TypeScript, Vite, Zustand, and Tailwind CSS.

Run the backend:

```powershell
uv run uvicorn ai_workbench.api.main:app --reload
```

Run the frontend:

```powershell
cd frontend
npm install
npm run dev
```

The frontend reads `VITE_API_BASE_URL`; by default it uses `http://localhost:8000`.

Current frontend behavior:

- Session sidebar with create/select session.
- Agent switcher for `session.default_agent_id`.
- Chat input for plain text, `@agent`, `@agent:action`, and `/command`.
- Lightweight autocomplete for Agents, Agent actions, and Commands.
- Message action buttons using `POST /api/sessions/{session_id}/actions`.
- Run panel with recent run status.
- Settings panel for enabling/disabling Agents and Capabilities and editing JSON `user_config`.
- Minimal WebSocket ping/pong and event-triggered refresh.

Limitations remain: only text output is rendered directly, WebSocket event handling is early, there is no authentication, and there is no multi-user permission model.

Disabled Agents are shown in the Agent switcher and cannot be selected as `session.default_agent_id`. Disabled Capability Commands are still visible in autocomplete but fail with a structured backend error if invoked.

## Persistence

Round 9 adds SQLite persistence through SQLModel.

Default database:

```text
sqlite:///./data/agent_workbench.db
```

Override it with:

```powershell
$env:AGENT_WORKBENCH_DATABASE_URL="sqlite:///D:/path/to/agent_workbench.db"
```

Persisted:

- sessions
- messages
- runs
- Agent config records
- Capability config records

Not persisted:

- EventBus subscribers
- active Python coroutine/task state
- WebSocket connections

On service startup, unfinished runs with `RUNNING` or `WAITING_FOR_USER` status are marked `INTERRUPTED`; sessions pointing at interrupted waiting runs have `waiting_run_id` cleared. The app does not try to resume Python execution across process restarts.

## Configuration

Round 10 adds basic persisted config APIs:

- AgentConfig stores `agent_id`, `enabled`, and JSON-object `user_config`.
- CapabilityConfig stores `capability_id`, `enabled`, and JSON-object `user_config`.
- Disabled Agents return `AGENT_DISABLED` when invoked.
- Disabled Capabilities return `CAPABILITY_DISABLED` for their Commands.

`user_config` must be a JSON object. Secret masking and encryption are not implemented yet, so do not store sensitive tokens in local config records unless you accept that they are plain SQLite data.

## Run Cancellation

Cancelable run states:

- `PENDING`
- `RUNNING`
- `WAITING_FOR_USER`

Terminal states are not cancellable: `DONE`, `FAILED`, `CANCELLED`, and `INTERRUPTED`.

Cancelling `WAITING_FOR_USER` also clears the session `waiting_run_id`. Cancelling `RUNNING` marks the run `CANCELLED`, but it does not kill an already executing Python task in this version.

## Schema Version

The database records a lightweight `schema_version = "1"` row in app metadata. The app currently uses `SQLModel.metadata.create_all` and does not include Alembic or a formal migration framework. Future incompatible schema changes may still require manually clearing or migrating a local development database.

## Requirements

- Python 3.10+
- uv

## Development

```powershell
uv sync
uv run pytest
```

## Core Rules

- Agents are invoked with `@agent_id`.
- Agent actions are invoked with `@agent_id:action`.
- Commands are invoked with `/command`.
- Agent ids are globally unique.
- Command names are globally unique.
- Slash Commands are declared only by Capability manifests.
- Agent manifests must not declare slash command aliases.
