# Provider status and runtime resources contract

Provider and model status is a read-only diagnostic surface. It never imports
heavy model runtimes during listing and never exposes API keys or absolute
filesystem paths.

## Status

Common profile states are `READY`, `PROVIDER_UNREACHABLE`,
`MODEL_NOT_AVAILABLE`, `MODEL_MISMATCH`, `MODEL_STATUS_UNKNOWN`, and
`MODEL_NOT_LOADED`. A reachable provider with no matching model is not ready.

`/api/llm-provider-profiles/{id}/test` and `/api/llm-profiles/{id}/test`
perform explicit checks. Inventory endpoints list safe relative model refs;
they do not load weights or download files. Model files remain user-managed.

## Runtime resources

`GET /api/runtime/resources` returns a cached CPU/RAM/GPU snapshot.
`GET /api/runtime/memory` and `POST /api/runtime/free-memory` expose
best-effort local cache release for supported targets. Release never deletes
model files, indexes, sessions, settings, attachments, or other user data.

The stateless inference profile APIs retain embedding and vision model
management for future phases. Their status/listing operations are no-load and
use the same redaction rules.
