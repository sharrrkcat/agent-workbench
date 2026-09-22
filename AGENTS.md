# Repository Instructions

Read `docs/AI_CONTEXT.md`, then the owning contract and relevant source/tests
before changing code. Contracts describe the current implementation. The removed
Agent/Action/Capability/Command and YAML architecture must not return.

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
  OpenAI-compatible protocol. Managed llama-server and Python workers run
  outside the API process.
- Model release defaults to manual. Titles use only the selected auxiliary
  model; absence or failure leaves the title unchanged.
- Reranker remains a model kind and a RAG operation. Keeping RRF order when
  reranking is unavailable is intentional retrieval behavior.
- No model downloads, image generation, or restored extension registries.

## Engineering

Keep services explicit, use strict Pydantic schemas and existing local APIs,
and cover meaningful behavior with tests. Frontend text changes update both
locales. Interface and workflow changes update the owning contract.

All repository documentation, including active plans, must be written in English.
Plans may remain while work is in progress. Update contracts as behavior is
implemented; completion requires deleting the plan and its references in the same
change. Preserve current limitations in their owning documents and historical
reports in Git or task results. See `docs/ai/DOCS_MAINTENANCE.md` for ownership
and the plan lifecycle.

Each implementation round reports changed files, commands and results,
API/settings/workflow changes, and remaining limitations. Run frontend tests/build,
relevant checks, and `scripts/check_docs_size.py`. Run backend tests only when
backend code changes; skip them for frontend-only or documentation-only work.

## Runtime verification and acceptance

- Keep installation checks at artifact and installation boundaries: downloaded
  archives and locked dependencies, dependency consistency, offline engine imports,
  native programs, release identity, entry points and path containment.
- Do not require full installed-environment per-file hash inventories or comparisons.
  Do not replace it with another whole-environment scanning subsystem.
- Routine Chatterbox, Qwen3-TTS and Whisper acceptance uses CUDA only. Add CPU
  checks only for affected CPU execution, device selection, dtype or inference
  dependency changes; CUDA results do not establish CPU compatibility. Kokoro
  retains its CPU checks.
- Reuse a verified installation for routine inference acceptance. Exercise
  installation/repair/uninstall when their behavior or artifacts change, or when
  explicitly required. The [README](README.md#verification) owns commands.
