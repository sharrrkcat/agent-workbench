# Task: Chat runtime

Read first:

- `../contracts/runtime-run-lifecycle.md`
- `../contracts/runtime-streaming.md`
- `../contracts/runtime-llm-resolution.md`
- `../contracts/attachments-vision.md`
- `../contracts/provider-status.md`
- `../contracts/utility-llm.md`
- `../contracts/managed-runtime.md`
- `../contracts/harness-tools.md`

Likely sources: `core/runtime.py`, `core/chat_runner.py`, `core/context.py`,
`core/run_lifecycle.py`, `core/models/`, `api/deps.py`, session/message/run
routes, `api/routes/models.py`, `api/routes/openai_compatible.py`, and WS.

The runtime has one default ChatRunner path and an opt-in HarnessAgentLoop.
Only registered `/tool_name` inputs invoke direct tools; unknown prefixes stay
text. Waiting approvals require the explicit API and block new messages.
Keep metadata compact, steps limited to generic kinds, and titles best effort.
Do not add dynamic registration or hidden compatibility branches. Internal chat and
external inference share the manager directly. Auxiliary titles use only the
explicit model selection, after the main lease releases. Local managed
processes use core/models/runtimes and the worker-only ai_workbench/workers
package. Do not restore in-process inference. Runtime tasks have their own
store and global events; they are not chat runs.
Harness private state owns the ordered pending queue and active-time budget.
Direct, chat and approval-resumed execution must share cancellation and results.

Run targeted runtime tests and then `uv run pytest -q`,
`uv run python -m compileall -q ai_workbench`, and `git diff --check`.
