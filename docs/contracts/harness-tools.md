# Harness and tools contract

Harness execution uses effective `harness_enabled` and `tools_allowed`. Ordinary
sessions default off with all general-purpose tools; explicit [] disables every tool.
Workspace sessions inherit Project defaults and may override them; Persona owns neither field.
Changing Harness enablement preserves the list, and new registry entries do
not rewrite existing lists. The composer's model menu toggles Harness immediately, displays on/off text and keeps the menu open; failure preserves confirmed state.
Its independent settings action opens a right Sheet with fade/slide transitions in both directions for catalog-backed session tool selection. Changes require Save; unsaved closing confirms discard, and failed saves retain edits. The Sheet is full-width on mobile and restores focus to the model trigger on close.
Session settings no longer edit or submit Harness/allowlists. Workspace inheritance and per-field resets for both fields live in the Sheet; reset submits null. Draft edits remain local until first send. Session changes close the menu/Sheet and ignore late saves. Global search settings remain separate.
Workspace tools are intersected with the Project allowlist; forbidden override submissions return 422.
A Project's Harness boolean is a default, so a session may enable it independently.
Each model round and queued call, including approval resumption, rechecks the current
Project tool ceiling. Revoked calls produce TOOL_NOT_ALLOWED without running their handler;
already executing handlers continue. Expanding the ceiling does not expand a running snapshot.
Timeline Projects expose no Harness or direct execution path.
Ordinary chat sends no tools
and rejects unexpected calls with `UNEXPECTED_TOOL_CALL`. An enabled harness
with an empty allowlist uses ordinary chat. Before the first model round, explicit local lack of tool support (unless its request_options skip is enabled) falls back to ordinary chat without sending or executing tools. The current user message gets a tools_ignored warning; saved Harness/allowlist settings do not change. Unknown support and providers pass through. Direct tool execution is independent of model checks. Public native-tool requests and incompatible approval continuations fail with UNSUPPORTED_CAPABILITY; existing tool results are never discarded to restart ordinary chat.

## Registry and tools

The registry contains only explicitly registered built-in Python tools. It
does not load manifests, plugin directories or dynamic modules. Each ToolSpec
has a lower snake_case name (at most 64 characters), description, Draft 2020-12
object schema, handler, risk, requires_approval and direct_callable.
Session allowlists are unique and reference registered names.
General-purpose built-ins support model and direct invocation through the same handler,
schema, permissions, approval and persistence paths. MCP clients and ComfyUI
tools are outside the current catalog and require separate design decisions.

Arguments and results must be finite JSON data. Duplicate object keys in
model arguments, multi-parameter slash calls and tool REST bodies are rejected.
Schema, allowlist and handler errors become structured tool results in the
model loop. Invalid direct requests fail before creating a run.

| Tool | Parameters | Approval |
| --- | --- | --- |
| read_file | path, max_bytes? | Every call |
| web_search | query, limit? | Every call |
| fetch_url | url, max_chars? | Every call |
| knowledge_search | query, knowledge_base_ids?, top_k?, max_context_chars? | Automatic |
| base64_encode / base64_decode | value | Automatic |
| qq_send_message | text (1..4000 characters, nonblank) | Automatic, QQBot model runs only |
| qq_send_image | asset_id (strict positive integer from this batch’s candidates) | Automatic, QQBot model runs only |
| qq_generate_image | prompt (1..32000 characters, nonblank) | Automatic, configured QQBot batches with an input keyword only |
| qq_skip_reply | Empty object | Automatic, unanswered QQ group follow-up/icebreaker runs only |

File paths are relative to the application root and restricted to `data/knowledge`
and `data/attachments`. Absolute paths, traversal, Windows alternate streams
and symlink/junction escapes are rejected. Reads are bounded to 200,000 bytes;
the result exposes a relative path, text, size and truncation flag.
Projects share these directories and the existing per-call approval; there is no Project filesystem sandbox.

Network tools accept public HTTP(S) URLs without credentials. Every DNS answer
and redirect target is checked. HTTP connects to a validated address while
retaining the original Host and TLS server name, preventing a second DNS
resolution from bypassing the policy. Environment proxies are disabled.
There are at most three redirects and a 1 MiB response limit, enforced during
streaming even without Content-Length. Requests ask for identity encoding;
compressed responses are rejected to keep decoding bounded. Only text content
is fetched, with an additional 200,000 character output limit.

Web search calls a configured SearXNG JSON service. Missing configuration
returns `TOOL_NOT_CONFIGURED`; malformed results return `NETWORK_INVALID_JSON`.
The service URL is snapshotted at run creation and shown in the approval step.
Changing settings while waiting affects later runs. Knowledge search accepts
only subsets of the run's resolved session bindings, including an explicit
empty subset. Codec input and output are each capped at 1 MiB and decoded
bytes must be valid UTF-8.

## QQ delivery and queues

The application owns one OneBot v11 WebSocket connection per enabled QQBot Project, with external NapCat installation/login.
Identity verification precedes ingestion. Transport reconnects automatically; status distinguishes authentication,
account mismatch and connection failure without exposing tokens. Wire messages are at most 1 MiB with a bounded receive queue.
Malformed bound messages are ignored with a content-free diagnostic. Duplicate external ids within a bound conversation
are ignored without resetting debounce. Bot echoes never enter batches; known external ids mark confirmed delivery records echoed.

QQ runs always enable Harness. Batches expose qq_send_message, qq_send_image when favorite candidates exist, and qq_generate_image when the snapshotted generation permission allows it; unanswered follow-up and icebreaker batches also expose qq_skip_reply.
QQ tools are absent from the general catalog/default selections, reject ordinary/Workspace allowlists and direct calls,
and require server-owned session, active batch/run and tool-call ids. The destination comes solely from the immutable Session binding.
One text send delivers one plain-text OneBot segment; CQ-looking content remains literal. Image tools send one separate OneBot image segment with base64 bytes, using only the immutable destination binding.
Every batch's first model call uses tool_choice=required; subsequent calls use auto. Model requests and queued execution share the same tool permissions.
Each call appends one qq_runtime system block: snapshotted target/bot identity, batch id/trigger kind and live confirmed-send count/limit.
It distinguishes mandatory replies, optional follow-ups and optional quiet-group icebreakers, excludes historical sends from the count and treats transcript names/text as data. Icebreakers naturally continue the topic without announcing a rescue or demanding engagement. Project prompts remain separate.
Successful qq_skip_reply immediately completes the run/batch without sending, another model call or a pause, recording metadata.qq_reply.skipped=true.
Skip expires only submitted participants whose current keyword epoch matches this batch's snapshot; newer keywords are protected.
Existing windows and queued batches remain valid. Each confirmed follow-up send renews only this batch's submitted participants to max(current expiry, confirmation time + 45 seconds), even after expiry; later failures retain that renewal. Keyword/private sends do not renew eligibility.
Confirmed icebreaker text/image sends grant their snapshotted lone speaker eligibility until max(current expiry, confirmation time + 60 seconds), in the same transaction as delivery confirmation. Grant sources use the submitted message id; newer sources and existing windows are preserved. Pending nickname decisions retain pre-confirmation eligibility for already-received messages. Skips, failures, unknown results and pre-send cancellation grant nothing; repeated receipts and restart never extend an existing grant.
Calls execute in order: a successful skip rejects remaining calls with QQ_REPLY_SKIPPED; a confirmed send removes skip and later skip calls receive TOOL_NOT_ALLOWED without expiring participants. Invalid arguments or a disallowed skip do not satisfy the reply decision.
Unsupported tools fail without ordinary-chat fallback. Final model prose remains internal. Ending without a confirmed send
or a legitimate skip fails the run/batch with QQ_REPLY_REQUIRED and pauses the Session. Provider rejection/ignored tool choice is not retried or downgraded.

The Project reply_message_limit defaults to 4 (strict integer, 1..20), distinct from the incoming batch limit.
Execution snapshots it with the configuration. Only confirmed qq_send_message/qq_send_image/qq_generate_image results increment the run's
private qq_sent_count; failed/unknown sends, validation errors and other tools do not count. Reaching the limit
completes the run and batch without pausing or another model call. Remaining calls already emitted by the model
receive rejected results with QQ_REPLY_LIMIT_REACHED and skipped steps, without creating delivery intents.
Icebreaker execution overrides its run snapshot's reply limit to 1, shared by text, favorite images and generated images. Skipping changes no participant eligibility; normal follow-up skip and renewal rules remain unchanged. Cooldown starts after context preparation when entering model inference. Queue/preparation cancellation consumes no cooldown; skips, later cancellation and failures retain it.
Cancellation, delivery errors and existing Harness limits retain precedence. Counts reset for each new batch.

Every expired debounce window creates a SQLite FIFO batch with fixed trigger policy, including during inference or pause.
Messages are reserved once. Execution is serialized across each Project, loading only the next unpaused Session's batch.
Project configuration resolves when execution starts, before asynchronous media waits/member lookup, then follows the immutable run snapshot.
After deduplicated ingress, four background media acquisitions run independently of the WebSocket reader and preserve stored segment order. They use reported HTTP(S) URLs, then get_image for a downloadable URL when needed; remote filesystem paths are never read locally. Public-network policy, download byte limits and image decoding guard this boundary. QFace 1.4.1 supplies the bundled system-face mapping with its MIT notice; unknown IDs remain labeled unavailable.
QQ media occurrences reference shared qq_media_assets, unique by SHA-256 of original PNG/JPEG/WebP/GIF bytes across all QQBot Projects. Resource rows own the original attachment, optional first-frame PNG for GIF/animated WebP/APNG, description, manual-description flag, favorite state and creation/update times. Static images reuse their attachment. An existing resource is attached before decoding; new resources are saved and referenced atomically so competing downloads retain one copy. Ordinary chat attachments do not share this deduplication. With image input enabled, a batch waits at most ten extra seconds for pending pictures/stickers, excluding system faces. Unavailable resources become positional text placeholders; late completion updates display but never sends historical images. Pending acquisition resumes after restart. History deletion releases a non-favorite resource after its final visible reference, protecting favorites and files referenced by other messages or model snapshots; late results cannot recreate deleted records and IDs are not reused.
QQDescriptionService sends each selected undescribed asset independently through core/models, using only a fixed Chinese description prompt and its static image, with non-streaming output, reasoning off, max_tokens=64, temperature=0 and no tools. Plain text is normalized to one line and at most 20 Unicode characters; empty/structured/tool output is ignored. Concurrent batches share in-flight asset tasks and normal ModelManager admission/timeout limits. Main replies never await descriptions, though shared providers retain their configured concurrency. Writes fill only still-existing, undescribed resources without manual edits; changes are visible to later contexts. Failure leaves the description empty without pausing chat or borrowing another model; later selected occurrences may retry. Shutdown cancels these in-memory tasks; there is no persistent description queue or history-wide backfill.
At ingress, only real text segments determine an internal image_generation_keyword flag for the literal substrings `生成` or `画`. Names, mentions, quotes, cards, descriptions and other synthetic text never contribute. Execution ORs the flags of visible, submitted batch messages after truncation; a configured generation model is also required. This permission stays fixed in the run snapshot, shared by tool visibility, qq_runtime and handler validation. Historical messages, tool results and model output cannot unlock it; a new batch such as `再来一张` without either keyword stays disabled. Keywords enable a tool, not an obligation to generate: instructions require an explicit request for a new picture and exclude discussing animation/scenes, text generation and requests not to draw.
Each preparation snapshots all global favorites with nonblank descriptions as ordered `{asset_id, description}` candidates. Only their text enters qq_runtime under the existing context budget; paths, URLs and image bytes are excluded. No candidates means no list or qq_send_image definition. Changes apply to later batches. Runtime instructions prefer text, discourage routine/consecutive unsolicited images and recommend at most one image per reply without a separate execution quota or cooldown. Descriptions/tags are untrusted candidate data, not instructions.
qq_send_image requires a snapshotted candidate id and rechecks that the resource exists, is favorite and has a nonblank description. After any icebreaker wait, it reads the original attachment synchronously before the durable intent, retaining animation rather than the model’s static derivative. The intent references the existing resource; confirmation atomically saves its receipt and historical text marker with the description at send time. It never copies the resource, changes its description or invokes a model. Missing, unfavorited, undescribed or unreadable resources return QQ_IMAGE_RESOURCE_UNAVAILABLE to the model before any intent/slot, allowing a text reply. Normal delivery failure, stop and recovery rules still apply.
qq_generate_image calls ModelManager.generate_images with n=1 and snapshotted Project size/quality/style overrides. Unset controls and response format inherit the selected image profile. URL results use the existing public-network download policy; URL/base64 images use attachment byte limits and QQ image decoding. Files are staged before dispatch. Only confirmed sends create/reuse a shared SHA-256 asset, linking it with the delivery and historical message in the confirmation transaction; its description becomes the full original prompt unless that asset has a manually edited description (including an intentionally cleared one). Provider revised_prompt is ignored. Unreferenced staged files are cleaned after normal completion, failure or cancellation; crash leftovers use explicit orphan cleanup.
Generation, download and preparation failures return QQ_IMAGE_GENERATION_FAILED to the model without consuming a reply slot or pausing, so the model may send text or invoke generation again. There is no automatic retry. Missing mandatory replies and normal loop limits still fail. A sending failure or uncertain receipt retains the existing terminal delivery policy; restart never regenerates or resends. Project execution remains serial while generation awaits its provider, with ingestion and Stop available.
Delivery intents persist before dispatch, unique by run/tool-call id, with pending/sending/sent/failed/unknown states.
Successful confirmation and its historical assistant message commit atomically; later failures preserve earlier sends.
OneBot rejection is failed; disconnect, timeout, cancellation during sending or an invalid receipt is unknown.
Delivery errors terminate the current run and pause the Session before another send. No automatic resend or regeneration occurs.
Main reply-model failures also pause. `/api/qq/sessions/{id}/control` pause prevents new execution while ingestion/batching continue;
stop additionally cancels active work. Resume requires idle state and selects untouched queued batches only.
Failed, cancelled and interrupted batches never replay. Disabling a connection stops ingress/dispatch and blocks later sends.
Restart retains ordinary queues, window membership/policy and absolute participant expiries, marks running batches interrupted and in-flight intents unknown, and pauses affected Sessions.
Existing run reconciliation remains authoritative. QQ history has no editing, retry or direct-send API.
Icebreaker observations are process-local and run on the existing supervisor. Pause, disablement, disconnect, restart or changes to icebreaker/connection settings discard observations and cancel unsent icebreakers. Resuming starts a fresh silence baseline; persisted cooldown deadlines survive. Restart cancels queued/running icebreakers with no delivery intent instead of replaying them; submitted sends retain normal interrupted/unknown recovery.
A second speaker or ordinary reply trigger cancels an icebreaker during queueing, media/member waits, context preparation, inference or image generation. Execution and sending wait for preceding nickname decisions; the sending entry point then rechecks eligibility before its durable intent and OneBot submission, with no intervening await. Once submitted, the message is not cancelled or retracted by new activity. Automatic invalidation records QQ_ICEBREAKER_CANCELLED on the batch without automatically pausing the Session; actual model/delivery errors retain normal failure handling. Explicit pause/stop still pauses.
Local [history deletion](chat-context.md#qqbot-conversations) excludes removed inputs before dispatch and cancels empty queued batches without changing participant eligibility or replaying work.
Deleting observed inputs uses only remaining visible messages; deleting all cancels the observation. History deletion never rewinds activity or cooldown clocks.
Deleting a Session/Project requires idle run/batch state and removes associated QQ records without retracting external messages.

Local fake-OneBot/fake-model tests cover transport, participant windows, skip/renewal races, batching, paired delivery history/pruning, nonblocking member queries, failures, cancellation and restart. Live NapCat delivery and member lookup,
reconnect backfill, real media/model round trips, manual sends, memory integration and Linux Local Runtime remain outside current acceptance;
[QQ integration boundaries](../FUTURE_QQ_INTEGRATION.md) retains deployment evidence and outstanding live verification.

## Loop, approval and cancellation

One run can execute eight tool-producing rounds, followed by a final model
answer. A further tool round fails with `TOOL_LOOP_LIMIT`. Each tool has a
30-second timeout; the harness has five minutes of cumulative active time. The QQ image-generation tool is exempt from both counters: provider queue/request, download and OneBot delivery retain their own timeouts and cancellation, while other model/tool work keeps the shared budgets.
Waiting for approval consumes no active time and holds no model lease.
QQ's send limit can complete a run earlier and does not increase these shared limits.

Each model round, including after approval, applies the shared
[chat token budget](chat-context.md#configuration-snapshots-and-context) to its final request.
Only prior conversation turns may be removed; the entire active tool transcript stays paired and
intact. Oversized tool results can end a run with CONTEXT_WINDOW_EXCEEDED before its next model
dispatch. Saved base context/configuration remain stable through approval; each call captures
its own retained request and budget. Tool-result compression is unimplemented.

Streaming call fragments are merged by index. IDs, names and JSON are validated
before execution; duplicate IDs across a run and incomplete calls are terminal
protocol errors. Assistant text streams incrementally over the existing message
events. A tool error or rejected approval is returned to the model as data;
model refusal, cancellation and the total time limit terminate the run.

Each model round records one assistant message with distinct tool_call parts.
Its model step stores one LLM statistics snapshot, including failed/cancelled calls; restored approvals retain earlier call statistics.
Each dispatched model call also retains its private input snapshot. Base-source provenance and exclusions
travel in the existing approval continuation; later calls append only already-produced assistant/tool exchanges.
Tool definitions reflect that round's effective allowlist. [Context detail](runs-streaming.md#context-detail) owns inspection.
The reply aggregates these rounds without charging tool execution or approval waits to generation speed; [Runs/streaming](runs-streaming.md#llm-statistics) owns the accounting rules.
Results use role=tool and tool_result parts with status
success/error/rejected/cancelled, data, error fields and a truncation flag.
Every attempted call has a tool step, including validation failures.

A sensitive call creates an approval step and sets WAITING_FOR_USER and the
session's waiting_run_id. Private harness_state_json preserves the original
input, transcript, ordered remaining calls, approval ID, round count, settings
and active time. It also preserves the effective reasoning mode selected before the first model round, including automatic adjustment; all rounds and approval resumptions keep that mode despite session edits. config_snapshot_json preserves the requested chat configuration. Retry resolves both modes again.
Neither private state appears in public run metadata, responses or events.
Base context stores typed attachment-image references, never image data URLs/base64. Every model round,
including approval resumption, reads only those references and applies the model's image capability/request limits.
The attachment byte limit is snapshotted with the context. Terminal cleanup discards continuation state; retained model-input snapshots keep their attachment references until history cleanup.

Only the approval endpoint resumes a waiting run. Approval executes the original
call; rejection skips its handler and records a rejected result. Remaining
calls from the same model round are processed before another model request.
A new sensitive call requires its own approval. Ordinary input and direct tool
requests are blocked while a session waits; other concurrent runs return
SESSION_BUSY. In-flight approval requests cannot claim the same call twice.

Chat, direct calls and resumed execution share the active-run cancellation
registry. Cancelling an active or waiting run records cancelled results for
outstanding calls, settles open steps, clears private state and the waiting
reference, and leaves a terminal CANCELLED run. Terminal status is immutable.
Restart preserves valid pending approvals; other unfinished execution becomes
INTERRUPTED and is never replayed automatically.

## REST and user workflow

- GET /api/tools returns the catalog and parameter schemas.
- GET/PATCH /api/tools/settings owns the optional searxng_base_url.
- POST /api/tools/{tool_name}/call accepts {session_id, arguments}.
- POST /api/tools/approvals/{run_id} accepts {decision: approve|reject}.
- GET /api/tools/runs/{run_id} returns a direct or harness run.

Tool responses contain run (including steps), messages and the current session.
Direct calls use Run.kind=tool; model harness runs retain kind=chat. Direct
calls require direct_callable and the effective allowlist, without requiring
harness_enabled. They never call a model for a summary or a title. Handler
errors and rejected direct calls end as FAILED with the corresponding error
code; their tool results remain visible.

Only registered names are recognized as /tool_name args. A single required
string receives the raw remainder, preserving whitespace; other schemas require
a JSON object. There is no key=value parser. Unknown slash prefixes remain
ordinary text; known unauthorized tools return TOOL_NOT_ALLOWED.

Tools settings show catalog, risk, JSON arguments, results and approval controls.
The chat reply shows the current call's parameters and supports approval, rejection
and cancellation outside collapsed processing history. Tools settings retain
RunPanel diagnostics and share the same approval controls. Adjacent calls render
as one collapsed command group; command rows expand arguments and corresponding
results without separate message avatars. Tool calls are retried only as part of
their whole chat run, never as standalone assistant answers. Historical tool parts are quoted data in ordinary/group
context within history limits; live loop results use native tool
roles. Tool data is never promoted to a system/developer instruction.

WebSocket tool_call_created, tool_result_created, approval_requested and
approval_resolved expose the workflow alongside message/run/step events.
Completion replaces streamed drafts authoritatively. The frontend merges
duplicate and older events, preserves newer approvals through stale refreshes,
and isolates asynchronous responses after session switches.

Tool-generated paths are relative; rejected absolute arguments are masked.
URL credentials and authentication query values are not echoed. Provider keys
are not passed to tools. Tool content is rendered as JSON/text, never executed.
All workflow labels, risks, results and step kinds have English/Chinese text.

OpenAPI describes the catalog, settings, direct calls and approval results with
validated run/message/session types. Tool parameters and results are explicitly
finite JSON, with field-specific documented exceptions for their tool-owned
schemas. Duplicate-key and non-finite input rejection still precedes execution;
domain validation remains responsible for tool execution constraints.
