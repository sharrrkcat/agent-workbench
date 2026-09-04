# Core Memory and Worldbook contract

Core Memory and Worldbook are deterministic context sources owned by the
workbench. ChatRunner injects them after selecting the session context and
before the model call; their contents are data, never instructions to the
runtime.

## Core Memory

`AppSettings.core_memory_enabled` controls injection of the trimmed
`core_memory_content`. Empty or disabled memory produces no context block and
records a compact skip reason. When enabled, the rendered block is wrapped in
`<core_memory>` tags and metadata includes only enabled/injected flags, length,
skip reason, and warnings.

## Worldbook

Worldbook settings live under `/api/worldbook/settings` and retain
`worldbook_enabled`, entry/context limits, case sensitivity, whole-word
matching, and recursion depth. Worldbooks and entries have explicit CRUD
routes; sessions bind an ordered list through `/api/sessions/{id}/worldbooks`.

Matching is deterministic over the current user text and configured keywords.
Only enabled entries within configured limits are rendered. Match-test is a
diagnostic operation and does not mutate a session or run.

## Context isolation

The generic context builder supports `single_assistant` and
`group_transcript` session modes plus recent/current/selected projections.
Speaker metadata is retained for transcript labeling. Memory, Worldbook,
Knowledge, and attachments are injected as separate data blocks; no extension
metadata or routing decision is accepted by the builder.
