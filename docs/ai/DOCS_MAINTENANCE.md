# Docs Maintenance

## Single Ownership

- `docs/AI_CONTEXT.md`: Codex entry point and task routing only.
- `docs/ai/TASK_*.md`: short Codex task cards with read-first docs, likely source,
  tests, avoid notes, and doc/i18n reminders.
- `docs/EXTENSION_API.md`: Agent, Capability, Script ctx, config schema, and output
  payload core contracts, with topic links instead of long runtime copies.
- `docs/RUNTIME_PROTOCOLS.md`: runtime topic index and short protocol summaries.
- `docs/EXTENSION_ARCHITECTURE.md`: architecture principles, configuration
  ownership, and Agent/Capability split decisions.
- `README.md`: install, startup, user-level feature overview, and links to deeper
  contracts.
- `docs/contracts/`: long topic contracts with one authoritative owner per
  topic.

## Contract Ownership

- `../contracts/intent-routing.md`: Intent Routing modes, thresholds, Route Test,
  safe auto-route gates, and route metadata.
- `../contracts/knowledge.md`: Knowledge settings, local model APIs, indexing,
  retrieval, session KB bindings, context injection, and Knowledge Capability.
- `../contracts/utility-llm.md`: Utility LLM backends/APIs, title generation, and
  raw-output/metadata limits.
- `../contracts/runtime-streaming.md`: `message_delta`, `message_completed`,
  `message_updated`, public Script streaming, and frontend merge rules.
- `../contracts/runtime-run-lifecycle.md`: run/run_step statuses, default steps,
  cancellation/failure, WebSocket run events, and compact run metadata.
- `../contracts/runtime-llm-resolution.md`: main LLM resolution, Provider vs
  Model Profile runtime semantics, capability flags, badges, and unload policy.
- `../contracts/provider-status.md`: Provider/Profile status, runtime memory
  release, and runtime resources API.
- `../contracts/attachments-vision.md`: upload metadata, Prompt Agent file
  context, vision input, Script attachment helpers, and generated attachments.
- `../contracts/settings-general.md`: General settings API, categories,
  ownership boundaries, unknown field rejection, and settings/i18n ownership.
- `../contracts/memory-worldbook.md`: Core Memory and Worldbook settings, APIs,
  matching, bindings, runtime injection, and compact metadata.

## Soft Line Limits

- `docs/AI_CONTEXT.md` <= 150 lines.
- `docs/ai/TASK_*.md` <= 120 lines per file.
- `README.md` <= 350 lines.
- `docs/EXTENSION_API.md` <= 350 lines.
- `docs/EXTENSION_ARCHITECTURE.md` <= 350 lines.
- `docs/RUNTIME_PROTOCOLS.md` <= 300 lines.

## Size Check

Run:

```bash
uv run python scripts/check_docs_size.py
```

The script enforces soft line limits for `AI_CONTEXT`, task cards, `README`, and
the compact index docs. Contracts may be longer, but they must stay
single-topic and should not duplicate other contracts.

## When A Document Exceeds Its Limit

- Move detailed rules to `docs/contracts/<topic>.md`.
- Keep only a summary and link in the original document.
- Avoid copying the same rule into multiple long documents.
- Prefer one authoritative contract plus task-card pointers.
- Task-card `Read first` lists are on-demand entry points. They do not mean every
  listed file must be read in full for every task.
- Task cards must not copy full contracts. Keep source entry points, tests, key
  boundaries, and links to owning contracts.
- If content must be repeated for user-facing clarity, keep the repeat short and
  link to the owning contract.

## Codex Report Requirements

When Codex updates docs, report:

- changed docs
- line-count delta for affected long docs and task cards
- moved content summary
- source behavior changed: yes/no
- docs requiring next-round cleanup

If source behavior, API shape, settings schema, metadata, or user workflow changed,
also report the relevant tests/build commands and whether i18n was updated.
