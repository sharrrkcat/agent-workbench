# Codex Round 2 Task

You are continuing implementation in the private repository:

https://github.com/sharrrkcat/agent-workbench.git

Work directly on the `main` branch.

## Environment

- Python version: 3.10.11
- Keep `requires-python` compatible with Python 3.10.
- Do not use Python 3.11+ only features.
- Continue using `uv`.
- Continue using Pydantic v2.
- Keep the implementation small, explicit, and well-tested.

## Current state

Round 1 is complete.

Already implemented:

- Pydantic schema models
- manifest loader
- AgentRegistry
- CapabilityRegistry
- CommandRegistry
- example Agent manifests:
  - `agents/chat/agent.yaml`
  - `agents/translate/agent.yaml`
- example Capability manifest:
  - `capabilities/base64/capability.yaml`
- Round 1 tests pass:
  - `8 passed`

Known current limitations:

- Registries are in-memory only.
- No router.
- No runners.
- No database.
- No frontend.
- No WebSocket.
- No LLM calls.
- No script Agent execution.
- No capability method execution.

## Round 2 goal

Implement runtime state models and deterministic routing.

This round should make the core able to decide where a user input should go:

- waiting run resume
- `/command`
- `@agent`
- `@agent:action`
- plain text to session default Agent

Do not execute Agents or Commands yet. This round should parse and route requests into structured route targets.

## Required scope

Implement:

1. In-memory stores:
   - `SessionStore`
   - `MessageStore`
   - `RunStore`

2. Router parser:
   - parse `/command args`
   - parse `@agent_id args`
   - parse `@agent_id:action_id args`
   - plain text fallback

3. Deterministic router:
   - waiting run wins
   - `/command` routes to Command target
   - `@agent_id:action_id` routes to Agent action target
   - `@agent_id` routes to Agent default action
   - plain text routes to session default Agent

4. Runner skeletons:
   - `AgentRunner`
   - `CommandRunner`

The runner skeletons should not perform real execution yet. They may return structured placeholder results or route targets, but should be shaped so Round 3 can implement actual Command execution.

## Routing rules

Implement this priority order exactly:

1. If `session.waiting_run_id` is set, return a resume target for that run.
2. If input starts with `/`, parse it as a Command.
3. If input starts with `@agent_id:action_id`, parse it as an Agent action.
4. If input starts with `@agent_id`, parse it as an Agent default action.
5. Otherwise, route to `session.default_agent_id` with action `default`.

Important namespace rules:

- `/xxx` always means Command.
- `@xxx` always means Agent.
- Agents do not declare slash command aliases.
- Unknown Command should produce a structured routing error.
- Unknown Agent should produce a structured routing error.
- Unknown Agent action should produce a structured routing error.
- Plain text should fail only if the session default Agent is missing or does not have a `default` action.

## Suggested files to create or update

Create or update:

```text
ai_workbench/core/
  router.py
  runner.py
  session.py
  stores.py

ai_workbench/core/schema/
  route.py

tests/
  test_router.py
  test_stores.py
```

You may split files differently if there is a cleaner design, but keep the public concepts clear.

## Data model requirements

### Session

In-memory model or dataclass is enough for Round 2.

Required fields:

- `session_id: str`
- `title: str`
- `default_agent_id: str`
- `waiting_run_id: str | None`
- `created_at`
- `updated_at`

### Message

Required fields:

- `message_id: str`
- `session_id: str`
- `role: str`
- `content: object | str`
- `agent_id: str | None`
- `command_name: str | None`
- `action_id: str | None`
- `run_id: str | None`
- `parent_message_id: str | None`
- `created_at`

### Run

Required fields:

- `run_id: str`
- `kind: agent | command | action | resume`
- `target_id: str`
- `action_id: str | None`
- `session_id: str`
- `status`
- `current_step: str`
- `error: str | None`
- `metadata: dict`
- `created_at`
- `updated_at`

Use the existing Round 1 run schema if present. Extend rather than duplicate when practical.

## Route result model

Create a structured route result. Suggested shape:

```python
class RouteKind(str, Enum):
    RESUME = "resume"
    COMMAND = "command"
    AGENT = "agent"
    ERROR = "error"

class RouteTarget(BaseModel):
    kind: RouteKind
    session_id: str
    raw_input: str
    target_id: str | None = None
    action_id: str | None = None
    args: str = ""
    run_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
```

Expected meanings:

- Command:
  - `kind = "command"`
  - `target_id = "/base64"`
  - `args = "hello"`

- Agent:
  - `kind = "agent"`
  - `target_id = "translate"`
  - `action_id = "default"` or `"formal"`
  - `args = "hello"`

- Resume:
  - `kind = "resume"`
  - `run_id = session.waiting_run_id`
  - `args = raw user input`

- Error:
  - `kind = "error"`
  - includes `error_code` and `error_message`

## Parser behavior examples

Input:

```text
/base64 hello world
```

Expected:

```text
Command target: /base64
args: hello world
```

Input:

```text
@translate hello
```

Expected:

```text
Agent target: translate
action: default
args: hello
```

Input:

```text
@translate:formal
```

Expected:

```text
Agent target: translate
action: formal
args: ""
```

Input:

```text
@translate:formal make it more academic
```

Expected:

```text
Agent target: translate
action: formal
args: make it more academic
```

Input:

```text
hello
```

Expected:

```text
Agent target: session.default_agent_id
action: default
args: hello
```

## Identifier parsing

Use the same compatible identifier style as Round 1:

- Agent id: `[a-zA-Z][a-zA-Z0-9_-]*`
- Action id: `[a-zA-Z][a-zA-Z0-9_-]*`
- Command name: `/[a-zA-Z][a-zA-Z0-9_-]*`

Do not allow empty `/` or empty `@`.

## Store behavior

### SessionStore

Required methods:

- `create_session(default_agent_id: str = "chat", title: str = "") -> Session`
- `get_session(session_id: str) -> Session`
- `set_default_agent(session_id: str, agent_id: str) -> Session`
- `set_waiting_run(session_id: str, run_id: str | None) -> Session`
- `list_sessions() -> list[Session]`

### MessageStore

Required methods:

- `add_message(...) -> Message`
- `list_messages(session_id: str) -> list[Message]`
- optional helper: `get_message(message_id: str)`

### RunStore

Required methods:

- `create_run(kind, target_id, session_id, action_id=None, metadata=None) -> Run`
- `get_run(run_id: str) -> Run`
- `update_status(run_id: str, status, current_step=None, error=None) -> Run`
- `list_runs(session_id: str) -> list[Run]`

In Round 2 these can be in-memory. Do not introduce SQLModel unless the implementation naturally already did; database persistence is for a later round.

## Runner skeleton behavior

### AgentRunner

Implement a skeleton method:

```python
async def run(agent_id: str, action_id: str, args: str, session_id: str) -> Run
```

For Round 2:

- validate Agent exists
- validate action exists
- create a Run
- mark it as `RUNNING`, then `DONE`
- do not call LLM
- do not create real assistant output yet unless useful for tests

### CommandRunner

Implement a skeleton method:

```python
async def run(command_name: str, args: str, session_id: str) -> Run
```

For Round 2:

- validate Command exists
- create a Run
- mark it as `RUNNING`, then `DONE`
- do not execute the capability method yet

If returning placeholder runs feels too much for Round 2, prioritize parser/router tests over skeleton execution.

## Tests required

Add tests for:

1. Plain text routes to the session default Agent.
2. `/base64 hello` routes to Command target `/base64`.
3. `@translate hello` routes to Agent `translate`, action `default`.
4. `@translate:formal` routes to Agent `translate`, action `formal`.
5. `@translate:formal more formal please` preserves args.
6. Unknown Command returns structured error.
7. Unknown Agent returns structured error.
8. Unknown Agent action returns structured error.
9. `session.waiting_run_id` routes to resume before parsing `/` or `@`.
10. SessionStore can create sessions and change default Agent.
11. RunStore can create and update runs.
12. MessageStore can append and list messages.

Run all tests:

```bash
uv run pytest
```

## Documentation updates

Update `README.md` with a short Round 2 status section explaining:

- supported routing syntax
- what is implemented
- what is not implemented yet

If `AGENTS.md` needs minor correction for Python 3.10 compatibility or Round 2 behavior, update it.

## Do not implement in Round 2

Do not implement:

- LLM calls
- Base64 encode/decode execution
- FastAPI endpoints
- WebSocket
- frontend
- SQLite persistence
- Script Agent runtime
- external integrations
- model loading/unloading behavior

## Completion response format

When done, report:

- changed files
- tests run
- test results
- known limitations
- next suggested round
