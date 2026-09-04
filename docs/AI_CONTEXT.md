# AI Context

This is the lightweight entry point for repository work. Read the roadmap and
the smallest relevant contract before searching source broadly.

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
