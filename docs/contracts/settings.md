# Settings contract

Settings have explicit domain owners and strict Pydantic inputs with
extra=forbid. Unknown/removed fields return HTTP 422. The frontend keeps seven
navigation entries and `/settings?tab=` values: general, models, personas,
knowledge, worldbook, tools, pet. Default/unknown tab selects General.

SettingsPage owns navigation and composition only. Domain panels own their
forms; shared controls are independent of the page. Types and API clients use
domain modules, with a single HTTP/error implementation. User-visible labels,
states and feedback have matching English/Chinese resources. User content,
prompts, ids, API fields and error codes retain their original values.

## General

GET/PATCH `/api/settings/general` owns attachment size/count and text-context
limits, title behavior, Core Memory, group transcript instruction,
streaming-delta persistence and nested PetSettings. Derived title/group prompt
defaults/effective values are read-only; frontend General submissions contain
only the editable fields shown in that form. Remaining limits/prompts are
available through this API even when the current form has no dedicated control.

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
These persist as the models object in appmetadatarecord. Model selection and
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

Personas owns prompt, model, context policy, generation, harness defaults and
ordered Knowledge/Worldbook bindings. Session overrides are explicit; see
[chat/context](chat-context.md). Harness settings own only the optional
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

## Pet settings and packages

PetSettings is nested in AppSettings: pet_enabled, default_pet_id, pet_scale,
show_status_bubble, bubble_offset_x/y, jump_on_hover, running_prefix, position
(default/custom with x/y), and bubble_texts. Bubble keys are idle, waiting,
done, failed, cancelled, interrupted, wake, tuck, status, select, reload, no_pet,
import_success/import_failed and delete_success/delete_failed.

GET `/api/pets/settings` returns `{settings: PetSettings}`. PATCH accepts
`{values: Partial[PetSettings]}`, validates strictly and deep-merges position
and bubble_texts. Command text configuration and top-level Pet fields are invalid.
Settings use the same AppSettingsStore as General.

`/api/pets` lists packages; POST `/scan` refreshes discovery; POST `/import`
accepts pet.json and spritesheet.webp; DELETE `/{pet_id}` removes a package;
GET `/{pet_id}/spritesheet.webp` serves the asset. Package errors use structured
4xx responses. Default selection uses the configured valid pet or first valid
package. Bundled package deletion is disabled.

PetOverlay loads current settings/catalog initially and after change events,
without polling or a second default-settings model. usePetData rejects stale
refreshes; usePetPosition bounds/persists dragging; petState derives sprite and
bubble status. Approval/WAITING_FOR_USER shows waiting; pending/running uses the
configured prefix and bilingual step kind; terminal states map to done/failed/
cancelled/interrupted. Hover/jump behavior is preserved. Custom bubble content
is stored user data and is not translated. No capability or chat-command path
controls the overlay.
