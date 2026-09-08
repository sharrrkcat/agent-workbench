# Chat and context contract

Chat uses explicit Persona data, ContextBuilder and ChatRunner. Ordinary input
has no intent router. Registered `/tool_name` inputs use the direct executor;
all other prefixes remain text. [Harness/tools](harness-tools.md) owns direct
syntax, allowlists, bounded loops and approvals.

## Personas and sessions

Personas are strict editable database records, never executable agents,
scripts, manifests or extension registrations. Fields are id, name, optional
avatar_attachment_id, system_prompt and timestamps. Ordered Knowledge/Worldbook
bindings are stored separately. The avatar references
an existing local image filename; bytes remain in the attachment store.

Migrations seed editable Chat and Translate records. New sessions bind Chat as
their only member/current speaker. Chat may be edited but not deleted. Persona
deletion fails while referenced by a session or unfinished run. Historical
messages retain speaker id/name/avatar snapshots.

`session_personas` is an ordered enabled member list. current_persona_id must
refer to an enabled member. Group sessions generate one response from the
manually selected speaker per input, without automatic round-robin.
New sessions persist a concrete model selection. When POST omits model_profile_id
or supplies null, select the enabled global-default LLM if present, otherwise the
first enabled LLM in profile-list order (name, then id). No eligible LLM leaves
the selection null. Explicit ids are validated and never substituted. Changing
the global default affects later sessions only; execution uses the saved session
id. PATCH omission preserves it and null clears it. An unselected session requires
an explicit choice even after a model is added. Neither chat model selector offers
a Global default entry; both show the saved model and a disabled empty/unavailable
state when appropriate. No model discovery, health check or inference is performed
to initialize a session.
Resolved configuration reports model_source=session; there is no inherited model
source at execution time.

Context, generation, Harness and tool selection belong only to the session. Context defaults to
session history with explicit attachments; generation defaults to {} and its
non-null fields override the selected model's parameters. Neither object is
nullable. Harness defaults off. New sessions omit tools_allowed to allow all
currently registered built-ins; an explicit [] allows none. Saved allowlists
do not change when the catalog grows. These settings never depend on Persona.

Personas own ordered Knowledge and Worldbook bindings. Each run combines only
the current speaker's bindings with independent ordered session additions,
deduplicating by id in first-occurrence order. Clearing additions never removes
Persona bindings; changing speaker preserves additions, including overlaps.
Resource enablement and retrieval/matching limits still apply. Retrieval and
Worldbook receive resolved ids explicitly.

| Endpoint | Ownership |
| --- | --- |
| `/api/personas` and `/{id}` | Strict Persona CRUD |
| `/api/personas/{id}/knowledge-bases`, `/worldbooks` | Persona bindings |
| `/api/sessions` and `/{id}` | Session creation, selection and configuration |
| `/api/sessions/{id}/personas` | Ordered members/current speaker |
| `/api/sessions/{id}/knowledge-bases`, `/worldbooks` | Session additions, Persona ids and effective ids |
| `/api/sessions/{id}/messages` | History and new input |
| `/api/messages/{id}`, `/edit` | User-message deletion and edit |
| `/api/runs/{id}`, `/{id}/retry` | Whole-reply deletion and chat retry |

References are validated before persistence. Unknown/removed fields return
422; missing or conflicting references return structured 404/409 errors.
A waiting approval blocks new messages and direct calls. Active overlapping
execution returns SESSION_BUSY. The explicit approval API resumes the same run.

Binding PATCH bodies contain only knowledge_base_ids or worldbook_ids arrays;
[] clears additions. Responses expose that array, read-only persona_* ids and
effective_* ids. There is no mode field. The UI locks the Persona section and
edits additions separately; it never writes effective ids back as additions.

## Configuration snapshots and context

Each run privately stores the resolved chat configuration in
config_snapshot_json. Its prompt/generation/context remain stable through
Persona edits, speaker switches and approval waits. Public metadata exposes
only ids, names, model selection, context mode, limits and binding ids.
Retry selects the original run's speaker and resolves a new configuration. It
keeps the input user message and deletes the selected run plus all later
conversation messages/runs. Tool runs cannot be retried as model answers.
DELETE /api/runs/{id} deletes only that reply's messages, steps, events and
private state, preserving its user input. User deletion also removes its
associated replies; user edit removes later conversation and associated runs.
History mutations require an idle session. SQLite pruning and user text edits
commit in one transaction. Responses and history_pruned events return
deleted_message_ids/deleted_run_ids. Message-level retry is removed; individual
assistant/tool deletion is rejected. Referenced attachment cleanup follows commit.

ContextBuilder supports single_assistant and group_transcript projection, with
none/current_message/recent_messages/session/selected_message policies, message
and character bounds and explicit attachments. The current Persona's nonempty
system prompt is always inserted once, independently of history mode; there is
no include_system_prompt switch. The chat header/session dialog selects speakers
and session configuration; selected-message
context uses an explicit source message and is cleared on session changes.
Group transcripts preserve historical speaker labels and reply as the current
speaker. Context sources are separate bounded data blocks, with compact
diagnostics rather than copied content in metadata.

Core Memory injects trimmed core_memory_content when enabled and nonempty,
wrapped in `<core_memory>` tags. Metadata contains flags, length, skip reason
and warnings only. The settings and reset boundary are in [settings](settings.md).

Worldbook is deterministic matching over current user text and configured
keywords. Enabled entries obey entry/context limits, case sensitivity,
whole-word matching and recursion depth. Books/entries have explicit CRUD;
match-test is diagnostic and changes no session/run. Persona/session bindings
use the resolution above. Memory, Worldbook, Knowledge and attachment content
are data, never runtime instructions or routing decisions.

Worldbook management opens inside its settings panel, with Configuration,
Entries and Match test tabs. Existing books and newly saved books open Entries.
The entry UI preserves the 768b335d card hierarchy: handle, disclosure, enabled
switch, name, dirty marker, mode and delete; the body has name/mode, keywords,
content, then save/reset/delete. Multiple cards and their drafts are independent.
Existing-entry switches PATCH only enabled and roll back on failure without
discarding other edits. Explicit save/reset affects one draft. Pointer/touch and
keyboard reordering share the handle and PATCH the full ordered id list, with
rollback on failure. Duplicate or mismatching reorder ids return 422.
Worldbook and entry PATCH validate the complete object before committing in both
stores; invalid regex/name/content never persists despite a rejected request.
Entry CRUD uses /api/worldbooks/{id}/entries and /api/worldbook-entries/{id};
ordering uses PATCH /api/worldbooks/{id}/entries/reorder. POST
/api/worldbooks/match-test returns counts, triggers, recursion and bounded previews.

[Knowledge](knowledge.md) owns indexing, hybrid retrieval, RRF and optional
rerank. Its context injection uses the run's resolved bindings. File context
and current-image handling follow the attachment rules below.

## Messages and attachments

Messages use content_version=2 and validated parts. The strict message schema
owns role, speaker identity, run/parent references and compact metadata.
Supported parts are text (plain/markdown), reasoning, json, file (inline_text or
attachment_ref), image, audio, video, media_group image galleries, notice,
error, tool_call and tool_result. Unknown types are rejected; there are no
forms, actions, command buttons or diff parts.

Large binary data belongs in the attachment store and is referenced by id/URL.
Uploads and serving use the configured attachment directory; General owns
size/count and text-context byte limits. Persisted parts retain ids, MIME,
name, size and compact metadata, never image data URLs. Orphan cleanup is an
explicit separate operation and considers Persona avatar references.

Current image attachments become OpenAI image_url parts through the selected
LLM and ModelManager. The profile must advertise vision; otherwise the run
returns UNSUPPORTED_CAPABILITY without an alternate model or silent display-only
path. Standalone image_embedding/vision profiles and managed backend limits
are described in [models](models.md#resolution-and-capabilities).

Text-file context obeys the enable switch and per-file/per-message bounds.
Other attachments contribute bounded descriptive markers. Historical attachment
bytes are not resent; normal history projection remains in force.

Tool calls require assistant role, a unique call id within the run, a name and
finite JSON object arguments. Results require tool role, matching call id,
success/error/rejected/cancelled status, optional JSON data/error fields and
truncation flag. Calls in one assistant message have distinct part ids.
Live loops use native assistant/tool pairs. Historical tool parts are quoted
as ordinary/group context data, allowing selected or truncated history without
orphan protocol calls. They never become system/developer instructions.

Reasoning is assistant-only strict {id,type:reasoning,text} data. The shared
assistant output normalizer accepts reasoning_content and extracts model
<think> markers incrementally, including split tags. Markdown inline/fenced/
indented code and escaped markers remain literal. Only internal chat extracts
markers; /v1 preserves model content. Reasoning never enters general historical
context. The live tool transcript retains upstream content and structured
reasoning where the provider needs it for continuation. Incomplete messages
are not eligible historical context or selected-context sources.

The frontend renders one reply per run with one historical Persona identity,
processing timeline, final answer and action bar. Only the current model round's
ordinary text appears as a provisional answer; tool-producing rounds move into
processing. Adjacent tools share a collapsed command group, with individually
collapsed arguments/results. Tool records have no separate avatars. Copy uses
answer text only. Context selection uses real message ids, including tool details.
Direct tool runs use this timeline without an invented model answer.

The frontend renders parts without executing or routing text. Markdown remains
content; edit/retry uses original text. MessageActions owns controls and
selected-context references; MessageParts owns presentation and attachment URLs.
Speaker snapshots are presentation data. Metadata may hold counts, source refs
and warnings, never full part bodies, prompts or secrets. Stream merging belongs
to [runs/streaming](runs-streaming.md).

## Auxiliary tasks and titles

UtilityLLMService is an internal ModelManager client without a separate backend,
unload path or public route. utility_model_profile_id is its only selector and
must identify an enabled LLM UUID. Missing or failed selection raises
UTILITY_MODEL_UNAVAILABLE and never borrows the default chat model.

generate_text uses non-streaming manager chat with only the supplied prompt.
generate_json parses the entire response and validates the supplied Pydantic
schema. Fenced/embedded JSON, unexpected calls and invalid output raise
UTILITY_OUTPUT_INVALID. These tasks create no messages/runs and share the
provider queue, lifecycle and status observations.

Titles are enabled by default, with session_title_prompt and a 1200-character
input limit. ChatRunner persists/publishes the completed response and run,
releases the main model lease, then requests a title using max_tokens=64 and
temperature=0. Only an empty/default title is eligible. Missing auxiliary
selection, failed/empty output or concurrent manual renaming leaves the title
unchanged and does not affect chat success. The bounded current user text is
the only input: no history, attachments, Memory, Worldbook or Knowledge.
