# Task: Knowledge

## Read first

Read only the entries needed for the specific change; this list is an on-demand
map, not a requirement to read every file in full.

- `../contracts/knowledge.md`
- `../contracts/intent-routing.md` when KB aliases or temporary
  `knowledge_query` overrides are involved.
- `README.md#settings`
- `README.md#sqlite-data`
- `docs/RUNTIME_PROTOCOLS.md#knowledge-context`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution`
- `docs/EXTENSION_API.md#capability-config`
- `docs/EXTENSION_API.md#config-schema-fields`
- `docs/EXTENSION_ARCHITECTURE.md#knowledge-bridge`
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`
- `docs/generated/REGISTRY.md` only when Capability/command registry details matter.

## Likely source

- `ai_workbench/core/knowledge_store.py`
- `ai_workbench/core/knowledge_settings.py`
- `ai_workbench/core/knowledge_indexing.py`
- `ai_workbench/core/knowledge_context.py`
- `ai_workbench/core/retrieval.py`
- `ai_workbench/core/vector_store.py`
- `ai_workbench/core/keyword_search.py`
- `ai_workbench/core/embedding.py`
- `ai_workbench/core/rerank.py`
- `ai_workbench/core/knowledge_models.py`
- `ai_workbench/api/routes/knowledge.py`
- `capabilities/knowledge`
- `frontend/src/components/settings/KnowledgeSettingsPanel.tsx`
- `frontend/src/components/ChatHeader.tsx`
- `frontend/src/i18n/resources/*/knowledge.json`

## Tests

- `uv run pytest tests/test_knowledge_settings.py tests/test_knowledge_models.py`
- `uv run pytest tests/test_knowledge_indexing.py`
- `uv run pytest tests/test_knowledge_retrieval.py`
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
- `uv run pytest tests/test_agent_settings.py`
- `uv run pytest tests/test_frontend_chat_contracts.py`
- `cd frontend && npm run build` when frontend changes.

## Avoid

- Do not copy the full Knowledge contract into this task card; update
  `../contracts/knowledge.md` instead.
- Do not add automatic model download, automatic dependency install, file watching,
  scheduled scan, background reindex, or chat-time reindex unless explicitly requested.
- Do not change retrieval ranking, indexing, embedding, reranking, or model backend
  behavior for thin Capability or UI-only work.
- Do not store full Knowledge snippets, source originals, vectors, or rendered
  context blocks in run, step, or message metadata.
- Do not use Knowledge indexes, vector storage, RAG retrieval, or FTS for Worldbook matching.

## Docs and i18n

- Knowledge API, settings, indexing, retrieval, injection, metadata, or model
  changes update `../contracts/knowledge.md` and relevant summary/index docs.
- Capability wrapper changes update the Knowledge contract and, when the public
  ctx/output/config API changes, `docs/EXTENSION_API.md`.
- User-visible Knowledge UI text changes require every supported locale.
