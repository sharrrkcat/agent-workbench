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
