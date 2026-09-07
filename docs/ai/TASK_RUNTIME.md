# Task: Runtime

Read [chat/context](../contracts/chat-context.md),
[runs/streaming](../contracts/runs-streaming.md), [models](../contracts/models.md)
and [harness/tools](../contracts/harness-tools.md).

The explicit assembly is api/deps.py. core/runtime.py coordinates input and
cancellation; ChatRunner builds context and calls ModelManager or HarnessAgentLoop.
Only registered slash tools dispatch directly. Waiting approvals block new
input and resume solely through the explicit approval API.

core/models owns adapters, queues, lifecycle, status and managed runtime jobs.
Workers live outside the API process. Runtime jobs are not chat runs. Internal
and external callers share the manager directly; titles use only the auxiliary
selector after the main response/lease completes.

Run snapshots and continuations are private. Preserve ordered pending calls,
active-time budgets, restart handling and cancellation across chat/direct/resumed
execution. Keep public metadata compact and errors structured. RunStep kinds
remain context/model/save/approval/tool, with bilingual frontend labels.

Relevant sources include core/chat_runner.py, harness/, models/, context.py,
stores.py, run_lifecycle.py, events.py and api routes/messages/tools/runs/ws.
Tests cover models, transport, Persona snapshots and harness behavior. Run the
full backend suite, frontend state tests/build and documentation checks.
