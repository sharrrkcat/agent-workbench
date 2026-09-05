# AI Context

This is the lightweight entry point for repository work. Read the roadmap and
the smallest relevant contract before searching source broadly.

Phase 2a is complete (2026-09-05); the next implementation phase is 2b.
Current schema head: `0003_phase2a_models`. See the roadmap implementation
record for changed modules, verification and the managed-runtime boundary.

## Fixed Refactor Constraints

The project is in testing with no users or user data. Long service outages are
acceptable; do not add keepalive measures. Delete abandoned structures without
legacy implementations, backward compatibility, fallback configuration, dual
writes, data migration, or preserving previous habits. These constraints apply
throughout the refactor. Alembic may recreate disposable SQLite data, including
sessions, settings, Knowledge and Worldbook; it must not delete model files,
attachments, runtimes, or other data directories.

Phase 2a unifies inference under `core/models` with only OpenAI-compatible
external connections. Local in-process inference is removed; managed backends
arrive in Phase 2b. Model release defaults to manual. Titles use only the
explicitly selected auxiliary model and stay unchanged on absence or failure.

## Task map

- [Runtime](ai/TASK_RUNTIME.md): ChatRunner, runs, streaming, attachments,
  provider status, and model lifecycle.
- [Knowledge](ai/TASK_KNOWLEDGE.md): indexing, hybrid retrieval, bindings, and
  context injection.
- [Memory/Worldbook](ai/TASK_MEMORY_WORLDBOOK.md): deterministic context stores
  and matching.
- [Settings](ai/TASK_SETTINGS.md): General, Models, Pet, and strict schemas.
- [Frontend](ai/TASK_FRONTEND_UI.md): components, stores, i18n, and client
  contracts.

Deleted extension task cards are not execution guides. There is no manifest,
registry, route parser, or script SDK to modify.

## Contract index

- `contracts/runtime-run-lifecycle.md`
- `contracts/runtime-streaming.md`
- `contracts/runtime-llm-resolution.md`
- `contracts/provider-status.md`
- `contracts/attachments-vision.md`
- `contracts/knowledge.md`
- `contracts/memory-worldbook.md`
- `contracts/settings-general.md`
- `contracts/pet.md`
- `contracts/message-parts.md`
- `contracts/utility-llm.md`
- `contracts/stateless-inference.md`

Interface, protocol, settings, metadata, or workflow changes update the owning
contract in the same change. User-visible text changes update both locales.
Run `uv run python scripts/check_docs_size.py` when changing documentation.
