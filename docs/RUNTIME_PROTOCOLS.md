# Runtime protocols

Phase 2a shares all model calls through core/models. Detailed contracts are in
[contracts](contracts).

## Chat and runs

Runtime dispatches ordinary text to ChatRunner and registered `/tool_name`
inputs to the shared tool executor. Pending approval blocks new input until
explicit approval, rejection or cancellation. ContextBuilder projects the session/group transcript and
injects Memory, Worldbook, Knowledge and permitted attachment context.

ChatRunner resolves session.model_profile_id, current Persona model, then the
global default and calls the shared manager. Each run snapshots the resolved
Persona privately; an explicitly selected auxiliary model may generate
a title after the main lease is released. Missing auxiliary configuration
leaves the title unchanged.

Runs use chat/tool kinds and context/model/save/approval/tool steps.
Harness details are in [harness tools](contracts/harness-tools.md).

## Models and streams

[Model resolution](contracts/runtime-llm-resolution.md) defines one profile
store, five kinds, one OpenAI-compatible external connection protocol and the
manager's bounded queue/manual-default lifecycle. Local managed runtimes use
the catalog, supervisor and worker protocol in
[managed-runtime](contracts/managed-runtime.md); API-process inference stays removed.

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

Alembic is the only schema authority. Head 0006_phase4_tools adds private
harness continuations and the tool run kind after Persona/session snapshots.
It discards disposable chat/run rows and clears waiting references without
touching non-database files. Valid new pending approvals survive application restart.
Model, attachment, runtime and other file directories are outside revision
ownership. The project has no users/user data, permits prolonged downtime and
retains no abandoned compatibility implementations.
