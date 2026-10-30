# Harness and tools contract

Harness execution uses effective `harness_enabled` and `tools_allowed`. Ordinary
sessions default off with all general-purpose tools; explicit [] disables every tool.
Workspace sessions inherit Project defaults and may override them; Persona owns neither field.
Changing Harness enablement preserves the list, and new registry entries do
not rewrite existing lists. The composer's model menu toggles Harness immediately, displays on/off text and keeps the menu open; failure preserves confirmed state.
Its independent settings action opens a right Sheet with fade/slide transitions in both directions for catalog-backed session tool selection. Changes require Save; unsaved closing confirms discard, and failed saves retain edits. The Sheet is full-width on mobile and restores focus to the model trigger on close.
Session settings no longer edit or submit Harness/allowlists. Workspace inheritance and per-field resets for both fields live in the Sheet; reset submits null. Draft edits remain local until first send. Session changes close the menu/Sheet and ignore late saves.
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
object schema, handler, risk, requires_approval, direct_callable and scope (general or qqbot).
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
| base64_encode / base64_decode | value | Automatic |
| web_search | query | Automatic |
| web_fetch | url (public absolute HTTP/HTTPS) | Automatic |

[QQBot](qqbot.md) owns QQ-scoped tool arguments, availability, delivery behavior and media downloads.

Codec input and output are each capped at 1 MiB and decoded
bytes must be valid UTF-8.

## Web tools

The explicit WebToolsService uses a provider-independent search/fetch interface; AnySearch is the current implementation.
Authenticated POSTs use [Search](https://www.anysearch.com/docs/api-endpoints/v1-search) with format=markdown and [Extract](https://www.anysearch.com/docs/api-endpoints/v1-extract) with only url. Search accepts only query; max_results, zone and language come from global web settings and cannot be overridden by model/REST tool arguments. Unset zone/language use provider defaults; tag/params are unavailable.
Both tools have general scope, network risk, direct invocation and no approval. Ordinary/Workspace allowlists apply; [QQBot](qqbot.md#tools-delivery-and-recovery) automatically includes both without separate configuration.
[Settings](settings.md) owns the independent write-only AnySearch key. Missing keys return WEB_NOT_CONFIGURED; calls never use anonymous quota or model-provider keys.
Requests retain the ordinary 30-second tool deadline, five-minute run budget and cancellation. Uncompressed responses are streamed with a 1 MiB limit; Extract bodies are limited to 16 KiB. Oversized responses fail explicitly; model context budgets still apply to retained content.
Targets require HTTP(S), a valid host and no credentials; non-public literal addresses/localhost are rejected. AnySearch owns target DNS, redirects and extraction. The API process contacts only the fixed AnySearch endpoint without following redirects or environment proxies.
HTTP statuses distinguish rejected input, authentication, exhausted quota, extraction failure, rate limits and service unavailability. Only status and valid UUID request_id diagnostics are retained; raw error bodies, including generated credentials, never enter results or traces. There is no automatic retry.
Search returns provider, query, ordered results (url/title, optional snippet/content), request_id and available search_time_ms. Fetch returns provider, url/title/content and request_id. Empty titles/results are valid; malformed page data fails the tool.
Ordinary/Workspace Harness and direct calls add source_id W1, W2, etc. to successful pages before persistence and model continuation. IDs are run-local, allocated in result order and reused for identical URLs. Private continuation retains the URL/source map across approvals; public source data stays in existing tool_result parts/events, with no new message type or table. QQ results omit source IDs.
Tool descriptions instruct models to treat page content as untrusted evidence; ordinary/Workspace model requests also require citing only current-run IDs as [W1]. QQ requests omit citation instructions. Errors remain structured tool results so the model can continue. [Chat/context](chat-context.md#messages-and-attachments) owns visible citations; [Runs/streaming](runs-streaming.md#run-lifecycle) owns web steps.
Each Harness model call with web_search in its effective tool list prepends an Instruction containing the current server-local date and weekday. The run's UI language is retained across approval continuation; dates refresh for each call. Disabling Harness, excluding/revoking web_search or falling back to ordinary chat omits the block. Direct tools and public inference do not receive it.
Automated acceptance uses mock AnySearch responses and model calls; live AnySearch requests remain unverified.

## Loop, approval and cancellation

One run can execute eight tool-producing rounds, followed by a final model
answer. A further tool round fails with `TOOL_LOOP_LIMIT`. Each tool has a
30-second timeout; the harness has five minutes of cumulative active time. [QQBot](qqbot.md#tools-delivery-and-recovery) owns send deadlines, generation budget exceptions and early completion.
Waiting for approval consumes no active time and holds no model lease.

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

- GET /api/tools returns all eight tools, their general/qqbot scope and parameter schemas.
  General defaults/selection include Base64 and web tools; existing saved allowlists are unchanged.
- GET/PATCH /api/tools/web/settings owns the independent web service key.
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

Tools settings contain the web key form and a session-independent, read-only catalog. General tools and QQ Bot tools
form two stacked lists separated by a divider; each entry shows its name, localized description
and a collapsed parameter schema. All four QQ tools remain visible regardless of Project configuration.
The page has no call form, results or approval controls. Slash web calls accept the raw query/URL; search preferences belong to the settings form.
The chat reply renders individual steps and keeps approval controls outside collapsed processing history.
Web steps use dedicated result links/page text, including QQ results without source IDs; only numbered results participate in citations/Sources. Other tools retain their general presentation.
Calls have no separate message avatars. Tool calls are retried only as part of
their whole chat run, never as standalone assistant answers. Historical tool parts are quoted data in ordinary/group
context within history limits; live loop results use native tool
roles. Tool data is never promoted to a system/developer instruction.

WebSocket tool_call_created, tool_result_created, approval_requested and
approval_resolved expose the workflow alongside message/run/step events.
Completion replaces streamed drafts authoritatively. The frontend merges
duplicate and older events, preserves newer approvals through stale refreshes,
and isolates asynchronous responses after session switches.

Model-provider keys are not passed to tools; the web service receives only its own configured key. Tool content is rendered as data, never executed.
All workflow labels, risks, results and step kinds have English/Chinese text.

OpenAPI describes the catalog, direct calls and approval results with
validated run/message/session types. Tool parameters and results are explicitly
finite JSON, with field-specific documented exceptions for their tool-owned
schemas. Duplicate-key and non-finite input rejection still precedes execution;
domain validation remains responsible for tool execution constraints.
