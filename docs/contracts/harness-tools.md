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
| web_search | searches (query, recency) | Automatic |
| web_fetch | url, optional focus/page | Automatic |

[QQBot](qqbot.md) owns QQ-scoped tool arguments, availability, delivery behavior and media downloads.

## Web tools

WebToolsService uses AnySearch's authenticated [Search](https://www.anysearch.com/docs/api-endpoints/v1-search)
and [Extract](https://www.anysearch.com/docs/api-endpoints/v1-extract) APIs with their independent write-only key.
Missing keys return WEB_NOT_CONFIGURED. Ordinary/Workspace allowlists apply; QQ automatically includes both tools.
Both tools have general scope, network risk, direct invocation and no approval. Public inference never executes them.

web_search accepts searches (1..4 objects with nonblank query and recency=any|week|month|year, default any).
Each query uses global max_results (default 5), zone and language; these options cannot be supplied as tool arguments.
Only query/options/format=markdown go upstream; recency is local. Queries execute concurrently with individual
25-second deadlines inside the ordinary 30-second tool deadline. Partial failures retain successful queries;
all failed queries return a sanitized error. Cancellation settles all children; there is no automatic retry.

Search decodes entities, strips provider wrappers, nested images, repeated text/headings, breadcrumbs,
players/countdowns and navigation. Code, tables and meaningful numeric lines are preserved. Article h1 titles
replace provider navigation titles. URLs and identical 150-character body prefixes are deduplicated, retaining
longer evidence. URL keys remove fragments/tracking parameters while preserving scheme, www, meaningful
query order and path differences.

Ranking evaluates each successful query separately against candidate titles, snippets and cleaned bodies.
English stop words are excluded; Chinese matching primarily uses bigrams. Numbers, versions, decimals,
times and quoted phrases stay atomic and are mandatory. Page-level IDF weights required terms by three;
coverage must reach 60%. There is no result minimum or per-query guarantee. Coverage then BM25 rank
results descending with stable ties. Excerpts select matching paragraphs in source order without a fixed
lead, at most 500 characters each. Packing keeps at most eight whole results and 5,000 rendered characters.
No qualifying evidence produces an explicit no-relevant-results response.

Dates prefer labeled date/Updated/Published and Chinese publication/update signals, including English
month names and N minutes/hours/days/weeks ago. Otherwise URL and the first 800 body characters supply
heuristic dates. Future and invalid dates are ignored; the newest valid past date wins. Relative dates stay
anchored to acquisition time through cache reads. Recency windows are 7/31/366 days without extra tolerance;
month-only dates use the month's interval. Undated results matched only by time-filtered queries come last,
at most two per call; any queries are unrestricted. Dates remain inferred, not verified publication dates.

web_fetch accepts a public url, optional nonblank focus and page (integer >=1, default 1). Only url goes to Extract.
The first fetch extracts; fresh Extract caches are reused across sessions, focuses and pages. Cleaned bodies
under 200 non-whitespace characters or under half the existing body's length fail with WEB_INSUFFICIENT_CONTENT.
Failures preserve cached content, title, hash, acquisition time and source identity, consume the normal call
budget and never masquerade as a successful refresh. Short legitimate pages can therefore be rejected.
HTML/Markdown/text cleaning retains useful body-link metadata. JSON evidence remains literal.
Without focus, pages follow document order; focus ranks paragraphs with document-local BM25 and restores
source order within each page. No matches and out-of-range pages return explicit notices. Pages target
4,000 body characters, at most 4,500 rendered characters. A content hash identifies the cached version;
refreshes can change pagination. An unrepresentably long URL returns WEB_OUTPUT_TOO_LARGE.
PDF and browser-rendered extraction are not implemented locally.

Full cleaned bodies and links live in the page cache, outside tool messages/events and model snapshots.
Structured results retain displayed excerpts, source/query/date/cache/page metadata, counts and budgets.
The model/history projection includes one second-precision retrieval time, single-line queries, evidence
and compact inferred dates. Each page adds a compact approximate character count of the available cleaned
body, not its displayed excerpt/page; provider-limited text cannot establish the full site's length.
It excludes diagnostic counts, budgets, matched-query lists, hashes, cache diagnostics
and Related page blocks. Limited search text warns that fetching may still require login or JavaScript.
Fetch retains pagination actions and meaningful failure notices. Web evidence has complete untrusted
boundaries; only less-than signs are escaped, preserving ordinary ampersands and greater-than signs.
The final web-only dispatch guard stays below 6,000 characters even on unexpected truncation.

Ordinary/Workspace results assign W1, W2, etc. only to displayed pages, reusing conservative URL keys within a run.
Private continuation preserves the source map across approval. Answers cite current-run [W1] identities; QQ uses
URLs without numbered citations. Existing tool_result parts/events and reply Sources own presentation.
When either web tool is effective, Instruction contains only the localized run-start date and weekday,
before Agent Persona; date/language stay fixed through approval. Tool descriptions own concise
query/focus/recency/privacy guidance and distinguish retrieval from publication/event dates. Shared web
content and citation rules appear once per request, on the first available web tool, including single-tool
allowlists. QQ omits numbered-citation guidance. Web content is untrusted evidence, never instructions.

Each run snapshots four search calls and six reads by default, configurable through [Settings](settings.md).
A batch costs one search call; cache reads, duplicate queries and failed executions also consume a call. Schema-invalid
calls do not. Exhaustion returns WEB_BUDGET_EXHAUSTED without dispatch and allows the model to answer.
Query deduplication uses Unicode normalization, case folding and collapsed whitespace plus recency, preserving
operators/punctuation. Approval retains counts and query keys; retries/new inputs/QQ batches reset them.
Direct calls each have their own run. The eight-round and five-minute Harness limits remain independent.

Uncompressed provider responses are streamed with a 1 MiB limit; Extract request JSON remains limited to 16 KiB.
HTTP(S), valid hosts and no credentials are required; non-public literal addresses/localhost are rejected.
AnySearch owns target DNS/redirects. The API contacts only its fixed endpoint without redirects or environment proxies.
Error bodies never enter traces/results; only safe status/request-id diagnostics survive. Per-tool step metadata.web
records output characters, reference-token estimates, filter counts, cache status and remaining budget; existing
model usage/context snapshots retain actual prompt/cached tokens separately.
Acceptance covers mocked ordinary/Workspace/QQ/direct paths and live ordinary research. Lexical matching lacks
synonym expansion, dates remain heuristic, and extraction may return only a site's shell. Source sufficiency,
stopping and answer scope remain model/Persona decisions. The QQ contract owns live-delivery limits.

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
its own retained request and budget. Web results use the bounded evidence projection above.

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

- GET /api/tools returns all six tools, their general/qqbot scope and parameter schemas.
  General defaults/selection include only web_search and web_fetch; QQ tools remain separately scoped.
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

Only registered names are recognized as /tool_name args. A tool with exactly one string parameter
receives the raw remainder, preserving whitespace; other schemas require
a JSON object. There is no key=value parser. Unknown slash prefixes remain
ordinary text; known unauthorized tools return TOOL_NOT_ALLOWED.

Tools settings contain the web key form and a session-independent, read-only catalog. General tools and QQ Bot tools
form two stacked lists separated by a divider; each entry shows its name, localized description
and a collapsed parameter schema. All four QQ tools remain visible regardless of Project configuration.
The page has no call form, results or approval controls. Slash web calls require JSON objects matching the same schemas; search preferences belong to the settings form.
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
