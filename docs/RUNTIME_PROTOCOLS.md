# Runtime protocols

This index summarizes the Phase 1 runtime. Detailed contracts live under
[`contracts/`](contracts).

## Chat and runs

`Runtime` dispatches every new message to `ChatRunner`; a session
`waiting_run_id` is resumed first. Input prefixes are preserved as text.
`ContextBuilder` projects session or group-transcript messages and appends
Memory, Worldbook, Knowledge, and permitted attachment context.

Runs use `chat`/`resume` kinds and generic steps: `context`, `model`, `save`,
`approval`, and reserved `tool`. Statuses, cancellation, and event payloads
are defined in [runtime-run-lifecycle](contracts/runtime-run-lifecycle.md).

## Streaming

WebSocket `message_started`, `message_delta`, and `message_completed` events
form the visible stream. Sequence numbers are monotonic; the completed
message parts are authoritative. See [runtime-streaming](contracts/runtime-streaming.md).

## Models and services

Main LLM resolution is session profile then global default. Provider/profile
status and local resource release are read-only/best effort. Utility LLM,
Knowledge, Pet, attachments, and NetworkPolicy are explicit core services; no
directory scanning or dynamic registration occurs at startup.

## Stateless inference

The disabled-by-default localhost `/v1` service retains chat, embedding, and
vision skeletons with strict auth, size, and profile guards. Stateless calls
never create project state.

## Persistence boundaries

Messages use generic role/speaker/parts fields (`content_version=2`). Metadata
contains compact references, counts, warnings, and public ids only. SQLite
schema changes are managed by Alembic; Phase 1's prune revision is intentionally
destructive for the disposable test database.
