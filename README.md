# Agent Workbench

Agent Workbench is a small local-first chat workbench. Phase 1 uses one
predictable chat path backed by explicit core services for sessions, runs,
memory, Worldbook, Knowledge/RAG, models, and the optional Pet overlay.

## Quick start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js and npm.

```powershell
uv sync
uv run uvicorn ai_workbench.api.main:app --reload
```

In another shell:

```powershell
cd frontend
npm install
npm run dev
```

The default frontend URL is `http://localhost:5173`. Copy `.env.example` to
`.env` when custom database, model, attachment, or frontend paths are needed.

## Chat behavior

Every message is sent to the static `chat` prompt target. Prefixes are not
commands: `/base64 hello`, `@chat hi`, `@chat:formal hi`, and `:formal hi`
are ordinary message text and are preserved in history and model context.
If a session has `waiting_run_id`, its waiting run is resumed before a new chat
run starts. Session model selection overrides the global default model.

The ChatRunner builds generic session or group-transcript context and injects
Core Memory, Worldbook, Knowledge results, and permitted attachments. Runs
persist `context`, `model`, `save`, and (when needed) `approval` steps; `tool`
is reserved for a later harness phase. Titles are generated best-effort by the
optional Utility LLM and never block a reply.

## Settings and services

The frontend Settings page contains only General, Models, Knowledge,
Worldbook, and Pet. General settings include attachments, Core Memory, title
generation, inference service limits, and nested `pet` settings. Models owns
provider profiles, chat profiles, the global default, and the single
`utility_model_profile_id` selector.

Utility LLM is an internal service with `generate_text`, `generate_json`,
`generate_title`, and best-effort `unload`. It resolves one enabled LLM profile;
missing or unavailable profiles return `UTILITY_MODEL_UNAVAILABLE`, invalid
validated JSON returns `UTILITY_OUTPUT_INVALID`, and title failures are
non-blocking.

Knowledge keeps source/chunk/index lifecycles, hybrid vector + keyword search,
RRF merging, session bindings, automatic context injection, and optional
post-retrieval reranking. There is one chunk size/overlap configuration.
Reranking always fails open to RRF and records `rerank_fallback` metadata.
Sources are created directly from text, attachments, or workspace paths.

Pet settings are served by `/api/pets/settings`; updates deep-merge
`position` and `bubble_texts` into `AppSettings`. Pet rendering follows run
status and stable step kinds, with `WAITING_FOR_USER` shown as a confirmation
state. Pet lists and settings load initially and refresh after changes.

`NetworkPolicy` is a side-effect-free boundary for future tools. It accepts
only public HTTP/HTTPS URLs, rejects credentials and non-public DNS results,
allows at most three redirects, and caps responses at 1 MiB. Phase 1 performs
no network fetches.

## API surface

Retained routes cover `/api/sessions`, `/api/messages`, `/api/runs`, settings,
LLM/provider profiles, Knowledge, Worldbook, Pet, attachments, health,
diagnostics, and the existing localhost-guarded `/v1` inference skeleton.
Removed Agent, Command, Intent, form, Web Context, ComfyUI, and image-generation
routes are ordinary 404s. Removed request fields are rejected with 422 by
strict Pydantic schemas.

## Database

SQLite is managed with Alembic. Empty databases upgrade directly to head;
`0001_current_schema` is the baseline and `0002_phase1_prune` is a destructive
test-phase migration that drops obsolete tables/columns without data-copy or
compatibility paths. Downgrade is intentionally unsupported. The default path
is `data/agent_workbench.db`; override it with
`AGENT_WORKBENCH_DATABASE_URL`.

## Verification

```powershell
uv run pytest -q
uv run python -m compileall -q ai_workbench
Push-Location frontend
npm run build
npm run check:i18n
npm run test:phase1-contracts
npm run test:knowledge-citations
npm run test:url
Pop-Location
```

See [docs/WORKBENCH_REFACTOR_ROADMAP.md](docs/WORKBENCH_REFACTOR_ROADMAP.md)
for the frozen architecture and Phase 2 follow-up work. Current API and data
contracts live under [docs/contracts](docs/contracts).
