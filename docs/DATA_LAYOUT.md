# Local data layout

The project is in testing with no users or user data. SQLite records are
disposable. File directories have separate ownership and are not removed by
schema revisions.

| Path | Contents | Ownership |
| --- | --- | --- |
| data/agent_workbench.db | Personas, session members, sessions, messages, runs, settings, Knowledge, Worldbook, provider_profiles and model_profiles | Application test state; ignored by Git |
| data/attachments/ | Uploaded files referenced by message parts | Explicit orphan cleanup only |
| data/knowledge/ | Source/index working data | Knowledge service |
| data/models/ | Manually placed model files | No model download or schema-driven deletion |
| data/runtimes/ | Pinned binaries, Python interpreters/venvs, cache and staging | Runtime supervisor |
| data/logs/ | Diagnostic and inference access logs | Operational state |
| data/backups/ | Optional operator backups | Ignored by Git |

The supported model inventory roots are defined in core/models/inventory.py;
only relative paths are returned. Inventory does not import/load runtimes.
The frontend build lives at frontend/dist/. Root dist/ was an obsolete
application snapshot and is not a supported runtime.

Alembic head is 0006_phase4_tools. Phase 2a recreated every SQLite business
table and Knowledge FTS index; Phase 2b added managed profile fields,
runtime_installations and runtime_jobs; Round 3 added Persona/session tables
and recreated disposable chat rows without touching file directories.
Phase 4 recreates the run kind constraint, adds private harness state, clears
disposable messages/run events/steps and waiting references. Model, attachment,
Knowledge and runtime files remain outside the migration's ownership.
Revisions copy no rows and downgrade is unsupported. Empty databases
upgrade to head. Nonempty unversioned databases are rejected instead of
auto-stamped. Health reports schema_revision; there is no schema_version
metadata authority.

Tests use temporary database/attachment/Knowledge/model roots. Audit the
current checkout and schema with scripts/audit_workspace.py --check.

Runtime binaries and venvs use the directories in
[managed-runtime](contracts/managed-runtime.md). Explicit uninstall removes
only that catalog entry's directory. Shared Python distributions and download
cache remain available for other variants. Task/process logs are capped at
10 MiB and retained under data/logs/runtimes. Database revisions own no files.
