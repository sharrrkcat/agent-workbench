# Chat and context contract

Chat uses explicit Personas, ContextBuilder and ChatRunner. Registered `/tool_name` inputs use the [direct executor](harness-tools.md); all other input is ordinary text.

## Personas and sessions

Character is the AI identity and mandatory owner of Sessions. Persona is an independent user identity.
Personas have name, avatar_attachment_id and background; Characters have name, avatar_attachment_id,
system_prompt and immutable kind=normal|qqbot, explicitly selected on creation. Each Session has a
nonempty immutable character_id and derives its normal/QQ type from that owner. Sessions cannot move
between Characters or select another responding Character.

User is the editable, protected default Persona with empty background. Cogita is the editable,
protected normal Character with empty system_prompt. Runtime bootstrap creates Cogita once through
the regular creation service. Neither default implies a personality. Protocol and context instructions
remain application-owned. Persona avatars and Character avatars reference local attachments.

Normal Characters own defaults for persona_id, model_profile_id, temperature, reasoning,
context_policy, harness_enabled, tools_allowed, memory_enabled, memory_learning, knowledge_base_ids and worldbook_ids. Sessions save
sparse overrides of those fields. PATCH omission preserves a field; null removes its override;
false, zero and [] are explicit values. Lists and context policies replace whole values. Parent edits
immediately affect inheriting Sessions, preserving explicit overrides. Responses expose effective
configuration and character|session sources; bound Persona uses binding and temperature may use model.

Default Persona is User, reasoning is true, Harness is false, resources are empty, and the tool list
captures currently available general tools at Character creation. The tool list is a default,
not a permission ceiling. Execution retains tool scope, permissions and approvals.
Only temperature (0..2) is a conversation-level generation parameter; absent temperature uses the
selected model's parameters, as do other generation options.

Omitting model_profile_id when creating a normal Character selects the enabled global default LLM,
then the first enabled LLM by name/id, or null. Explicit null means no model. This selection happens
once; later model creation or global-default changes never replace it. Execution resolves only
Session > Character. Missing/disabled selections remain unavailable. Creation performs no discovery,
model loading or inference.

Knowledge and Worldbook mounts are configuration only. Normal chat, Harness, retry and compaction
never retrieve, match, inject or budget mounted resources. Independent resource management, indexing,
explicit Knowledge search and Worldbook match tests remain available. Durable memory below is independent of these mounts.

New chat opens a local draft under its Character without creating a Session or WebSocket. First send
creates the Session with all overrides atomically and submits captured input/attachments. Creation
failure restores the draft; an unaccepted send failure retains the created Session for retry.
Repeated draft navigation preserves it; switching locations or refreshing discards it.

Normal composers accept FIFO queued messages and attachments during replies/approvals. Queues live
in browser memory per Session; leaving stops dispatch and returning reconciles before continuing.
Refresh/close clears them; deleting their Session or Character discards them. Actual submission time
determines Persona and configuration. Queue rows keep two-line text, attachment summaries, edit/delete
controls and no history number. Only one row can be edited; saving retains its id/position. A head edit
blocks dispatch, while editing a later row permits earlier messages. Uploads retain the original
session/edit destination and must finish before submission. Enter submits, Shift+Enter inserts a line,
and IME confirmation does not submit. [Runs/streaming](runs-streaming.md) owns acceptance and pauses.

New normal user messages store the effective Persona in speaker_id; assistant messages store the
fixed Character. History resolves current names/avatars by those ids, without per-message identity
snapshots. The first accepted normal input atomically binds bound_persona_id with its message and Run;
attachment-only input and identity-bearing direct tools also bind. Rejected/unsent input does not.
Failure, clearing history, default changes and override resets never unlock it. Name/background edits
remain effective for later Runs. Bound Sessions and live memories block Persona deletion in addition
to Character defaults, explicit selection and unfinished Runs. Historical labels retain deleted-source handling.

Character deletion requires every execution, approval and QQ operation idle. It removes its Sessions
and conversation state while preserving shared resources. Deleting the current normal Session selects
a sibling or opens a draft under the same Character; QQ keeps an empty binding state. Deleting the
current Character returns to Cogita. Delayed reads/deletions/creations preserve later navigation.

[QQBot](qqbot.md) owns its Character configuration, immutable group/friend bindings and delivery.
QQ Sessions accept title edits only; no Persona, ordinary overrides, mounts, Harness switch or manual send.

| Endpoint | Ownership |
| --- | --- |
| `/api/personas` and `/{id}` | User Persona CRUD; no collection or resource endpoints |
| `/api/characters` and `/{id}` | Strict normal/QQBot Character CRUD |
| `/api/characters/{id}/sessions` | Owned Session creation and listing |
| `/api/sessions/{id}` | Individual read/update/delete; normal title/overrides or QQ title |
| `/api/sessions/{id}/messages` | Normal input |
| `/api/sessions/{id}/history`, `/history/users` | Bounded conversation and user navigation |
| `/api/messages/{id}`, `/edit` | User-message deletion and edit |
| `/api/runs/{id}`, `/{id}/retry` | Whole-reply deletion and chat retry |

Old Project and standalone Session creation/listing paths have no forwarding routes. Unknown/removed
fields return 422; missing/conflicting references return structured 404/409. Waiting approval blocks
new input/direct calls; overlapping execution returns SESSION_BUSY. Approval resumes the same Run.

## Durable memory

Each fact belongs to one Character and one Persona, optionally a Session. Character records stay local;
General retains a source Character and crosses Characters only for the same Persona. There is no
all-Persona audience. Manual records can omit Session; model records cannot.
Original attribution is preserved separately from current ownership when records are transferred.
Defaults are memory_enabled=true, memory_learning=manual, external isolation off and shared Sessions.
Read/learning preferences follow Character defaults and sparse overrides; all memory-tool switches share memory_learning, with manual preserving recall but disabling the tools. memory_isolation is Session state.
Session modes shared/block_outgoing/block_incoming/isolated independently permit imports/exports.
Own records remain eligible; incoming blocks exclude General. Character memory_external_isolation
blocks General without blocking same-Character records. All existing active records follow current
origin policy dynamically. Every read filters Persona, status and scope before scoring, counts and paging.
History-off can still read enabled durable memory. Memory-off disables recall/model capture but keeps
facts and manual management. Persona filters are context boundaries, not authenticated user accounts.
Administrative /api/memories supports CRUD, origin_session_id filtering and selected-revision /{id}/publish; Session list/search
and ID reads use /api/sessions/{id}/memories. Unknown/inaccessible IDs return the same unavailable error.
Manual edits create user-managed records protected from model writes. General publication creates an
independent version copy; local edits/isolation/deletion do not synchronize it. Repeating a live
publication of the same source revision reuses it. Summary/body limits are 160/2,000 characters.
Model writes retain the producing Run and no message evidence; pruning that Run makes them needs-review.
Existing message-linked facts still follow source edit/delete; user-managed facts are independent. Forget removes content/indexes, retaining body-free tombstones.
Deleting normal owners uses memory-deletion-preview and explicit revision-checked choices. Session
keep detaches Session ownership and makes all kept facts user-managed Character-shared records for
the same Persona. Character keep requires transfer to another normal Character or publication to
General. Existing General copies independently require keep/delete. Original IDs survive deleted
sources; needs-review survives transfer. Memory and owner removal share the persistence transaction.
Recall prefers pins, literal matches, then bounded recent facts; SQLite-local Latin words/CJK character
n-grams share normalization with the in-memory store. No embedding or auxiliary extraction is required.
Injected facts and retained memory-tool content share min(1,024 tokens, 10% of input budget, remaining
capacity); model counting removes complete facts/tool pairs before history maintenance and dispatch. Memory is user-role evidence.
[Harness](harness-tools.md#durable-memory-tools) owns model capture; [Runs](runs-streaming.md) owns commit outcomes.
Memory references invalidate consuming checkpoints; version checks prevent stale summary commits.
Memory-tool payloads are excluded from ordinary history and compaction. Saved request snapshots are
inspection records. Old assistant prose can retain repeated facts; forgetting is not transcript erasure.
Literal recall misses paraphrases; a producing Run does not prove factual support. QQ, vectors, automatic
consolidation and auxiliary-model extraction remain deferred. Knowledge/Worldbook mounts stay inactive.

## Configuration snapshots and context

Each run privately stores the resolved chat configuration in
config_snapshot_json, with explicit character_id and persona_id. Character prompt, Persona background,
model, mounts, tools, generation and context remain fixed through edits and approval waits. Public metadata exposes
only identities, model selection, context policy, limits and binding ids.
Retry and user-message edit resolve the original user message's Persona using its current background,
while re-resolving other configuration and preserving the Session's selection. A deleted original Persona fails before pruning. It
keeps the input user message and deletes the selected run plus all later
conversation messages/runs. Tool runs cannot be retried as model answers.
DELETE /api/runs/{id} deletes only that reply's messages, steps, events and
private state, preserving its user input. User deletion also removes its
associated replies; user edit removes later conversation and associated runs, retains the message id, and persists created_at as the latest submission time in both the response and message_updated event.
History mutations require an idle session. Edits require content and attachment_ids (the unique subset of original attachments to retain, in original order); [] removes all attachments. Empty text with no retained attachments returns EMPTY_MESSAGE; invalid ids return INVALID_ATTACHMENTS. Editing cannot add attachments.
SQLite pruning, text, attachments, timestamps and history_version commit together. Responses and history_pruned events return deleted_message_ids/deleted_run_ids. Message-level retry and individual assistant/tool deletion are rejected. Referenced attachment cleanup follows commit.

Normal/QQ context_policy defaults to history_enabled=true, strategy=token_budget and include_attachments=explicit.
Its parameter groups are compaction={enabled:true,trigger_percent:80,target_percent:55,max_summary_tokens:null}, message_window={max_messages:100}, and retrieval={trigger_percent:80,target_percent:55,max_checkpoint_tokens:null}.
Strategies are token_budget, message_window and history_retrieval. Counts are strict integers (message limit 1..10000); percentages satisfy 0 < target < trigger < 100; token caps are null or positive integers.
Top-level max_messages/max_chars, mode and source_message_id are rejected. Each normal Session inherits/overrides the whole policy; inactive parameter groups remain saved.
History off omits old history and checkpoints; current Harness work can still compact/reset. Automatic compaction off reuses summaries and permits token pruning.
Message-window mode keeps up to N eligible historical messages, omits a split oldest turn, and can retain fewer after token counting. It never reads, injects or updates summaries or retrieval memory.
Token-budget mode validates and reuses its saved summary. No strategy silently falls back to another.
On-demand history requires Harness, including with an empty business-tool list, and always maintains its window automatically. It uses working checkpoints and bounded original-history retrieval instead of summary inference; [Harness](harness-tools.md#on-demand-history) owns its tools, windows, recovery and limits.
Its checkpoint allowance defaults to min(2048,max(128,floor(B/10))), shared by conversation memory and run progress. Model counting includes referenced text; oversized existing memory remains stored and is available by reference.
Settings share a strategy selector: message mode shows its count, token mode its compaction controls, and on-demand mode its trigger/target/checkpoint cap. The third option requires effective Harness; execution rechecks the requirement without changing the saved strategy.
Controls remain editable with history off except the historical message count; advanced controls start collapsed. Character instructions and Persona background remain independent of history selection.
SQLite reads history in pages of 128 with stable timestamp/message-id boundaries and identity-only turn lookups. Only candidate recent history and a summary batch are retained; a single stored message can still be large.
Eligible user input from failed/cancelled turns remains; errors, incomplete assistant output and internal context-tool records are excluded. Mixed tool messages retain their business data.
Web history uses bounded evidence, never full page caches. Original messages and attachments remain unchanged.

Every internal model call enforces input tokens + output reserve + margin <= effective window.
Runs snapshot the configured window and output reserve. Unset maximum output reserves
min(4096, floor(configured window / 4)) and sends it as max_tokens; explicit limits are never reduced.
For providers that count reasoning within completion tokens, that reserve covers reasoning and answer together.
Local native counts reserve 32 tokens; provider estimates reserve max(128, ceil(window * 0.1)).
Missing provider windows return CONTEXT_WINDOW_REQUIRED. Counting covers the final translated
request, including images and tool definitions, within the existing model lease. Oldest raw history
turns can be removed as complete groups in message-window mode, when automatic compaction is off or during later Harness calls.
A bounded suffix search recounts the final selection. Summaries, current input,
configured instructions stay intact. [Harness](harness-tools.md#loop-approval-and-cancellation) may summarize completed tool prefixes before this final selection; remaining tool pairs stay intact. If they do not fit,
CONTEXT_WINDOW_EXCEEDED ends the call before dispatch. Counting failures return CONTEXT_COUNT_FAILED;
these request failures do not mark the model broken. Sources, token_limit exclusions and attachment
references describe the retained request.

For token-budget strategy, before the first answer call ContextCompactionService evaluates B = window - output reserve - margin.
Above trigger_percent of B it selects a complete recent-turn suffix toward the soft target_percent of B.
It releases counting admission before calling core/models with the selected model, non-streaming, temperature zero, no tools and capability-aware reasoning off.
Summary output defaults to min(2048, max(128, floor(B / 10))); explicit caps are never reduced. Historical and active-run summaries share at most four calls per run, existing model timeouts and the Harness active-time budget.
The role-labelled input combines the previous summary and newly covered history, splitting oversized text by summary budget.
Reasoning and system prompts are omitted; images contribute only existing text/descriptions/references.
Structured Markdown preserves goals, constraints, corrections, facts, open work and sources. It enters as user-role historical data.
Only after all batches finish, final recount fits and tokens decrease is one private checkpoint atomically replaced.
It stores stable coverage, history_version, attachment policy, model/step identity, format, time and counts.
Generation holds no database transaction; commit checks history_version. Edit/delete/retry invalidation shares the history transaction.
Attachment-policy mismatch discards the checkpoint; model/percentage changes re-evaluate the same memory.
Empty, length, tool-calling, timed-out, over-four-call or non-shrinking summaries preserve the prior checkpoint.
If the original request fits, context_compaction_failed is retained as a diagnostic and answering continues; otherwise
CONTEXT_COMPACTION_FAILED stops the run. Cancellation always terminates. [Context detail](runs-streaming.md#context-detail)
retains each dispatched summary request and the summary actually used by the answer.
`/compact` manually evaluates idle normal history with history enabled and token_budget or history_retrieval selected. Token mode works even with automatic compaction off; on-demand mode performs a local reset without generation. It bypasses the trigger, retaining the target, cap and four-call limit.
The selected configuration and inclusive eligible-history boundary are captured before execution. Counts include fixed Character/Persona context, effective tools and answer reserve, without composer input or Knowledge retrieval. Fixed-only native counting uses an empty protocol user frame that is never retained or sent for inference. The next chat recounts its complete request.
Empty history or input already below target returns not_needed; successful reduction commits the checkpoint, while actual summary failures fail the run even when the original context fits. [Runs/streaming](runs-streaming.md#run-lifecycle) owns the dedicated API, event and cancellation.
Typing a slash prefix opens the sole /compact completion: click/Enter executes, Tab completes, Escape dismisses; Shift+Enter and IME confirmation do not execute. Only a standalone command with optional surrounding whitespace is accepted, without arguments or attachments.
The command bypasses message creation, queue insertion, answers and title generation. Drafts, loading, active/approval runs, pending submissions, queued/editing messages and configuration saves block execution, retaining input. Accepted execution clears only the submitted draft.
Ordinary messages may queue during compaction: success permits dispatch; failure/cancellation/interruption pauses it. Queues remain browser-local. No slash command registry is introduced.
QQ uses the same automatic preparation with its [batch history](qqbot.md#context-and-media). QQ manual compaction, overflow retry and draft previews are deferred.
Summaries are lossy; model-specific factual retention and accumulated drift require representative real-model acceptance.
Three consecutive successful summaries with factual-retention acceptance remain outstanding on a representative model.
A successful individual compression or mocked test does not establish long-conversation quality. Acceptance must not use 0.8B LLMs; the README owns model selection and commands.
Autonomous on-demand checkpoint/recovery quality requires model-specific acceptance: tested provider configurations can omit native tool calls, invent tool results in prose or time out. The tested 9B GGUF on CPU reaches the five-minute run limit before recovery. These outcomes do not establish successful multi-reset recovery.

The [context meter](runs-streaming.md#context-detail) displays actual per-call input plus output usage beside the model selector. Input reflects history limits and token trimming; policy edits affect the next request, not recorded usage.

Persona background is trimmed, wrapped in <user_background> tags under User background and appended once as contextual data;
empty text produces no block. The Run snapshots it before execution. Compact user_persona metadata
contains identity, injection status, length and empty skip reason, never the content. Current input,
history, summary inputs and retrieved text have no generated Persona or user-message ID markers; summary text uses role labels only.
Identity stays in storage and inspection metadata. User-authored text and saved snapshots are not rewritten.
General settings have no Core Memory fields or enable switch.

Worldbook is deterministic matching over current user text and configured
keywords. Enabled entries obey entry/context limits, case sensitivity,
whole-word matching and recursion depth. Books/entries have explicit CRUD;
match-test is diagnostic and changes no session/run. It requires explicit worldbook_ids
and has no session target. Character/Session mounts do not invoke Worldbook matching or injection.
Persona background and attachment content are data, never routing decisions.

Worldbook settings have Configuration, Entries and Match test tabs; existing/newly saved books open Entries.
Entry headers contain a reorder handle, disclosure, enabled switch, name, dirty marker, mode and delete;
bodies contain name/mode, keywords, content and save/reset/delete. Drafts and save/reset are per entry.
Switches PATCH only enabled, rolling back failure without discarding drafts. Pointer/touch/keyboard handles
PATCH the full ordered id list with rollback; duplicate/mismatching ids return 422. Both stores validate complete
Worldbook/entry PATCH objects before committing, including regex/name/content. Entry CRUD uses
/api/worldbooks/{id}/entries and /api/worldbook-entries/{id}; ordering uses /api/worldbooks/{id}/entries/reorder.
POST /api/worldbooks/match-test returns counts, triggers, recursion and bounded previews.

[Knowledge](knowledge.md) owns independent indexing and explicit search; saved mounts remain inactive in chat. Attachment rules below own file/image context.

## Messages and attachments

Messages use content_version=2 and validated parts; [Runs/streaming](runs-streaming.md) owns their visible session numbering. The strict message schema
owns role, speaker identity, run/parent references and compact metadata.
Supported parts are text (plain/markdown), reasoning, json, file (inline_text or
attachment_ref), image, audio, video, media_group image galleries, notice,
error, tool_call and tool_result. Unknown types are rejected; there are no
forms, actions, command buttons or diff parts.

Text parts use plain text/Markdown; reasoning uses expanded GFM and [timed Trace disclosures](runs-streaming.md). Its optional nullable duration_ms is a strict nonnegative integer persisted in parts JSON, without a schema migration. Knowledge citations such as `[K1]` use ordinary Markdown without a dedicated parser, lookup or popover.
Web citations resolve [W1] markers only against successful tool results in the current reply. Markdown AST parsing preserves code, normal links, escaped markers and unknown IDs; plain text also supports citations. Hover Card/Button compositions show a hostname with title/link details on hover, keyboard focus or touch. Empty titles use the hostname.
Below the answer and above its actions, a collapsed Sources Trace lists only cited URLs, deduplicated in first-citation order. Inline and footer links open new tabs. Streaming and reloaded history share source resolution; copying converts valid markers to ordinary Markdown links without copying processing content.

Large binary data belongs in the attachment store and is referenced by id/URL.
Uploads and serving use the configured attachment directory; General owns
size/count and text-context byte limits. Persisted parts retain ids, MIME,
name, size and compact metadata, never image data URLs. Orphan cleanup is an
explicit separate operation and considers current Persona and Character avatars, not message/run avatar snapshots.

User images persist only as metadata.attachments references; message parts do not duplicate them.
History selection uses the configured strategy; image inputs participate in final token counting.
History projection keeps images with their user message. Image-only messages remain eligible history.
Included references become OpenAI image_url parts immediately before inference, including historical follow-ups.
Before first inference, local image support is checked unless skipped in request_options. Unknown support and provider inputs pass through.
Explicitly unsupported images are omitted from this request, including retained history; empty historical image messages are omitted. Original messages/attachments stay intact. The current user bubble receives an images_ignored warning; if the current input has no remaining text, images_require_text ends the run as FAILED without main/auxiliary generation.
Missing retained images return ATTACHMENT_NOT_FOUND; corrupt local images and request limits follow
[models](models.md#external-inference-api). Images outside history/attachment/capability selection are not read; token counting can inspect candidate images that are later pruned.

Text-file context obeys the enable switch and per-file/per-message bounds.
Other attachments contribute bounded descriptive markers. include_attachments=none excludes all image inputs.
File selection, clipboard images and dropping share per-file status, previews and removal; partial failure keeps successful uploads. Session changes clear ordinary pending attachments; queue edits retain theirs.
Composer images use 120px vertical Attachment cards with names, types and sizes; other files use horizontal cards, bottom-aligned with image cards. Sizes use uploaded File.size then persisted size, in 1024-based B/KB/MB/GB with at most one decimal. Image removal uses a circular top-right button.
User metadata.attachments render as right-aligned scrolling groups: files above the text bubble and images below it, preserving order within each group. Images use 160px preview cards without visible names/sizes; file cards retain both. Attachment-only messages have no empty bubble; image/file-only messages remain eligible history.
Editing uses the same file/body/image order with removal buttons; cancellation restores originals and failed saves retain the draft. Regeneration uses only retained attachments. Cleanup after commit preserves references from messages, Personas, Characters, Knowledge and model-input snapshots.
Thumbnails and zoom previews resolve stored references after refresh. Request warnings, attachment-policy and size errors have English/Chinese guidance; retries retain the message's saved attachments.

Tool calls require assistant role, run-unique call id, name and finite JSON object arguments, with distinct part ids per message. Results require tool role, matching call id, success/error/rejected/cancelled status, optional JSON data/errors and truncation flag.
Live loops use native assistant/tool pairs. Normal history quotes tool parts as data, permitting truncation without orphan protocol calls or promoting data to system/developer instructions. [QQBot](qqbot.md#context-and-media) owns its confirmed-delivery history pairs.

Reasoning is assistant-only strict {id,type:reasoning,text} data. All sources accept reasoning_content. Managed local content stays literal; provider internal chat incrementally extracts <think> markers, including split tags, while Markdown code and escapes stay literal. The resolved source selects this behavior before output arrives.
`/v1` preserves engine fields. Reasoning/incomplete messages are excluded from history; live tool transcripts retain upstream content/structured reasoning for continuation. Summaries exclude structured reasoning and parse raw <think> markers only for providers, preserving literal local content.
Known provider limitation: [DeepSeek thinking-mode documentation](https://api-docs.deepseek.com/guides/thinking_mode)
requires earlier-turn reasoning when tools are supplied, including answers without tool calls. Internal history
currently omits that earlier reasoning; only the active tool loop preserves it. No model-specific history switch exists.
[Runs/streaming](runs-streaming.md) owns replies, provisional answers, processing/reasoning, command groups and usage. Replies retain original Character identity; copy uses answer text only, and direct tools never invent a model answer.

The frontend renders parts as data; edit/retry uses original text. MessageActions owns controls, MessageParts presentation, ChatAttachments cards/URLs, and [runs/streaming](runs-streaming.md) stream merging. Send/edit/retry pass the current UI language through X-UI-Language (en/zh-CN; absent defaults to en, other values return 422) for application-owned instructions. Each new run snapshots that language; model content and saved snapshots are never translated when the UI changes.
User messages use right-aligned gray secondary bubbles with 24px corners; assistant replies use open body layout. Assistant replies use current Character identity; user rows use the current profile of their original Persona. Headers use 14px names and 12px timestamps/numbers, ordered number/time/name for users and name/time/number for assistants.
Assistant action buttons stay visible. On hover-capable fine-pointer devices, timestamps and message numbers, user action buttons and reply usage metrics appear on message hover or keyboard focus,
fade in and out over 180ms (instantly with reduced motion), and retain layout space. Touch layouts keep them visible; editing keeps save/cancel visible and an open usage modal keeps its owner visible. Message bodies use 16px text with Markdown headings, lists, quotes, code, tables and media.
Markdown block code uses gray secondary Bubble surfaces with 24px corners and preserves preformatted text; inline code retains its compact styling. Message action tooltips open below their buttons without flipping above, including usage details. Wide code, tables and tool results scroll inside their own bounds; general tool results are limited to 320px height on desktop and 240px below 768px. [Runs/streaming](runs-streaming.md) owns the shorter web-fetch bounds.

Saving a user edit immediately restores the bubble with the submitted text while regeneration runs; request failure restores the editor and draft with the existing error feedback. Newly sent user bubbles animate once with a 300ms blur fade and 6px upward motion; historical loading, session switches and edits do not replay it. Reduced motion disables the animation.
User messages are MessageScroller anchors. A vertically centered left tick rail tracks the current turn, previews summaries on hover/focus and navigates to user messages; it scrolls internally and is hidden below 768px message-area width or with fewer than two user messages. Ticks have 8px center spacing, 2px thickness and a shared left edge; ordinary, immediately neighboring and active ticks are 12px, 18px and 24px wide. Only the active tick changes color. History reading pauses streaming follow; the latest-message button resumes it.
The InputGroup composer has 20px corners and circular buttons: an outlined plus opens the Photos & Files upload menu, an up arrow sends, and active runs expose stop. Empty or single-line drafts place buttons and text on one row; explicit newlines or wrapping expand the text above the toolbar. Deleting back to one line or clearing collapses it. Wrapping is measured at the compact text width, excluding the placeholder, and recalculated for content, width and font changes. The same textarea and toolbar stay mounted; height and text layout transition over 180ms ease-out, instantly with reduced motion. Expanded text starts at 56px and grows to min(12rem, 30dvh), then scrolls internally. Attachments and context remain outside the input and do not force expansion. Existing draft, upload and keyboard behavior remains; contextual drag/limit/error feedback remains, without a static image hint or service footer/health request.
The composer places a fully rounded model menu before send/stop, capped at 160px (120px below 640px), truncating long names. Text measurement reserves the actual action widths; the placeholder uses a fitting short label or hides when necessary, retaining its full accessible name. One model group contains all LLM profiles with Local first and provider labels; unconfigured sources are separate. Disabled/missing selections remain visible without automatic replacement. A second group contains the immediate Harness toggle, its independent settings action and the immediate Reasoning toggle. The menu stays accessible without eligible models. [Harness/tools](harness-tools.md) owns the session Sheet; selection/configuration saves block sending until settled.

## Auxiliary tasks and titles

UtilityLLMService uses ModelManager admission/lifecycle without separate routes or message/run records.
utility_model_profile_id must select an enabled LLM UUID; absence/failure returns UTILITY_MODEL_UNAVAILABLE without borrowing chat's model.
generate_text sends only the supplied prompt, without streaming. generate_json validates the entire response against its Pydantic schema;
fenced/embedded JSON, tool calls and invalid output return UTILITY_OUTPUT_INVALID.

First accepted input names an untitled session from its first 15 Unicode characters after trimming/collapsing whitespace,
adding an ellipsis only when truncated; attachment-only input uses the first filename. Explicit tool input receives only this basic title.
Failed runs retain it, and explicitly supplied/manual titles are protected. auto_generate_session_titles defaults on and controls only auxiliary improvement.
After publishing the completed run and releasing the main model lease, ChatRunner requests an improved title using max_tokens=64,
temperature=0, session_title_prompt and at most 1200 input characters. Missing auxiliary selection, failed/empty output or concurrent
manual renaming preserves the title without affecting chat success. Only the first chat input is eligible; later inputs never rename it.
Auxiliary input excludes history, attachments, Persona context, Worldbook and Knowledge. Title state/metadata retain the input excerpt,
originating input id and successful auxiliary-generation identity.

## HTTP schemas

OpenAPI covers Personas, configuration, parts, mount configuration, paginated history and Worldbook; private snapshots remain excluded.
Responses preserve optional-field omission, explicit nulls and existing PATCH/error behavior.
Message/run timestamps retain UTC Z and microseconds; Worldbook keeps +00:00. Uploads document
one multipart file; downloads document stored-MIME bytes, Range, 200/206 headers and empty 416.
