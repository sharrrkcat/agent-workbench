# Task: Settings and models

Read first: `../contracts/settings-general.md`, `../contracts/pet.md`,
`../contracts/runtime-llm-resolution.md`, `../contracts/knowledge.md` and
`../contracts/managed-runtime.md` and `../contracts/harness-tools.md`.

Likely sources: `core/settings.py`, `core/knowledge_settings.py`, model profile
schemas/stores in `core/models/`, `api/routes/models.py`, settings/pet routes,
`frontend/src/components/SettingsPage.tsx`, `settings/ModelsPanel.tsx`, and
`store/useModelsStore.ts`.

Managed runtime ownership is in `core/models/runtimes/`,
`api/routes/runtimes.py` and `settings/RuntimesPanel.tsx`. Read
`../contracts/managed-runtime.md` for catalog, tasks, download settings and
profile binding. Global model events must work without a chat session.

Use strict Pydantic schemas and nested `AppSettings.pet`. The settings
navigation is General, Models, Personas, Knowledge, Worldbook, Tools, and Pet. Main
model resolution is session override, Persona model, then global default; Utility LLM has one
profile selector in /api/models/settings. Models owns five kinds, connection
CRUD, per-kind parameters, lifecycle and external-service settings. Preserve
key omission/clearing semantics and reference guards. Removed fields must
produce 422, not be ignored.
HarnessSettings owns the SearXNG URL; ToolsPanel also exposes catalog/direct
calls and the shared approval workflow. Persona/session allowlists use only
registered built-in tool names.

Run `uv run pytest tests/test_phase2a_persistence.py tests/test_phase2a_manager.py -q`
and the frontend contract/build/i18n scripts.
