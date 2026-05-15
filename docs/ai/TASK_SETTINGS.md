# Task: Settings

## Read first

Read only the entries needed for the specific change; this list is an on-demand
map, not a requirement to read every file in full.

- `../contracts/settings-general.md` for General settings fields and ownership.
- `../contracts/utility-llm.md` for Utility LLM or session title settings.
- `../contracts/intent-routing.md` for Intent Routing settings.
- `../contracts/knowledge.md` for Knowledge settings.
- `../contracts/memory-worldbook.md` for Core Memory or Worldbook settings.
- `../contracts/runtime-llm-resolution.md` for Model Profile runtime behavior.
- `../contracts/provider-status.md` for Provider/Profile status behavior.
- `../EXTENSION_API.md#agent-overrides`
- `../EXTENSION_API.md#capability-config`
- `../EXTENSION_API.md#config-schema-fields`
- `../EXTENSION_ARCHITECTURE.md#configuration-ownership`

## Likely source

- `ai_workbench/core/settings.py`
- `ai_workbench/core/agent_settings.py`
- `ai_workbench/core/llm_config.py`
- `ai_workbench/core/session_titles.py`
- `ai_workbench/api/routes/settings.py`
- `ai_workbench/api/routes/configs.py`
- `frontend/src/components/settings/SettingsDetailPanel.tsx`
- `frontend/src/components/settings/SettingsConsole.tsx`
- `frontend/src/components/settings/SettingsObjectList.tsx`
- `frontend/src/types.ts`
- `frontend/src/api/client.ts`
- `frontend/src/i18n/resources`

## Tests

- `uv run pytest tests/test_settings_data.py`
- `uv run pytest tests/test_agent_settings.py tests/test_config_schema.py`
- `uv run pytest tests/test_session_titles.py` when title settings change.
- `uv run pytest tests/test_session_title_backends.py` when title backend selection changes.
- `uv run pytest tests/test_frontend_chat_contracts.py` for frontend/runtime metadata contracts.
- `cd frontend && npm run build` when frontend changes.
- `cd frontend && node scripts/check-i18n.mjs` for user-visible text changes.

## Avoid

- Do not copy full topic contracts into this task card; update the relevant
  `../contracts/*.md` file instead.
- Do not move ownership between AgentConfig, CapabilityConfig, General settings,
  Provider Profiles, or Model Profiles without updating docs.
- Do not rewrite tutorial docs for Settings-only changes.
- Do not change Utility LLM or title fallback behavior incidentally while moving
  settings UI.
- Do not store secrets in Agent manifests.

## Docs and i18n

- Settings schema, ownership, metadata, or workflow changes update the owning
  contract under `../contracts/` and the compact API/architecture summary only
  when that summary changes.
- README should keep user-facing Settings overview current but should not become
  the long contract source.
- User-visible frontend text changes require every supported locale.
