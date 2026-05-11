# AI Context

## Rule

Before searching the repository, identify the task type below and read the listed docs/source files first. Do not scan the whole repository unless these docs are insufficient.

- Start here, then read the linked contract docs and generated registry for the task.
- Prefer `docs/EXTENSION_API.md`, `docs/RUNTIME_PROTOCOLS.md`, and `docs/generated/REGISTRY.md` before broad source search.
- Search source only when the listed docs and source pointers do not answer the question.
- If an interface or protocol changes, update the relevant contract doc in the same change.
- If an Agent or Capability manifest changes, run `uv run python scripts/generate_registry_docs.py`.

## Task Map

### Create or modify a Script Agent

Read:
- `docs/EXTENSION_API.md#script-agents`
- `docs/generated/REGISTRY.md#agents`

Likely source:
- `agents/<agent_id>/agent.yaml`
- `agents/<agent_id>/agent.py`
- `ai_workbench/core/script.py` only if SDK behavior changes

Tests:
- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_script_agent.py`

Avoid unless needed:
- Do not inspect unrelated agents unless using them as examples.

### Create or modify a Prompt Agent

Read:
- `docs/EXTENSION_API.md#agent-manifest`
- `docs/EXTENSION_API.md#prompt-agents`
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution`
- `docs/generated/REGISTRY.md#agents`

Likely source:
- `agents/<agent_id>/agent.yaml`
- `ai_workbench/core/runner.py` only if runtime behavior changes

Tests:
- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_prompt_agent_execution.py`

Avoid unless needed:
- Do not change Script Agent runtime for prompt-only manifest edits.

### Create or modify a Capability / slash command

Read:
- `docs/EXTENSION_API.md#capabilities`
- `docs/EXTENSION_API.md#output-payloads`
- `docs/generated/REGISTRY.md#capabilities`

Likely source:
- `capabilities/<capability_id>/capability.yaml`
- `capabilities/<capability_id>/__init__.py`
- `ai_workbench/core/capabilities.py` only if runtime behavior changes

Tests:
- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_capabilities.py` if present

Avoid unless needed:
- Do not add slash command aliases to Agents.

For the built-in Knowledge Capability, also read `docs/EXTENSION_ARCHITECTURE.md#knowledge-bridge` and `docs/RUNTIME_PROTOCOLS.md#knowledge-context`. Keep `capabilities/knowledge` as a thin wrapper around `ai_workbench/core/retrieval.py` and the Knowledge store; do not change automatic context injection or retrieval/indexing/model algorithms for `/kb-search`.

### Create or modify an external integration / workflow agent

Read:
- `docs/EXTENSION_ARCHITECTURE.md`
- `docs/EXTENSION_API.md#script-agents`
- `docs/EXTENSION_API.md#capabilities`
- `docs/EXTENSION_API.md#output-payloads`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#message-streaming`
- `docs/RUNTIME_PROTOCOLS.md#attachments-and-vision`
- `docs/generated/REGISTRY.md`

Likely source:
- `agents/<integration_agent>/agent.yaml`
- `agents/<integration_agent>/agent.py`
- `capabilities/<integration_name>/capability.yaml`
- `capabilities/<integration_name>/__init__.py`
- `tests/test_<integration_name>*.py`
- `ai_workbench/core/capability_runtime.py` only if capability runtime behavior changes
- `ai_workbench/core/script.py` only if ctx API behavior changes
- frontend message rendering files only if output renderer changes

Tests:
- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_script_agent.py`
- `uv run pytest tests/test_<integration_name>*.py`
- `cd frontend && npm run build` if renderer changes

Avoid unless needed:
- Do not change Script ctx API for one integration.
- Do not change message streaming protocol for one integration.
- Do not rely on real external services in tests.
- Do not store durable outputs only as remote temporary URLs.
- Do not add product-specific blueprint docs unless the integration has special operator setup that cannot fit this general architecture.

### Change Script Agent ctx API

Read:
- `docs/EXTENSION_API.md#script-context-api`
- `docs/RUNTIME_PROTOCOLS.md#message-streaming`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`

Likely source:
- `ai_workbench/core/script.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/run_lifecycle.py`

Tests:
- `uv run pytest tests/test_script_agent.py`
- `uv run pytest tests/test_prompt_agent_execution.py`

Avoid unless needed:
- Do not change manifest schemas unless the API change requires new fields.

### Change output rendering / output types

Read:
- `docs/EXTENSION_API.md#output-payloads`
- `docs/RUNTIME_PROTOCOLS.md#message-streaming`

Likely source:
- `ai_workbench/core/script.py`
- `ai_workbench/core/capabilities.py`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/store/useWorkbenchStore.ts`

Tests:
- `uv run pytest`
- `cd frontend && npm run build`

Avoid unless needed:
- Do not alter LLM resolution for pure rendering changes.

### Change message streaming

Read:
- `docs/RUNTIME_PROTOCOLS.md#message-streaming`

Likely source:
- `ai_workbench/core/script.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/events.py`
- `frontend/src/store/useWorkbenchStore.ts`
- `frontend/src/components/MessageBubble.tsx`

Tests:
- `uv run pytest tests/test_script_agent.py tests/test_prompt_agent_execution.py`
- `cd frontend && npm run build`

Avoid unless needed:
- Do not make internal LLM streams visible unless routed through public output APIs.

### Change run steps / long task lifecycle

Read:
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`

Likely source:
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/script.py`
- `ai_workbench/db/models.py`
- `frontend/src/components/MessageBubble.tsx`

Tests:
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
- `cd frontend && npm run build`

Avoid unless needed:
- Do not change routing or command registry for run-step display work.

### Change LLM provider/model profile behavior

Read:
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution`
- `docs/RUNTIME_PROTOCOLS.md#provider-and-model-status`

Likely source:
- `ai_workbench/core/llm*.py` or existing LLM/provider files
- `ai_workbench/api/routes/llm*.py`
- frontend Settings LLM files

Tests:
- `uv run pytest tests/test_provider_status.py`
- `uv run pytest tests/test_prompt_agent_execution.py`

Avoid unless needed:
- Do not update Agent manifest docs for provider-only behavior.

### Change attachments / vision / file input

Read:
- `docs/EXTENSION_API.md#attachments-in-script-agents`
- `docs/RUNTIME_PROTOCOLS.md#attachments-and-vision`

Likely source:
- attachment route/store files
- `ai_workbench/core/runner.py`
- frontend composer/message components

Tests:
- `uv run pytest tests/test_file_http_attachments.py`
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`

Avoid unless needed:
- Do not make file attachments part of Prompt Agent context without checking General settings.

### Change Settings schema / overrides

Read:
- `docs/EXTENSION_API.md#agent-overrides`
- `docs/EXTENSION_API.md#capability-config`
- `docs/RUNTIME_PROTOCOLS.md#session-title-generation` if changing automatic title settings or title behavior

Likely source:
- agent/capability config routes/stores
- frontend settings components
- `ai_workbench/core/settings.py` for General settings
- `ai_workbench/core/session_titles.py` for automatic title generation

Tests:
- `uv run pytest tests/test_agent_settings.py tests/test_config_schema.py tests/test_settings_data.py`
- `uv run pytest tests/test_session_titles.py` if automatic title settings or behavior changes
- `cd frontend && npm run build` if frontend changed

Avoid unless needed:
- Do not rewrite tutorial docs for Settings-only changes.

### Change Knowledge / RAG settings, injection, or local model APIs

Read:
- `README.md#settings`
- `README.md#sqlite-data`
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#session-title-generation`
- `docs/EXTENSION_API.md#config-schema-fields`
- `docs/EXTENSION_API.md#capability-config`
- `docs/EXTENSION_ARCHITECTURE.md#knowledge-bridge`
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`
- `docs/generated/REGISTRY.md`

Likely source:
- `ai_workbench/core/vector_store.py`
- `ai_workbench/core/keyword_search.py`
- `ai_workbench/core/retrieval.py`
- `ai_workbench/core/knowledge_context.py`
- `ai_workbench/core/runner.py` if Prompt Agent injection changes
- `ai_workbench/core/script.py` if Script Agent `ctx.llm` injection changes
- `ai_workbench/core/agent_settings.py` if Agent Knowledge overrides change
- `ai_workbench/core/knowledge_models.py`
- `ai_workbench/core/knowledge_settings.py`
- `ai_workbench/core/embedding.py`
- `ai_workbench/core/rerank.py`
- `ai_workbench/core/knowledge_indexing.py`
- `ai_workbench/core/knowledge_store.py`
- `ai_workbench/api/routes/knowledge.py`
- `frontend/src/components/settings/KnowledgeSettingsPanel.tsx`
- `frontend/src/components/ChatHeader.tsx` if the Session KB picker changes
- `frontend/src/components/settings/AgentDetail.tsx` if Agent Knowledge overrides change
- `frontend/src/components/settings/SettingsConsole.tsx`
- `frontend/src/components/settings/SettingsObjectList.tsx`
- `frontend/src/components/settings/SettingsDetailPanel.tsx`
- `frontend/src/i18n/resources/*/knowledge.json` when changing user-visible Knowledge UI text

Tests:
- `uv run pytest tests/test_knowledge_settings.py tests/test_knowledge_models.py`
- `uv run pytest tests/test_knowledge_indexing.py`
- `uv run pytest tests/test_knowledge_retrieval.py`
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py tests/test_agent_settings.py`
- `uv run pytest tests/test_frontend_chat_contracts.py`
- `cd frontend && npm run build`

Avoid unless explicitly in scope:
- Do not add Knowledge Capability, `/kb-search`, automatic model download, local-file sources, or retrieval/indexing/backend changes for Knowledge injection work unless explicitly requested.
- Knowledge environment/download-command UI work should route through Settings -> Knowledge docs and `frontend/src/components/settings/KnowledgeSettingsPanel.tsx`. The project may provide local helper scripts that print user-run commands, but do not add a backend download API, background download task, automatic dependency install, automatic model download, or frontend shell execution unless a task explicitly asks for that behavior.
- The Knowledge Defaults Download tab generates copyable `uv run python scripts/download_knowledge_model.py --type ... --model-id ... --target ...` commands only. Presets should stay grouped as recommended/advanced embeddings and recommended/advanced rerankers, with the same model IDs and target folder names documented in `README.md`.

UI/i18n rule:
- Any new or changed user-visible frontend text must update every supported locale file in `frontend/src/i18n/resources`. Do not leave new Knowledge Defaults, Download, or Install text hardcoded in JSX.

## Documentation Update Rules

- If `agent.yaml` or `capability.yaml` fields change, update `EXTENSION_API` and regenerate `REGISTRY`.
- If `ctx` API changes, update `EXTENSION_API`.
- If WebSocket event protocol changes, update `RUNTIME_PROTOCOLS`.
- If run or run_step fields change, update `RUNTIME_PROTOCOLS`.
- If LLM resolution changes, update `RUNTIME_PROTOCOLS`.
- If adding a new complex integration pattern, update `EXTENSION_ARCHITECTURE.md` rather than creating a product-specific recipe first.
- If an integration requires a new output shape or streaming behavior, update `EXTENSION_API.md` or `RUNTIME_PROTOCOLS.md`.
- If only UI style changes, docs usually do not need updating.
