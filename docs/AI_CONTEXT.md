# AI context

Read the [roadmap](WORKBENCH_REFACTOR_ROADMAP.md), then the smallest relevant
contract before searching source broadly. Phases 0-5 are complete. Schema head
is `0007_phase5_cleanup`; final verification is recorded in the roadmap.

## Fixed constraints

This project is in testing with no users or user data. Prolonged downtime is
acceptable. Delete abandoned code directly: no compatibility layers, legacy
implementations, configuration fallbacks, dual writes or data conversions.
Alembic alone owns schema revisions. SQLite test records may be reset, but
revisions never delete models, runtimes, attachments or other file directories.
See [data layout](DATA_LAYOUT.md) for the Phase 5 settings reset.

All inference uses core/models. External connections speak only the
OpenAI-compatible protocol. Local inference runs in managed llama-server or
isolated Python workers, not the API process. Model weights are placed manually.
Model release defaults to manual. Auxiliary titles use only the explicitly
selected model; absence or failure leaves the title unchanged. Reranker remains
a model kind and RAG operation; preserving RRF order on failure is intentional.

Personas are database prompt data. Harness is opt-in with explicit built-in
tools, bounded loops and durable approvals. Unknown prefixes are plain text.
There is no Agent/Action/Capability/Command registry, YAML execution, intent
router, script SDK, image generation or model downloader to extend.

## Contracts

- [Models](contracts/models.md): profiles, adapters, lifecycle, runtimes, `/v1`.
- [Chat/context](contracts/chat-context.md): Personas, sessions, context, parts, titles.
- [Harness/tools](contracts/harness-tools.md): direct calls, loops, permissions, approval.
- [Knowledge](contracts/knowledge.md): sources, indexing, hybrid retrieval and rerank.
- [Runs/streaming](contracts/runs-streaming.md): status, events, persistence, reconciliation.
- [Settings](contracts/settings.md): strict ownership, seven UI entries, Pet.

## Task map

- [Runtime](ai/TASK_RUNTIME.md)
- [Knowledge](ai/TASK_KNOWLEDGE.md)
- [Memory/Worldbook](ai/TASK_MEMORY_WORLDBOOK.md)
- [Settings](ai/TASK_SETTINGS.md)
- [Frontend](ai/TASK_FRONTEND_UI.md)

Interface/workflow changes update the owning contract. UI text changes update
both locales. Run backend tests, frontend tests/build and
`uv run python scripts/check_docs_size.py` for every implementation round.
Verification commands and startup examples are in the [README](../README.md).
Future work is limited to the short [model service records](FUTURE_MODEL_SERVICES.md).
