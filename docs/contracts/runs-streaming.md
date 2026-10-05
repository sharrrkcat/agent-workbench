# Runs and streaming contract

This contract owns runs, steps, persistence and reconciliation; [Chat/context](chat-context.md) owns configuration snapshots/message content and [Harness/tools](harness-tools.md) owns tools/approvals.

## Run lifecycle

Run.kind is chat or tool and stores its Agent persona_id (empty for QQ without an Agent). Statuses
are PENDING, RUNNING, CANCELLING, WAITING_FOR_USER, DONE, FAILED, CANCELLED and
INTERRUPTED. Terminal runs never return to running.

RunStep.kind is context/model/save/approval/tool; statuses are pending/running/completed/failed/skipped.
Steps have stable order, optional parent ids, timing, compact messages and structured errors.
Both locales label stable kinds, never implementation progress strings.

The optional Pet foundation selects session statuses/steps/progress without a UI, separate stream or polling.
QQ uses existing chat runs, inspection and cancellation; [Harness/tools](harness-tools.md#qq-delivery-and-queues) owns batches and delivery. Public metadata.qq_reply retains sent_count, message_limit, limit_reached and skipped during execution and termination, including partial sends before failure/cancellation.
Only normal completion at the send limit sets limit_reached=true. A legitimate follow-up skip completes with skipped=true and no delivery; ending without a confirmed reply or allowed skip fails with QQ_REPLY_REQUIRED before DONE.

ChatRunner persists messages, runs, steps and events. Run/message metadata contains public ids, counts, timings, warnings
and source refs, never prompts, full history/context, vectors, binaries or keys. Model resolution includes
source_type and provider_profile_id (null for local/unbound); local worker traces carry source_type=local.
config_snapshot_json and harness_state_json are private and absent from public
responses/events. The latter preserves pending tool execution through approval.

session.waiting_run_id blocks new input/direct calls until explicit approval,
rejection or cancellation. There is no implicit chat-resume path or resume kind.
Valid pending approvals survive restart with their original configuration,
remaining queue and active-time budget. Other unfinished runs become
INTERRUPTED and are not replayed.

Active/waiting cancellation uses one registry: record cancelled outstanding calls, settle open steps,
clear continuation/waiting references and end CANCELLED. Interruptions carry explanatory errors/status;
direct rejection/handler failure is FAILED, while model-loop tool errors may lead to a model answer.

Run reads/cancellation are `/api/runs/{id}`, `/{id}/events`, `/{id}/cancel` and
`/api/sessions/{id}/history`. Tool responses and explicit approvals are defined by
the harness contract. Direct tool runs never create model summaries or auxiliary titles;
explicit chat tool input receives the basic input title described in the chat contract.

Visible conversation items have consecutive session-local numbers starting at #1 beside their timestamps.
Each standalone message or whole reply occupies one number, including active, failed, cancelled and
direct-tool replies. Processing messages share their reply's number. Numbers follow current display
order, are computed by database counts after history mutations and are not persisted. User-message navigation uses
these same numbers while continuing to target only user messages.
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

The composer snapshots and clears text/attachments on ordinary submit, locking text until acceptance is observed. A persisted user message's client_message_id confirms acceptance through events or history; the execution response's run also confirms acceptance. Text and attachments can then be drafted and queued while the current request/run settles.
Creation, binding or unaccepted ordinary send failure restores the snapshot in the same session epoch. Accepted generation failure/cancellation and automatic queue submission never overwrite a newer draft. Session changes discard ordinary UI snapshots and release local previews; queue edits retain their own uploaded references.

Queue dispatch requires a mounted, synchronized conversation with valid configuration, completed configuration/history
saves, no active/waiting run, approval/message submission, pause or head edit. Submission reserves client_message_id
and locks the row against edit/delete; only confirmed acceptance removes it. HTTP/WS/database schemas are unchanged;
there is no backend queue. A lost POST response checks history pages back to the pre-submission boundary and the
retained active run. Unaccepted items remain paused in place; failed reconciliation retains the submission identity
and blocks retransmission. Resume queue retries reconciliation first. Run/submission identity outlives bounded history;
late responses update their original queue, and returning checks pending submissions/nonterminal runs before dispatch.
Normal completion continues FIFO; FAILED/CANCELLED/INTERRUPTED pause. Stop pauses before requesting cancellation,
including completion races. Append/edit/delete never resume implicitly. Resume queue is explicit and duplicate/stale
terminal observations cannot undo it. Enqueueing during approvals preserves the explicit approval workflow.

Clients request `next_event` at `/api/ws/{session_id}` and receive session_id, optional run_id/message_id and payload.
Global model/runtime events use `/api/models/events`, even without a selected session. Subscriptions filter before
enqueueing and retain at most 256 events / 4 MiB. Overflow closes with 1013 and releases the queue independently
of `next_event`; sends time out after five seconds. EventBus has no history. Reconnect refreshes durable state;
unsaved streaming drafts recover at completion.

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
| history_pruned | deleted_message_ids/deleted_run_ids for the session; QQ also returns deleted_qq_message_ids, deleted_qq_delivery_ids and history_version |
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

useCogitaStore composes session/message/queue/run actions; shared merges keep session/message/run/step updates atomic.
Refreshes preserve newer content/approvals. Microsecond run/step ordering prevents stale events from restoring resolved
approvals or regressing terminal status. REST direct-call/approval results share reconciliation and session isolation;
concurrent approval submission is blocked by run id. Previous-session results cannot change the visible conversation.
Session navigation tracks its target and loading/ready/error state separately from initialization;
no target is idle. Required session/history/run reads commit together before opening the WebSocket.
Connection-time reconciliation then preserves live events using the existing version checks.
Real switches increment the epoch once and reset composer/attachment/dialog state, while
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
refresh removes records absent from the window without regressing newer events.
History pages use before/after/around cursors (mutually exclusive), default 50/max 100,
ordered by created_at, kind (message before reply), id. Replies remain whole.
Responses provide numbers, boundary cursors, has_before/has_after, history_version and a compact active_run.
The UI retains at most 200 items and their associated messages/steps, preserving scroll anchors on eviction.
Automatic pagination responds to user scrolling; programmatic jumps do not load adjacent pages.
Older-history browsing updates loaded items and active status only; Latest messages or sending loads the tail.
User navigation independently reads 50 summaries via /history/users. Destructive version changes reload around the anchor.
Concurrent refreshes coalesce. /runs/{id}/events uses after, limit (default 100/max 500), items/next_cursor/has_more.

Model/runtime stores reject stale refreshes and keep newer live occupancy/job
revisions. UI state does not infer residency from a successful health check.

## Context detail

The composer places a context ring immediately left of the model selector, included in width
measurement. Its Hover Card supports hover, focus and touch (44px minimum target). It shows the
latest terminal model step's actual (prompt_tokens + completion_tokens) / effective window,
full token numbers, output reserve, input budget and removed turns. Cached and reasoning tokens
are already included in their respective counts; output reserve is not actual usage. The card omits
the latest-call subtitle and separate model, window and input rows. Totals above the effective window
use the overflow color; the ring caps at 100% while numbers retain the actual total.
During generation it retains the previous reported call and labels generation in progress. Missing
input or output usage stays unknown without substituting estimates or earlier calls; zero is valid.
New sessions and model/window
mismatches are neutral until a matching call completes. Run/step events and refresh restore the
display; pruning removes deleted calls. No polling or draft preview API is used.

Internal ordinary/Workspace/QQBot and Harness model calls save one immutable private `context_snapshot_json`
on their model step immediately before transport dispatch. Preparation failures have no snapshot;
failed/cancelled/interrupted dispatched calls retain theirs. Direct tools, auxiliary titles and `/v1`
do not record context. Reads never reconstruct missing inputs from current configuration or history.
Snapshots preserve the outbound body, source positions, exclusions, model identity, capture time and
context policy. Images use attachment-store references instead of binary data URLs. Source excerpts
and Unicode character counts are resolved on the backend; usage stays in `metadata.llm`.
Step `metadata.context` exposes availability, message/tool/image counts and a strict budget: configured
and effective window_tokens, input_budget_tokens, pre-call input_tokens, counting=native|estimated,
output_tokens, margin_tokens and removed_turns. The snapshot contains the same budget. Counts are
distinct from actual usage; public statistics contain no prompt text. Ordinary run/message
reads and events never load private snapshot columns. `GET /api/runs/{run_id}/steps/{step_id}/context`
returns strict detail data; missing snapshots or mismatched run/step ownership return CONTEXT_NOT_FOUND (404).
Snapshot validation/storage errors prevent dispatch with CONTEXT_SAVE_FAILED and sanitized text.

The Layers action sits between retry and usage, independent of recorded usage. It appears on chat replies
at terminal status or approval waiting when a snapshot exists. Its read-only modal defaults to the final
answer's call, otherwise the latest captured call; a single call has no selector. Input structure follows
send order, with system sources nested as Agent, Project, QQ runtime (QQ only), Cogita Persona and Knowledge, and tools separate. QQ runtime records that call's identity/batch/count; paired historical sends retain whole-message excerpts and a shared input turn for pruning. System groups use the label System without a request-position prefix.
Empty system sources recorded as empty/no-bindings/no-results appear muted in Agent/Project/Cogita/Knowledge order,
with an Empty label and no transmitted-message number for a synthetic system group. They do not change request data
or counts; other exclusions remain collapsed diagnostics. Ordinary chats do not invent a Project source.
Request data shows supplied generation parameters; omitted engine defaults and rendered/tokenized native
prompts are unknown. Each call loads lazily with local caching/error retry;
late results cannot replace another selection. Navigation, deletion or resumed execution closes the modal.
The 896px-wide modal is bounded to min(48rem, 100dvh - 2rem). Its title, call badges, tabs and footer stay fixed;
desktop source/content columns scroll independently. Touch stacks navigation (at most 30%) over independently scrolling
content; expanded diagnostics have a separate bounded scroll region. Both locales preserve focus and chat scroll position.
The model uses a primary Badge; message/tool counts and actual input tokens use secondary Badges on the call row.
Source rows show characters normally and approximate tokens on hover/focus; touch shows approximate tokens directly.
The count slot reserves its width from known character counts and stays right-aligned before estimates arrive.
Desktop source navigation is 17rem wide. History and current-input sources with message references
use Message #N (localized), matching the current conversation number in navigation and detail headings,
without the request-position prefix. Their labels stay on one line; attachment/citation names may wrap.
Context detail supplies current reference_numbers even outside the loaded window; multiple sources from one reply share its number. Deleted references show Deleted message; sources
without a message reference retain their category label. Tool sources retain tool labels.
Context and usage dialogs are sibling roots, so Context detail receives the standard dimmed, blurred backdrop.
An Info Hover Card beside the source name/role contains characters, approximate tokens and captured identifiers;
keyboard focus and touch press also open it. Changing the source or closing the modal dismisses it.
Approximate source counts use the bundled gpt-tokenizer o200k_base reference encoding in a lazily loaded Web Worker,
with special-token strings treated as ordinary text. Counts are cached per call/source only while the dialog is open.
They remain frontend-only, marked approximately equal and never summed or substituted for actual model usage.
Empty sources count zero; image, pending and failed estimates are unknown. Tokenization requires no model or network service.
Included attachments remain referenced by surviving snapshots. History/session/Project pruning removes
snapshots with their steps and cleans newly unreferenced attachments after commit, including snapshot-only references.

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
Each summary metric pairs an icon with its value and retains a localized screen-reader label and hover/focus tooltip.
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
REST run, step, history and stored-event responses have runtime validation and
typed lifecycle/message/delta/tool/approval payloads. Omitted fields and explicit
nulls remain distinct, and timestamps retain microseconds. Private snapshots are
absent from those types. WebSocket transport remains defined here rather than
being represented as an HTTP operation. Response validation failures produce a
sanitized 500 INTERNAL_ERROR without internal validation values.
