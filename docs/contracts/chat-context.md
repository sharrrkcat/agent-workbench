# Chat and context contract

Chat uses explicit Persona data, ContextBuilder and ChatRunner. Ordinary input has no intent router. Registered `/tool_name` inputs use the direct executor;
all other prefixes remain text. [Harness/tools](harness-tools.md) owns direct
syntax, allowlists, bounded loops and approvals.

## Personas and sessions

Personas are strict editable database records with id, immutable collection, name,
optional avatar_attachment_id, system_prompt and timestamps. They are identities,
never executable agents, scripts, manifests or extension registrations. All four collections share CRUD and ordered bindings. Avatars reference existing local image
filenames; bytes remain in the attachment store.

| Collection | Settings page | Resources | Execution |
| --- | --- | --- | --- |
| user | Cogita Persona | Knowledge | Singleton background and display identity |
| agent | Agent Personas | Knowledge | Ordinary/Workspace assistant |
| roleplay_user | User Personas | Worldbook | Management and Timeline selection only |
| character | Character Personas | Worldbook | Management and Timeline selection only |

Migrations seed User (empty prompt) and Cogita (helpful-assistant prompt), with no
roleplay defaults. Both may be edited but not deleted; protection follows stable
ids and is exposed as read-only is_protected. POST requires a creatable collection;
PATCH cannot change collection. The Cogita singleton cannot be created through CRUD;
its category name does not replace its editable name/avatar. Persona deletion fails while referenced by a Project, session or unfinished run.
Assistant replies and selected-context labels resolve the latest Agent name/avatar by
run.persona_id or message.speaker_id; changing session selection preserves original authorship.
Deleted Personas display a localized deleted-persona label and default avatar. Assistant
messages store identity ids without name/avatar snapshots. SessionResponse.user_persona
provides the current singleton identity for user rows/labels. Neither edit rewrites history;
run prompts/configuration stay fixed. Identity events also reach historical referencing sessions.

Ordinary sessions have one persona_id, initially Cogita; selection accepts only agent records.
There are no members, speaker lists, conversation modes or group transcripts.
New ordinary sessions persist a concrete model selection. When POST omits model_profile_id
or supplies null, select the enabled global-default LLM if present, otherwise the
first enabled LLM in profile-list order (name, then id). No eligible LLM leaves
the selection null. Explicit ids are validated and never substituted. Changing
the global default affects later sessions only; execution uses the saved session
id. PATCH omission preserves it and null clears it. An unselected session requires
an explicit choice even after a model is added. Neither chat model selector offers
a Global default entry; both show the saved model and a disabled empty/unavailable
state when appropriate. No model discovery, health check or inference is performed
to initialize a session.
Ordinary resolved configuration reports model_source=session.

New chat navigation opens an in-memory ordinary/Workspace draft, without a session
record or session WebSocket. Drafts support the full configuration dialog and
Knowledge additions; saving changes only local state. Reopening the same draft
preserves it; switching conversations/Projects or refreshing discards it. First
send creates the session, applies additions, then submits captured input and attachments.
Repeated submissions are locked. Creation failure retains the draft; later binding/
send failure retains the created id and input for retry. Existing creation APIs
remain explicit immediate creation operations; no database migration is needed.

Ordinary context, generation, Harness and tool selection belong to the session. Context defaults to
session history with explicit attachments. Session generation defaults to {} and accepts only
optional temperature (0..2); a non-null value overrides the model. {} or temperature:null
clears the override; PATCH omission preserves it. Other model generation parameters remain
inherited and available in the resolved configuration. Neither context nor generation is nullable. Harness defaults off. New sessions omit tools_allowed to allow all
currently registered built-ins; an explicit [] allows none. Saved allowlists
do not change when the catalog grows. These settings never depend on Persona.

Each run combines Knowledge bindings in Cogita Persona, selected Agent Persona, Project (Workspace only), then
session-addition order, deduplicating by first occurrence. Clearing additions never removes
inherited bindings; changing the Agent preserves additions, including overlaps. Resource
enablement and retrieval limits still apply. Retrieval receives resolved ids explicitly.
Worldbook bindings belong to roleplay_user/character Personas and Timeline Projects;
they do not participate in ordinary/Workspace sessions. Wrong resource combinations return 422.

Projects share global resource catalogs but isolate sessions, history and configuration.
Project.kind is immutable workspace|timeline. Workspace requires agent_persona_id,
the fixed singleton cogita_persona_id, context_policy, harness_enabled and tools_allowed;
system_prompt, model_profile_id, temperature (0..2) and ordered knowledge_base_ids are optional.
Timeline requires character_persona_id, roleplay user_persona_id and context_policy;
model_profile_id, temperature and ordered worldbook_ids are optional. Harness, Knowledge
and Project prompts are not Timeline fields. Timeline supports CRUD/settings only;
session creation/listing returns PROJECT_CHAT_UNAVAILABLE (409). Persona/Worldbook injection
and per-speaker historical identity for Timeline conversations remain unimplemented.

Session.kind and project_id follow the creation location and cannot be changed or moved.
Ordinary and Workspace have distinct schemas; timeline is a reserved session identity.
Workspace sessions store only sparse overrides for persona_id, context_policy, model_profile_id,
temperature, harness_enabled and tools_allowed. PATCH accepts title/overrides; omission keeps
values, null removes an override, and false/0/[] are explicit values. Inherited values are
resolved on reads and runs, never copied into session storage. The fixed Cogita Persona has no override.
Models resolve session > Project > global default using the ordinary default-selection rule;
changes to the global default affect inheriting Workspace sessions, including existing ones.
Temperature resolves session > Project > selected model. Other parameters remain model-owned.
Responses include effective configuration, model_source=session|project|global and typed sources.
Project settings and Persona/model edits refresh affected session responses through session_updated.
Tools are bounded by the current Project list; [Harness](harness-tools.md) owns revocation during runs.
Project deletion requires all its sessions idle, deletes their conversation state/bindings,
and preserves shared resources. Persona/model/resource deletion rejects Project references.

| Endpoint | Ownership |
| --- | --- |
| `/api/personas` and `/{id}` | Strict Persona CRUD; optional collection list filter |
| `/api/personas/{id}/knowledge-bases`, `/worldbooks` | Persona bindings |
| `/api/projects` and `/{id}` | Typed Project CRUD |
| `/api/projects/{id}/knowledge-bases`, `/worldbooks` | Type-restricted Project bindings |
| `/api/projects/{id}/sessions` | Workspace session creation and scoped listing |
| `/api/sessions` and `/{id}` | Ordinary creation/listing; individual ordinary/Workspace configuration |
| `/api/sessions/{id}/knowledge-bases` | Additions, Cogita/Agent/Project bindings and effective ids |
| `/api/sessions/{id}/messages` | History and new input |
| `/api/messages/{id}`, `/edit` | User-message deletion and edit |
| `/api/runs/{id}`, `/{id}/retry` | Whole-reply deletion and chat retry |

References are validated before persistence. Unknown/removed fields return
422; missing or conflicting references return structured 404/409 errors.
A waiting approval blocks new messages and direct calls. Active overlapping
execution returns SESSION_BUSY. The explicit approval API resumes the same run.

Deleting a different session from the sidebar preserves the current conversation,
draft and selected context. Deleting the current session selects its first remaining
sibling. The last ordinary session opens an unsaved draft; the last Workspace session leaves its Project settings/empty tree. Delayed deletion/draft loading
responses preserve subsequent session selections; delayed creation/selection cannot replace later navigation. Failed deletion leaves the
displayed state intact and reports the error.

Session binding PATCH accepts only knowledge_base_ids; [] clears additions. Responses
include user_persona_knowledge_base_ids, agent_persona_knowledge_base_ids, project_knowledge_base_ids and
effective_knowledge_base_ids. The UI locks inherited sections and edits additions
separately; it never writes effective ids back as additions. Persona resource endpoints
accept the matching knowledge_base_ids or worldbook_ids array; [] clears its bindings.

## Configuration snapshots and context

Each run privately stores the resolved chat configuration in
config_snapshot_json. Agent/Project prompts, Cogita Persona background, model, bindings, generation and context remain stable
through edits and approval waits; current Project tool revocations still apply. Public metadata exposes
only identities, model selection, context policy, limits and binding ids.
Retry resolves a new configuration for the original run's Agent Persona without changing
the session selection. A missing/deleted Persona fails before pruning. It
keeps the input user message and deletes the selected run plus all later
conversation messages/runs. Tool runs cannot be retried as model answers.
DELETE /api/runs/{id} deletes only that reply's messages, steps, events and
private state, preserving its user input. User deletion also removes its
associated replies; user edit removes later conversation and associated runs, retains the message id, and persists created_at as the latest submission time in both the response and message_updated event.
History mutations require an idle session. SQLite pruning and user text edits
commit in one transaction. Responses and history_pruned events return
deleted_message_ids/deleted_run_ids. Message-level retry is removed; individual
assistant/tool deletion is rejected. Referenced attachment cleanup follows commit.

ContextBuilder projects ordinary user/assistant history with none/current_message/
recent_messages/session/selected_message policies, message/character bounds and explicit
attachments. The selected Agent's nonempty system prompt is inserted once independently
of history mode; there is no include_system_prompt switch. The composer selects the concrete
model; the session dialog owns Agent, model, context, temperature and Knowledge settings. Selected-message context uses an explicit source message and clears on session changes. Context sources
are bounded data blocks, with compact diagnostics rather than copied content in metadata.

Workspace inserts its Project prompt after the Agent prompt and before Persona/Knowledge data, independently of history mode.
The singleton Cogita Persona is always active. Its trimmed nonempty system_prompt is
background data wrapped in <user_persona> tags and appended once to the system context;
empty text produces no block. The run snapshots this text before execution. Compact
user_persona metadata contains identity, injection status, length and empty skip reason,
never the content. General settings contain no Core Memory fields or enable switch.

Worldbook is deterministic matching over current user text and configured
keywords. Enabled entries obey entry/context limits, case sensitivity,
whole-word matching and recursion depth. Books/entries have explicit CRUD;
match-test is diagnostic and changes no session/run. It requires explicit worldbook_ids
and has no session target. Worldbooks have no ordinary-chat binding or injection path;
roleplay Persona/Timeline bindings are stored for later workflows. Cogita Persona, Worldbook,
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

Text parts choose plain text or Markdown; reasoning uses GFM when expanded and [single-line plain-text previews](runs-streaming.md) when compact.
Knowledge citation labels such as `[K1]` follow ordinary Markdown rendering,
without a citation-specific parser, source lookup or popover.

Large binary data belongs in the attachment store and is referenced by id/URL.
Uploads and serving use the configured attachment directory; General owns
size/count and text-context byte limits. Persisted parts retain ids, MIME,
name, size and compact metadata, never image data URLs. Orphan cleanup is an
explicit separate operation and considers current Persona avatars, not message/run avatar snapshots.

User images persist only as metadata.attachments references; message parts do not duplicate them.
ContextBuilder selects history by policy, message count and character budget before reading images.
Image bytes do not consume the text budget. History projection keeps images with their user message. Image-only messages can be selected context.
Included references become OpenAI image_url parts immediately before inference, including historical follow-ups.
Before first inference, local image support is checked unless skipped in request_options. Unknown support and provider inputs pass through.
Explicitly unsupported images are omitted from this request, including selected history; empty historical image messages are omitted. Original messages/attachments stay intact. The current user bubble receives an images_ignored warning; if the current input has no remaining text, images_require_text ends the run as FAILED without main/auxiliary generation.
Missing selected images return ATTACHMENT_NOT_FOUND; corrupt local images and request limits follow
[models](models.md#external-inference-api). Excluded or pruned images are never read.

Text-file context obeys the enable switch and per-file/per-message bounds.
Other attachments contribute bounded descriptive markers. include_attachments=none excludes all image inputs.
File selection, clipboard images and file dropping share an upload flow with per-file status, previews and removal.
Partial failure keeps successful uploads. Session changes clear pending attachments and ignore late results.
Message thumbnails and zoom previews resolve stored references after refresh. Request warnings, attachment-policy
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

The frontend renders one reply per run with its original Persona's current identity,
processing timeline, final answer and action bar. Only the current model round's
ordinary text appears as a provisional answer; tool-producing rounds move into
processing. Adjacent tools share a collapsed command group, with individually
collapsed arguments/results. Tool records have no separate avatars. Copy uses
answer text only. Context selection uses real message ids, including tool details.
Direct tool runs use this timeline without an invented model answer.
Assistant replies expose aggregated LLM usage after the action buttons and per-call statistics in a usage modal; auxiliary titles are excluded.
[Runs/streaming](runs-streaming.md#llm-statistics) owns their timing, persistence, completeness and display rules.

The frontend renders parts without executing or routing text. Markdown remains
content; edit/retry uses original text. MessageActions owns controls and
selected-context references; MessageParts owns presentation and attachment URLs.
Metadata may hold counts, source refs and warnings, never full part bodies, prompts or secrets. Stream merging belongs
to [runs/streaming](runs-streaming.md).

User messages use right-aligned gray secondary bubbles with 24px corners; assistant replies use open body layout. Assistant replies use current Agent identity; user rows use current Cogita Persona identity. User headers place time before the name; assistant headers place it after the name.
Assistant action buttons stay visible. On hover-capable fine-pointer devices, timestamps, user action buttons and reply usage metrics appear on message hover or keyboard focus,
fade in and out over 180ms (instantly with reduced motion), and retain layout space. Touch layouts keep them visible; editing keeps save/cancel visible and an open usage modal keeps its owner visible. Message bodies use 16px text with Markdown headings, lists, quotes, code, tables and media.
Markdown block code uses gray secondary Bubble surfaces with 24px corners and preserves preformatted text; inline code retains its compact styling. Message action tooltips open below their buttons without flipping above, including usage details. Wide code, tables and tool results scroll inside their own bounds; tool results are limited to 320px height on desktop and 240px below 768px.

Saving a user edit immediately restores the bubble with the submitted text while regeneration runs; request failure restores the editor and draft with the existing error feedback. Newly sent user bubbles animate once with a 300ms blur fade and 6px upward motion; historical loading, session switches and edits do not replay it. Reduced motion disables the animation.
User messages are MessageScroller anchors. A vertically centered left tick rail tracks the current turn, previews summaries on hover/focus and navigates to user messages; it scrolls internally and is hidden below 768px message-area width or with fewer than two user messages. Ticks have 8px center spacing, 2px thickness and a shared left edge; ordinary, immediately neighboring and active ticks are 12px, 18px and 24px wide. Only the active tick changes color. History reading pauses streaming follow; the latest-message button resumes it.
The InputGroup composer has 20px corners and circular buttons: an outlined plus opens the Photos & Files upload menu, an up arrow sends, and active runs expose stop. Empty or single-line drafts place buttons and text on one row; explicit newlines or wrapping expand the text above the toolbar. Deleting back to one line or clearing collapses it. Wrapping is measured at the compact text width, excluding the placeholder, and recalculated for content, width and font changes. The same textarea and toolbar stay mounted; height and text layout transition over 180ms ease-out, instantly with reduced motion. Expanded text starts at 56px and grows to min(12rem, 30dvh), then scrolls internally. Attachments and context remain outside the input and do not force expansion. Existing draft, upload and keyboard behavior remains; contextual drag/limit/error feedback remains, without a static image hint or service footer/health request.
The composer places a fully rounded model menu before send/stop, capped at 160px (120px below 640px), truncating long names. Text measurement reserves the actual action widths. One model group contains all LLM profiles with Local first and provider labels; unconfigured sources are separate. Disabled/missing selections remain visible without automatic replacement. A second group contains the immediate Harness toggle, its independent settings action and a disabled Reasoning placeholder. The menu stays accessible without eligible models. [Harness/tools](harness-tools.md) owns the session Sheet; selection/configuration saves block sending until settled.

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

First accepted input names an untitled session from its first 15 Unicode characters,
after trimming/collapsing whitespace, with an ellipsis only when truncated. Attachment-only
input uses the first filename. Explicit tool input receives only this basic title;
failed chat runs retain it. Explicitly supplied or manually edited titles are protected.
auto_generate_session_titles defaults on and controls auxiliary improvement only;
turning it off retains basic naming. The first chat input remains the sole title source.
ChatRunner publishes the completed response/run and releases the main model lease,
then requests an improved title with max_tokens=64, temperature=0, session_title_prompt
and a 1200-character input limit. Missing auxiliary selection, failed/empty output,
or concurrent manual renaming preserves the title without affecting chat success.
Later inputs do not request new titles. Auxiliary input excludes history, attachments,
Persona context, Worldbook and Knowledge. Existing title state/metadata identify the
input excerpt and originating input id or successful auxiliary generation.

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
