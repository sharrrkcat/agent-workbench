# Local data layout

SQLite records are disposable test state. Files have separate ownership and
are never removed by schema revisions.

| Path | Contents and owner |
| --- | --- |
| data/cogita.db | Application test state: Personas, sessions/messages/runs, settings, models/providers, Knowledge/Worldbook, runtime jobs |
| data/attachments/ | Uploaded files and Persona avatars; explicit orphan cleanup |
| data/tmp/voice-references/ | Model-service temporary reference audio; no database records |
| data/tmp/asr-inputs/ | Request-scoped transcription uploads; no database records |
| data/knowledge/ | Knowledge service source/index working files |
| data/models/ | Manually managed model weights; no application downloader |
| data/runtimes/ | Supervisor-owned local inference release, caches and staging |
| data/logs/ | Operational diagnostics and inference/runtime logs |
| data/assets/ | Existing local files, including retired font assets; untouched by cleanup |
| data/pet/ | Retired Pet packages; untouched and no longer scanned or served |
| data/backups/ | Optional operator backups; ignored by Git |
| frontend/dist/ | Generated frontend production build |
| build/ | Generated portable package and optional ZIP; ignored by Git |

Root dist/ is the removed application snapshot and remains unsupported.
The portable builder uses build/ and excludes local data and secrets. It copies
the maintained README, run guide and docs rather than embedding another guide.

## Database revisions

Alembic head is `0019_asr`; there are 24 current business tables.
Empty databases upgrade to head. Nonempty unversioned databases are rejected
instead of auto-stamped. Health reports schema_revision; there is no separate
schema_version authority. Destructive test revisions do not support downgrade.

The default `data/cogita.db` is initialized independently, with fresh settings,
model/provider profiles and runtime registration. Other database files are not
imported, moved or removed. Model, attachment and runtime files retain their separate ownership.

Revisions 0001 through 0006 record the baseline, extension pruning, unified
models, managed runtimes, Persona/session members and private harness
continuations. They remain executable history, not alternative current schemas.

Revision `0007_phase5_cleanup` changes no tables: it deletes only
appmetadatarecord's app_settings row. This resets General, Core Memory and Pet
settings to current defaults. Models, harness settings, sessions, messages,
pending approvals, Knowledge, Worldbook and other records are preserved. No old
settings JSON is copied or converted. Repeating upgrade at head leaves newly
saved settings intact.

Revision `0008_chat_configuration` recreates Persona/session tables with
session-owned configuration. It discards disposable Personas and their bindings,
session members/additions, messages, runs, steps, events and private snapshots,
then seeds reduced Chat and Translate records. Knowledge, Worldbook, models,
runtimes and settings are preserved. No filesystem operations or record
conversions are performed.

Revision `0009_pet_foundation` deletes only appmetadatarecord's app_settings row
to remove the old Pet presentation schema. General, Core Memory and Pet position
reset to defaults. Other settings and business records, including new sessions
and runs, survive. Repeated upgrade preserves subsequently saved settings.
Existing Pet assets, models, runtimes, attachments and all other file directories
are untouched.

Revision `0010_runtime_maintenance` recreates only disposable runtime_jobs and
clears runtime installation job_id references. Installation identity, version,
state and integrity digests, other business records and all file directories
survive. There is no conversion of historical jobs. Repeating upgrade preserves
newly recorded maintenance tasks.

Revision `0011_tts` extends model_profiles' kind constraint to include tts.

Revision `0012_runtime_families` discards excluded runtime/model configurations,
dependent Knowledge indexes and unfinished continuations, and clears affected
model selections. Unaffected records and all files remain; no records are converted.
Existing record values remain unchanged. Repeated upgrades preserve new TTS
profiles. The revision performs no filesystem operations.

Revision `0013_unified_backend` rebuilds backend/model/runtime configuration and
seeds the reserved local backend. It clears model selections, dependent Knowledge
records/bindings and unfinished model-backed continuations, preserving completed
history and unrelated settings. It does not convert records or touch files.
Old installation directories remain on disk but are not executable backends.
Repeated upgrades preserve newly saved configuration.

Revision `0014_provider_runtime_separation` replaces disposable model/backend configuration
with provider_profiles and constrained nullable local/provider model sources, without converting old profiles.
It resets local_runtime_settings, model/default/utility/session/reranker selections, dependent test Knowledge
and unfinished model continuations, preserving completed histories and unrelated settings.
Alembic batch alteration removes runtime backend foreign keys: installation uses internal singleton id=local;
jobs have no backend column. Installation version/state/digest/job linkage/timestamps and every job's
identity, result, progress, state and log reference survive. A previously valid installation remains recognized.
The revision changes only database schema/rows, never installation/model/attachment/cache/log files.
Repeat upgrades preserve newly saved configuration and do not rebuild the environment.

Revision `0015_wd14_vision` extends ck_model_source to permit local vision alongside LLM/TTS,
retaining Provider LLM/text-embedding rules. It deletes only obsolete vision drafts without parameter conversion;
other models, providers, runtime installation/jobs and business records survive. Repeating upgrade preserves
new vision profiles. No filesystem operations or installed-environment rebuild occurs.
WD14 directories under data/models/vision require model.onnx and selected_tags.csv; config.json is optional.
Inventory and loading boundaries check only file existence and path containment, not model identity or contents.

Revision `0016_siglip_image_embedding` permits local image_embedding sources and deletes only their obsolete unbound drafts.
It performs no parameter conversion and preserves other records and all model/attachment/runtime files. Repeat upgrades preserve
new SigLIP profiles. SigLIP keeps native safetensors/configuration under data/models/image_embeddings; loaded identity is held in memory,
without model verification manifests or stored embeddings. [Models](contracts/models.md#siglip-image-and-text-embeddings) owns hashing and lifetime rules.

Revision `0017_local_text_embeddings` permits local text embedding bindings and removes kb_embeddings.embedding_normalize_snapshot.
Profiles, source/chunk/vector records, indexes, other settings and all filesystem data survive; repeated upgrades preserve them.
Text packages remain under data/models/embeddings. Inspection reads JSON metadata and no text-embedding path hashes model files,
creates model manifests or detects same-path replacements. Explicit unload/reload and Knowledge reindexing are required after replacement.

Revision `0018_local_rerankers` permits local reranker bindings and resets only abandoned reranker parameters to an empty object.
It preserves profile IDs/references, Knowledge indexes, other records and every file directory; repeated upgrades preserve new configurations.
CrossEncoder packages remain under data/models/rerankers, with configuration-only inspection and no model hashes or fingerprints.
Same-path replacement requires explicit unload/reload and does not require rebuilding embedding indexes.

Revision `0019_asr` extends the model-kind and local-source constraints with asr. Existing profiles, runtime registration/jobs and all other records survive unchanged; the revision never touches filesystem data.
Native Whisper directories reside under data/models/asr. Inspection reads configuration JSON; no ASR path hashes model files or writes fingerprints/manifests. Replacing files requires explicit unload/reload.

Revision `0020_directory_models` requires local sources for TTS, vision, image_embedding and ASR. It deletes obsolete TTS/WD14 profiles, local GGUF file-reference profiles and newly invalid unbound profiles without converting configuration. Affected default/auxiliary/session selections and unfinished model runs are cleared; completed histories, other profiles/settings, runtime installations/jobs and every filesystem directory survive. Repeated upgrades preserve new profiles. Local references now select directories; detected architecture and GGUF main/projector paths are held in active adapters rather than persisted as editable settings.

Kokoro ONNX files reside under data/models/tts; presets use voices/<id>.bin.
The manually unpacked en_core_web_sm 3.7.1 pipeline resides directly under
data/models/_auxiliary/en_core_web_sm and is excluded from inventory. Kokoro
reads it at model load; installation and uninstall never copy or alter it.

Migration tests use temporary stub files to cover repeat upgrades and file preservation.
The global test fixture compares repository model file presence sets only, without reading contents,
sizes or hashes. Runtime artifact and locked-dependency verification follows the Models contract.
`uv run python scripts/audit_workspace.py --check` verifies current schema,
integrity, foreign keys and absence of the retired root snapshot/test model stubs.

## Runtime files

Installation directories and process ownership are defined in
[models](contracts/models.md#managed-catalog-and-installation). Explicit runtime
uninstall removes the recorded data/runtimes/local/<version>, containing the shared
env/ and separate native/cpu and native/cuda programs. Workers ship in ai_workbench/workers;
the installed interpreter executes those application sources. Pinned Python
archives under python/archives and dependency/native caches under .cache remain.
Task/process logs are bounded and retained under data/logs/runtimes.
Native artifact reuse uses .cache/cogita-artifacts; other cache files remain until explicit maintenance.
installation.json contains only dependency identity and executable paths; the database's
manifest_sha256 binds this small metadata file. It contains no environment file inventory.
Old release/file-inventory metadata is rejected and retained until explicit repair
rebuilds the current release. No metadata conversion, database reset or model-profile reset occurs.
Release labels do not relocate installed files; successful repair replaces the recorded installation.
Installation-job state is durable; file/dependency inspection only updates cached availability.
Runtime storage accounting covers ordinary files across runtimes, deduplicates
hard links and reports exclusive logical size rather than physical disk recovery.
Manual uv prune/clean acts only on .cache, through the shared runtime task lock.
It does not uninstall the local release or remove Python archives. Retained hard links keep
installed files alive; a later installation may need to download cache entries again.

## Temporary voice references

The model service creates one random session directory under data/tmp/voice-references.
It removes abandoned owned session directories when reference storage initializes
after restart. Key/profile changes invalidate published references; expired and
one-request files are removed on reference access or final lease release. Active
requests keep files until inference/cancellation finishes. Reference limits and TTL
are owned by [Models](contracts/models.md#audio-tts-and-temporary-references).
Optional Qwen transcripts exist only in reference memory and are discarded with it.
These files are separate from attachments and manually supplied model resources;
no schema revision, model uninstall or runtime cache job deletes them.

## Temporary ASR inputs

ASR input storage creates one random session under data/tmp/asr-inputs. Startup removes abandoned owned sessions; generated filenames and worker references must remain within their owned roots.
Each transcription stores a file only after admission and removes it after completion, failure or cancellation. Cancellation stops the worker before file deletion; interrupted staging waits for the file write before cleanup. Normal shutdown removes the empty session. Unowned files are preserved.
These inputs have no TTL, voice IDs or persistent transcript records and do not use voice-reference or attachment storage. Schema revisions, cache maintenance and model/runtime uninstall do not own their cleanup.

## Environment and maintenance

- COGITA_DATABASE_URL overrides the SQLite path.
- COGITA_ATTACHMENTS_DIR overrides attachment storage.
- COGITA_FRONTEND_DIST selects frontend assets for direct ASGI startup;
  the launcher sets it from --frontend-dist.
- Only current environment names are read; earlier prefixes have no fallback.
- Model/provider configuration is stored in the database, not environment fallback.

`scripts/reset_data.py` is an explicit SQLite-file reset command; its default is
a dry run and `--yes` deletes only the selected database file.
`scripts/cleanup_attachments.py` performs separate explicit orphan cleanup.
No schema revision invokes either file-maintenance workflow.
