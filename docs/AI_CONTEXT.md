# AI context

Read the [current plan](WORKBENCH_SIMPLIFICATION_PLAN.md), then the smallest
relevant contract before searching source broadly. Phases 0-5 are complete;
the [historical roadmap](WORKBENCH_REFACTOR_ROADMAP.md) records that baseline.
The new plan supersedes its Persona, session-binding and Pet decisions.
Schema head is `0010_runtime_maintenance`. The current
[runtime maintenance plan](RUNTIME_MAINTENANCE_PLAN.md) adds storage accounting,
manual cache cleanup and Windows llama CUDA; its verification is recorded there.
The independent [conversation presentation plan](CHAT_PRESENTATION_PLAN.md)
adds one visible reply per run, collapsible processing and whole-reply actions.
Its verification is recorded separately from the completed roadmap.

## Fixed constraints

This project is in testing with no users or user data. Prolonged downtime is
acceptable. Delete abandoned code directly: no compatibility layers, legacy
implementations, configuration fallbacks, dual writes or data conversions.
Alembic alone owns schema revisions. SQLite test records may be reset, but
revisions never delete models, runtimes, attachments or other file directories.
See [data layout](DATA_LAYOUT.md) for the chat and application-settings resets.

All inference uses core/models. External connections speak only the
OpenAI-compatible protocol. Local inference runs in managed llama-server or
isolated Python workers, not the API process. Model weights are placed manually.
Model release defaults to manual. Auxiliary titles use only the explicitly
selected model; absence or failure leaves the title unchanged. Reranker remains
a model kind and RAG operation; preserving RRF order on failure is intentional.

Personas own identity, prompts and resource bindings. Session settings own
model selection, context, generation and Harness. Nonempty Persona prompts are
always included. New sessions save the enabled global-default LLM or the first
enabled LLM; later default changes do not replace a session's selection.
Resources combine the current speaker's bindings with session
additions. Harness is opt-in with explicit built-in tools, bounded loops and
durable approvals. New sessions allow all registered tools. Unknown prefixes are plain text.
There is no Agent/Action/Capability/Command registry, YAML execution, intent
router, script SDK, image generation or model downloader to extend.
The Codex Pet UI and package flows are removed. Only position settings,
dimension-independent dragging and task-state foundations remain for a future Pet.

## Contracts

- [Models](contracts/models.md): profiles, adapters, lifecycle, runtimes, `/v1`.
- [Chat/context](contracts/chat-context.md): Personas, sessions, context, parts, titles.
- [Harness/tools](contracts/harness-tools.md): direct calls, loops, permissions, approval.
- [Knowledge](contracts/knowledge.md): sources, indexing, hybrid retrieval and rerank.
- [Runs/streaming](contracts/runs-streaming.md): status, events, persistence, reconciliation.
- [Settings](contracts/settings.md): strict ownership, six UI entries, Pet foundations.

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
Deferred work is recorded in [model services](FUTURE_MODEL_SERVICES.md) and the
new plan's future Pet boundary.
