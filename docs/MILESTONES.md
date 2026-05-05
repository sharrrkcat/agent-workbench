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
