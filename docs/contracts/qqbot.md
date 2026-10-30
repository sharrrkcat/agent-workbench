# QQBot contract

QQBot owns external OneBot v11 conversations, Project settings, triggers, media, delivery and local history management.
[Chat/context](chat-context.md) owns shared Project/Persona rules and token budgets; [Harness/tools](harness-tools.md) owns the common loop and approvals.
[Runs/streaming](runs-streaming.md) owns run/event and snapshot formats; [Models](models.md) owns inference through core/models.
[Data layout](../DATA_LAYOUT.md) owns storage boundaries and revisions. The [QQBot task](../ai/TASK_QQBOT.md) maps source and tests.

## Configuration and bindings

Projects select an optional Agent, Project prompt, explicit external LLM, temperature, reasoning and context policy. Connecting requires an external LLM with no global fallback.
Accounts belong to one Project and cannot change while Sessions are bound. WebSocket URLs require ws/wss without credentials, query or fragment.
An omitted access_token preserves it; an empty token removes it. Public reads expose only has_access_token; private storage follows Data layout.
Sessions bind an immutable group|friend and positive decimal-string target_id, unique per Project; only title is editable.
Sessions use Project settings at execution time and Agent identity/prompt only. Cogita Persona, Knowledge, Worldbook, manual attachments and overrides are excluded; resource-binding APIs reject QQ targets.

| Setting | Default and contract |
| --- | --- |
| connection_enabled / agent_persona_id / model_profile_id | false / null / null |
| reasoning / keywords | true / empty list; keywords are trimmed, case-insensitively deduplicated |
| batch_message_limit / reply_message_limit | Strict integers: 20 (1..200) / 4 (1..20) |
| image_input_enabled | Strict boolean, false; derives effective context_policy.include_attachments |
| image_description_model_profile_id | null; enabled external LLM, independent of the main model |
| image_generation_model_profile_id | null (disabled); enabled provider image_generation profile |
| image_generation_options | Non-null object with nullable size/quality/style; unset controls inherit model defaults |
| icebreaker_enabled | Strict boolean, false |
| icebreaker_cold_seconds / icebreaker_wait_seconds / icebreaker_cooldown_seconds | Strict positive integers: 7200 / 120 / 10800 |

PATCH omission retains settings; null is invalid for booleans and limits. Null clears optional model selections or restores individual generation-control inheritance.
Unknown fields, invalid types/ranges and invalid nulls return 422.
Description/generation models participate in Project/unfinished-run reference protection. Generation always requests one image regardless of profile n.
Configuration, image switches/models and generation controls resolve before asynchronous media/member waits, then remain fixed in the run snapshot.
New Projects have an editable conversational prompt: stay on topic, match participants' language, usually reply once and follow the selected Persona.
Prefer qq_send_message; use favorite images sparingly for fitting emotional interaction, without routine illustrations, consecutive unsolicited images or duplicate links/announcements.
A topic/tag match alone does not justify sending. Prompts recommend at most one image per reply, without a separate execution quota or cooldown.
Use generation only for explicit new-picture requests; pre-send image failures permit text. API omission chooses the English prompt; explicit empty text stays empty and existing prompts are preserved.

## Ingress and triggers

Each enabled Project owns one OneBot v11 WebSocket connection to independently installed/logged-in NapCat. Identity verification precedes ingestion; transport reconnects automatically.
Status distinguishes authentication, account mismatch and connection failure without exposing tokens. Wire messages are limited to 1 MiB with a bounded receive queue.
Only bound conversations are recorded. Malformed messages produce content-free diagnostics; duplicate external ids do not reset debounce, and bot echoes never enter batches.
Records retain sender identity, UTC-offset time, mention/reply references and ordered image/sticker/system-face positions from arrays or CQ strings. Literal placeholders are never parsed as media or backfilled.

Share segments use title/url; JSON link cards use meta.news.title/jumpUrl with top-level prompt as title fallback, producing [分享链接: title (url)].
JSON accepts objects or strings in data.data; lightapp also accepts data.content. Small-app cards are lightapp or JSON apps prefixed com.tencent.miniapp.
They use prompt, then meta.detail_1.title, and the first nonempty qqdocurl/jumpUrl/url in detail_1, producing [小程序: prompt (url)].
Fields accept strings only, trimming/collapsing whitespace. Missing URLs omit parentheses; URL-only cards show [type: url]; recognized empty cards show [分享链接] or [小程序].
Unknown/malformed JSON becomes [非文字消息] without discarding adjacent segments. Markers reach display, saved batches and history without raw JSON, fetching links or backfilling old records.

Group keywords match case-insensitive substrings in text, normalized real @QQ-id segments and mentioned members' group cards (nickname when no card).
A built-in complete @bot-id matches real self mentions and literal text, independently of editable keywords; bare numbers and longer account prefixes do not match.
Quotes, media/card fields and model-only identity labels cannot trigger independently. Clearing keywords preserves the built-in account trigger. Private messages always require replies.
Keyword matches grant a new 60-second Session eligibility epoch; eligible senders' ordinary messages trigger follow-ups. Participant arrivals extend silence five seconds from receipt; bystanders join without extending it.
Membership lasts until freezing, even after eligibility expires. Both durations are fixed. Arrivals exactly at a deadline follow expiry.
Text/account matches decide immediately. Otherwise real mentions use cached names or bounded asynchronous lookup outside the socket reader.
Pending decisions complete in Session receipt order using original receipt times; batching excludes later unclassified inputs. Failure/timeout uses available text/accounts; late names never retrigger messages.
Connection changes discard unfinished decisions while retaining raw records. Display refreshes and later context projection do not repeat trigger decisions.

Real at segments save code-point spans, ids, names and self flags in references_json; typed mentions stay literal and spans are not reconstructed. at=all means everyone.
Models receive names/ids with a self marker; display uses names with ids/self in status details. Display and submission project names asynchronously; submission freezes names/input against renames.
Lookup prefers observed same-conversation senders, then get_group_member_info (card before nickname), get_stranger_info for private names, or verified login information for self.
Each Project caches 1024 conversation/member entries for 600 seconds (60 after failure). Shared queries allow four concurrent calls and two seconds per page/batch; offline/failure retains ids without pausing.

## Batches and icebreakers

Expired debounce windows create SQLite FIFO batches during inference or pause. Each message belongs to at most one batch; Project execution is serial, selecting the next unpaused Session's batch.
Freezing takes the newest batch_message_limit unassigned messages and marks older records skipped. Any keyword in the window makes the batch mandatory before truncation; otherwise group follow-ups are optional.
Batch policy and submitted speakers' participant epochs are immutable. Raw batch text remains separate from the submitted [time][name (QQ:id)]:content projection.
Messages after eligibility expiry cannot open new windows; already triggered windows and queued batches remain valid. [Manual resume](#tools-delivery-and-recovery) coalesces untouched ordinary backlog.

### Quiet-group icebreakers

Icebreakers have independent group clocks; friends retain their mandatory flow. Continuous online silence strictly longer than the cold threshold enables observation.
The next nonempty member message starts single-speaker observation; each supplement from that speaker restarts the wait. Text, pictures, stickers and other normalized nonempty messages qualify.
Empty/malformed messages, duplicate ids and bot echoes do not participate. Confirmed bot sends update activity once. Another member cancels observation.
Keywords, existing follow-up eligibility and outstanding ordinary reply work take priority. Expiry precedes exact-deadline ingress; a second speaker can still cancel the resulting unsent batch.
At expiry, the newest configured count of visible observation messages forms an immutable icebreaker batch with its lone speaker and last submitted message as grant source; older pending inputs are skipped.
Later supplements do not rewrite frozen inputs. Icebreaker run snapshots and public metadata use message_limit=1, shared by text and both image tools.

Cooldown starts after context preparation on entering inference. Queue/preparation cancellation consumes none; skips, later cancellation and failures retain it.
Confirmed icebreaker replies grant their speaker eligibility until max(current expiry, confirmation time + 60 seconds), atomically with delivery confirmation.
Grant sources use the submitted message id; newer sources and existing windows are preserved. Pending nickname decisions retain pre-confirmation eligibility for already-received messages.
Skips, failures, unknown sends and pre-send cancellation grant nothing; repeated receipts/restart never extend a grant. Skipping an icebreaker does not change participant eligibility.
Cooldown does not block ordinary follow-ups; another icebreaker requires a new message after cooldown and sufficient silence.

### Icebreaker cancellation and recovery

Observations are process-local on the existing supervisor. Pause, disablement, disconnect, restart or icebreaker/connection edits discard observations and cancel unsent icebreakers.
Resume starts a fresh silence baseline; durable cooldowns survive. Restart cancels queued/running icebreakers without a delivery intent instead of replaying; submitted sends follow normal interrupted/unknown recovery.
A second speaker or ordinary reply trigger cancels during queueing, media/member waits, context preparation, inference or generation.
Execution/sending waits for preceding nickname decisions, then rechecks eligibility before the durable intent and OneBot submission without an intervening await.
Once submitted, new activity cannot cancel or retract the message. Automatic invalidation records QQ_ICEBREAKER_CANCELLED without automatically pausing; actual model/delivery errors and explicit pause/stop retain normal handling.
Deleting observed inputs uses remaining visible messages; deleting all cancels observation without rewinding activity or cooldown clocks.

## Context and media

Shared [context budgets](chat-context.md#configuration-snapshots-and-context) apply. Only the current batch supplies image bytes through core/models when image input is enabled.
Take the last five available pictures, then the last stickers filling remaining slots; count occurrences and preserve original positions. System faces consume no slots or image bytes.
Faces use [QQ表情：name], or [QQ表情] for unknown names. Historical, over-limit, disabled and unavailable pictures/stickers use [图片：description]/[表情包：description], omitting absent descriptions and their colon.
Each new context reads current shared descriptions; built contexts and captured requests stay immutable. Image sources preserve message/part positions and static model attachments.
Disabled/unavailable images record attachments_disabled/qq_image_unavailable exclusions. Late acquisition cannot change captured inputs or submit historical images.

Confirmed deliveries project as native assistant qq_send_message/qq_send_image/qq_generate_image calls with paired receipts and stable delivery-derived ids, without duplicate prose.
Generation calls retain their original prompt and [生成的图片:prompt] receipt; favorite calls use asset_id and [图片:description] saved at sending. Neither returns bytes, attachments or URLs to history.
Later shared-description changes do not alter delivery text/prompt. Earlier confirmed sends survive failed/cancelled runs. Skips retain submitted input but exclude the skip tool.
Unsubmitted/truncated inputs, internal prose and failed/unknown sends are excluded. Retained inputs and confirmed sends are selected/pruned together; historical pairs never execute.
max_messages counts nonempty saved inputs/sends, not expanded protocol records; character/token budgets include expanded tool data. Historical sends share a turn for pruning and retain whole-message excerpts.

### Acquisition and shared assets

Four background acquisitions run independently of the socket reader, preserving segment order. Use reported HTTP(S) URLs, then get_image for a downloadable URL; never read remote filesystem paths locally.
Downloads accept public HTTP(S) without credentials. Validate every DNS answer and redirect; connect to a validated address while retaining Host/TLS server name, preventing a second DNS resolution bypass.
Disable environment proxies; allow at most three redirects. Enforce the caller's image byte limit during streaming without relying on Content-Length; request identity encoding and reject compressed responses.
QQ decoding and attachment byte limits still apply. Bundled QFace 1.4.1 provides system-face names/resources with its MIT notice; unknown ids remain labeled unavailable.

Media occurrences reference global qq_media_assets, deduplicated by SHA-256 of original PNG/JPEG/WebP/GIF bytes across QQBot Projects. Ordinary attachments do not share this deduplication.
Assets own originals, optional first-frame PNGs for GIF/animated WebP/APNG, description/manual flag, favorite state and timestamps; static images reuse their attachment.
Attach existing assets before decoding; save/reference new assets atomically so competing downloads retain one copy. Image-enabled batches wait at most ten extra seconds for pending pictures/stickers, excluding faces.
Unavailable media keeps positional placeholders; late completion updates display. Pending acquisition resumes after restart. Deleted records cannot be recreated by late results; ids are not reused.

### Asynchronous descriptions

With image input enabled, completed contexts schedule descriptions only for selected undescribed resources, at most five distinct assets once per batch.
QQDescriptionService calls the selected external LLM independently per asset with a fixed Chinese prompt and static image: non-streaming, reasoning off, max_tokens=64, temperature=0, no tools.
Normalize plain text to one line and at most 20 Unicode characters; ignore empty/structured/tool output. Concurrent batches share in-flight asset tasks and ModelManager admission/timeouts.
Replies do not await descriptions, though shared providers retain configured concurrency. Writes fill only existing, undescribed resources without manual edits.
Failure leaves description empty without pausing or borrowing a model; later selected occurrences may retry. Shutdown cancels tasks; no persistent description queue or history-wide backfill exists.
Writes advance history_version in every referencing Session. Original display and description-based alt/preview text work independently of main-model image input and description-model selection.

## Tools, delivery and recovery

QQ runs always enable Harness with web_search/web_fetch plus the available QQ tools below. Web tools reuse global AnySearch settings without Project configuration; other general tools are excluded.
The four QQ tools are automatic, scope=qqbot, excluded from ordinary/Workspace allowlists and direct calls. Their handlers require server-owned Session, active batch/run and tool-call ids; only the immutable Session binding supplies the destination.
Web tools retain shared deadlines, cancellation, fixed run-start date instructions, bounded evidence and context budgets. Search/read call budgets reset per batch and remain separate from reply slots. Missing configuration, request failures and tool timeouts return structured results so the model can continue; total timeout and cancellation remain terminal.
QQ web results retain bounded excerpts/page links and query/cache/page metadata without source_id or numbered citation instructions. Processing history displays web steps without citations/Sources; later batches retain only the existing input/confirmed-delivery history.

| Tool | Strict arguments | Availability |
| --- | --- | --- |
| qq_send_message | text: nonblank, 1..4000 characters | Every QQ model batch |
| qq_send_image | asset_id: positive integer in snapshotted candidates | Described favorite candidates exist |
| qq_generate_image | prompt: nonblank, 1..32000 characters | Configured generation model and current-batch keyword permission |
| qq_skip_reply | Empty object | Unanswered group follow-up/icebreaker batch |

### Reply decisions and quotas

Each batch's first model call uses tool_choice=required, then auto; model requests and queued execution share permissions. Unsupported tools fail without ordinary-chat fallback.
Each call appends qq_runtime: snapshotted target/bot identity, batch id/trigger kind and live confirmed-send count/limit, excluding historical sends. Project prompts stay separate.
The block distinguishes mandatory replies, optional follow-ups and icebreakers; names/text and favorite descriptions/tags are data. Icebreakers continue the topic without announcing a rescue or demanding engagement.
Successful skip immediately completes run/batch without sending, another call or pause. Follow-up skip expires only submitted participants whose current keyword epoch matches the snapshot; newer keywords, windows and queues survive.
Each confirmed follow-up send renews submitted participants to max(current expiry, confirmation time + 45 seconds), even after expiry; later failures retain renewal. Keyword/private sends do not renew.
Calls execute in order: successful skip rejects remaining calls with QQ_REPLY_SKIPPED. A confirmed send removes skip; later skip calls return TOOL_NOT_ALLOWED without expiring participants.
Invalid arguments/disallowed skip do not satisfy the reply decision. Final model prose is internal; no confirmed send or legitimate skip fails run/batch with QQ_REPLY_REQUIRED and pauses the Session before DONE.

Provider rejection/ignored tool choice is neither retried nor downgraded. Only confirmed sends increment private qq_sent_count; failed/unknown sends, validation errors and other tools consume no slot.
All tools share eight tool-producing model rounds per batch; multiple calls in one response count once. Web calls consume rounds but no send slots and cannot satisfy a reply decision. The default four-message send limit is independent of the round limit.
Reaching the snapshotted reply limit completes run/batch without pause or another call. Remaining emitted calls receive QQ_REPLY_LIMIT_REACHED with rejected results/skipped steps and no intents.
Cancellation, delivery errors and common Harness limits retain precedence; counts reset per batch. Public metadata.qq_reply retains sent_count, message_limit, limit_reached and skipped, including partial sends before failure/cancellation.
Only normal completion at the limit sets limit_reached=true; legitimate skip sets skipped=true with no delivery.

### Send deadlines

Text sends one plain-text OneBot segment; CQ-looking content stays literal. Image tools send a separate OneBot image segment with base64 bytes.
All sends pass NapCat timeout=60000 ms and wait up to 90 seconds for the response; ordinary queries retain 20 seconds. Stop and earlier run-budget deadlines still cancel sending; errors return immediately.
Text/favorite sends use remaining five-minute Harness time instead of the ordinary 30-second tool timeout. qq_generate_image is exempt from both counters: Provider queue/request, download and delivery own deadlines/cancellation.
Other model/tool work retains shared budgets. QQ reply limits can end a run early without increasing the common round/time limits.

### Image tools

At ingress, only real text segments set image_generation_keyword for literal substrings 生成 or 画. Names, mentions, quotes, cards, descriptions and synthetic text do not contribute.
Execution ORs flags of visible submitted messages after truncation and requires the configured generation model. Permission stays private/fixed in the run snapshot for tool visibility, qq_runtime and handler validation.
History, tool results and model output cannot unlock generation; a new batch such as 再来一张 stays disabled. Keywords enable capability, not obligation: animation/scene discussion, text generation and requests not to draw are excluded by instructions.

Preparation snapshots all global favorites with nonblank descriptions as ordered {asset_id, description} candidates. Only text enters qq_runtime under normal context budgets; paths/URLs/bytes stay out.
No candidates means no list or qq_send_image definition. Favorite/description edits affect later batches; sending rechecks existence, favorite state and nonblank description.
After any icebreaker wait, favorite sending reads the original attachment synchronously before the durable intent, retaining animation. The intent references the asset; confirmation saves receipt/history marker atomically.
It never copies the asset, changes descriptions or invokes a model. Missing/unfavorited/undescribed/unreadable assets return QQ_IMAGE_RESOURCE_UNAVAILABLE before intent/slot, allowing text.

Generation calls ModelManager.generate_images with n=1 and snapshotted size/quality/style; unset controls and response format inherit profile defaults. URL results follow the download policy above; URL/base64 results use attachment limits and QQ decoding.
Stage files before dispatch. Only confirmed sends create/reuse an asset and link delivery/history in one transaction. Its description becomes the full original prompt unless manually edited, including intentionally cleared descriptions; ignore provider revised_prompt.
Clean unreferenced staged files after completion/failure/cancellation; crash leftovers use explicit orphan cleanup. Preparation/download/provider failures return QQ_IMAGE_GENERATION_FAILED without a slot or pause, allowing text or another model-chosen attempt.
There is no automatic retry. Missing mandatory replies/common loop limits still fail; sending failures retain terminal delivery policy. Restart never regenerates/resends. Project execution stays serial while generation awaits; ingestion and Stop remain available.

### Delivery receipts

Delivery intents persist before dispatch, unique by run/tool-call id, with pending/sending/sent/failed/unknown states. Confirmation and historical assistant message commit atomically; later failures preserve earlier sends.
Only a successful response matching the current request echo with a valid integer/nonblank string message id confirms delivery. Known self reports mark confirmed records echoed; an active send retains at most 128 self ids for its bound Session.
An early self report can set echoed in confirmation; self reports alone cannot confirm unknown sends. Temporary ids are discarded after sending; duplicates add no history, count or eligibility.

OneBot errors normally mean failed. For send_group_msg/send_private_msg, the native sendMsg/onMsgInfoListUpdate Timeout diagnostic in message/wording means unknown with QQ_SEND_ACK_TIMEOUT.
Other retcode=1200 errors, unrelated timeouts and EventChecker Failed are not reclassified. Tool errors retain only action, numeric retcode and normalized cause, never raw upstream diagnostics.
Disconnect, response timeout, cancellation during sending or invalid receipts mean unknown. Accept delayed success within the deadline; responses after request termination cannot confirm in background or reopen runs.
No history lookup or content/time matching is used. Delivery errors terminate the run and pause before another send; main reply-model failures also pause. No automatic resend or regeneration occurs.
### Pause, resume and restart

Pause prevents new execution while ingestion/batching continue; Stop also cancels active work. Disabling connections stops ingress/dispatch and blocks later sends.
Manual resume requires idle state and coalesces backlog for every pause reason, including stop/failure/restart. Repeating resume when already unpaused/idle leaves queues and observation unchanged.
Resume waits only for nickname decisions already pending, using existing deadlines, then consumes the classified receipt-order prefix; later unclassified arrivals remain for normal batching.
One SQLite transaction replaces untouched ordinary queues and the pending triggered window with at most one new batch, reapplies the current input limit, clears consumed membership/deadline and unpauses.
Allocate the replacement before deleting queues and append it to Project FIFO. Deleted/skipped inputs stay excluded. No ordinary trigger means no replacement; pending group context remains available.
Any source keyword batch/window makes the merged group batch mandatory before truncation; otherwise it is optional follow-up, while private stays mandatory. Apply the normal reply limit once.
Each retained speaker takes its latest epoch only from retained messages' source batches/current window; resume never extends eligibility. Failed/cancelled/interrupted batches never replay.
Restart retains ordinary queues, window membership/policy and absolute participant expiry; it marks running batches interrupted, in-flight intents unknown and pauses affected Sessions. Shared run reconciliation remains authoritative.

## Resources and history management

The shared gallery contains each received picture/custom sticker, image delivery and retained favorite once per global asset; face-only assets are excluded.
Manual descriptions accept multiline text and clearing without automatic caption truncation. Late captions and repeated generation preserve manual edits, including empty descriptions; creation time never changes after receipts/edits.
Favorites survive their last chat reference. Unfavoriting an unreferenced asset returns QQ_RESOURCE_UNREFERENCED (409); the UI confirms DELETE instead, retaining the favorite on cancellation.
Shared deletion requires every referencing Session idle or returns SESSION_BUSY (409). Its transaction detaches incoming/delivery references and advances their history versions, preserving positions and transport identities.
Deleted images/stickers become plain [图片] placeholders without preview/description. Deleted image-delivery history becomes a plain assistant placeholder without the original tool call/prompt/description.
In-flight deliveries protect resources/files. Captured requests stay unchanged; new arrivals may acquire identical bytes as a new asset, but deleted positions never reconnect.

### Local history deletion

Local incoming/delivery/reply deletion requires an idle run/batch; busy returns SESSION_BUSY (409), missing/mismatched records 404. Each removes only its local history/context contribution, never QQ messages.
Incoming deletion rebuilds raw batch and submitted input using remaining messages' original times/frozen mentions. Empty queued batches cancel; empty submitted input is omitted while delivery pairs survive.
Delivery deletion removes its saved assistant message and both protocol records. Deleted ingress/receipt identities remain private for deduplication; statuses, participant eligibility, other messages and historical send counts stay unchanged.
Deleting a QQ run removes all its deliveries/messages/steps/events/private state and clears the batch run reference, preserving inputs. SQLite deletion, input updates and history_version commit together.
Deletion never sends, regenerates, resumes or rewrites retained replies/request snapshots. Idle Session/Project deletion removes associated QQ records without retracting external messages.
History/delivery/reply/Session/Project deletion releases non-favorite assets after their last visible reference. Post-commit attachment cleanup protects favorites, other references and model snapshots.
Candidate search and manual sending remain deferred; model sending uses the complete favorite list captured for the run.

## Interface and HTTP surface

QQ configuration uses shared typed Project APIs and title-only Session PATCH. The QQ API exposes the following additional surface:

| Endpoint | Behavior |
| --- | --- |
| GET /api/qq/projects/{id}/status | Connection status |
| GET /api/qq/sessions/{id} | Binding, pause, busy and history_version |
| GET /api/qq/sessions/{id}/messages, /batches, /deliveries | history_version and newest-first integer before cursors; default 50/max 100 |
| POST /api/qq/sessions/{id}/control | pause / resume / stop |
| DELETE /api/qq/sessions/{id}/messages/{message_id}, /deliveries/{delivery_id} | Local bubble deletion |
| DELETE /api/runs/{id} | Whole QQ reply deletion |
| GET /api/qq/resources | page=1, page_size=30 (1..100), sort=created_at\|size, order=asc\|desc (desc default), favorite=all\|favorites\|unfavorited |
| PATCH /api/qq/resources/{id} | Only description (string/null) and strict is_favorite boolean; omission retains fields |
| DELETE /api/qq/resources/{id} | Shared deletion; returns deleted |

Resource lists return items/total/page/page_size; items expose id, original attachment, description, is_favorite, created_at and has_references. Equal sort values use asset id in the same direction.
Missing/face-only resources return QQ_RESOURCE_NOT_FOUND (404). Batches expose trigger_kind=keyword|followup|private|icebreaker; participant epochs/windows and persisted cooldown stay private.
Messages expose strict ordered text/image segments plus summary text. Images include media_id, nullable asset_id/description, image|sticker|face kind, pending|ready|failed|deleted state, label, original attachment and error_code.
Download addresses, model derivatives and internal paths stay private. Deliveries expose kind=text|generated_image|resource_image and nullable prompt/asset_id/description/attachment; resource_image prompt is null, without download URLs/binary payloads.
Ordinary sending, direct tools, editing and regeneration are rejected and hidden. [Shared events](runs-streaming.md#websocket-events) carry history invalidation; QQ polling reconciles versions across the loaded range and invalidates completed-run caches.
Older pending media refreshes even when batched/skipped. Pre-deletion/mixed-version responses cannot restore records; Session navigation isolates late responses.

### Project editor and conversation

Creation/settings share Connection (initial), Replies and Images tabs and one save action. Tab choice resets on opening; dialog tabs/actions sit outside the scrolling body.
Sections stay expanded; disabled icebreaker/generation fields remain conditional. Hidden panels stay mounted outside focus/accessibility navigation; submission reveals the first invalid field before native feedback.
The settings header has only name/sidebar toggle; immediate group/friend binding stays in the sidebar. Editor width is at most 48rem; container widths 32rem/40rem enable two/three columns for timing/image fields.
Prompt/keywords keep four/three rows with internal scrolling. Token clearing is inline; hints cover syntax/essential semantics. Failed saves retain drafts.
New UI prompts use the opening language; changing language preserves the draft, clearing/saving stays empty, and editing never reapplies defaults.
The image-description selector sits beside image input with Do not use. Generation uses a separate provider-only selector, Disabled initially, with model-default size/quality/style overrides; disabling retains controls.
Icebreaker enabling reveals the three durations; disabling hides them while retaining values. Helpers explain real-mention names, built-in account matching and 60-second post-icebreaker follow-up.
Context fields use one blank/unlimited and zero/no-history hint. Image helpers cover the five-current-image limit, later descriptions, one image per generation call and size syntax; reply limits explain shared text/image allowance.

Each original incoming message, including image-only input, has its own right-side secondary bubble. Consecutive sender ids group within 120 seconds from group start, interrupted by another sender or model reply.
Only the first row has avatar/name/time; continuations have a 6px gap and no header. Outside icons retain pending/batched/skipped state without changing timestamps.
Resume overflow becomes skipped without batch association, preserving text/media. Retained inputs move to the replacement; old unsubmitted queues disappear and history_version refreshes loaded states/associations without altering submitted history.
Each run appears once on the left with processing, usage/context detail, original time and delivery states; inputs are not duplicated. Delivery bubbles omit headers/times, with 6px gaps and 8px after model actions.
Generated/favorite images are separate bubbles with shared description alt/preview text. Older history loads into the same conversation without tabs or pagination controls.
Both locales show reply-limit completion, skips without bubbles and missing-reply pauses. Unknown remains unconfirmed; QQ_SEND_ACK_TIMEOUT asks users to check QQ before resuming, while QQ_ACTION_FAILED reports a send API error in existing tooltips.
There is no manual confirmation or automatic unpause; old records stay unchanged. The header shows title without a separate target number or run controls.
The disabled composer shows localized "Chatting in {targetId}" for groups/friends, without Persona name. Outlined pause/resume and Stop replace attachment/send controls on the left; context usage/model menu stay right.
The hint shares the row when it fits, otherwise moves above the toolbar based on both control groups. The model menu PATCHes only the Project external LLM or reasoning field; later batches inherit edits and active runs keep snapshots.
Harness has no toggle/settings entry. Pending saves block duplicate configuration edits but not Stop; failures preserve confirmed values with feedback, and late results preserve subsequent navigation.
Incoming rows order delete/status/bubble; delivery rows order bubble/status/delete. Delete controls reserve space and appear on hover/focus with existing 180ms/reduced-motion behavior; touch keeps them visible.
Whole-reply deletion stays in model actions. Every deletion confirms scope; busy/pending mutations disable it and failures retain records with feedback.
Ordered media renders in place: images up to 240px, stickers 160px, inline faces 24px, all constrained by bubble width. Original animations play; shared preview opens images and pending/failed markers retain position.

### Shared gallery

Every saved QQBot Project shows Shared resources as its first session-style row at /projects/{id}/resources; all open the same global gallery. Other Project kinds reject it.
The responsive vertical Attachment grid has at most six columns with approximately 160px minimum width, two-line descriptions and format/size labels. Originals animate; heart/delete appear on hover/focus and stay visible on touch.
All/Favorites/Not favorited tabs show the image count beside them. Date/size sorting works both ways, initially newest-first; URL query retains filter/sort/page. Pagination uses 30 items and corrects exhausted pages after deletion.
Cards open a right Sheet, 480px desktop/full-width phone, with uncropped preview, metadata, description, save/reset, favorite/delete. Saving keeps it open; failures retain drafts and favorite mutations are independent.
Closing/navigation/history/unload protect unsaved edits; pending mutations prevent departure. All deletes confirm global scope. A favorite with a nonblank description becomes available to models next batch; optional tags use the same field.

## Limits and acceptance

Local fake-OneBot/fake-model tests cover transport, ingestion, triggers/participant windows, skip/renewal races, batching, icebreaker timing/cancellation/cooldowns, delivery, resume, deletion, stop and restart.
Media/provider fixtures cover shared assets, ordering/current-batch selection, names/faces/cards, captions, original animations/static frames, generation, failures and late acquisition/deletion. Web fixtures cover shared settings/rounds, citation-free traces and error recovery; live AnySearch-to-QQ replies remain unverified. Browser fixtures cover both locales and desktop/touch workflows.
Live NapCat delivery/member lookup/card reception, media URLs/system faces, vision-model round trips, real Provider-to-NapCat generated images, original-animation presentation and restrained real-model image frequency remain unverified.
The 60-second native timeout, 90-second response wait and native-timeout classification have simulated coverage only. Live acceptance must use explicitly designated targets, compare actual QQ receipt with recorded outcome and check duplicate prevention.
Self reports without a successful matching action response do not establish delivery; longer timeouts cannot repair an absent native success event.
QQ/NapCat installation/login management, reconnect history backfill, manual sends, candidate search and memory integration are unimplemented. Worldbook/memory needs explicit bot/conversation isolation and a separate injection design.
Linux Local Runtime is outside this integration. [Run guide](../../README_RUN.md#qqbot-deployment) owns deployment conclusions; detailed historical experiments remain in Git and external operational records.
Short Linux login/health/idle evidence does not establish inference, first-use tokenizer cost, long histories, concurrent generation, media workloads, reconnect, cached-login restart, 24–72-hour stability or a RAM guarantee.
QQ shutdown behavior still needs operational acceptance. Paginated history/context and bounded subscriber queues do not establish long-running QQ memory acceptance; both context limits null still permit growth.
