# Settings contract

Settings have explicit domain owners and strict Pydantic inputs with
extra=forbid. Unknown/removed fields return HTTP 422. The frontend keeps six
domains and `/settings?tab=` values: general, models, personas, knowledge,
worldbook, tools. Default/unknown tab selects General, including pet.

SettingsPage owns navigation and composition only. Domain panels own their
forms; shared controls are independent of the page. Types and API clients use
domain modules, with a single HTTP/error implementation. User-visible labels,
states and feedback have matching English/Chinese resources. User content,
prompts, ids, API fields and error codes retain their original values.

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
Select, Combobox, Checkbox, Switch, Tabs, Collapsible, ToggleGroup, Dialog,
AlertDialog, Tooltip, Badge and Table directly. Domain components retain model filtering and
resource binding rules. Vite, TypeScript and the test module loader resolve
`@/` to `frontend/src/`; `cn` combines component styles.

Desktop controls retain Mira density. Coarse-pointer buttons, options and form
actions have at least 44px targets; Checkbox/Switch keep compact marks with
expanded targets and associated labels. Field labels/descriptions are connected
to controls. Forms retain native required/range validation and existing blank,
null and zero semantics. Hidden file inputs remain behind visible Buttons.
Controlled Select preserves groups, disabled options, empty choices and missing
selected records. Model IDs and projector paths use editable Comboboxes whose
text is the field value, including values outside the suggestions.

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

Home and Settings share one SidebarProvider/SidebarInset shell bounded to the
dynamic viewport height. The desktop sidebar
is 16rem wide, initially expanded and can be fully hidden; hidden controls leave
the focus order. Visibility is shared across routes but not persisted. Below 768px it becomes an initially
closed Sheet, at most 18rem wide with viewport margins. Close, backdrop and Escape
return focus to the toggle. Drawers are titled Sessions or Settings. Selecting/creating
a session, opening Settings or accepting settings navigation closes the drawer;
rejected navigation keeps it open.

The sidebar fixes its brand/new-session header, two disabled feature placeholders
and Settings footer; only the session list scrolls. Each row has one truncated
title, with its full title available, and a delete menu shown on hover, focus,
menu opening or coarse pointers. Placeholders have no routes. Session deletion
semantics belong to [chat/context](chat-context.md#personas-and-sessions).

The fixed chat header contains the sidebar toggle, title, concrete model selector
and session settings; the model selector occupies a second row on narrow screens.
Mode and speaker changes live in the session dialog. The message column is at most
48rem wide, with an independent scroller and aligned fixed composer/status area.
The composer uses InputGroup and a single horizontally scrolling AttachmentGroup;
its textarea grows to at most 12rem, with a lower cap in short viewports.
Service states and error dismissal have matching English/Chinese labels.
MessageScroller uses pinned @shadcn/react 0.3.1; transcript behavior belongs to
[runs/streaming](runs-streaming.md#run-lifecycle).

Settings fixes its title in the shared sidebar brand position and a Back to chat footer; the middle navigation
scrolls independently. SidebarGroup reflects responsibility: Application preferences
contains General; Models and execution contains Models/Tools; Personas and context
contains Personas/Knowledge/Worldbook. Each domain is a SidebarMenu. Models, Knowledge
and Worldbook have parent menu buttons and nested SidebarMenuItem pages; clicking a
parent only toggles its menu. These menus start collapsed, keep their icons, and
hide closed pages from keyboard navigation. Groups stay visible; single-page menus
have direct entries. Parent menus have no selected state; active pages use aria-current.
The 11 pages replace secondary Tabs:

| Domain | Pages / `view` values |
| --- | --- |
| General, Personas, Tools | Single page; no `view` |
| Models | Model profiles `profiles`, Providers `providers`, Local Runtime `localRuntime`, External API `service` |
| Knowledge, Worldbook | Resources `list`, Global settings `settings` |

Missing/unknown views select profiles or list. Page changes push browser history;
reselecting the effective current page adds no entry. Back to chat navigates to `/`.
Refresh restores the domain/subpage; resource selection and detail Tabs are local.
The fixed page header shares Home's primary-row height and toggle position and shows
only the current location. Content scrolls
independently, with a 64rem maximum width and ordinary forms limited to 48rem.
FieldSet/FieldGroup and separators organize forms; resource rows wrap on narrow
screens. Code, logs and tables contain their own overflow.

## General

GET/PATCH `/api/settings/general` owns attachment size/count and text-context
limits, title behavior, Core Memory, group transcript instruction,
streaming-delta persistence, show_full_processing and nested PetSettings. Derived title/group prompt
defaults/effective values are read-only; frontend General submissions contain
only the editable fields shown in that form. Remaining limits/prompts are
available through this API even when the current form has no dedicated control.
The form groups conversation display, Core Memory, titles and group prompts,
with one explicit save action.

show_full_processing is a strict boolean, default false, labeled Show full
processing history in General. It controls initial expansion of active reply
processing only; recording and final answers are identical in both modes. The
saved value immediately updates Workbench state. Terminal replies always start
collapsed, even with this preference enabled. PATCH null/non-booleans return 422.

appearance_font_* and resource_status_* are removed; reads omit them and PATCH
rejects them. Font asset routes and startup font scanning are removed.
`GET /api/runtime/resources` remains a cached diagnostic API, independent of
display preferences. Existing font files remain untouched.

Application settings use only the current schema, with no old JSON filtering
or conversion. Disposable settings resets and protected data boundaries are
documented in [data layout](../DATA_LAYOUT.md#database-revisions).

## Model settings

GET/PATCH `/api/models/settings` owns default_model_profile_id,
utility_model_profile_id, external_enabled, external_api_key and max_request_mb.
These persist as the model_settings object in appmetadatarecord. The chat default
initializes new sessions; changing it preserves existing session selections.
The header and session settings select concrete LLM profiles without a Global
default option. Model selection and
profile parameters are defined in [models](models.md); title behavior belongs
to [chat/context](chat-context.md#auxiliary-tasks-and-titles).

Models has four sidebar pages. Default chat/auxiliary model selectors appear only
on Model profiles. Providers manages external connections; Local Runtime shows installation,
storage, download settings and task history, with a log dialog. Forms and the kind filter
retain drafts across subpages. Models use grouped Unbound, Local Runtime and configured-provider
choices, filtered to supported kinds; disabled providers are marked. TTS defaults to local Kokoro and vision to local WD14 CPU;
other new profiles start unbound. Local models expose inventory, execution options and release policy.
Vision offers only Unbound/Local Runtime, WD14/Tags read-only fields, general/character thresholds (0.35/0.85),
CPU with four threads, release policy and external visibility. Thresholds require finite values in [0,1]; zero and
fractions round-trip, while blank fields prevent submission. The removed vision batch-size field is rejected by the API.
WD14 directory suggestions require model.onnx and selected_tags.csv; arbitrary safe manual relative references remain editable.
GGUF vision exposes required mmproj_ref with inventory suggestions and manual relative-path entry.
Changing the main model or disabling vision clears the projector. Transformers vision remains selectable;
the worker verifies actual image capability during execution.
Provider models expose model-ID entry and optional discovery; failed discovery leaves manual entry,
saving and inference available. Late results from a previous source cannot replace current suggestions.
Changing local/provider source or provider id clears model_ref and replaces source options. Unbinding
preserves model_ref; binding an unbound draft retains its reference for validation. Reselecting is a no-op.
Local rows show health/load/unload/residency/logs; provider rows show recent-request state and occupancy,
without lifecycle controls or a trial-inference action. Local engine selection follows reference/architecture.
TTS profiles select Kokoro, Chatterbox or Qwen3-TTS Base, speed and MP3/WAV defaults.
Chatterbox/Qwen expose an optional seed: blank saves null (unfixed), and 0 is a valid fixed seed.
Speech requests may override it; omitted/null request seeds inherit the profile. Fixed seeds control
randomness without guaranteeing identical audio. Seed edits use the existing profile save/lifecycle flow.
Switching architecture preserves speed/format and clears incompatible generation
and execution settings, resetting seed to null for Audio or removing it for Kokoro;
reselecting the source retains the selected architecture and seed.
Saved Kokoro editors show preset availability by language; Audio editors
explain reference-based API usage and Qwen's optional transcripts. Voices are request
selections, not profile records. Ownership/expiry belong to [Models](models.md#audio-tts-and-temporary-references).

Provider/settings reads omit secret keys and expose presence flags. PATCH
omission retains a key; an explicit empty string clears it. External enablement
requires a nonempty key. Local key storage is unencrypted. Busy connection
edits, referenced deletion and invalid model combinations return errors.

LocalRuntimeSettings has no profile id or editable name. GET/PATCH `/api/models/local-runtime/settings`
owns enabled=true and nested download defaults. It is independent of provider CRUD and runtime job identity.
Providers can be added, edited and deleted when unreferenced; local maintenance does not block provider inference.
Installation details show the recorded installed version. Reads check dependency identity, metadata and entries;
source changes reuse the environment. Invalid/old metadata or changed dependencies show Repair required.
Checks recover on refresh when files/dependencies are restored; failed/interrupted jobs require explicit repair.
Install never rebuilds an unavailable installation; manual Repair also rebuilds healthy ones. Finalizing precedes promotion.
The local settings download object owns http_proxy, pypi_index_url,
pytorch_index_url and github_release_proxy_url, patched at `/api/models/local-runtime/settings`.
Index/release
proxy URLs require HTTPS; HTTP is allowed for the explicit proxy. URL credentials
are rejected. These settings serve runtime artifacts/dependencies only.
Storage is fetched on entry, explicit refresh and maintenance completion, with
no timer. Incomplete scans show unknown values; cache recovery uses an exclusive
logical-size estimate. Clear cache requires confirmation, including the estimate
and future-download consequence. Maintenance actions share the runtime task lock.
Cache history/results have their own labels and no synthetic runtime identity.
CUDA profiles use an Automatic/Manual GPU-layer control, preserving a draft's
manual value while switching modes. Defaults and execution belong to Models.

## Other domains

Personas owns identity, avatar, prompt and ordered Knowledge/Worldbook bindings.
Session configuration owns model selection, context, generation, the Harness
boolean and a catalog-backed tool list. Resources show locked Persona bindings
and editable session additions; there are no Persona configuration overrides.
See [chat/context](chat-context.md). Harness settings own only the optional
searxng_base_url through `/api/tools/settings`.

ToolsPanel shows catalog, risk, parameter schema, direct JSON calls, results and
approval controls shared with RunPanel. Catalog and call/results use two columns
on wide screens and stack on narrow screens; search settings form a separate section.
Search configuration is snapshotted for
a run; edits never change a pending call's destination. [Harness/tools](harness-tools.md)
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
to the existing Workbench store; no Pet-specific task endpoint or polling is added.
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
