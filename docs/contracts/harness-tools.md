# Harness and tools contract

Harness execution is opt-in through the session's non-null `harness_enabled`
boolean (default false) and `tools_allowed` list. Persona owns neither field.
New sessions default to all registered tools; explicit [] disables every tool.
Changing Harness enablement preserves the list, and new registry entries do
not rewrite existing lists. The session UI uses catalog-backed tool switches.
Ordinary chat sends no tools
and rejects unexpected calls with `UNEXPECTED_TOOL_CALL`. An enabled harness
with an empty allowlist uses ordinary chat. A model lacking native tool support
returns `UNSUPPORTED_CAPABILITY`; there is no text-command fallback.

## Registry and tools

The registry contains only explicitly registered built-in Python tools. It
does not load manifests, plugin directories or dynamic modules. Each ToolSpec
has a lower snake_case name (at most 64 characters), description, Draft 2020-12
object schema, handler, risk, requires_approval and direct_callable.
Session allowlists are unique and reference registered names.

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

File paths are relative to the workspace and restricted to `data/knowledge`
and `data/attachments`. Absolute paths, traversal, Windows alternate streams
and symlink/junction escapes are rejected. Reads are bounded to 200,000 bytes;
the result exposes a relative path, text, size and truncation flag.

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
Results use role=tool and tool_result parts with status
success/error/rejected/cancelled, data, error fields and a truncation flag.
Every attempted call has a tool step, including validation failures.

A sensitive call creates an approval step and sets WAITING_FOR_USER and the
session's waiting_run_id. Private harness_state_json preserves the original
input, transcript, ordered remaining calls, approval ID, round count, settings
and active time. config_snapshot_json preserves the resolved chat configuration.
Neither private state appears in public run metadata, responses or events.

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
RunPanel shows the current call's parameters and supports approval, rejection
and cancellation, including while waiting. Tool call messages cannot be retried
as assistant answers. Historical tool parts are quoted data in ordinary/group
context (including selected-message context); live loop results use native tool
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
