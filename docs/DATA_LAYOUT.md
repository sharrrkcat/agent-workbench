# Local data layout

SQLite records are disposable test state. Files have separate ownership and
are never removed by schema revisions.

| Path | Contents and owner |
| --- | --- |
| data/agent_workbench.db | Application test state: Personas, sessions/messages/runs, settings, models/providers, Knowledge/Worldbook, runtime jobs |
| data/attachments/ | Uploaded files and Persona avatars; explicit orphan cleanup |
| data/knowledge/ | Knowledge service source/index working files |
| data/models/ | Manually managed model weights; no application downloader |
| data/runtimes/ | Supervisor-owned pinned binaries, Python interpreters/venvs, caches/staging |
| data/logs/ | Operational diagnostics and inference/runtime logs |
| data/assets/ | Existing local files, including retired font assets; untouched by cleanup |
| data/backups/ | Optional operator backups; ignored by Git |
| frontend/dist/ | Generated frontend production build |
| build/ | Generated portable package and optional ZIP; ignored by Git |

Root dist/ is the removed application snapshot and remains unsupported.
The portable builder uses build/ and excludes local data and secrets. It copies
the maintained README, run guide and docs rather than embedding another guide.

## Database revisions

Alembic head is `0007_phase5_cleanup`; there are 24 current business tables.
Empty databases upgrade to head. Nonempty unversioned databases are rejected
instead of auto-stamped. Health reports schema_revision; there is no separate
schema_version authority. Destructive test revisions do not support downgrade.

Earlier phases recorded the baseline, extension pruning, unified model schema,
managed runtimes, Persona/session members and private harness continuations.
Phase 5 changes no tables: it deletes only appmetadatarecord's app_settings row.
This resets General, Core Memory and Pet settings to current defaults.
Models, harness settings, sessions, messages, pending approvals, Knowledge,
Worldbook and other records are preserved. No old settings JSON is copied or
converted. Repeating upgrade at head leaves newly saved settings intact.

The implementation validates protected file paths, sizes and modification times
around the actual database upgrade. Automated tests use temporary roots;
the suite additionally checks hashes of repository model files.
`uv run python scripts/audit_workspace.py --check` verifies current schema,
integrity, foreign keys and absence of the retired root snapshot/test model stubs.

## Runtime files

Installation directories and process ownership are defined in
[models](contracts/models.md#managed-catalog-and-installation). Explicit runtime
uninstall removes only its catalog entry's directory. Shared Python
distributions and download cache remain available for other variants.
Task/process logs are bounded and retained under data/logs/runtimes.

## Environment and maintenance

- AGENT_WORKBENCH_DATABASE_URL overrides the SQLite path.
- AGENT_WORKBENCH_ATTACHMENTS_DIR overrides attachment storage.
- AGENT_WORKBENCH_FILE_ALLOWED_DIRS controls permitted attachment file access;
  harness read_file has its own narrower allowlist.
- Model/provider configuration is stored in the database, not environment fallback.

`scripts/reset_data.py` is an explicit SQLite-file reset command; its default is
a dry run and `--yes` deletes only the selected database file.
`scripts/cleanup_attachments.py` performs separate explicit orphan cleanup.
No schema revision invokes either file-maintenance workflow.
