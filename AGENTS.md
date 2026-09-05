# Repository Instructions

Read `docs/AI_CONTEXT.md`, then `docs/WORKBENCH_REFACTOR_ROADMAP.md` and the
owning contract before changing code. The roadmap supersedes the removed
Agent/Action/Capability/Command and YAML architecture.

## Permanent Refactor Constraints

- This project is in testing, with no users and no user data.
- Prolonged service downtime is acceptable. Do not add keepalive or availability
  scaffolding for intermediate refactor steps.
- Delete abandoned methods and structures directly. No backward compatibility,
  legacy implementations, forwarding layers, old configuration fallbacks,
  dual writes, data conversions, or accommodation of prior user habits.
- Alembic records schema changes. Disposable SQLite test data may be recreated;
  model files, attachments, runtimes, and other data directories are not deleted
  by schema revisions.
- All inference uses `core/models`. External connections speak only the
  OpenAI-compatible protocol. Managed runtimes belong to Phase 2b.
- Model release defaults to manual. Titles use only the selected auxiliary
  model; absence or failure leaves the title unchanged.
- Reranker remains a model kind and a RAG operation. Keeping RRF order when
  reranking is unavailable is intentional retrieval behavior.
- Persona belongs to Phase 3; harness and tool execution belong to Phase 4.
  No model downloads, image generation, or restored extension registries.

## Engineering

Keep services explicit, use strict Pydantic schemas and existing local APIs,
and cover meaningful behavior with tests. Frontend text changes update both
locales. Interface and workflow changes update the owning contract.

Each implementation round reports changed files, commands and results,
API/settings/workflow changes, and remaining limitations. Run backend tests,
frontend build and relevant checks, and `scripts/check_docs_size.py`.
