# Task: Settings and models

Read first: `../contracts/settings-general.md`, `../contracts/pet.md`,
`../contracts/runtime-llm-resolution.md`, and `../contracts/knowledge.md`.

Likely sources: `core/settings.py`, `core/knowledge_settings.py`, model profile
schemas/stores, `api/routes/settings.py`, `api/routes/pets.py`, and
`frontend/src/components/SettingsPage.tsx`.

Use strict Pydantic schemas and nested `AppSettings.pet`. The settings
navigation is General, Models, Knowledge, Worldbook, and Pet. Main model
resolution is session override then global default; Utility LLM has one
profile selector. Removed fields must produce 422, not be ignored.

Run `uv run pytest tests/test_phase1_contracts.py tests/test_phase1_migrations.py -q`
and the frontend contract/build/i18n scripts.
