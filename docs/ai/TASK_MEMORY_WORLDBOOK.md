# Task: Memory and Worldbook

## Read first

- `../contracts/memory-worldbook.md`
- `../contracts/settings-general.md` for General Memory settings ownership.
- `../contracts/runtime-run-lifecycle.md` for runtime metadata and run steps.
- `../contracts/knowledge.md` for Knowledge boundary and injection order.
- `../FRONTEND_UI_COMPONENTS.md` for chat context modals, Settings headers, or
  Worldbook entry UI.
- `../EXTENSION_API.md#agent-overrides`
- `../EXTENSION_ARCHITECTURE.md#configuration-ownership`

## Likely source

- `ai_workbench/core/settings.py`
- `ai_workbench/core/memory_context.py`
- `ai_workbench/core/worldbook.py`
- `ai_workbench/core/worldbook_context.py`
- `ai_workbench/db/models.py`
- `ai_workbench/db/stores.py`
- `ai_workbench/api/routes/settings.py`
- `ai_workbench/api/routes/worldbook.py`
- `ai_workbench/api/routes/sessions.py`
- `ai_workbench/core/runner.py` for Prompt Agent injection changes.
- `ai_workbench/core/script.py` for Script Agent `ctx.llm` injection changes.
- `frontend/src/components/settings/WorldbookSettingsPanel.tsx`
- `frontend/src/components/ChatHeader.tsx`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/components/ui`
- `frontend/src/i18n/resources`

## Tests

- `uv run pytest tests/test_settings_data.py`
- `uv run pytest tests/test_worldbook.py`
- `uv run pytest tests/test_core_memory_context.py tests/test_worldbook_context.py`
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
  when runtime injection changes.
- `uv run pytest tests/test_frontend_chat_contracts.py` for frontend metadata or
  context-modal contracts.
- `cd frontend && npm run build`
- `cd frontend && node scripts/check-i18n.mjs` for user-visible text changes.

## Avoid

- Do not modify Agent or Capability manifests for Worldbook storage/API work.
- Keep Core Memory and Worldbook injection limited to Prompt Agent main LLM calls
  and opted-in Script Agent `ctx.llm.*` calls.
- Do not route Core Memory or Worldbook through title generation, query expansion,
  embeddings, reranking, commands, `/kb-search`, or non-LLM Capability calls.
- Do not store full Core Memory text, full Worldbook entry content, rendered
  context blocks, full Knowledge snippets, or vector blobs in run, step, or
  message metadata.
- Do not use Knowledge indexes, vector storage, RAG retrieval, or FTS for
  Worldbook matching.

## Docs and i18n

- Settings/API, matching defaults, injection, compact metadata, or UI workflow
  changes update `../contracts/memory-worldbook.md` and any directly affected
  compact index/summary docs.
- User-visible Core Memory or Worldbook frontend text requires every supported
  locale file.
