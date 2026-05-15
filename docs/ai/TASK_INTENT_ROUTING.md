# Task: Intent Routing

## Read first

Read only the entries needed for the specific change; this list is an on-demand
map, not a requirement to read every file in full.

- `../contracts/intent-routing.md`
- `../contracts/utility-llm.md` when Utility extraction, status, or model
  backend behavior is involved.
- `../contracts/knowledge.md` when `knowledge_query`, KB aliases, or temporary
  Knowledge overrides are involved.
- `docs/RUNTIME_PROTOCOLS.md#intent-routing`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#conversation-context-modes`
- `docs/EXTENSION_API.md#agent-overrides`
- `docs/EXTENSION_API.md#prompt-agents`
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`
- `README.md#intent-routing-alpha`

## Likely source

- `ai_workbench/core/settings.py`
- `ai_workbench/core/agent_settings.py`
- `ai_workbench/core/intent_router.py`
- `ai_workbench/core/intent_semantic_router.py`
- `ai_workbench/core/utility_llm.py`
- `ai_workbench/core/runtime.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/knowledge_context.py` for temporary Knowledge overrides.
- `ai_workbench/api/routes/intent.py`
- `ai_workbench/api/routes/settings.py`
- `frontend/src/components/settings/SettingsDetailPanel.tsx`
- `frontend/src/components/settings/AgentDetail.tsx`
- `frontend/src/types.ts`
- `frontend/src/i18n/resources`

## Tests

- `uv run pytest tests/test_settings_data.py`
- `uv run pytest tests/test_agent_settings.py`
- `uv run pytest tests/test_intent_routing.py`
- `uv run pytest tests/test_intent_auto_routing.py`
- `uv run pytest tests/test_intent_semantic_router.py` when semantic thresholds or candidates change.
- `uv run pytest tests/test_utility_llm.py`
- `uv run pytest tests/test_utility_llm_gguf.py` for GGUF behavior.
- `uv run pytest tests/test_session_titles.py` when title behavior is affected.
- `uv run pytest tests/test_frontend_chat_contracts.py` for metadata/frontend contracts.
- `cd frontend && npm run build`
- `cd frontend && node scripts/check-i18n.mjs` for user-visible text changes.

## Avoid

- Do not copy the full Intent Routing contract into this task card; update
  `../contracts/intent-routing.md` instead.
- Do not let explicit `/command`, `@agent`, `@agent:action`, or `:action` enter
  Intent Routing.
- Do not make shadow mode alter selected Agent/action, title generation, provider
  context, Knowledge, Core Memory, or Worldbook behavior.
- Do not expand safe auto-route execution beyond the documented `chat`,
  `knowledge_query`, and narrow `/pet` allowlist without a contract update.
- Do not use broad regex or keyword parsers as the primary natural-language router.
- Do not modify Agent or Capability manifests for route candidate work.
- Do not store raw Utility LLM output, prompts, embeddings, full examples,
  Knowledge/Worldbook/Core Memory content, or full chat history in metadata.

## Docs and i18n

- Routing settings, safe auto-route behavior, Utility LLM behavior, Route Test,
  metadata shape, or user workflow changes update
  `../contracts/intent-routing.md` and any affected summary/index docs.
- User-visible frontend text changes require every supported locale.
