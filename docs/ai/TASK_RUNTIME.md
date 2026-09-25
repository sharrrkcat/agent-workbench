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
- core/models/inspection.py reads SigLIP configuration; core/models/siglip.py owns prepared identity
  and the tower client; siglip_adapter.py owns the two clients and shared identity under ModelManager's queue.
  workers/siglip_catalog.py, siglip_engine.py and siglip_server.py own local files and single-tower execution.
- workers/embedding_catalog.py inspects native text metadata; embedding_engine.py/embedding_server.py provide independent Sentence Transformers execution.
- workers/reranker_catalog.py inspects CrossEncoder metadata; reranker_engine.py/reranker_server.py provide independent native pair scoring.
- workers/asr_catalog.py inspects Whisper metadata; asr_engine.py/asr_server.py provide native long-form transcription. core/models/asr_inputs.py owns request-scoped files; ModelManager.transcribe serves internal callers and the multipart public API.
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
test_text_embeddings.py/test_text_embedding_runtime.py cover metadata, prompts, scoring, migration and worker lifecycle.
scripts/smoke_text_embedding_runtime.py reuses installation for native CUDA comparison, API/Knowledge and short-text CPU acceptance.
test_rerankers.py/test_reranker_runtime.py cover metadata, scoring, API, migration, RAG and lifecycle; scripts/smoke_reranker_runtime.py owns native CUDA/Knowledge and short-text CPU acceptance.
test_siglip.py, test_siglip_runtime.py and test_siglip_service.py cover inspection, identity, engines, shared queues,
tower cleanup, public API, profiles and migration. scripts/smoke_siglip_runtime.py defaults to a short CUDA API smoke, with optional native comparison.
scripts/siglip_lifecycle.py supplies the extended --full-lifecycle matrix only for explicit user requests, outside routine tests and CI;
[Models](../contracts/models.md#siglip-image-and-text-embeddings) owns acceptance limits.
Audio references, queue admission and key/profile invalidation use test_audio.py;
test_audio_runtime.py covers locks, offline workers, isolation and TTS reference limits. test_qwen_tts.py covers Base layouts, transcripts, generation,
languages and API/reference validation. test_tts_seed.py covers seed validation, inheritance and worker RNG scope.
scripts/smoke_audio_runtime.py defaults to Chatterbox/Qwen Windows CUDA cases with TTS PCM seed comparisons.
test_asr.py/test_asr_runtime.py cover configuration, schemas, migration, full-file generation, API, cancellation and request-file cleanup; scripts/smoke_asr_runtime.py reuses installation for real CUDA long-form and focused base CPU acceptance, without model hashing.
scripts/smoke_llm_runtime.py covers real llama-server/Transformers CPU/CUDA, streaming and tools.
Chat/Harness tests cover private snapshots, ordered approvals, active budgets,
restart handling and cancellation; test_chat_presentation.py covers partial
output and whole-reply operations. Use the full backend suite, frontend state
tests/build and documentation gates in the [README](../../README.md#verification).
That guide also owns isolated browser, CUDA and offline Kokoro smoke instructions.
