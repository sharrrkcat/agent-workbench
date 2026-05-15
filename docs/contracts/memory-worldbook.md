# Core Memory And Worldbook Contract

This contract owns Core Memory settings/injection and Worldbook storage,
matching, bindings, runtime injection, and compact metadata.

## Core Memory

Core Memory fields live in General settings. They control whether Core Memory is
enabled and the text block eligible LLM calls may receive.

Effective defaults:

- Prompt Agent main LLM calls default to Core Memory enabled when General
  settings enable it.
- Script Agent `ctx.llm.*` calls default to Core Memory disabled unless the Agent
  opts in through runtime settings/overrides.

Injection is best effort. Failures record compact warnings and do not fail the
main LLM call.

Run/message metadata may store enablement, injection state, counts, ids,
truncation, and warnings. It must not store full Core Memory text or rendered
context blocks.

## Worldbook APIs

Worldbook is Workbench-owned settings/storage, not Agent or Capability manifest
schema. Main API groups include:

- settings API for Worldbook defaults.
- Worldbooks API for worldbook records.
- entries API for entry records.
- session bindings API for Context Sources binding order.
- match-test API for diagnostics.

Deleting a worldbook deletes its entries and session bindings.

## Worldbook Fields And Activation

Worldbook entries include user-owned content plus matching and ordering fields
such as enabled state, activation mode, keyword text, regex flags, recursion
controls, case/whole-word behavior, and `sort_order`.

Activation modes:

- `always`: entry is eligible without keyword matching.
- `keyword`: entry is eligible when keyword or regex matching succeeds.

`keywords_text` is split on English commas. Each trimmed non-empty item becomes
a regex pattern; empty items are ignored. Invalid regex patterns are rejected on
save. If legacy bad data already exists, match-test and runtime matching report a
structured warning and skip that pattern instead of crashing.

Whole-word matching uses ASCII boundaries to avoid English partial-word matches
while preserving CJK substring matching. Case-sensitive and whole-word behavior
apply only to matching modes that support them. Recursion follows the
implemented Worldbook matching rules and must keep diagnostics compact.

Ordering is:

1. session binding order.
2. entry `sort_order` inside each bound worldbook.

Worldbook matching is SQLite/text/regex based and does not use Knowledge
indexes, vectors, rerankers, or FTS.

Matching scans only the current input text. It does not scan historical chat,
assistant output, command results, Knowledge snippets, or call an LLM.

## Runtime Injection

Runtime appends context blocks in this order for eligible calls:

```text
Core Memory -> Worldbook -> Retrieved Knowledge -> conversation context -> current user message
```

Injection runs for:

- Prompt Agent main LLM calls.
- opted-in Script Agent `ctx.llm.text`, `ctx.llm.json`, `ctx.llm.stream`,
  `ctx.llm.stream_to_output`, and chat-backed `ctx.llm.generate`.

Injection does not run for:

- session title generation.
- commands.
- embeddings.
- reranking.
- Knowledge query expansion.
- `/kb-search`.
- non-LLM Capability calls.
- form JSON/recipe JSON handling unless script code explicitly uses injected
  `ctx.llm.*` calls.

Direct prompt-backed `ctx.llm.generate` receives rendered Core Memory,
Worldbook, and Knowledge blocks prepended to the prompt when enabled.

## Metadata And Inspection

Metadata stores compact refs/counts/warnings only:

- enabled/disabled state.
- injection/skipped state.
- worldbook ids and entry refs.
- counts and truncation.
- warnings.

It must not store:

- full Core Memory text.
- full Worldbook entry content.
- rendered context blocks.
- full Knowledge snippets.
- vectors or search indexes.

Chat context inspection fetches current content from refs. Edited or deleted
user-owned Worldbook/Core Memory content should be reflected at inspection time
rather than read from old metadata snapshots.

## Knowledge Boundary

Core Memory and Worldbook are separate from Knowledge. Worldbook matching must
not use Knowledge indexes, vector storage, RAG retrieval, rerankers, or FTS.
Knowledge retrieval and metadata are owned by [knowledge.md](knowledge.md).
