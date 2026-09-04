# Local data layout

The application is local-first. Model files remain user-managed; the Phase 1
database revision is destructive because this is a disposable test stage.

| Path | Contents | Ownership |
| --- | --- | --- |
| `data/agent_workbench.db` | SQLite sessions, messages, runs, settings, Knowledge, Worldbook, and model profiles. | Application state; not committed. |
| `data/attachments/` | Uploaded files referenced by message parts. | User assets; cleanup only removes unreferenced files. |
| `data/knowledge/` | Source/index working data. | Knowledge service. |
| `data/models/` | Models manually placed by the user (`llms`, `embeddings`, `rerankers`, `vision`, and image embeddings). | Never downloaded or removed by the app. |
| `data/runtimes/` | Future worker/runtime installations. | Rebuildable Phase 2 area. |
| `data/logs/` | Diagnostic and access logs. | Operational data, not business state. |
| `data/backups/` | Optional local operator backups. | Sensitive and ignored by Git. |

`dist/` is a generated frontend build, not user data. Tests pass a temporary
`root` so databases, attachments, Knowledge files, and model fixtures stay out
of the repository. The Alembic head is `0002_phase1_prune`; it does not copy or
convert rows and its downgrade is unsupported.
