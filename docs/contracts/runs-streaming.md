# Runs and streaming contract

This contract owns run status, steps, persistence and transport reconciliation.
[Chat/context](chat-context.md) owns configuration snapshots and message content;
[harness/tools](harness-tools.md) owns tool execution and approval rules.

## Run lifecycle

Run.kind is chat or tool and each run stores its selected persona_id. Statuses
are PENDING, RUNNING, CANCELLING, WAITING_FOR_USER, DONE, FAILED, CANCELLED and
INTERRUPTED. Terminal runs never return to running.

RunStep.kind is context/model/save/approval/tool. Step statuses are
pending/running/completed/failed/skipped. Steps have stable order, optional
parent ids, timing, compact messages and structured errors. UI labels come
from stable kinds and both locales, never implementation progress strings.

ChatRunner persists user messages, runs, steps, assistant/tool messages and
events. Run/message metadata contains public ids, counts, timings, warnings
and source refs, never prompts, full history/context, vectors, binaries or keys.
config_snapshot_json and harness_state_json are private and absent from public
responses/events. The latter preserves pending tool execution through approval.

session.waiting_run_id blocks new input/direct calls until explicit approval,
rejection or cancellation. There is no implicit chat-resume path or resume kind.
Valid pending approvals survive restart with their original configuration,
remaining queue and active-time budget. Other unfinished runs become
INTERRUPTED and are not replayed.

Active/waiting cancellation shares one active-run registry. It records cancelled
results for outstanding calls, settles open steps, clears private continuation
and waiting references, and ends as CANCELLED. Interrupted execution carries
an explanatory error/status. Direct rejection/handler failure is FAILED;
model-loop tool errors may be followed by a model answer.

Run reads/cancellation are `/api/runs/{id}`, `/{id}/events`, `/{id}/cancel` and
`/api/sessions/{id}/runs`. Tool responses and explicit approvals are defined by
the harness contract. Direct tool runs never create model summaries or titles.

## WebSocket events

Session clients connect to `/api/ws/{session_id}`, request `next_event`, and
receive events with session_id and optional run_id/message_id plus payload.
Global model/runtime events are also available without a selected chat session.

| Event | Meaning |
| --- | --- |
| session_updated | Persisted session configuration/title |
| message_updated | Persisted user message or metadata |
| message_started | Assistant draft with stable ids |
| message_delta | Incremental text and seq=1,2,... |
| message_completed | Authoritative final persisted message |
| run_started/completed/failed/cancelled | Public run lifecycle |
| run_step_created/updated | Stable step progress |
| tool_call_created/tool_result_created | Persisted tool messages |
| approval_requested/resolved | Current public run and call identity |
| model_status | Global model profile id and status |
| runtime_job_updated/runtime_status | Global runtime progress/status |

Approval requests include arguments, risk and step id. Global events have an
empty session_id, create no business rows and share alias occupancy. Models
subscriptions remain active without a session and across settings navigation.
Runtime jobs use their own store, not chat runs.

## Client reconciliation

messageStream tracks sequence numbers, ignores duplicates/late/gapped deltas,
and replaces drafts with completed parts. Gaps are repaired by completion or
authoritative refresh. Tool events merge by message id, including repeated
completion of an assistant tool-call message. Failure/cancellation discards
transient streaming drafts while preserving persisted tool results.

useWorkbenchStore composes session, message and run actions into one Zustand
store. Shared merge functions preserve atomic session/message/run/step updates.
Refreshes begun before newer events cannot overwrite live content or approvals.
Run/step timestamps retain microsecond ordering; old events cannot restore a
resolved approval or regress terminal status. REST direct-call/approval results
use the same reconciliation and session isolation. Concurrent approval submission
is blocked by run id. Session switches reject previous-session results.

Model/runtime stores reject stale refreshes and keep newer live occupancy/job
revisions. UI state does not infer residency from a successful health check.

## Persistence

Final messages use content_version=2 and validated parts. Deltas are transport-only
unless persist_streaming_message_deltas is enabled for local debugging. Steps,
errors, warnings, final messages and lifecycle events persist. Terminal status
is authoritative over partial drafts. Alembic owns schema revisions; see
[data layout](../DATA_LAYOUT.md).

## External SSE

The [models contract](models.md#external-inference-api) owns `/v1` request,
authentication, visibility and statelessness rules. External chat supports SSE
without invoking internal harness execution.

One public id, created timestamp and alias persist across all chunks. Content
and tool-call fragments are followed by one finish reason, optional usage when
stream_options.include_usage=true, and exactly one `data: [DONE]`.
Backend/load checks happen before response headers. Later inference/queue
failures emit an explicit SSE error and DONE. Disconnects close upstream
streams and release model occupancy. Invalid choices, malformed upstream chunks
and truncated streams are errors, never silently successful empty responses.
Access logs record the final outcome after the complete response ends.
