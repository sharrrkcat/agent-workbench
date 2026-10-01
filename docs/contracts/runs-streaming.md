# Runs and streaming contract

This contract owns run status, steps, persistence and transport reconciliation.
[Chat/context](chat-context.md) owns Project/Agent/Cogita Persona configuration snapshots and message content;
[harness/tools](harness-tools.md) owns tool execution and approval rules.

## Run lifecycle

Run.kind is chat or tool and each run stores its selected Agent persona_id. Statuses
are PENDING, RUNNING, CANCELLING, WAITING_FOR_USER, DONE, FAILED, CANCELLED and
INTERRUPTED. Terminal runs never return to running.

RunStep.kind is context/model/save/approval/tool. Step statuses are
pending/running/completed/failed/skipped. Steps have stable order, optional
parent ids, timing, compact messages and structured errors. UI labels come
from stable kinds and both locales, never implementation progress strings.

The optional Pet foundation consumes these same statuses, step kinds and
progress fields through a pure current-session frontend selector. No Pet UI,
animation vocabulary, separate task stream or polling participates in execution.

ChatRunner persists user messages, runs, steps, assistant/tool messages and
events. Run/message metadata contains public ids, counts, timings, warnings
and source refs, never prompts, full history/context, vectors, binaries or keys. Model resolution includes
source_type and provider_profile_id (null for local/unbound); local worker traces carry source_type=local.
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
the harness contract. Direct tool runs never create model summaries or auxiliary titles;
explicit chat tool input receives the basic input title described in the chat contract.

The chat view presents each run inside its reply, without a separate footer
RunPanel or context/model/save step list. Elapsed seconds use started_at (or
created_at) through finished_at, including approval waits; active clocks update
locally and terminal clocks freeze. General show_full_processing controls initial
active expansion. User toggles survive incoming deltas; entering a terminal state
collapses the outer history, and reopened conversations start terminal histories
collapsed. Final answers and approval controls stay outside that history.
User message metadata.request_warnings contains run_id and deduplicated images_ignored/images_require_text/tools_ignored codes. Chat emits message_updated on change, including clearing prior warnings on retry. Warnings render as localized warning-colored text below the current user bubble, survive refresh, and never enter model context; historical messages are not rewritten.
History and tool details use controlled Base UI Collapsible sections; replacing
their controls does not reset user expansion during streaming. Shared control
and overlay behavior belongs to [Settings](settings.md#frontend-styling-foundation).
Disclosure arrows follow labels: the processing clock arrow stays visible; command
group/item arrows appear on hover or keyboard focus and stay visible on touch.
The elapsed label aligns with the reply content's left edge. The processing header
has no cancel button; cancellation remains available in the composer.
Reasoning previews show one line of plain text extracted from Markdown, merging
whitespace and retaining code text and link labels. Streaming previews follow the
tail with a left ellipsis when overflowing; completed previews show the beginning
with a right ellipsis. Text that fits has no ellipsis and cannot be expanded.
A later part, message completion
or terminal run resets that preview to its beginning and collapses manual expansion.
Reasoning places an icon-only expand/collapse control beside the first preview line,
without a separate heading or arrow. Incoming deltas preserve manual
expansion, which renders the full Markdown. Text and width changes remeasure
horizontal overflow, and reopened histories start compact.
MessageScroller follows streamed content near the bottom and yields when the user
reads earlier messages. Disclosures use registered header anchors to retain the
reading position. Returning to the bottom, choosing Latest messages or sending
input resumes following. Each session gets a fresh scroller opened at its latest
content. The fixed shell and responsive layout belong to
[Settings](settings.md#frontend-styling-foundation).

## WebSocket events

Session clients connect to `/api/ws/{session_id}`, request `next_event`, and
receive events with session_id and optional run_id/message_id plus payload.
Global model/runtime events use `/api/models/events`, including without a selected chat session.

| Event | Meaning |
| --- | --- |
| session_updated | Session configuration/title or refreshed inherited Project/Persona/model settings |
| persona_updated/persona_deleted | Current persona in payload.persona, or removed payload.persona_id; includes historical referencing sessions |
| message_updated | Persisted user message or metadata |
| message_started | Assistant draft with stable ids |
| message_delta | part_id, part_type=text/reasoning, delta and seq=1,2,... |
| message_completed | Authoritative final persisted message |
| run_started/completed/failed/cancelled | Public run lifecycle |
| run_step_created/updated | Stable step progress |
| tool_call_created/tool_result_created | Persisted tool messages |
| approval_requested/resolved | Current public run and call identity |
| history_pruned | deleted_message_ids/deleted_run_ids for the session |
| model_status | Global model profile id and status |
| runtime_job_updated/runtime_status | Global runtime progress/status |

Approval requests include arguments, risk and step id. Global events have an
empty session_id, create no business rows and share alias occupancy. Models
subscriptions remain active without a session and across settings navigation.
Runtime jobs use their own store, not chat runs.
Workspace reads and new runs resolve current defaults; existing run context/model snapshots remain fixed.
The Harness contract owns live Project tool revocation, including resumed approvals.
The same global runtime_job_updated event carries cache_prune/cache_clean jobs,
including version=null and optional before/after accounting; jobs carry no provider reference.
Installation events describe the single local runtime. Cache maintenance never
emits an installation-state update. Local Runtime details refresh
storage when a newer terminal maintenance job arrives, without periodic polling.

## Client reconciliation

Chat loading and socket connection/reconnection refresh the Persona list. Identity events
update the shared Persona store; changes received during list reads win over stale responses.
Loading/failure preserves known identities and never implies deletion; errors use the existing banner.

messageStream tracks one sequence per message across text and reasoning parts,
ignores duplicates/late/gapped deltas, and replaces drafts with completed parts.
Part ids remain stable and cannot change type. Gaps are repaired by completion or
authoritative refresh. Tool events merge by message id, including repeated
completion of an assistant tool-call message. Controlled cancellation and caught
failure first publish a persisted message_completed with metadata.incomplete=true
for any received output. Terminal handling discards only unsaved transient drafts,
preserving these incomplete messages and tool results. User-requested cancellation
returns the cancelled run through REST, without an HTTP failure; external task
shutdown still propagates cancellation.

useCogitaStore composes session, message and run actions into one Zustand
store. Shared merge functions preserve atomic session/message/run/step updates.
Refreshes begun before newer events cannot overwrite live content or approvals.
Run/step timestamps retain microsecond ordering; old events cannot restore a
resolved approval or regress terminal status. REST direct-call/approval results
use the same reconciliation and session isolation. Concurrent approval submission
is blocked by run id. Session switches reject previous-session results.
Session navigation tracks its target and loading/ready/error state separately from initialization;
no target is idle. Required session/history/run reads commit together before opening the WebSocket.
Connection-time reconciliation then preserves live events using the existing version checks.
Real switches increment the epoch once and reset composer/context/attachment/dialog state, while
only the message scroller remounts. Explicit failed-load retry preserves the epoch; repeated target
selection is a no-op. Background refresh retains content and never re-enters navigation loading.
Draft promotion retains the composer epoch, uploaded attachments and submission lock.
It starts the session WebSocket and replaces the draft route without resetting input.
First-send creation/binding/message requests retain their original configuration and
target; delayed responses may update the list but cannot select over later navigation.

Whole-reply/user history operations atomically remove messages, runs, steps and
events. REST pruning responses and history_pruned share a frontend reducer.
Deleted ids block late messages, steps, runs and REST results; session epochs
reject requests from earlier visits even after switching back. Authoritative
refresh removes records absent from the server without regressing newer events.

Model/runtime stores reject stale refreshes and keep newer live occupancy/job
revisions. UI state does not infer residency from a successful health check.

## LLM statistics

Each attempted model call saves one typed `metadata.llm` snapshot on its model step, including model/profile and assistant message ids,
UTC start/first-response times, completion state, usage and timing. Ordinary chat and Harness use the same ModelManager collector.
Snapshots survive completed, failed and controlled-cancelled calls, including calls without a saved assistant message. Existing step events/REST
carry them; messages and runs do not duplicate counts. Approval restoration reuses saved steps. Hard interruption preserves only saved snapshots.
Input tokens include the complete request; output may include reasoning/tools. Cached input and reasoning output are subsets, never added twice.
Unknown counts remain null; total is derived only when both input/output counts are known. Embedding accounting is separate.
Call first response measures manager entry to the first nonempty content/reasoning/tool name or arguments, before text normalization.
Role, tool id and empty frames do not qualify. Non-streaming has no observed first response. Call total includes preparation, source queue and local
loading through upstream completion, excluding post-call release. Queue/load are only locally observed; provider load time is unknown.
Durations use a monotonic clock. Native speed uses `timings.predicted_n/predicted_ms`; estimated speed uses final output tokens divided by
first-output-to-finish duration. Estimation needs two output chunks and a successful stop/tool finish; length/filter/cancel/truncation cannot estimate.
Replies sum all model-call usage, excluding auxiliary titles. Speed uses summed generation tokens/time, never averaged rates or tool/approval time.
Missing/incomplete call counts mark known totals incomplete and suppress aggregate speed. A mix including estimates remains labelled estimated.
Reply first response starts at Run start; reply total retains the whole Run clock including tools/approval waits. Neither clock measures client rendering.
At terminal status or approval waiting, input/output, first response and speed follow the reply action buttons.
The usage icon opens a controlled modal with aggregate total time, call count and per-call counts, cache/reasoning, timing and source.
The modal omits explanatory prose, includes Model calls in the summary grid, and separates individual calls with horizontal rules.
It scrolls within the viewport and returns focus to its trigger without moving the message list.
Approval statistics are labelled So far; failed/cancelled statistics are incomplete. During active generation only the existing Run clock updates.
User messages, direct tool runs and histories without recorded statistics do not receive invented LLM metrics. Both locales and narrow layouts are supported.
Qwen3.5-0.8B GGUF/Transformers statistics have Windows CPU/CUDA acceptance. GGUF reports native speed/cache hits; Transformers reports streaming estimates without cache/reasoning breakdowns.

## Persistence

Final messages use content_version=2 and validated parts. Deltas are transport-only
unless persist_streaming_message_deltas is enabled for local debugging. Steps,
errors, warnings, final messages and lifecycle events persist. Terminal status
is authoritative over partial drafts. Alembic owns schema revisions; see
[data layout](../DATA_LAYOUT.md).

Caught failure and controlled cancellation persist accumulated reasoning/text,
independently of the debug delta-persistence setting. Hard process interruption
can retain only already-persisted content. Accumulated parts use JSON storage
and content_version=2; there is no checkpoint for every streaming token.

## External SSE

The [models contract](models.md#external-inference-api) owns `/v1` request,
authentication, visibility and statelessness rules. External chat supports SSE
without invoking internal harness execution.

One public id, created timestamp and alias persist across all chunks. Content/tool fragments are followed by one finish reason,
then at most one `choices: []` statistics tail and exactly one `data: [DONE]`. `stream_options.include_usage` selects usage;
`cogita.include_metrics` independently selects cogita_metrics. Upstream same-frame/separate usage snapshots replace rather than accumulate.
Non-tail usage is null when requested, otherwise omitted. Missing tail usage is null. Failures emit no successful statistics tail.
Local image validation/normalization, request-size checks, source admission and loading precede response headers;
providers never perform discovery preflights. Later inference/queue
failures emit an explicit SSE error and DONE. Disconnects close upstream
streams and release model occupancy. Invalid choices, malformed upstream chunks
and truncated streams are errors, never silently successful empty responses.
Access logs record the final outcome after the complete response ends.

OpenAPI describes the chat 200 response as either JSON or text/event-stream.
The SSE body remains text, with fixed chunk, usage, failure and DONE examples;
x-event-schemas references the generated chunk/error models for frame validation.
REST run, step, timeline and stored-event responses have runtime validation and
typed lifecycle/message/delta/tool/approval payloads. Omitted fields and explicit
nulls remain distinct, and timestamps retain microseconds. Private snapshots are
absent from those types. WebSocket transport remains defined here rather than
being represented as an HTTP operation. Response validation failures produce a
sanitized 500 INTERNAL_ERROR without internal validation values.
