<!-- FILE: AGENTS.md -->

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


<!-- FILE: docs/ARCHITECTURE.md -->

# Architecture

## Product definition

A lightweight local AI workbench.

Users interact through a normal chat UI. They can:

- set a default Agent for a session
- invoke Agents with `@agent_id`
- invoke Agent actions with `@agent_id:action`
- invoke Commands with `/command`
- click message action buttons

The system does not depend on autonomous model decisions. Agent flows are fixed by configuration or Python code.

## Namespaces

### Agent namespace

`@agent_id`

- global
- unique
- used for user-callable assistants
- may be set as a session default

### Action namespace

`@agent_id:action_id`

- scoped under one Agent
- used by text calls and message buttons

### Command namespace

`/command`

- global
- unique
- declared by Capability manifests
- used for stateless tools

## Core runtime flow

```text
User input
  ↓
Router
  ├─ waiting run → resume
  ├─ /command → CommandRunner → Capability method
  ├─ @agent:action → AgentRunner
  ├─ @agent → AgentRunner default action
  └─ plain text → session.default_agent default action

AgentRunner
  ↓
ContextBuilder
  ↓
Prompt Agent or Script Agent
  ↓
CapabilityRegistry / LLM / Storage
  ↓
Run events + Messages
  ↓
Frontend
```

## Agent manifest

Example prompt Agent:

```yaml
id: chat
name: Chat Agent
type: prompt
description: Default chat agent
avatar: "🤖"

actions:
  - id: default
    description: Normal multi-turn chat

model:
  provider: openai_compatible
  base_url: http://localhost:1234/v1
  model: qwen2.5-3b-instruct

prompt: |
  You are a concise, reliable assistant.

context_policy:
  mode: session
  max_messages: 20
  max_chars: 12000

model_lifecycle:
  load: on_demand
  unload: never
  unload_failure: warn
```

Example translate Agent:

```yaml
id: translate
name: Translate Agent
type: prompt
description: Translate the current input
avatar: "🌐"

actions:
  - id: default
    description: Translate current input
  - id: formal
    label: More formal
    description: Rewrite the selected translation in a more formal tone
    context_policy:
      mode: selected_message
      include_original_user_message: true
      include_last_agent_message: true
  - id: casual
    label: More casual
    description: Rewrite the selected translation in a more casual tone
    context_policy:
      mode: selected_message
      include_original_user_message: true
      include_last_agent_message: true
  - id: retry
    label: Retry
    description: Retry based on the selected source message
    context_policy:
      mode: selected_message
      include_original_user_message: true

model:
  provider: openai_compatible
  base_url: http://localhost:1234/v1
  model: qwen2.5-1.5b-instruct

prompt: |
  Translate the user input into natural, accurate English.
  Output only the translation.

context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 6000

model_lifecycle:
  load: on_demand
  unload: after_run
  unload_failure: warn
```

## Capability manifest

Commands are declared inside a Capability manifest.

Example:

```yaml
id: base64
name: Base64 Capability
description: Base64 encoding and decoding

methods:
  - id: encode
    description: Encode text to Base64
    input_schema:
      text:
        type: string
        required: true
    output:
      type: text

  - id: decode
    description: Decode Base64 text
    input_schema:
      text:
        type: string
        required: true
    output:
      type: text

commands:
  - name: /base64
    method: encode
    description: Encode text to Base64
    safe: true

  - name: /base64-decode
    method: decode
    description: Decode Base64 text
    safe: true
```

## Context policy

Required v0 modes:

| Mode | Meaning |
|---|---|
| `none` | no session history |
| `current_message` | current user text only |
| `recent_messages` | last N messages |
| `session` | session history within limits |
| `selected_message` | message related to a button/action invocation |

Default recommendations:

| Target | Mode |
|---|---|
| Chat Agent | `session` |
| Translate Agent | `current_message` |
| Command | `none` |
| message rewrite actions | `selected_message` |

## Model lifecycle

Required v0 fields:

```yaml
model_lifecycle:
  load: on_demand
  unload: never
  unload_failure: warn
```

Supported `unload` values in v0:

- `never`
- `after_run`
- `manual`

Script Agents must be able to call:

```python
await ctx.llm.unload()
```

Provider unload is best-effort. Unsupported unload should not crash unless `unload_failure: fail`.

## Run status

```python
PENDING
RUNNING
WAITING_FOR_USER
DONE
FAILED
CANCELLED
INTERRUPTED
```

On server startup, any persisted `RUNNING` or `WAITING_FOR_USER` run should be marked `INTERRUPTED`.

## WebSocket events

Client to server:

- `user_message`
- `action_invoke`
- `command_invoke`
- `set_default_agent`
- `user_input_reply`
- `cancel_run`

Server to client:

- `message_start`
- `message_delta`
- `message_done`
- `run_started`
- `run_step`
- `run_waiting_for_input`
- `run_done`
- `run_failed`
- `run_cancelled`
- `session_updated`
- `error`

All events should include:

```json
{
  "version": 1,
  "session_id": "...",
  "run_id": "...",
  "message_id": "..."
}
```


<!-- FILE: docs/MILESTONES.md -->

# Implementation Milestones

This project should be implemented in multiple small rounds. Do not try to complete everything in one pass.

## Round 0 — Project bootstrap and specification lock

Goal: create the repository skeleton and lock v0 terms.

Deliverables:

- `AGENTS.md`
- `README.md`
- `pyproject.toml`
- backend package skeleton
- test skeleton
- example manifests for `chat`, `translate`, and `base64`

Acceptance checks:

- Project installs with `uv sync`
- Tests run with `uv run pytest`
- Manifests can be loaded as plain YAML

## Round 1 — Core schema and registries

Goal: implement the schema layer and registries.

Deliverables:

- `AgentSchema`
- `ActionSchema`
- `CapabilitySchema`
- `CommandSchema`
- `ContextPolicy`
- `ModelLifecyclePolicy`
- `AgentRegistry`
- `CapabilityRegistry`
- `CommandRegistry`

Acceptance checks:

- `chat` and `translate` Agent manifests load
- `base64` Capability manifest loads
- `/base64` and `/base64-decode` register as Commands
- duplicate Agent ids fail
- duplicate Command names fail
- Agent manifests cannot create slash command aliases

## Round 2 — Session, message, run, and router

Goal: implement core runtime state and deterministic routing.

Deliverables:

- SQLite + SQLModel setup
- `SessionStore`
- `MessageStore`
- `RunStore`
- router parser for `/command`, `@agent`, `@agent:action`
- `AgentRunner` skeleton
- `CommandRunner` skeleton

Acceptance checks:

- plain text routes to session default Agent
- `@chat hi` routes to `chat.default`
- `@translate:formal` routes to `translate.formal`
- `/base64 hi` routes to CommandRunner
- unknown Agent returns structured error
- unknown Command returns structured error
- waiting run resumes before parsing `/` or `@`

## Round 3 — Base64 Command and minimal event pipeline

Goal: make one non-LLM Command work end to end.

Deliverables:

- `base64` Capability implementation
- Command input parsing
- Command result as a Message
- Run status transition for Commands
- minimal EventBus interface

Acceptance checks:

- `/base64 hello` returns `aGVsbG8=`
- `/base64-decode aGVsbG8=` returns `hello`
- Command does not read session history
- one Run row is created per command invocation
- failed decode returns `FAILED` run with a safe error

## Round 4 — LLM Capability and Prompt Agents

Goal: make local OpenAI-compatible model services work for Prompt Agents.

Deliverables:

- `llm` Capability
- OpenAI-compatible provider
- streaming support
- ContextBuilder
- PromptAgentRunner
- model lifecycle `after_run` best-effort unload
- `chat` Agent
- `translate` Agent

Acceptance checks:

- Chat Agent receives session context
- Translate Agent receives only current input
- `@translate hello` returns translation through the configured local model
- model unload unsupported case reports a warning or structured unsupported result
- no model function-calling support is required

## Round 5 — Agent actions and message buttons

Goal: make action invocation consistent across text and UI.

Deliverables:

- `@agent:action` execution path
- `action_invoke` API/WebSocket event
- message `available_actions`
- selected-message context
- translate actions: `formal`, `casual`, `retry`

Acceptance checks:

- clicking a message action and typing `@translate:formal` use the same action runner path
- selected-message context is used for rewrite actions
- action can create a new Message with parent linkage

## Round 6 — Script Agent SDK

Goal: implement the SDK for fixed Python script Agents.

Deliverables:

- `AgentContext`
- `ctx.reply`
- `ctx.stream`
- `ctx.step`
- `ctx.ask`
- `ctx.capability`
- `ctx.llm.generate`
- `ctx.llm.unload`
- ScriptAgentRunner
- tiny local demo Script Agent for testing only

Acceptance checks:

- Script Agent can emit step events
- Script Agent can call Base64 Capability
- Script Agent can call LLM Capability
- Script Agent can manually unload model
- exceptions produce structured `run_failed`

## Round 7 — Frontend MVP

Goal: make the project usable from a chat interface.

Deliverables:

- React + TypeScript + Vite setup
- Session sidebar
- Chat view
- Agent switcher
- `/command` autocomplete
- `@agent` autocomplete
- `@agent:action` autocomplete
- Message actions
- Run progress display

Acceptance checks:

- user can create/open sessions
- user can switch default Agent
- user can chat with default Agent
- user can invoke `@translate`
- user can invoke `/base64`
- user can click action buttons
- run progress appears for longer operations

## Round 8 — Documentation and polish

Goal: make v0 usable by another developer.

Deliverables:

- README quickstart
- Agent manifest guide
- Capability manifest guide
- Prompt Agent guide
- Script Agent guide
- Local model service setup guide
- Troubleshooting guide

Acceptance checks:

- fresh checkout can run chat, translate, and base64
- a developer can add a new Prompt Agent from docs
- a developer can add a new Capability + Command from docs
- test suite passes


<!-- FILE: docs/CODEX_ROUND_1.md -->

# Codex Round 1 Task

Implement the initial backend skeleton, schemas, manifest loaders, and registries.

## Goal

Create a minimal Python package that can load Agent and Capability manifests and register Commands exposed from Capabilities.

Do not implement LLM calls, frontend, external app integrations, or long-running script examples in this round.

## Required files

Create or update:

```text
pyproject.toml
README.md
AGENTS.md

ai_workbench/
  __init__.py
  core/
    __init__.py
    agent_registry.py
    capability_registry.py
    command_registry.py
    manifest_loader.py
    schema/
      __init__.py
      action.py
      agent.py
      capability.py
      command.py
      context_policy.py
      model_lifecycle.py
      run.py
      message.py

agents/
  chat/agent.yaml
  translate/agent.yaml

capabilities/
  base64/capability.yaml

tests/
  test_manifest_loading.py
  test_registries.py
```

## Schema requirements

Use Pydantic v2 models.

### Agent manifest model

Fields:

- `id: str`
- `name: str`
- `type: Literal["prompt", "script"]`
- `description: str = ""`
- `avatar: str = ""`
- `entry: str | None = None`
- `actions: list[ActionSchema]`
- `model: dict | None = None`
- `prompt: str | None = None`
- `context_policy: ContextPolicy`
- `model_lifecycle: ModelLifecyclePolicy`
- `capabilities: list[str] = []`
- `config_schema: list[dict] = []`

Validation:

- `id` must match `^[a-zA-Z][a-zA-Z0-9_\\-]*$`
- `actions` must contain `default`
- `type=script` should require `entry`
- Agent manifests must not contain command aliases
- action ids must be unique inside one Agent

### Action schema

Fields:

- `id: str`
- `label: str | None = None`
- `description: str = ""`
- `input_schema: dict = {}`
- `context_policy: ContextPolicy | None = None`
- `attach_to: str | None = None`
- `callable: bool = True`

### Context policy

Fields:

- `mode: Literal["none", "current_message", "recent_messages", "session", "selected_message"]`
- `max_messages: int | None = None`
- `max_chars: int | None = None`
- `include_system_prompt: bool = True`
- `include_attachments: Literal["none", "explicit"] = "none"`
- `include_last_agent_message: bool = False`
- `include_original_user_message: bool = False`

### Model lifecycle

Fields:

- `load: Literal["on_demand"] = "on_demand"`
- `unload: Literal["never", "after_run", "manual"] = "never"`
- `unload_failure: Literal["ignore", "warn", "fail"] = "warn"`

### Capability manifest model

Fields:

- `id: str`
- `name: str`
- `description: str = ""`
- `methods: list[CapabilityMethod]`
- `commands: list[CommandSchema] = []`

Validation:

- method ids unique
- every command method must exist in `methods`

### Command schema

Fields:

- `name: str`
- `method: str`
- `description: str = ""`
- `safe: bool = False`
- `confirm: str | None = None`

Validation:

- command name must start with `/`
- command name must match `^/[a-zA-Z][a-zA-Z0-9_\\-]*$`

## Registry requirements

### AgentRegistry

- load Agent schemas from directories
- register by unique `agent.id`
- reject duplicates
- get by id
- list Agents

### CapabilityRegistry

- load Capability schemas from directories
- register by unique `capability.id`
- reject duplicates
- get by id
- list Capabilities

### CommandRegistry

- collect commands from registered Capabilities
- command names must be globally unique
- each command stores:
  - command name
  - capability id
  - method id
  - description
  - safety fields

## Example manifests

### `agents/chat/agent.yaml`

Use:

- id `chat`
- type `prompt`
- default action
- context mode `session`
- unload `never`

### `agents/translate/agent.yaml`

Use:

- id `translate`
- type `prompt`
- actions `default`, `formal`, `casual`, `retry`
- context mode `current_message`
- action override context mode `selected_message`
- unload `after_run`

### `capabilities/base64/capability.yaml`

Expose:

- method `encode`
- method `decode`
- command `/base64`
- command `/base64-decode`

## Tests

Implement tests for:

1. Agent manifests load.
2. Capability manifest loads.
3. CommandRegistry exposes `/base64` and `/base64-decode`.
4. Duplicate Agent id fails.
5. Duplicate Command name fails.
6. Agent without default action fails.
7. Command referencing a missing method fails.
8. Agent manifest containing any slash-command alias-like field fails or is ignored with a clear validation error.

## Completion response format

When done, report:

- changed files
- tests run
- test results
- known limitations
- next suggested round


<!-- FILE: docs/CODEX_KICKOFF_PROMPT.md -->

# Codex Kickoff Prompt

You are implementing a new lightweight personal AI workbench.

Start by reading `AGENTS.md`, then implement `docs/CODEX_ROUND_1.md`.

Important constraints:

- Keep the first round small.
- Implement only schema, manifest loading, and registries.
- Use Pydantic v2.
- Use tests.
- Agents are invoked with `@agent_id`.
- Agent actions are invoked with `@agent_id:action`.
- Commands are invoked with `/command`.
- Slash Commands belong only to Capability manifests.
- Agents must not declare slash command aliases.
- Commands must be globally unique.
- Agent ids must be globally unique.
- The first example Agents are `chat` and `translate`.
- The first example Capability is `base64`, exposing `/base64` and `/base64-decode`.
- Do not add external app integrations during the first core round.

When the round is complete, summarize changed files, tests run, results, limitations, and next suggested round.


<!-- FILE: README.md -->

# Lightweight Personal AI Workbench — Codex Implementation Pack

This package contains the implementation instructions for Codex.

Start here:

1. `AGENTS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/MILESTONES.md`
4. `docs/CODEX_ROUND_1.md`
5. `docs/CODEX_KICKOFF_PROMPT.md`

## Project in one sentence

A lightweight local AI workbench where users can set a default Agent for a chat session, invoke Agents with `@agent_id`, invoke Agent actions with `@agent_id:action`, and call stateless Commands with `/command`.

## First implementation target

Round 1 implements only:

- schemas
- manifest loading
- registries
- example manifests
- tests

No frontend, LLM calls, or external integrations are required in Round 1.
