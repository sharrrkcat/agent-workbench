# Task: Runtime

Read [chat/context](../contracts/chat-context.md),
[runs/streaming](../contracts/runs-streaming.md), [models](../contracts/models.md)
and [harness/tools](../contracts/harness-tools.md).

## Source map

Paths below are under ai_workbench:

- api/deps.py assembles services; core/runtime.py coordinates input/cancellation.
- core/chat_runner.py, core/context.py and core/harness/ handle chat/tool execution.
- core/models/ owns adapters, queues, lifecycle and status; core/models/runtimes/ owns
  catalog, supervision, storage accounting and cache maintenance.
- core/stores.py, core/run_lifecycle.py and core/events.py work with db/stores.py and
  API message/tool/run/WebSocket routes for persistence and transport.

## Verification

Model tests are tests/test_phase2a_manager.py, test_phase2a_protocol.py and
test_phase2a_transport.py under tests/. Managed runtime tests are
test_phase2b_runtime.py, test_runtime_maintenance.py and test_llama_cuda.py.
Kokoro API, engine boundaries and installation use test_tts.py and test_tts_runtime.py.
Chat/Harness tests cover private snapshots, ordered approvals, active budgets,
restart handling and cancellation; test_chat_presentation.py covers partial
output and whole-reply operations. Use the full backend suite, frontend state
tests/build and documentation gates in the [README](../../README.md#verification).
That guide also owns isolated browser, CUDA and offline Kokoro smoke instructions.
