# Local data layout

The project is in testing with no users or user data. SQLite records are
disposable. File directories have separate ownership and are not removed by
schema revisions.

| Path | Contents | Ownership |
| --- | --- | --- |
| data/agent_workbench.db | Sessions, messages, runs, settings, Knowledge, Worldbook, provider_profiles and model_profiles | Application test state; ignored by Git |
| data/attachments/ | Uploaded files referenced by message parts | Explicit orphan cleanup only |
| data/knowledge/ | Source/index working data | Knowledge service |
| data/models/ | Manually placed model files | No model download or schema-driven deletion |
| data/runtimes/ | Future worker/runtime installations | Phase 2b |
| data/logs/ | Diagnostic and inference access logs | Operational state |
| data/backups/ | Optional operator backups | Ignored by Git |

The supported model inventory roots are defined in core/models/inventory.py;
only relative paths are returned. Inventory does not import/load runtimes.
The frontend build lives at frontend/dist/. Root dist/ was an obsolete
application snapshot and is not a supported runtime.

Alembic head is 0003_phase2a_models. Its static DDL recreates every SQLite
business table and Knowledge FTS index, including sessions/settings/Knowledge/
Worldbook. It copies no rows and its downgrade is unsupported. Empty databases
upgrade to head. Nonempty unversioned databases are rejected instead of
auto-stamped. Health reports schema_revision; there is no schema_version
metadata authority.

Tests use temporary database/attachment/Knowledge/model roots. Audit the
current checkout and schema with scripts/audit_workspace.py --check.
