# Harness and tools contract

Harness execution uses effective `harness_enabled` and `tools_allowed`. Ordinary
sessions default off with all registered tools; explicit [] disables every tool.
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
Built-ins support both model and direct invocation through the same handler,
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

## Loop, approval and cancellation

One run can execute eight tool-producing rounds, followed by a final model
answer. A further tool round fails with `TOOL_LOOP_LIMIT`. Each tool has a
30-second timeout; the harness has five minutes of cumulative active time.
Waiting for approval consumes no active time and holds no model lease.

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
