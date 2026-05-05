# AGENTS.md

## Project

Build a lightweight personal AI workbench.

The app looks like a normal chat client, but it supports callable Agents and slash Commands:

- Plain user text goes to the current session's default Agent.
- `@agent_id text` invokes a specific Agent.
- `@agent_id:action args` invokes a specific Agent action.
- `/command args` invokes a global Command exposed by a Capability.
- Message buttons invoke the same action system as text calls.

The first implementation should stay small, testable, and local-first.

## Core vocabulary

### Agent

A user-callable assistant.

Two Agent types exist in v0:

1. `prompt`
   - Uses an LLM provider with a prompt and model settings.
   - Examples: chat, translate.

2. `script`
   - Runs a fixed Python script.
   - May call Capabilities and LLM helpers through `AgentContext`.
   - Use this for multi-step local automations after the core is stable.

Agents have globally unique `id`s.

Agents do not own slash commands. Slash commands belong only to Commands.

### Action

An Agent entry point.

Each Agent must have a `default` action.

Examples:

- `@chat hello` -> `chat.default`
- `@translate hello` -> `translate.default`
- `@translate:formal` -> `translate.formal`

Actions may also appear as buttons on messages.

### Capability

An internal callable module used by Agents and Commands.

Examples:

- `llm.generate`
- `llm.chat`
- `llm.unload`
- `base64.encode`
- `base64.decode`
- `storage.get`
- `storage.set`

Capabilities are not automatically exposed to users.

### Command

A user-facing wrapper declared inside a Capability manifest.

Examples:

- `/base64 hello`
- `/base64-decode SGVsbG8=`

Commands are globally unique.

### Session

A conversation with:

- message history
- current `default_agent_id`
- optional `waiting_run_id`

### Run

One execution of:

- an Agent action
- a Command

Runs store status, steps, errors, and metadata.

### Context Policy

Controls how much conversation context an Agent or Action receives.

v0 modes:

- `none`
- `current_message`
- `recent_messages`
- `session`
- `selected_message`

### Model Lifecycle Policy

Controls when the local LLM is loaded or released.

v0 fields:

- `load: on_demand`
- `unload: never | after_run | manual`
- `unload_failure: ignore | warn | fail`

Manual unload must be available to script Agents through `ctx.llm.unload()`.

## Routing rules

Implement routing in this exact priority order:

1. If the current session has a `waiting_run_id`, resume that run.
2. If input begins with `/`, route to `CommandRunner`.
3. If input begins with `@agent_id:action`, route to `AgentRunner`.
4. If input begins with `@agent_id`, route to `AgentRunner` with `default` action.
5. Otherwise route to `session.default_agent_id` with `default` action.

`@` and `/` must remain separate namespaces.

## First implementation scope

Implement the core workbench before adding domain-specific integrations.

Required v0 examples:

- `chat` Prompt Agent
- `translate` Prompt Agent
- `base64` Capability with `/base64` and `/base64-decode`

Script Agent support should be implemented as a framework capability, with one tiny sample script Agent only if needed for testing. Do not add heavy external integrations in the first core milestone.

## Recommended stack

Backend:

- Python 3.10+
- FastAPI
- SQLModel
- SQLite
- Pydantic v2
- uv
- pytest

Frontend:

- React
- TypeScript
- Vite
- Zustand
- Tailwind CSS

## Backend package layout

Target structure:

```text
ai_workbench/
├── core/
│   ├── agent_registry.py
│   ├── capability_registry.py
│   ├── command_registry.py
│   ├── router.py
│   ├── runner.py
│   ├── session.py
│   ├── events.py
│   ├── context.py
│   └── schema/
│       ├── agent.py
│       ├── action.py
│       ├── capability.py
│       ├── command.py
│       ├── message.py
│       ├── run.py
│       ├── context_policy.py
│       └── model_lifecycle.py
│
├── capabilities/
│   ├── llm/
│   │   ├── capability.yaml
│   │   └── __init__.py
│   ├── base64/
│   │   ├── capability.yaml
│   │   └── __init__.py
│   └── storage/
│       ├── capability.yaml
│       └── __init__.py
│
├── agents/
│   ├── chat/
│   │   └── agent.yaml
│   └── translate/
│       └── agent.yaml
│
├── db/
│   ├── database.py
│   └── models.py
│
├── api/
│   ├── main.py
│   ├── ws.py
│   └── routes/
│       ├── agents.py
│       ├── commands.py
│       ├── sessions.py
│       ├── capabilities.py
│       └── runs.py
│
└── frontend/
```

You may adjust filenames if implementation quality improves, but keep the concepts stable.

## Coding rules

- Keep the first version small and explicit.
- Prefer simple Python classes and Pydantic models.
- Avoid hidden runtime magic.
- Do not let LLMs decide routing.
- Do not require function-calling support from the model.
- Treat LLM output as plain text unless the Agent script explicitly parses and validates it.
- The LLM Capability should target OpenAI-compatible local services first.
- Model unload is best-effort. Providers may report unsupported unload.
- Every Command must be registered from a Capability manifest and must be globally unique.
- Every Agent id must be globally unique.
- Agents must not declare slash command aliases.
- Context must be built by the core from `context_policy`, not ad hoc inside each Agent.
- Tests should cover registries, router parsing, context selection, and run state transitions.

## Minimum done criteria for each round

Each implementation round must end with:

1. Updated tests.
2. A short summary of completed work.
3. A list of changed files.
4. Commands run and their results.
5. Known limitations or intentionally deferred work.
