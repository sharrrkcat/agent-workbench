# Runtime protocols

Phase 2a shares all model calls through core/models. Detailed contracts are in
[contracts](contracts).

## Chat and runs

Runtime dispatches to ChatRunner, with waiting-run resume first. Prefixes stay
ordinary text. ContextBuilder projects the session/group transcript and
injects Memory, Worldbook, Knowledge and permitted attachment context.

ChatRunner resolves session.model_profile_id then the global default and
calls the shared manager. An explicitly selected auxiliary model may generate
a title after the main lease is released. Missing auxiliary configuration
leaves the title unchanged.

Runs retain chat/resume kinds and context/model/save/approval steps; tool is
reserved. See [run lifecycle](contracts/runtime-run-lifecycle.md).

## Models and streams

[Model resolution](contracts/runtime-llm-resolution.md) defines one profile
store, five kinds, one OpenAI-compatible external connection protocol and the
manager's bounded queue/manual-default lifecycle. Local managed runtimes are
Phase 2b; API-process inference implementations are removed.

WebSocket message_started/message_delta/message_completed share one message
id; seq increases from 1 and the completed parts are authoritative. The client
rejects duplicate/late/gapped deltas. Session refresh preserves active drafts.
Global model_status events share occupancy across aliases.
See [streaming](contracts/runtime-streaming.md) and
[status](contracts/provider-status.md).

## External protocol

The optional single-key localhost service exposes /v1/models,
/v1/chat/completions and /v1/embeddings. Chat supports SSE, function tool data,
image input and response_format according to declared capabilities. It never
executes tools or writes business rows. See
[stateless inference](contracts/stateless-inference.md).

## Persistence

Alembic is the only schema authority. Head 0003_phase2a_models recreates the
whole disposable test database without row conversion or downgrade support.
Model, attachment, runtime and other file directories are outside revision
ownership. The project has no users/user data, permits prolonged downtime and
retains no abandoned compatibility implementations.
