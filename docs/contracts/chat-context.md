# Chat and context contract

Chat uses explicit Personas, ContextBuilder and ChatRunner. Registered `/tool_name` inputs use the [direct executor](harness-tools.md); all other input is ordinary text.

## Personas and sessions

Personas are strict editable identity records: id, immutable collection, name, optional avatar_attachment_id,
system_prompt and timestamps. All four collections share CRUD and ordered bindings. Avatar filenames reference
local attachment-store bytes. Personas never execute agents, scripts, manifests or extension registrations.

| Collection | Settings page | Resources | Execution |
| --- | --- | --- | --- |
| user | Cogita Persona | Knowledge | Singleton background and display identity |
| agent | Agent Personas | Knowledge | Ordinary/Workspace assistant; optional QQ identity/prompt |
| roleplay_user | User Personas | Worldbook | Management and Timeline selection only |
| character | Character Personas | Worldbook | Management and Timeline selection only |

Migrations seed User (empty prompt) and Cogita (helpful-assistant prompt), with no roleplay defaults.
Both are editable but protected from deletion by stable ids and read-only is_protected. POST requires
a creatable collection; PATCH preserves collection. The Cogita singleton has no creation API, and its
category name does not replace its editable identity. Referenced Projects, sessions or unfinished runs block deletion.
Replies resolve current Agent identity from run.persona_id/message.speaker_id, storing ids without name/avatar snapshots.
Session selection preserves authorship; deleted Personas display a localized label/default avatar.
SessionResponse.user_persona supplies the singleton for ordinary/Workspace user rows; QQ returns null.
Identity edits/events refresh historical referencing sessions without rewriting history or captured run configuration.

Ordinary sessions have one persona_id, initially Cogita, accepting only agent records; no members, speaker lists,
conversation modes or group transcripts. New sessions persist a concrete model selection: omitted/null POST
model_profile_id selects the enabled global-default LLM, else the first enabled LLM by name/id, else null.
Explicit ids are validated without substitution. Global-default changes affect later sessions only; execution
uses the saved id (model_source=session). PATCH omission preserves it; null clears it. Adding a model leaves
unselected sessions unchanged. Both chat selectors show the saved model or a disabled empty/unavailable state,
without a Global default entry. Session initialization performs no model discovery, health check or inference.

New chat navigation opens a local ordinary/Workspace draft with configuration/Knowledge editing and no record/WebSocket.
Reopening preserves it; switching conversations/Projects or refreshing discards it. First send creates the session,
applies additions and submits captured input/attachments. Creation failure restores the draft; binding/send failure
retains its id for retry. Creation APIs remain immediate; [Runs/streaming](runs-streaming.md) owns input acceptance/restoration.

Ordinary/Workspace composers accept FIFO messages with uploaded attachments during replies/approvals.
Queues are per-session frontend memory: leaving stops dispatch, returning reconciles before continuing;
refresh/close clears them, and session/Project deletion discards them. Actual send time determines configuration.
Rows stack above the composer with two-line text, attachment summaries and edit/delete controls, scrolling within
min(15rem, 25dvh). They have no history number, immediate-send or reorder action. One edit at a time replaces
the composer's text/attachments and marks the original row Editing. Submit saves its original id/position;
a head edit blocks until saved/deleted, while a later edit permits earlier dispatch. Deleting an edit clears its composer.
Edits survive navigation; ordinary drafts retain their lifecycle. Upload results belong to the original session/edit.
Stop and enqueue coexist; editing labels submit Save queued message. Enter submits, Shift+Enter inserts a line,
and IME confirmation does not submit. Uploads must finish before enqueue/save. Removal releases local previews;
uploaded references retain existing cleanup. [Runs/streaming](runs-streaming.md#websocket-events) owns pauses/acceptance.

Ordinary context, generation, Harness and tool selection belong to the session. Context defaults to session history with explicit attachments.
Generation defaults to {} and accepts only optional temperature (0..2); a non-null value overrides the model. {} or temperature:null clears it; PATCH omission preserves it.
Other model generation parameters remain inherited and available in resolved configuration. Neither context nor generation is nullable.
The strict session reasoning boolean defaults true. The composer model menu toggles it immediately, preserving confirmed state on save failure; pending saves block sending. Draft selection persists through first send, and model changes preserve the choice.
Workspace overrides.reasoning accepts a boolean; omission/null selects true, independently of Project defaults. Ordinary PATCH omission preserves reasoning and null is invalid.
Before the first model round, local preflight may replace an explicitly unsupported mode with an explicitly supported alternative, unless the selected mode's check is skipped. Unknown support passes through. The user message saves reasoning_enabled/reasoning_disabled warnings and run metadata saves requested/effective modes; session selection and reasoning text remain unchanged. Public /v1 never adjusts modes.
Harness defaults off. Omitted tools_allowed selects all general-purpose built-ins; [] allows none, and saved lists do not change with the catalog. These settings never depend on Persona.

Ordinary/Workspace runs combine Knowledge in Cogita Persona, Agent, Workspace Project, then session-addition order,
deduplicating by first occurrence. Clearing additions preserves inheritance; Agent changes preserve additions/overlaps.
Retrieval receives resolved ids and respects resource enablement/limits. Worldbook belongs only to roleplay_user/character
Personas and Timeline Projects, without ordinary/Workspace injection. Wrong resource combinations return 422.

Projects share global resource catalogs but isolate sessions, history and configuration.
Project.kind is immutable workspace|timeline|qqbot. Workspace requires agent_persona_id,
the fixed singleton cogita_persona_id, context_policy, harness_enabled and tools_allowed;
system_prompt, model_profile_id, temperature (0..2) and ordered knowledge_base_ids are optional.
Timeline requires character_persona_id, roleplay user_persona_id and context_policy;
model_profile_id, temperature and ordered worldbook_ids are optional. Harness, Knowledge
and Project prompts are not Timeline fields. Timeline supports CRUD/settings only;
session creation/listing returns PROJECT_CHAT_UNAVAILABLE (409). Persona/Worldbook injection
and per-speaker historical identity for Timeline conversations remain unimplemented.

Session.kind and project_id follow the creation location and cannot be changed or moved.
Ordinary, Workspace and QQBot have distinct schemas; timeline is a reserved session identity.
Workspace sessions store only sparse overrides for persona_id, context_policy, model_profile_id,
temperature, reasoning, harness_enabled and tools_allowed. PATCH accepts title/overrides; omission keeps
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
| `/api/projects/{id}/sessions` | Workspace/QQBot creation and scoped listing |
| `/api/sessions` and `/{id}` | Ordinary creation/listing; individual ordinary/Workspace configuration |
| `/api/sessions/{id}/knowledge-bases` | Additions, Cogita/Agent/Project bindings and effective ids |
| `/api/sessions/{id}/messages` | New input |
| `/api/sessions/{id}/history`, `/history/users` | Bounded conversation and user-navigation pages |
| `/api/messages/{id}`, `/edit` | User-message deletion and edit |
| `/api/runs/{id}`, `/{id}/retry` | Whole-reply deletion and chat retry |

References are validated before persistence: unknown/removed fields return 422; missing/conflicting references return structured 404/409.
Waiting approval blocks new input/direct calls; overlapping execution returns SESSION_BUSY. The approval API resumes the same run.

Deleting a different session from the sidebar preserves the current conversation,
draft. Deleting the current session selects its first remaining
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
History mutations require an idle session. Edits require content and attachment_ids (the unique subset of original attachments to retain, in original order); [] removes all attachments. Empty text with no retained attachments returns EMPTY_MESSAGE; invalid ids return INVALID_ATTACHMENTS. Editing cannot add attachments.
SQLite pruning, text, attachments, timestamps and history_version commit together. Responses and history_pruned events return deleted_message_ids/deleted_run_ids. Message-level retry and individual assistant/tool deletion are rejected. Referenced attachment cleanup follows commit.

ContextBuilder projects current-session history with max_messages (0..10000), max_chars (1..1000000), defaulting to 100 messages / 100000 characters, and include_attachments=explicit. Explicit null retains all
eligible history; zero messages excludes history; positive N keeps newest N excluding current input.
Characters deduct current input first and retain whole recent messages; oversized current input
stays with a warning. mode/source_message_id return 422; Workspace inherits/overrides the whole
policy. Agent prompts are inserted independently of history limits. Provenance follows projection;
[context snapshots](runs-streaming.md#context-detail) preserve each call privately, outside metadata.
SQLite reads eligible history in batches of 128 and stops at count/character limits; zero skips history reads. Window-external exclusions aggregate counts, including empty projections with no message limit; turn identities use identity-only lookups. Existing explicit policies are unchanged. Both limits null may grow memory with history; character-only limits do not bound image-only history, and row counts do not bound single-message size.

Every internal model call enforces input tokens + output reserve + margin <= effective window.
Runs snapshot the configured window and output reserve. Unset maximum output reserves
min(4096, floor(configured window / 4)) and sends it as max_tokens; explicit limits are never reduced.
Local native counts reserve 32 tokens; provider estimates reserve max(128, ceil(window * 0.1)).
Missing provider windows return CONTEXT_WINDOW_REQUIRED. Counting covers the final translated
request, including images and tool definitions, within the existing model lease. Oldest history
turns are removed as complete groups after message/character filters, without restoring exclusions
or changing stored messages. A bounded suffix search recounts the final selection. Current input,
configured instructions, Knowledge and active run tool records stay intact. If they do not fit,
CONTEXT_WINDOW_EXCEEDED ends the call before dispatch. Counting failures return CONTEXT_COUNT_FAILED;
these request failures do not mark the model broken. Sources, token_limit exclusions and attachment
references describe the retained request. Summaries, tool-result compression and draft previews
remain unimplemented.

The [context meter](runs-streaming.md#context-detail) displays actual per-call input plus output usage beside the model selector. Input reflects history limits and token trimming; policy edits affect the next request, not recorded usage.

Workspace inserts its Project prompt after the Agent prompt and before Persona/Knowledge data, independently of history limits.
The singleton Cogita Persona is active in ordinary/Workspace chat. Its trimmed nonempty system_prompt is
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

Worldbook settings have Configuration, Entries and Match test tabs; existing/newly saved books open Entries.
Entry headers contain a reorder handle, disclosure, enabled switch, name, dirty marker, mode and delete;
bodies contain name/mode, keywords, content and save/reset/delete. Drafts and save/reset are per entry.
Switches PATCH only enabled, rolling back failure without discarding drafts. Pointer/touch/keyboard handles
PATCH the full ordered id list with rollback; duplicate/mismatching ids return 422. Both stores validate complete
Worldbook/entry PATCH objects before committing, including regex/name/content. Entry CRUD uses
/api/worldbooks/{id}/entries and /api/worldbook-entries/{id}; ordering uses /api/worldbooks/{id}/entries/reorder.
POST /api/worldbooks/match-test returns counts, triggers, recursion and bounded previews.

[Knowledge](knowledge.md) owns retrieval and injection using the run's resolved bindings; attachment rules below own file/image context.

## QQBot conversations

QQBot Projects own bot_account, ws/wss websocket_url, write-only access_token, connection_enabled, image_input_enabled, optional image_description_model_profile_id, optional Agent, Project prompt, explicit external LLM, temperature, reasoning, context policy, keyword reply mode and input/reply limits.
Defaults: disconnected, no Agent/model, empty keywords, reasoning on, input batch size 20 (1..200), reply_message_limit 4 (strict integer, 1..20). Both limits are public Project settings; omitted PATCH fields are retained and null is invalid.
New Projects use an editable, brief conversational prompt: stay on topic, match the participants' language, usually reply once and follow the selected Persona. API omission selects English; explicit empty text stays empty. Existing prompts are preserved.
Connecting requires an external LLM with no global fallback. Accounts belong to one Project and cannot change while Sessions are bound. An omitted token preserves it; an empty token removes it. Reads expose only has_access_token. URL credentials/query/fragment are rejected.
QQ Sessions bind an immutable group|friend and positive decimal-string target_id, unique per Project; only title is editable. Sessions use Project settings at execution time and Agent identity/prompt only; Cogita Persona, Knowledge, Worldbook, manual attachments and overrides are excluded. Resource APIs reject QQ targets.
Resolved configuration snapshots the bot account, target and reply limit. Each model call adds a separate qq_runtime source with the batch id and current confirmed count; [Harness/tools](harness-tools.md#qq-delivery-and-queues) owns its rules.
Only bound conversations are recorded, retaining sender identity, UTC-offset time, mention/reply references and ordered image/sticker/system-face positions from arrays or CQ strings. Literal placeholder text is never interpreted as media; old placeholder-only records are not backfilled.
Incoming share segments use title/url; JSON link cards use meta.news.title/jumpUrl with top-level prompt as the title fallback. They become [分享链接: title (url)]. JSON payloads accept objects or JSON strings in data.data; lightapp also accepts data.content. Small-app cards are lightapp segments or JSON apps prefixed com.tencent.miniapp: they use prompt, then meta.detail_1.title, and the first nonempty qqdocurl/jumpUrl/url in detail_1, becoming [小程序: prompt (url)].
Card fields accept strings only, trimming and collapsing whitespace. Missing URLs omit parentheses; URL-only cards show [type: url], and recognized empty cards show [分享链接] or [小程序]. Unknown or malformed JSON stays [非文字消息] without discarding adjacent segments. These positional text markers reach display, saved batches and model history without raw JSON or link fetching. Existing records are not backfilled; live NapCat card reception remains unverified.
The strict Project image_input_enabled switch defaults to false; omitted PATCH preserves it, while null/non-booleans return 422. History always saves/displays images. The switch alone derives effective context_policy.include_attachments, captured before batch execution waits. Only the current batch can send images through core/models: among available images, take the last five pictures, then the last stickers filling remaining slots, counting occurrences and preserving their original positions. System faces never consume slots or send image bytes; they use [QQ表情：name], or [QQ表情] for unknown names. Historical, over-limit, disabled and unavailable pictures/stickers use [图片：description]/[表情包：description], omitting the colon and description when absent. Each new context reads current shared descriptions; a run and its captured requests retain their built context.
QQ `/messages` returns strict ordered text/image segments alongside summary text. Image segments expose media_id, nullable shared asset_id/description, image|sticker|face kind, pending|ready|failed state, label, original attachment and error_code; download addresses, model derivatives and internal paths stay private. Acquisition and its ten-second batch wait belong to [Harness/tools](harness-tools.md#qq-delivery-and-queues). The optional image_description_model_profile_id defaults null; PATCH omission preserves it and null clears it. It accepts enabled external LLMs, participates in model-reference protection and is captured before batch waits. With image input enabled, the completed context schedules descriptions only for its selected, undescribed resources (at most five distinct assets), once per batch. Description generation belongs to [Harness/tools](harness-tools.md#qq-delivery-and-queues). Description writes advance history_version in every referencing Session, refreshing loaded historical media. Image and preview alt text use the description when present; all pictures, animations and system faces remain visible regardless of model selection. No manual description API/editor is provided.
Group keywords match case-insensitive substrings over text and normalized real `@QQ-id` segments; configuring `@bot-id` matches that mention. Name lookup, quotes, media and card fields do not trigger independently.
Keyword matches grant senders a new 60-second Session eligibility epoch; their ordinary messages trigger follow-ups. Empty keywords prevent new grants; private messages always require replies. Participant arrivals extend silence by five seconds from receipt; bystanders join without extending it. Membership lasts until freezing, even after eligibility expires. Both durations are fixed.
Expiry precedes arrivals exactly at the deadline. Any keyword in the window makes the batch mandatory before truncation; freezing takes the newest configured count of unassigned messages and marks older records skipped. Batch policy and submitted speakers' participant epochs are immutable; [Harness/tools](harness-tools.md#qq-delivery-and-queues) owns reply/skip updates.
Batch text stays raw; submission saves one projected input of `[time][name (QQ:id)]:content` lines. Ordinary messages after eligibility expiry cannot open new windows, while already triggered windows/queued batches remain valid.
Real at segments save code-point spans, ids, names and self flags in references_json; typed mentions stay literal, and references without spans are not reconstructed. Models receive names/ids with a self marker; display uses names plus ids/self in status details. at=all means everyone. Display and submission project names asynchronously outside the socket reader; submission freezes names/input against later renames, without affecting triggers.
Name lookup prefers observed same-conversation senders, then get_group_member_info (card before nickname), get_stranger_info for private names, or verified login information for self. The per-Project cache holds 1024 conversation/member entries for 600 seconds, or 60 after failure. Shared queries allow four concurrent calls and two seconds per page/batch; failure/offline retains ids without pausing.
QQ history projects confirmed deliveries as native assistant qq_send_message calls with matching receipts and stable delivery-derived ids, without duplicate prose. Earlier sends survive failed/cancelled runs. Skipping a reply retains its submitted input but excludes the skip tool from history; unsubmitted/truncated inputs, internal prose and failed/unknown sends are excluded.
Remaining input batches and confirmed sends are selected/pruned together. max_messages counts nonempty saved inputs/sends, not expanded protocol messages; character/token budgets include expanded tool data. Historical pairs are never executed. [Harness/tools](harness-tools.md#qq-delivery-and-queues) owns execution/recovery.
`/api/qq/projects/{id}/status` reads connection state; `/api/qq/sessions/{id}` reads binding/pause state, busy and history_version. Its `/messages`, `/batches` and `/deliveries` return history_version and newest-first integer before cursors, default 50/max 100; `/control` accepts pause|resume|stop. Batches expose trigger_kind=keyword|followup|private; participant epochs/window internals stay private.
Each original incoming message has its own right-side secondary bubble, including image-only messages. Identity headers group consecutive sender IDs within 120 seconds of the group start, interrupted by a different sender or model reply. Only the first row has an avatar, name and time; continuations have no header and a 6px gap. Outside icons retain each message's pending/batched/skipped state and stored timestamps are unchanged.
Each run appears once on the left with processing, usage/context detail, original time and delivery states; batch inputs are not duplicated. Delivery bubbles have no headers or times, with 6px gaps and 8px after the model action area. Older records load into the same conversation without tabs or pagination controls. Both locales show reply-limit completion, legitimate skips without delivery bubbles and missing-reply failures/pauses.
The composer keeps input disabled and shows a localized "Chatting in {targetId}" hint for groups and friends, without a Persona name. The header shows the title without a separate target number or run controls.
Outlined icon/text pause/resume and stop buttons replace attachment/send controls on the left; context usage and the model menu remain on the right. The hint shares their row when it fits and expands above the toolbar otherwise, measured against both control groups without hiding the hint.
The model menu selects external-provider LLMs and toggles reasoning by patching only that Project field. All bound Sessions inherit Project setting changes for later-starting batches; active runs retain their snapshots. Harness remains mandatory with no toggle/settings entry. Pending saves block duplicate configuration edits but not Stop; failures preserve confirmed settings with visible feedback, and late responses preserve subsequent navigation. Session/Project deletion requires idle state.
DELETE `/api/qq/sessions/{id}/messages/{message_id}` or `/deliveries/{delivery_id}` removes only that local bubble and its future context contribution. All history deletions require an idle run/batch; running Sessions return SESSION_BUSY (409), missing or mismatched records return 404. Ordinary send, direct tools, editing and regeneration remain rejected and hidden.
Incoming deletion rebuilds raw batch text and saved input from remaining records with original timestamps and frozen mentions. Empty queued batches are cancelled; empty submitted inputs are omitted while remaining delivery pairs survive. Delivery deletion also removes its saved assistant message and both historical protocol records. Deleted ingress/receipt identities remain private for deduplication; status, participant eligibility, other messages and historical send counts are unchanged.
DELETE `/api/runs/{id}` removes a QQ reply, all its delivery bubbles, messages, steps, events and private state, clearing its batch run reference while preserving inputs. SQLite deletion, input updates and history_version commit together. Deletion never recalls QQ messages, sends, regenerates or resumes execution. Retained replies and recorded request snapshots are not rewritten.
Incoming rows place delete/status/bubble from left to right; delivery rows place bubble/status/delete. Bubble delete buttons appear on row hover/focus with reserved space and the existing 180ms/reduced-motion rules; touch keeps them visible. The model action group has a permanent delete action. Every deletion confirms its scope; busy/pending mutations disable deletion, and failure retains the records with visible feedback.
QQ bubbles render ordered segments in place: ordinary images fit within 240px, stickers within 160px, and system faces use 24px inline images, constrained by bubble width. Original animations play and images open the shared preview; pending/failed markers retain their position. QQ polling also refreshes loaded older messages with pending media even when batched/skipped. It reconciles changed history versions across the loaded range and invalidates completed-run caches. Pre-deletion or mixed-version responses cannot restore removed records; session navigation isolates late responses.

## Messages and attachments

Messages use content_version=2 and validated parts; [Runs/streaming](runs-streaming.md) owns their visible session numbering. The strict message schema
owns role, speaker identity, run/parent references and compact metadata.
Supported parts are text (plain/markdown), reasoning, json, file (inline_text or
attachment_ref), image, audio, video, media_group image galleries, notice,
error, tool_call and tool_result. Unknown types are rejected; there are no
forms, actions, command buttons or diff parts.

Text parts use plain text/Markdown; reasoning uses expanded GFM or compact [plain-text previews](runs-streaming.md). Knowledge citations such as `[K1]` use ordinary Markdown without a dedicated parser, lookup or popover.

Large binary data belongs in the attachment store and is referenced by id/URL.
Uploads and serving use the configured attachment directory; General owns
size/count and text-context byte limits. Persisted parts retain ids, MIME,
name, size and compact metadata, never image data URLs. Orphan cleanup is an
explicit separate operation and considers current Persona avatars, not message/run avatar snapshots.

User images persist only as metadata.attachments references; message parts do not duplicate them.
ContextBuilder selects history by message count and character budget before reading images.
Image bytes do not consume the text budget. History projection keeps images with their user message. Image-only messages remain eligible history.
Included references become OpenAI image_url parts immediately before inference, including historical follow-ups.
Before first inference, local image support is checked unless skipped in request_options. Unknown support and provider inputs pass through.
Explicitly unsupported images are omitted from this request, including retained history; empty historical image messages are omitted. Original messages/attachments stay intact. The current user bubble receives an images_ignored warning; if the current input has no remaining text, images_require_text ends the run as FAILED without main/auxiliary generation.
Missing retained images return ATTACHMENT_NOT_FOUND; corrupt local images and request limits follow
[models](models.md#external-inference-api). Excluded or pruned images are never read.

Text-file context obeys the enable switch and per-file/per-message bounds.
Other attachments contribute bounded descriptive markers. include_attachments=none excludes all image inputs.
File selection, clipboard images and dropping share per-file status, previews and removal; partial failure keeps successful uploads. Session changes clear ordinary pending attachments; queue edits retain theirs.
Composer images use 120px vertical Attachment cards with names, types and sizes; other files use horizontal cards, bottom-aligned with image cards. Sizes use uploaded File.size then persisted size, in 1024-based B/KB/MB/GB with at most one decimal. Image removal uses a circular top-right button.
User metadata.attachments render as right-aligned scrolling groups: files above the text bubble and images below it, preserving order within each group. Images use 160px preview cards without visible names/sizes; file cards retain both. Attachment-only messages have no empty bubble; image/file-only messages remain eligible history.
Editing uses the same file/body/image order with removal buttons; cancellation restores originals and failed saves retain the draft. Regeneration uses only retained attachments. Cleanup after commit preserves references from messages, Personas, Knowledge and model-input snapshots.
Thumbnails and zoom previews resolve stored references after refresh. Request warnings, attachment-policy and size errors have English/Chinese guidance; retries retain the message's saved attachments.

Tool calls require assistant role, run-unique call id, name and finite JSON object arguments, with distinct part ids per message. Results require tool role, matching call id, success/error/rejected/cancelled status, optional JSON data/errors and truncation flag.
Live loops use native assistant/tool pairs. Ordinary/Workspace history quotes tool parts as data, permitting truncation without orphan protocol calls or promoting data to system/developer instructions. QQ uses the confirmed-delivery pairs described above, excluding other internal tool history.

Reasoning is assistant-only strict {id,type:reasoning,text} data. The output normalizer accepts reasoning_content and incrementally extracts <think> markers, including split tags; Markdown inline/fenced/indented code and escapes stay literal.
Only internal chat extracts markers; /v1 preserves content. Reasoning/incomplete messages are excluded from history; live tool transcripts retain upstream content/structured reasoning for provider continuation.
[Runs/streaming](runs-streaming.md) owns replies, provisional answers, processing/reasoning, command groups and usage. Replies retain original Persona identity; copy uses answer text only, and direct tools never invent a model answer.

The frontend renders parts as content without execution/routing; edit/retry uses original text. MessageActions owns controls,
MessageParts owns presentation, ChatAttachments owns cards/URLs, and [runs/streaming](runs-streaming.md) owns stream merging.

User messages use right-aligned gray secondary bubbles with 24px corners; assistant replies use open body layout. Assistant replies use current Agent identity; user rows use current Cogita Persona identity. User headers place time before the name; assistant headers place it after the name.
Assistant action buttons stay visible. On hover-capable fine-pointer devices, timestamps, user action buttons and reply usage metrics appear on message hover or keyboard focus,
fade in and out over 180ms (instantly with reduced motion), and retain layout space. Touch layouts keep them visible; editing keeps save/cancel visible and an open usage modal keeps its owner visible. Message bodies use 16px text with Markdown headings, lists, quotes, code, tables and media.
Markdown block code uses gray secondary Bubble surfaces with 24px corners and preserves preformatted text; inline code retains its compact styling. Message action tooltips open below their buttons without flipping above, including usage details. Wide code, tables and tool results scroll inside their own bounds; tool results are limited to 320px height on desktop and 240px below 768px.

Saving a user edit immediately restores the bubble with the submitted text while regeneration runs; request failure restores the editor and draft with the existing error feedback. Newly sent user bubbles animate once with a 300ms blur fade and 6px upward motion; historical loading, session switches and edits do not replay it. Reduced motion disables the animation.
User messages are MessageScroller anchors. A vertically centered left tick rail tracks the current turn, previews summaries on hover/focus and navigates to user messages; it scrolls internally and is hidden below 768px message-area width or with fewer than two user messages. Ticks have 8px center spacing, 2px thickness and a shared left edge; ordinary, immediately neighboring and active ticks are 12px, 18px and 24px wide. Only the active tick changes color. History reading pauses streaming follow; the latest-message button resumes it.
The InputGroup composer has 20px corners and circular buttons: an outlined plus opens the Photos & Files upload menu, an up arrow sends, and active runs expose stop. Empty or single-line drafts place buttons and text on one row; explicit newlines or wrapping expand the text above the toolbar. Deleting back to one line or clearing collapses it. Wrapping is measured at the compact text width, excluding the placeholder, and recalculated for content, width and font changes. The same textarea and toolbar stay mounted; height and text layout transition over 180ms ease-out, instantly with reduced motion. Expanded text starts at 56px and grows to min(12rem, 30dvh), then scrolls internally. Attachments and context remain outside the input and do not force expansion. Existing draft, upload and keyboard behavior remains; contextual drag/limit/error feedback remains, without a static image hint or service footer/health request.
The composer places a fully rounded model menu before send/stop, capped at 160px (120px below 640px), truncating long names. Text measurement reserves the actual action widths; the placeholder uses a fitting short label or hides when necessary, retaining its full accessible name. One model group contains all LLM profiles with Local first and provider labels; unconfigured sources are separate. Disabled/missing selections remain visible without automatic replacement. A second group contains the immediate Harness toggle, its independent settings action and the immediate Reasoning toggle. The menu stays accessible without eligible models. [Harness/tools](harness-tools.md) owns the session Sheet; selection/configuration saves block sending until settled.

## Auxiliary tasks and titles

UtilityLLMService uses ModelManager's queue, lifecycle and status with no separate backend,
public route or message/run records. Its only selector, utility_model_profile_id, must be an
enabled LLM UUID; absence/failure returns UTILITY_MODEL_UNAVAILABLE without borrowing chat's model.
generate_text sends only the supplied prompt without streaming. generate_json parses the entire
response and validates its Pydantic schema; fenced/embedded JSON, tool calls and invalid output
return UTILITY_OUTPUT_INVALID.

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

OpenAPI covers Personas, configuration, parts, bindings, paginated history and Worldbook; private snapshots remain excluded.
Responses preserve optional-field omission, explicit nulls and existing PATCH/error behavior.
Message/run timestamps retain UTC Z and microseconds; Worldbook keeps +00:00. Uploads document
one multipart file; downloads document stored-MIME bytes, Range, 200/206 headers and empty 416.
