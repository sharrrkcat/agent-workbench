# Settings contract

Settings have explicit domain owners and strict Pydantic inputs with
extra=forbid. Unknown/removed fields return HTTP 422. The frontend keeps six
navigation entries and `/settings?tab=` values: general, models, personas,
knowledge, worldbook, tools. Default/unknown tab selects General, including pet.

SettingsPage owns navigation and composition only. Domain panels own their
forms; shared controls are independent of the page. Types and API clients use
domain modules, with a single HTTP/error implementation. User-visible labels,
states and feedback have matching English/Chinese resources. User content,
prompts, ids, API fields and error codes retain their original values.

## General

GET/PATCH `/api/settings/general` owns attachment size/count and text-context
limits, title behavior, Core Memory, group transcript instruction,
streaming-delta persistence, show_full_processing and nested PetSettings. Derived title/group prompt
defaults/effective values are read-only; frontend General submissions contain
only the editable fields shown in that form. Remaining limits/prompts are
available through this API even when the current form has no dedicated control.

show_full_processing is a strict boolean, default false, labeled Show full
processing history in General. It controls initial expansion of active reply
processing only; recording and final answers are identical in both modes. The
saved value immediately updates Workbench state. Terminal replies always start
collapsed, even with this preference enabled. PATCH null/non-booleans return 422.

appearance_font_* and resource_status_* are removed; reads omit them and PATCH
rejects them. Font asset routes and startup font scanning are removed.
`GET /api/runtime/resources` remains a cached diagnostic API, independent of
display preferences. Existing font files remain untouched.

Revision `0007_phase5_cleanup` deletes the disposable app_settings JSON row.
General, Core Memory and Pet settings therefore reset to defaults on upgrade;
new writes use only the current schema. No old JSON filtering/conversion is
performed. Other settings objects, records and data directories are preserved.
This irreversible test-state reset is documented in [data layout](../DATA_LAYOUT.md).

## Model settings

GET/PATCH `/api/models/settings` owns default_model_profile_id,
utility_model_profile_id, external_enabled, external_api_key and max_request_mb.
These persist as the model_settings object in appmetadatarecord. The chat default
initializes new sessions; changing it preserves existing session selections.
The header and session settings select concrete LLM profiles without a Global
default option. Model selection and
profile parameters are defined in [models](models.md); title behavior belongs
to [chat/context](chat-context.md#auxiliary-tasks-and-titles).

Models has Profiles, Connections, Runtimes and External service tabs. The kind
filter, profile and connection editors, external-service form and runtime view
share useModelsStore. Drafts survive switching between Models tabs. Health,
load, unload, inventory and runtime actions use the common model services.
Local inventory/provider listing do not load weights. External unknown
residency/unsupported unload remains visible.

Provider/settings reads omit secret keys and expose presence flags. PATCH
omission retains a key; an explicit empty string clears it. External enablement
requires a nonempty key. Local key storage is unencrypted. Busy connection
edits, referenced deletion and invalid model combinations return errors.

Runtime download settings at `/api/models/runtime/settings` own http_proxy,
pypi_index_url, pytorch_index_url and github_release_proxy_url. Index/release
proxy URLs require HTTPS; HTTP is allowed for the explicit proxy. URL credentials
are rejected. These settings serve runtime artifacts/dependencies only.
Runtimes exposes install/cancel/reinstall/uninstall, job history and bounded logs.

## Other domains

Personas owns identity, avatar, prompt and ordered Knowledge/Worldbook bindings.
Session configuration owns model selection, context, generation, the Harness
boolean and a catalog-backed tool list. Resources show locked Persona bindings
and editable session additions; there are no Persona configuration overrides.
See [chat/context](chat-context.md). Harness settings own only the optional
searxng_base_url through `/api/tools/settings`.

ToolsPanel shows catalog, risk, parameter schema, direct JSON calls, results and
approval controls shared with RunPanel. Search configuration is snapshotted for
a run; edits never change a pending call's destination. [Harness/tools](harness-tools.md)
owns the runtime workflow and permissions.

Knowledge settings own chunk/retrieval/context controls and unified reranker
selection. KB records select unified embedding profiles. Model paths, connection
timeouts, preprocessing instructions, dimensions, batching and normalization
belong to Models. [Knowledge](knowledge.md) owns index invalidation and retrieval.
Worldbook settings stay at `/api/worldbook/settings`; its matching/context
rules are owned by chat/context. There are no independent per-kind model pages,
extension configuration objects or old General inference-service settings.

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
422. Revision 0009 resets disposable app_settings without filtering old JSON.

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
