# Task: Chat runtime

Read first:

- `../contracts/runtime-run-lifecycle.md`
- `../contracts/runtime-streaming.md`
- `../contracts/runtime-llm-resolution.md`
- `../contracts/attachments-vision.md`
- `../contracts/provider-status.md`
- `../contracts/utility-llm.md`

Likely sources: `core/runtime.py`, `core/chat_runner.py`, `core/context.py`,
`core/run_lifecycle.py`, `api/deps.py`, session/message/run routes, and WS.

The runtime has one default ChatRunner path. Waiting-run resume precedes new
messages; all prefixes remain text. Keep metadata compact, steps limited to
the generic kinds, and title generation best effort. Do not add route parsing,
dynamic registration, or hidden compatibility branches.

Run targeted runtime tests and then `uv run pytest -q`,
`uv run python -m compileall -q ai_workbench`, and `git diff --check`.
