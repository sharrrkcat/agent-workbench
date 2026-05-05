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
