# AI context

The [repository instructions](../AGENTS.md) own permanent constraints. Read the
smallest relevant contract below, then use the task cards to locate source and
tests before searching broadly. Contracts describe implemented behavior; active
plans describe ongoing work and do not turn proposed features into current capabilities.

## Current product

Agent Workbench provides local chat and a single-key, loopback-only
OpenAI-compatible model service. Internal and external inference share
ModelManager. Local execution uses managed llama-server or isolated Python
workers; external connections use the OpenAI-compatible protocol.
Kokoro ONNX and Windows PyTorch Audio provide offline MP3/WAV TTS through
`/v1/audio/speech`. Kokoro uses presets; English Chatterbox and multilingual
Qwen3-TTS Base use temporary references or one-request audio. Qwen accepts optional
reference transcripts. Chat playback and live capture are deferred.

Personas own identity, prompts and resource bindings; sessions own concrete model
selection, context, generation and opt-in Harness configuration. Chat combines the
current speaker's resources with session additions. Each run has one visible
reply, processing history and whole-reply actions. Built-in tools share direct
and model invocation with bounded execution and durable approvals; `/v1` forwards
tool data without executing it. Core Memory, Worldbook and Knowledge support chat.
Pet has position, dragging and task-state foundations only, with no mounted UI.

## Contracts

- [Models](contracts/models.md): profiles, lifecycle, runtimes, CUDA, storage/cache, `/v1`.
- [Chat/context](contracts/chat-context.md): Personas, sessions, Worldbook, parts, titles.
- [Harness/tools](contracts/harness-tools.md): direct calls, loops, permissions, approval.
- [Knowledge](contracts/knowledge.md): sources, indexing, hybrid retrieval and rerank.
- [Runs/streaming](contracts/runs-streaming.md): status, WS/SSE, persistence, reconciliation.
- [Settings](contracts/settings.md): strict ownership, six UI entries, Pet foundations.

HTTP schemas and validation belong to these same domain contracts. OpenAPI
generation and verification commands are in the [README](../README.md#http-contract).

## Accepted work

- [Runtime families](ai/PLAN_RUNTIME_FAMILIES.md): accepted target and remaining
  implementation work. Implemented runtime behavior is recorded in the Models contract.

## Task map

- [Runtime](ai/TASK_RUNTIME.md)
- [Knowledge](ai/TASK_KNOWLEDGE.md)
- [Memory/Worldbook](ai/TASK_MEMORY_WORLDBOOK.md)
- [Settings](ai/TASK_SETTINGS.md)
- [Frontend](ai/TASK_FRONTEND_UI.md)

## Supporting documents

- [README](../README.md): source installation, model setup, API examples and verification.
- [Run guide](../README_RUN.md): launchers and portable packaging.
- [Data layout](DATA_LAYOUT.md): storage ownership, schema revisions and maintenance.
- [Documentation maintenance](ai/DOCS_MAINTENANCE.md): English-only documentation,
  ownership and active-plan completion rules.
- [Future model services](FUTURE_MODEL_SERVICES.md): unimplemented design boundaries.
  Future Pet visuals remain undecided under [Settings](contracts/settings.md#pet-foundations).
