# Chat and context contract

Chat uses explicit Persona data, ContextBuilder and ChatRunner. Ordinary input
has no intent router. Registered `/tool_name` inputs use the direct executor;
all other prefixes remain text. [Harness/tools](harness-tools.md) owns direct
syntax, allowlists, bounded loops and approvals.

## Personas and sessions

Personas are strict editable database records with id, immutable collection, name,
optional avatar_attachment_id, system_prompt and timestamps. They are identities,
never executable agents, scripts, manifests or extension registrations. All four
collections share CRUD and ordered bindings. Avatars reference existing local image
filenames; bytes remain in the attachment store.

| Collection | Settings page | Resources | Execution |
| --- | --- | --- | --- |
| user | User Persona | Knowledge | Singleton user background and display identity |
| agent | Agent Personas | Knowledge | Selected ordinary-session assistant |
| roleplay_user | User Personas | Worldbook | Management only |
| character | Character Personas | Worldbook | Management only |

Migrations seed User (empty prompt) and Cogita (helpful-assistant prompt), with no
roleplay defaults. Both may be edited but not deleted; protection follows stable
ids and is exposed as read-only is_protected. POST requires a creatable collection;
PATCH cannot change collection. The user singleton cannot be created through CRUD.
Persona deletion fails while selected by a session or referenced by an unfinished run.
Historical assistant messages retain identity/avatar snapshots. SessionResponse.user_persona
contains the current singleton identity; all user-message and selected-context labels use
its latest name/avatar without rewriting history. User messages reference the singleton id
and do not snapshot its avatar. Updating the singleton notifies all sessions.

Each session has one persona_id, initially Cogita; selection accepts only agent records.
There are no members, speaker lists, conversation modes or group transcripts.
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
session history with explicit attachments. Session generation defaults to {} and accepts only
optional temperature (0..2); a non-null value overrides the model. {} or temperature:null
clears the override; PATCH omission preserves it. Other model generation parameters remain
inherited and available in the resolved configuration. Neither context nor generation is nullable. Harness defaults off. New sessions omit tools_allowed to allow all
currently registered built-ins; an explicit [] allows none. Saved allowlists
do not change when the catalog grows. These settings never depend on Persona.

Each run combines Knowledge bindings in User Persona, selected Agent Persona, then
session-addition order, deduplicating by first occurrence. Clearing additions never removes
Persona bindings; changing the Agent preserves additions, including overlaps. Resource
enablement and retrieval limits still apply. Retrieval receives resolved ids explicitly.
Worldbook bindings are restricted to roleplay_user and character collections and do not
participate in ordinary sessions. Wrong collection/resource combinations return 422.

| Endpoint | Ownership |
| --- | --- |
| `/api/personas` and `/{id}` | Strict Persona CRUD; optional collection list filter |
| `/api/personas/{id}/knowledge-bases`, `/worldbooks` | Persona bindings |
| `/api/sessions` and `/{id}` | Session creation, selection and configuration |
| `/api/sessions/{id}/knowledge-bases` | Session additions, User/Agent Persona ids and effective ids |
| `/api/sessions/{id}/messages` | History and new input |
| `/api/messages/{id}`, `/edit` | User-message deletion and edit |
| `/api/runs/{id}`, `/{id}/retry` | Whole-reply deletion and chat retry |

References are validated before persistence. Unknown/removed fields return
422; missing or conflicting references return structured 404/409 errors.
A waiting approval blocks new messages and direct calls. Active overlapping
execution returns SESSION_BUSY. The explicit approval API resumes the same run.

Deleting a different session from the sidebar preserves the current conversation,
draft and selected context. Deleting the current session selects the first remaining
session, or creates an empty one when it was the last. Delayed deletion/replacement
responses preserve subsequent session selections. Failed deletion leaves the
displayed state intact and reports the error.

Session binding PATCH accepts only knowledge_base_ids; [] clears additions. Responses
include user_persona_knowledge_base_ids, agent_persona_knowledge_base_ids and
effective_knowledge_base_ids. The UI locks each Persona section and edits additions
separately; it never writes effective ids back as additions. Persona resource endpoints
accept the matching knowledge_base_ids or worldbook_ids array; [] clears its bindings.

## Configuration snapshots and context

Each run privately stores the resolved chat configuration in
config_snapshot_json. Its Agent prompt, User Persona background, bindings, generation and context remain stable
through Persona edits, selection changes and approval waits. Public metadata exposes
only identities, model selection, context policy, limits and binding ids.
Retry resolves a new configuration for the original run's Agent Persona without changing
the session selection. A missing/deleted Persona fails before pruning. It
keeps the input user message and deletes the selected run plus all later
conversation messages/runs. Tool runs cannot be retried as model answers.
DELETE /api/runs/{id} deletes only that reply's messages, steps, events and
private state, preserving its user input. User deletion also removes its
associated replies; user edit removes later conversation and associated runs.
History mutations require an idle session. SQLite pruning and user text edits
commit in one transaction. Responses and history_pruned events return
deleted_message_ids/deleted_run_ids. Message-level retry is removed; individual
assistant/tool deletion is rejected. Referenced attachment cleanup follows commit.

ContextBuilder projects ordinary user/assistant history with none/current_message/
recent_messages/session/selected_message policies, message/character bounds and explicit
attachments. The selected Agent's nonempty system prompt is inserted once independently
of history mode; there is no include_system_prompt switch. The header selects the concrete
model; the session dialog owns one Agent selection and configuration. Selected-message
context uses an explicit source message and clears on session changes. Context sources
are bounded data blocks, with compact diagnostics rather than copied content in metadata.

The singleton User Persona is always active. Its trimmed nonempty system_prompt is
background data wrapped in <user_persona> tags and appended once to the system context;
empty text produces no block. The run snapshots this text before execution. Compact
user_persona metadata contains identity, injection status, length and empty skip reason,
never the content. General settings contain no Core Memory fields or enable switch.

Worldbook is deterministic matching over current user text and configured
keywords. Enabled entries obey entry/context limits, case sensitivity,
whole-word matching and recursion depth. Books/entries have explicit CRUD;
match-test is diagnostic and changes no session/run. It requires explicit worldbook_ids
and has no session target. Worldbooks have no ordinary-chat binding or injection path;
roleplay Persona bindings are stored for later workflows. User Persona, Worldbook,
Knowledge and attachment content are data, never routing decisions.

Worldbook management opens inside its settings panel, with Configuration,
Entries and Match test tabs. Existing books and newly saved books open Entries.
Each entry card's header contains a handle, disclosure, enabled
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
and image handling follow the attachment rules below.

## Messages and attachments

Messages use content_version=2 and validated parts. The strict message schema
owns role, speaker identity, run/parent references and compact metadata.
Supported parts are text (plain/markdown), reasoning, json, file (inline_text or
attachment_ref), image, audio, video, media_group image galleries, notice,
error, tool_call and tool_result. Unknown types are rejected; there are no
forms, actions, command buttons or diff parts.

Text parts choose plain text or Markdown; reasoning uses Markdown with GFM.
Knowledge citation labels such as `[K1]` follow ordinary Markdown rendering,
without a citation-specific parser, source lookup or popover.

Large binary data belongs in the attachment store and is referenced by id/URL.
Uploads and serving use the configured attachment directory; General owns
size/count and text-context byte limits. Persisted parts retain ids, MIME,
name, size and compact metadata, never image data URLs. Orphan cleanup is an
explicit separate operation and considers Persona avatar references.

User images persist only as metadata.attachments references; message parts do not duplicate them.
ContextBuilder selects history by policy, message count and character budget before reading images.
Image bytes do not consume the text budget. History projection keeps images with their user message. Image-only messages can be selected context.
Included references become OpenAI image_url parts immediately before inference, including historical follow-ups.
The selected LLM must advertise vision; otherwise UNSUPPORTED_CAPABILITY ends the run.
Missing selected images return ATTACHMENT_NOT_FOUND; corrupt local images and request limits follow
[models](models.md#external-inference-api). Excluded or pruned images are never read.

Text-file context obeys the enable switch and per-file/per-message bounds.
Other attachments contribute bounded descriptive markers. include_attachments=none excludes all image inputs.
File selection, clipboard images and file dropping share an upload flow with per-file status, previews and removal.
Partial failure keeps successful uploads. Session changes clear pending attachments and ignore late results.
Message thumbnails and zoom previews resolve stored references after refresh. Model capability, attachment-policy
and size errors have English/Chinese guidance. Text editing/retry retains image references; pruning cleans unreferenced files.

Tool calls require assistant role, a unique call id within the run, a name and
finite JSON object arguments. Results require tool role, matching call id,
success/error/rejected/cancelled status, optional JSON data/error fields and
truncation flag. Calls in one assistant message have distinct part ids.
Live loops use native assistant/tool pairs. Historical tool parts are quoted
as ordinary context data, allowing selected or truncated history without
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

User messages use right-aligned secondary bubbles; assistant replies use open
body layout. Assistant replies retain historical identity and avatars; user rows use the current
User Persona identity. Both retain message timestamps. Message bodies
use 16px text with Markdown headings, lists, quotes, code, tables and media.
Wide code, tables and tool results scroll inside their own bounds; tool results
are limited to 320px height on desktop and 240px below 768px.

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
the only input: no history, attachments, Persona context, Worldbook or Knowledge.

## HTTP schemas

OpenAPI defines public Personas, resolved session configuration, typed message
parts, timelines, bindings, history mutations and Worldbook match diagnostics.
Responses are validated without adding absent optional fields or removing
explicit nulls. Message/run UTC timestamps retain Z and microsecond precision;
Worldbook's existing +00:00 timestamps remain unchanged. Manual attachment and
Persona parsing retain their current error codes and PATCH merge behavior.
Uploads document one multipart file; downloads document stored-MIME binary bytes,
the single Range header, 200/206 length/range headers and an empty 416 response.
Private run continuation and configuration snapshots are absent from public types.
