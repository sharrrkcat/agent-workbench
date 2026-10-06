# Settings contract

Settings have explicit domain owners and strict Pydantic inputs with extra=forbid. Unknown/removed fields return HTTP 422. The frontend keeps six
domains and `/settings?tab=` values: general, models, personas, knowledge,
worldbook, tools. Default/unknown tab selects General, including pet.

SettingsPage owns navigation and composition only. Domain panels own their
forms; shared controls are independent of the page. Types and API clients use
domain modules, with a single HTTP/error implementation. User-visible labels,
states and feedback have matching English/Chinese resources. User content,
prompts, ids, API fields and error codes retain their original values.

Both locales display Cogita. Language uses browser key `cogita.locale`, defaulting to English when absent or invalid.

## Frontend styling foundation

Tailwind CSS 4 uses its Vite plugin. shadcn/ui uses Base UI and the Mira preset
`b1D0dv72` (`base-mira`, Neutral, Lucide, default menus and subtle accents).
`frontend/src/styles.css` is the only application CSS entry, with preset tokens,
base rules and scoped application layout, Markdown and media styles. Shared
controls own their styling in their component classes. Preset light/dark tokens
are retained, while the HTML root always selects dark and declares a dark
color scheme. There is no theme setting or system-theme tracking. Inter Variable
ships in the build; headings inherit the body font and Chinese uses system fallbacks.
Fonts do not use external CDNs or the removed backend font settings.

Shared controls are generated with shadcn CLI 4.21.0 and maintained in
`frontend/src/components/ui/`. Callers compose Button, Field, Input, Textarea,
Select, Combobox, Checkbox, Switch, Tabs, Card, Collapsible, ToggleGroup, Dialog,
AlertDialog, Tooltip, Badge and Table directly. Domain components retain model filtering and
resource binding rules. Vite, TypeScript and the test module loader resolve
`@/` to `frontend/src/`; `cn` combines component styles.

Field labels/titles use explicit 12px medium text; descriptions, field errors and shared save/error Feedback use 12px regular text. Section legends stay 14px; touch inputs retain 16px text. Desktop controls retain Mira density. Coarse-pointer buttons, options and form
actions have at least 44px targets, except the compact [chat tick rail](chat-context.md#messages-and-attachments); Checkbox/Switch keep compact marks with
expanded targets and associated labels. Field labels/descriptions are connected
to controls. Forms retain native required/range validation and existing blank,
null and zero semantics. Hidden file inputs remain behind visible Buttons.
Controlled Select preserves groups, disabled options, empty choices and missing
selected records. Model references use editable Comboboxes for local directories or provider IDs;
their text is the field value, including values outside the suggestions. Detected file paths are read-only.

Detail/editor Tabs use arrow keys for focus and Enter/Space for activation. Model
and resource subpages retain mounted drafts; hidden panels and their overlays
leave the focus order and accessibility tree. Other editors retain parent-owned drafts.
Advanced Collapsible fields stay mounted; invalid submissions expand their
section and focus the field. CUDA mode uses a single-selection ToggleGroup.

Base UI owns modal focus, Escape, backdrops and scroll locking. Dialogs use Mira's
default width; large editors use `max-w-3xl`. Side margins and scrollable bodies
bound them to the viewport; settings editor actions stay in a fixed footer.
Nested Select/Combobox and confirmation popups return
focus to their trigger, and busy editors retain their close restrictions.
Close, Clear, confirmation and Tooltip labels have both locales.

`useConfirmDialog` returns a local `Promise<boolean>` action and an AlertDialog
node rendered by its owner. One request may be pending per owner; overlapping
requests, cancellation, Escape, hidden owners and unmount resolve false. Accepting continues
the existing action. Cache clearing uses this same confirmation workflow.
`SettingsLeaveContext` and `onLeaveGuardChange` accept async guards with the target route.
App commits routes only after acceptance. For guarded browser back/forward,
it restores the current history entry before asking and replays the target once
on acceptance; cancellation preserves the page, drafts and history order.

Home and Settings share one SidebarProvider/SidebarInset shell bounded to dynamic viewport height.
The 16rem desktop sidebar starts expanded and can be hidden, removing controls from focus order.
Visibility is shared across routes without persistence. Below 768px an initially closed Sheet
is at most 18rem wide with viewport margins; Close/backdrop/Escape return focus to its toggle.
Drawers are titled Sessions or Settings. Accepted navigation/creation closes the drawer;
rejected navigation keeps it open.

The sidebar fixes its brand, New session/New Workspace/New Timeline/New QQBot actions and Settings footer.
The scrolling tree contains Projects and ordinary sessions. Sessions has a header creation icon;
Project names toggle expansion. Workspace/QQBot rows place creation before settings/delete actions,
without a separate arrow or internal creation row.
Creation icons respond to their header-row hover or keyboard-visible focus; session actions respond only to their own row or open menu.
Mouse focus does not retain hover feedback. Touch actions stay visible with 44px targets.
Project sessions retain left indentation and share the Project's right action column; selections keep their own highlight.
Opening a Workspace draft expands its row. Timeline expands an unavailable-chat notice.
Project settings use `/projects/{id}`; `?session={id}` opens a belonging Workspace/QQBot session.
`/new` and `/projects/{id}/new` open drafts, replaced with conversation locations on first send.
Routes survive refresh/history, reject mismatched membership and retain unsaved-navigation guards.
Timeline conversation creation remains unavailable. Global Settings returns to the previous home route.
QQBot creation and Project settings share Connection (initial), Replies and Images tabs with one save action. Tab selection is local and resets on opening; dialog tabs and actions stay outside its scrolling body. All sections stay expanded; disabled icebreaker/generation options remain conditional. Panels stay mounted while hidden and leave focus/accessibility navigation; submission reveals the first invalid field before native validation feedback. Conversation creation binds a group/friend immediately.
The QQ Project settings header contains only its name and sidebar toggle; conversation creation stays in the sidebar. The QQ editor is at most 48rem wide: container widths of 32rem use two columns, and 40rem use three for timing/image parameters. Prompt/keyword inputs keep four/three rows with internal scrolling. Token clearing is inline; hints cover only input syntax and essential semantics. Creation, inheritance and deletion follow [chat/context](chat-context.md#personas-and-sessions).

The fixed chat header contains the sidebar toggle, title and session settings; the composer owns the concrete model menu with Harness and Reasoning on/off controls. Reasoning selects generation mode with session defaults and automatic-adjustment feedback owned by [chat/context](chat-context.md#personas-and-sessions).
The header stays on one row on narrow screens. Agent Persona selection lives in the session dialog.
The message column is at most 48rem wide, with an independent scroller and aligned fixed composer/status area.
Assistant bodies align with both composer edges; user messages align with its right edge. Avatars sit outside
the body column. Below 61rem of chat width, avatars and names share a row above each body, left-aligned
for assistants and right-aligned for users, without narrowing the body or composer.
The composer uses InputGroup and a horizontally scrolling AttachmentGroup; its textarea grows to 12rem, less in short viewports.
Service states and error dismissal have matching English/Chinese labels.
MessageScroller uses pinned @shadcn/react 0.3.1; [runs/streaming](runs-streaming.md#run-lifecycle) owns transcript behavior.

Settings fixes its title in the shared sidebar brand position and a Back to chat footer; the middle navigation
scrolls independently. SidebarGroup reflects responsibility: Application preferences
contains General; Models and execution contains Models, Providers & Runtime and Tools; Daily Chat & Workspace
contains Personas (Cogita Persona, Agent Personas) and Knowledge; Roleplay & Timeline
contains Personas (User Personas, Character Personas) and Worldbook. The two Personas
menus have distinct ids and accessible group context. Each menu uses SidebarMenu;
parents only toggle their nested pages and have no selected state. Menus start collapsed
and closed pages leave keyboard navigation. Active pages use aria-current.
| Menu | Pages / `view` values |
| --- | --- |
| General, Tools | Single page; no `view` |
| Personas | Cogita Persona `user`, Agent Personas `agent`, User Personas `roleplay_user`, Character Personas `character` |
| Models | Dashboard `dashboard`; LLM `llm`, Text Embedding `embedding`, Reranker `reranker`, Image Embedding `image_embedding`, Vision `vision`, Text to Speech `tts`, Speech to Text `asr`, Processor `processor` |
| Providers & Runtime | Model Providers `providers`, Local Runtime `localRuntime` (both remain under `tab=models`) |
| Knowledge, Worldbook | Resources `list`, Global settings `settings` |

Missing/unknown views select user for Personas, dashboard for Models or list for resources. Page changes push browser history;
reselecting the effective current page adds no entry. Back to chat restores the previous ordinary/Project route.
Refresh restores the domain/subpage; resource selection and detail Tabs are local.
The fixed location header shares Home's primary-row height and toggle position. Content scrolls independently
within 64rem; ordinary forms use 48rem. FieldSet/FieldGroup and separators organize forms, resource rows wrap,
and code, logs and tables contain their own overflow.

Home, Project, settings and Runtime show background-free loading text after 200ms, without skeletons; completion/unmount cancels it, new conversations restart it, and errors/retry appear immediately.
Session navigation immediately updates selection and route/title, keeping the header/composer mounted; only history loads before showing messages or confirmed empty content. Uncached targets use a neutral loading title until details arrive.
Failed loads keep the shell and show local retry; sending, attachments and configuration stay disabled until ready. Repeated target selection preserves input and does not reload or restart feedback. Project refreshes retain listed sessions; empty text waits for completion.

## General

GET/PATCH `/api/settings/general` owns attachment size/count and text-context
limits, title behavior, streaming-delta persistence, show_full_processing and nested
PetSettings. The derived title default is read-only; General submissions contain only
fields shown in that form. Other attachment limits/title prompts remain available through
the API. The form groups conversation display and titles with one explicit save action.
Core Memory fields and group transcript instructions are removed and rejected by PATCH.

show_full_processing is a strict boolean, default false, labeled Show full processing history in General.
It controls initial active-reply expansion and immediately updates Cogita state when saved; recording and final
answers are unchanged. Terminal replies start collapsed. PATCH null/non-booleans return 422.

appearance_font_* and resource_status_* are omitted from reads and rejected by PATCH; font routes/scanning are removed.
`GET /api/runtime/resources` remains a cached diagnostic API, independent of
display preferences. Existing font files remain untouched.

Application settings use only the current schema, without old JSON filtering or conversion.
[Data layout](../DATA_LAYOUT.md#database-revisions) owns disposable settings resets and protected data boundaries.

## Model settings

GET/PATCH `/api/models/settings` owns default_model_profile_id, utility_model_profile_id,
external_enabled, external_api_key, max_request_mb and max_normalized_request_mb in appmetadatarecord.model_settings.
HTTP bodies default to 32 MiB (1..100); the strict integer normalized limit defaults to 128 MiB (1..1024). Omitted PATCH fields retain values; null/invalid normalized limits return 422.
Defaults apply to absent settings; explicitly saved HTTP limits remain authoritative. No database schema change or settings conversion is required.
Models → Dashboard → External API shows both limits in MiB; valid edits autosave on blur or Enter, while blank, fractional and out-of-range drafts are not submitted.
The normalized limit also applies to in-app local chat, WD14, SigLIP and reranking while the external service is disabled. Chat image hints display the configured value; help distinguishes runtime limits.
Changes apply to subsequent request preparation without restarting workers. [Models](models.md#external-inference-api) owns byte accounting and the lower native GGUF ceiling.
The default initializes new sessions; changing it preserves existing selections. Header/session
settings select concrete LLMs without a Global default option. [Models](models.md) owns profile
parameters; [chat/context](chat-context.md#auxiliary-tasks-and-titles) owns titles.

Models contains Dashboard followed by all nine model kinds. Dashboard stacks Default models above External API; only enabled LLMs appear in the default chat/auxiliary selectors. Each kind page owns its filtered card list and independent editor draft; adding or copying stays in that kind, which is read-only in the editor. There is no list kind selector.
Providers & Runtime contains Model Providers for external connections and Local Runtime for runtime cards, Storage & cache, collapsed download settings and task history with a log dialog. Both menus share model state and the busy navigation guard. Forms retain drafts across their subpages, with inactive overlays hidden. Removed profiles/service views follow the normal Dashboard default, without redirects. LLM/text embedding/TTS offer Local Runtime and configured providers; image generation requires a provider, while other kinds use Local Runtime only. Disabled providers are marked. New forms default to Local Runtime except image generation, which requires explicit provider selection. Existing unbound profiles show Unconfigured; editing/copying requires selecting a source before saving, without changing the nullable backend contract. Detected Kokoro/WD14 use CPU, DLSS NR uses D3D12, and other engines use CUDA. Unresolved
LLM/TTS/WD14 directories expose no guessed engine options. Local editors expose directory suggestions, execution options and release policy. Vision shows detected WD14/backbone information, read-only Tags,
general/character thresholds (0.35/0.85), CPU with four threads, release policy and external visibility. Thresholds require finite values in [0,1]; zero and fractions round-trip, while blank fields
prevent submission. The removed vision batch-size field is rejected by the API. WD14 directory suggestions require model.onnx and selected_tags.csv; arbitrary safe manual relative references remain
editable. GGUF references select directories; the information panel shows the main model and optional projector without file selectors. LLM editors expose Streaming (default on), and local-only Skip tool capability check / Skip image capability check plus Instant / Reasoning preflight declarations (all default off). The declaration group explains the exclusive skip rules owned by [Models](models.md#resolution-and-request-options). Directory inspection never changes these options; source changes clear all skips. There are no general capability or JSON-format declarations. Missing projectors never disable the skip control. Ambiguity is shown as a blocking load diagnostic while saving remains available. Provider models expose model-ID entry and optional discovery; failed discovery leaves manual entry, saving and
inference available. Opening an active editor or changing sources loads suggestions for its kind/source; reopening refreshes them. Local suggestions include directories already used by profiles. Loading, empty directories/models, no matches and failures have distinct feedback; manual references remain valid. Late results from a previous source cannot replace current suggestions. Changing local/provider source or provider id clears model_ref and replaces source options and
source-specific embedding parameters. Binding an existing unbound draft retains its reference for validation. Reselecting is a no-op. Single-column cards show an unlabeled, accessible enable switch, name/source badge and alias; references and engine/version/installation summaries are omitted. Local cards retain health/load/unload/residency/logs, device/GPU details, tower states and diagnostics; providers show recent-request state and occupancy. Switches PATCH only enabled, stay locked during saving and retain their state on failure. Card details/actions wrap on narrow screens. One toolbar holds status refresh and Add model; there is no inventory list or scan button. Local engine selection follows directory inspection.
New model drafts (including copies) fill each blank name/alias on reference selection or manual-input blur, for every kind and source. Names use the full trimmed reference; aliases lowercase it, replace runs outside [a-z0-9._-] with a hyphen, strip non-alphanumeric prefixes and truncate to 128 characters. Empty results require manual aliases; collisions use normal save validation. Nonempty fields and saved-profile identities are preserved. New LLM drafts require an integer context window before saving (minimum 512; local maximum 1048576). Local drafts start at 4096. Source selection fills only an empty window with 4096 locally or 258000 for providers; nonempty windows, including defaults, carry across sources into the corresponding existing API field. Directory inspection preserves entered windows, including deliberately cleared drafts. Existing editors retain optional-context behavior and the nullable API contract is unchanged. Model dialogs omit Enabled; cards own enablement, new profiles default enabled, and editing retains saved enablement. External API visibility remains in the dialog.
Image generation keeps Local Runtime visible but disabled in Model source. Save requires a provider; discovery and manual model IDs share the normal provider flow. Editors expose image count (default 1) and optional size, quality, style and URL/base64 response format, with Provider default clearing optional values. There are no local execution/lifecycle controls, architecture selection, image history or generation page.
TTS also supports Model Providers. External editors select grok-voice-latest or Customize as a voice architecture independently of the upstream model ID. Grok offers alloy/echo/fable/onyx/nova/eve/sal/rex; Customize requires a manual voice ID. Requests may override the saved default voice. Switching to a provider initializes Grok/alloy; source/provider changes clear model_ref, retain speed/format and reset source-specific parameters. Switching to Customize retains the voice; switching to Grok retains a supported voice or selects alloy, without changing model_ref. Defaults are speed=1/MP3; new models still start locally and TTS cannot be unbound. External editors have no local execution or lifecycle controls.
TTS directories automatically identify Kokoro, Chatterbox or Qwen3-TTS Base; architecture is read-only. New drafts contain speed=1/MP3 defaults. Chatterbox/Qwen expose an optional seed: blank saves
null (unfixed), and 0 is a valid fixed seed. Speech requests may override it; omitted/null request seeds inherit the profile. Fixed seeds control randomness without guaranteeing identical audio. Seed
edits use the existing profile save/lifecycle flow. Switching architecture preserves speed/format and clears incompatible generation and execution settings, resetting seed to null for Audio or
removing it for Kokoro. Same-engine directory changes preserve customized settings. Directory changes clear old information and ignore late responses; new draft identity suggestions follow the shared model form rules. Saved Kokoro editors show preset availability by language; Audio editors explain reference-based API usage and Qwen's optional transcripts. Local voices are request selections, not profile records. Ownership/expiry belong to [Models](models.md#audio-tts-and-temporary-references).

Image embedding uses Local Runtime. Choosing/editing a directory reads inspect information without loading; structure, image/text dimensions, native text position limit and processor settings are
read-only, with missing values marked Determined when loading. Tokenizer placeholder lengths are not presented as the position limit. Diagnostics/errors do not block saving. Changing the reference
clears old information immediately and ignores late responses, preserving names and runtime policies; new empty identity fields follow the shared model form rules.
The strict unload_other_tower_on_call switch defaults on. Off permits both towers to reside while requests remain serial. Device, threads, worker batch limit (1..16) and release policy remain
editable; architecture/dimensions/normalization are not parameters. Rows expose separate tower badges and cached vector identity. Load and log menus select Image/Text; Unload releases the whole
profile. Health, busy locks and hidden subpage menus use the shared lifecycle. [Models](models.md#siglip-image-and-text-embeddings) owns execution and acceptance limits.

Text embedding offers Local Runtime/providers. Directory selection inspects metadata without loading; pipeline, pooling, prompt inclusion, normalization, similarity, dimensions and
effective token limit are read-only. Resolved query/document templates are visible; collapsed advanced controls select declared prompt names or automatic resolution. Directory changes clear stale
information and prompt selections; source changes reset incompatible parameters/options. Diagnostics block loading, not saving. Runtime controls retain CPU/CUDA, four threads, batch 1..16 and manual
release defaults. [Models](models.md#local-text-embeddings) owns native semantics and Harrier-only acceptance limits. Rerankers use Local Runtime and automatically inspect
architecture, scoring/activation, pipeline and effective token limit. Directory changes clear old information and ignore late responses; unnamed new drafts receive directory-name suggestions.
Diagnostics block loading, not saving. Parameters are empty: architecture, templates and scoring tokens are not editable. CPU/CUDA, four threads, batch 1..16 (default 1), manual release and external
visibility use existing controls. [Models](models.md#local-reranking) owns native processing and acceptance limits.

ASR uses Local Runtime, with CUDA, four threads, manual release and external visibility off by default. Directory selection inspects architecture, processor, sample rate, features, native window,
languages and timestamp support as read-only information. Changing directories clears stale results and preserves edited names/defaults; unnamed new drafts receive directory-name suggestions. Invalid
directories remain saveable. Language (auto or supported code), prompt, temperature (0..1) and response format are editable defaults for internal/public requests. Explicit auto/empty prompt resets
them; request overrides never change the profile. Both locales explain that json/text omit timestamps and verbose_json returns segment timestamps, while every format transcribes complete recordings.
There is no architecture selector, duplicated preprocessing configuration or transcription page. [Models](models.md#local-speech-recognition) owns execution and limitations.

Processor fixes its source to Local Runtime and shows read-only DLSS NR/image processing, resource diagnostics, style/preset/intensity/tone/structure/skin/auto-mask/channel-order defaults, GPU index,
release policy and external visibility. Incomplete directories remain saveable. There is no processing page. [Models](models.md#dlss-nr-image-processing) owns ranges and execution. Local Runtime has
full-width Core Runtime and DLSS NR cards, one per row at every viewport. Version, platform and architecture appear as three separate badges beside each title, wrapping on narrow screens; status and running jobs stay separate.
Completed jobs remain in history. Install/update, repair-required and cancel are contextual primary actions; other maintenance/log actions use a menu. Cards have no Details disclosure; the DLSS summary names
the manual NR resource requirement. Installing/repairing components requires a healthy base. Component completion refreshes profiles so the generated default appears immediately.

Model Providers uses one full-width card per row: an unlabeled left switch, name/URL, and edit/delete actions that wrap right on narrow screens. Switches have localized accessible names and save only enabled through PATCH; busy actions lock and errors retain the last confirmed state. Refresh/Add share one toolbar without introductory copy or status badges. Provider editors expose the default-off connection.allow_unindexed_complete_tool_call switch with localized scope guidance. Creation defaults to false; PATCH omission retains its value, explicit false disables it, and null/non-boolean values fail. It uses existing connection JSON storage and busy-edit/client-invalidation behavior; no database rewrite or automatic enablement occurs.
Provider editors own only name/connection; creation enables by default and editing omits enabled. Provider/settings reads omit secret keys and expose presence flags. PATCH omission retains keys; empty strings clear them. External enablement requires a nonempty key; storage is unencrypted. Busy connection edits, referenced deletion and invalid combinations fail.

LocalRuntimeSettings has no profile id, enablement switch or editable name. GET/PATCH `/api/models/local-runtime/settings` owns only nested download defaults. Local Runtime is always enabled without
automatic installation/loading. Download edits do not invalidate local models or refresh runtime/profile reads. Settings remain independent of provider CRUD and runtime
job identity. Providers can be added, edited and deleted when unreferenced; local maintenance does not block provider inference. Installation details show the recorded installed version. Reads check
dependency identity, metadata and entries; source changes reuse the environment. Invalid/old metadata or changed dependencies show Repair required. Checks recover on refresh when files/dependencies
are restored; failed/interrupted jobs require explicit repair. Install never rebuilds an unavailable installation; manual Repair also rebuilds healthy ones. Finalizing precedes promotion. The local
settings download object owns http_proxy, pypi_index_url, pytorch_index_url and github_release_proxy_url, patched at `/api/models/local-runtime/settings`. Index/release proxy URLs require HTTPS; HTTP
is allowed for the explicit proxy. Credentials are rejected; these settings serve runtime artifacts/dependencies only. Refresh status reads runtime metadata; only Scan storage fetches page storage
statistics. Entry, navigation, reconnects, disclosure and maintenance completion never scan automatically. Before scanning the card shows an empty state; snapshots survive subpage navigation in memory,
show their scan time and become stale after maintenance. Failed rescans retain the last snapshot with an error. Incomplete scans show unknown sizes, never zero. Cache recovery uses an exclusive logical-size
estimate. Prune is a secondary action; Clear cache lives in the cache menu and confirms consequences even without a scan. Maintenance shares the task lock and retains its internal before/after accounting.
The page adopts active cache jobs and jobs started there; terminal feedback is dismissible and clears on leaving/reload, while history/details retain results and logs. Log reads do not refresh other state.
CUDA profiles use an Automatic/Manual GPU-layer control, preserving a draft's manual value while switching modes.
Defaults and execution belong to Models.

## Other domains

Persona editors share identity/avatar/prompts and collection-specific resources; [chat/context](chat-context.md) owns restrictions.
Cogita Persona opens its singleton editor without create/delete controls. Other collections use lists/dialogs;
the protected Agent Cogita also has no delete control. Editors retain tab drafts, guard navigation and clean temporary avatars.
Session dialogs own Agent/model/context/temperature and Knowledge; the composer menu and [Harness Sheet](harness-tools.md) own Harness and tool selection. Workspace controls show inheritance and per-setting reset,
submit only changed overrides, lock Cogita identity and inherited Knowledge, and disable Project-forbidden tools.
Project editors offer type-specific Configuration and Knowledge/Worldbook tabs; missing required Personas
have management links. Context controls expose message/character limits and attachments, with no History selector.
Creation defaults to unlimited session history, global model inheritance and, for Workspace, the default Agent, fixed Cogita Persona, Harness off and the explicit current tool catalog.
QQBot settings place an optional external image-description model selector beside image input, with an explicit Do not use choice. Image input permits at most five current-batch images, prioritizing pictures and recent occurrences; history uses current description placeholders. Descriptions and original display are independent of main model input; [Chat/context](chat-context.md#qqbot-conversations) owns selection, sharing and alt text. New QQBot forms initialize their editable conversational prompt in the opening UI language. Language changes preserve the draft; clearing and saving retains an empty prompt. Editing existing Projects never reapplies the default. QQBot image generation has a separate provider-only image_generation model selector with Disabled as the default. Selecting a model shows size/quality/style overrides, each supporting model defaults. Disabling generation retains the saved controls. Brief helpers state the current-batch image limit, later history descriptions, one generated image per call and size syntax; reply limits note the shared text/image allowance. Generated images use existing picture previews and delivery controls; no separate generation page is provided.
QQBot settings include a default-off group icebreaker switch beside reply triggers. Enabling it reveals three positive integer fields in seconds: cold silence, observation wait and cooldown. Disabling hides the fields while retaining values. A brief bilingual helper explains replying to a lone speaker after quiet; [Chat/context](chat-context.md#qqbot-conversations) owns defaults and trigger rules. QQBot context fields replace the shared descriptions with one blank/unlimited and zero/no-history hint; other editors retain their descriptions. Failed saves retain the draft.
Harness global settings own only searxng_base_url through `/api/tools/settings`.

ToolsPanel shows catalog, risk, parameter schema, direct JSON calls, results and
approval controls shared with RunPanel. Catalog and call/results use two columns
on wide screens and stack on narrow screens; search settings form a separate section.
Search configuration is snapshotted for a run; edits never change a pending call's destination. [Harness/tools](harness-tools.md)
owns the runtime workflow and permissions.

Knowledge settings own chunk/retrieval/context controls and unified reranker
selection. KB records select unified embedding profiles. Model paths, connection
timeouts, preprocessing instructions, dimensions, batching and normalization
belong to Models. [Knowledge](knowledge.md) owns index invalidation and retrieval.
Worldbook settings stay at `/api/worldbook/settings`; its matching/context
rules are owned by chat/context. There are no independent per-kind model pages,
extension configuration objects or old General inference-service settings.

Knowledge and Worldbook default to resource lists, with a separate Global settings
sidebar page and inline details. Refreshing a resource page returns to its list.
Internal detail Tabs preserve drafts; switching list/settings retains global-settings
drafts. Clicking Resources while in a detail returns to the list. Leaving an edited
detail asks before discarding; switching domains or returning to chat also protects
global-settings drafts. Browser unload protects unsaved work. Busy mutations prevent
departure, and stale detail reads cannot replace a new selection.

Worldbook submits only editable settings, omitting id and timestamps. One
case-sensitive control synchronizes its inverse regex field. Advanced context,
matching and recursion controls start collapsed. Knowledge exposes all retained
retrieval, chunk, source-limit and context fields; advanced items start collapsed.
Its optional score threshold precedes default_min_score; both empty means no
score filtering. Chunk overlap must be smaller than chunk size. Model kinds,
paths and source settings remain under Models. Both forms retain advanced drafts
when collapsed and preserve nullable override semantics.

## Pet foundations

The Codex Pet overlay, sprite format, package service, settings page and all
discovery/import/selection/deletion/asset flows are removed. Their routes return
404; no placeholder routes or package scanning remain. Existing data/pet files
are untouched. No Pet is mounted or fetched by the current application.

PetSettings remains nested in AppSettings with only position:
`{mode: default|custom, x: int|null, y: int|null}`. Coordinates are strict integers
between -20000 and 20000. Default position has null coordinates. GET
`/api/pets/settings` returns `{settings: {position}}`; PATCH accepts
`{values: {position?: Partial[PetPosition]}}`. It deep-merges position using the
same AppSettingsStore as General. Removed fields and null position/mode return
422. Settings reset effects belong to the data-layout document above.

usePetPosition receives saved position, width, height and onCommit. It bounds
dragging to the viewport, commits rounded coordinates on pointer release and
returns saving/error state. Pointer cancellation restores the drag origin and
does not save. It has no sprite, package, API client or event-dispatch dependency.
Without both custom coordinates it uses a default bottom-right position.

petTaskState is a pure current-session selector over existing runs and steps.
It returns run_id, raw RunStatus (or IDLE), step_kind and progress fields. Active
runs take precedence over recent terminal runs; timestamps retain microseconds.
Approval steps take precedence while waiting; terminal states expose no active
step. It imports no animation states or bubble text. Future visuals subscribe
to the existing Cogita store; no Pet-specific task endpoint or polling is added.
New appearance, asset format and animations are explicitly deferred.

## HTTP schemas

OpenAPI covers every retained settings owner, derived General fields, Pet
position, storage maintenance and cached health/resource diagnostics. Ordinary
JSON responses have runtime validation. Manual PATCH request documentation
preserves merge-time validation, field omission, explicit null and empty-string
semantics; keys remain write-only with presence flags in read models.
All errors use the application's error envelope, including 422, and invalid
server responses return sanitized 500 INTERNAL_ERROR. Frontend types and clients
are maintained directly rather than generated from OpenAPI.
