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
- workers/server.py dispatches the shared ONNX control service; workers/wd14_engine.py owns tagging,
  while core/models/images.py validates/normalizes inline images before admission.
- core/stores.py, core/run_lifecycle.py and core/events.py work with db/stores.py and
  API message/tool/run/WebSocket routes for persistence and transport.

## Verification

Model tests are tests/test_phase2a_manager.py, test_phase2a_protocol.py and
test_phase2a_transport.py under tests/. Managed runtime tests are
test_phase2b_runtime.py, test_runtime_maintenance.py and test_llama_cuda.py.
test_runtime_installation.py covers fixed-file checks, explicit repair and traversal guards;
test_runtime_dependencies.py covers normalized identity, version paths, recoverable checks and application workers.
test_runtime_smoke_cli.py covers installation-only modes and device defaults.
test_provider_runtime.py covers strict sources, provider ownership, maintenance isolation,
configuration reset, installation/job preservation and the shared lock/wheel audit.
test_provider_inference.py covers optional discovery and request status. scripts/build_runtime_wheels.py
reproduces upstream patches; scripts/check_qwen_rope.py checks checkpoint buffer restoration.
Kokoro API, engine boundaries and installation use test_tts.py and test_tts_runtime.py.
test_wd14.py and test_wd14_runtime.py cover tagging schemas, preprocessing, migration, input limits,
public API, queue cancellation, crash recovery and profile/Kokoro isolation.
scripts/smoke_wd14_runtime.py requires an explicit local model and reuses installation for real CPU API acceptance.
Audio references, queue admission and key/profile invalidation use test_audio.py;
test_audio_runtime.py covers locks, offline workers, isolation, private Whisper
dispatch and its decoded-duration boundary. test_qwen_tts.py covers Base layouts, transcripts, generation,
languages and API/reference validation. test_tts_seed.py covers seed validation, inheritance and worker RNG scope.
scripts/smoke_audio_runtime.py defaults to three Windows CUDA cases with TTS PCM seed comparisons;
scripts/smoke_llm_runtime.py covers real llama-server/Transformers CPU/CUDA, streaming and tools.
Chat/Harness tests cover private snapshots, ordered approvals, active budgets,
restart handling and cancellation; test_chat_presentation.py covers partial
output and whole-reply operations. Use the full backend suite, frontend state
tests/build and documentation gates in the [README](../../README.md#verification).
That guide also owns isolated browser, CUDA and offline Kokoro smoke instructions.
