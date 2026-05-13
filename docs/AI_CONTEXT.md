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

### Change runtime memory control

Read:
- `docs/RUNTIME_PROTOCOLS.md#provider-and-model-status`
- `docs/EXTENSION_API.md#capabilities`
- `docs/generated/REGISTRY.md#capabilities`

Likely source:
- `ai_workbench/core/runtime_memory.py`
- `ai_workbench/api/routes/runtime.py`
- `capabilities/runtime`
- `ai_workbench/core/knowledge_models.py` for local embedding/reranker cache release
- `capabilities/comfyui/__init__.py` for ComfyUI `/free`
- `frontend/src/components/ChatHeader.tsx`
- `frontend/src/i18n/resources/*/chat.json`

Tests:
- `uv run pytest tests/test_runtime_memory.py`
- `uv run python scripts/generate_registry_docs.py --check` when the runtime command manifest changes
- `cd frontend && npm run build`

Avoid unless needed:
- Do not delete model files, knowledge bases, indexes, sessions, or settings from memory release paths.
- Do not generalize LLM unload beyond LM Studio until the provider exposes a reliable unload API.

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
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution` if a setting references Model Profiles

Likely source:
- agent/capability config routes/stores
- frontend settings components
- `ai_workbench/core/settings.py` for General settings
- `ai_workbench/core/session_titles.py` for automatic title generation

Tests:
- `uv run pytest tests/test_agent_settings.py tests/test_config_schema.py tests/test_settings_data.py`
- `uv run pytest tests/test_session_titles.py` if automatic title settings or behavior changes
- `uv run pytest tests/test_session_title_backends.py` if title backend selection, fallback, profile resolution, or title unload behavior changes
- `cd frontend && npm run build` if frontend changed

Avoid unless needed:
- Do not rewrite tutorial docs for Settings-only changes.

### Change session title generation

Read:
- `docs/RUNTIME_PROTOCOLS.md#session-title-generation`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution`
- `docs/EXTENSION_API.md` General settings and metadata contracts
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`
- `README.md` title generation and Utility LLM notes

Likely source:
- `ai_workbench/core/session_titles.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/script.py`
- `ai_workbench/core/llm_config.py` and Model/Profile stores only when resolution behavior changes
- `ai_workbench/core/settings.py`
- `ai_workbench/api/routes/settings.py`
- `frontend/src/components/settings/SettingsDetailPanel.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types.ts`
- `frontend/src/i18n/resources`

Tests:
- `uv run pytest tests/test_session_titles.py`
- `uv run pytest tests/test_session_title_backends.py`
- `uv run pytest tests/test_utility_llm.py`
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
- `uv run pytest tests/test_intent_routing.py tests/test_intent_auto_routing.py`
- `uv run pytest tests/test_settings_data.py`
- `uv run pytest tests/test_frontend_chat_contracts.py` if frontend/runtime metadata contracts change
- `cd frontend && npm run build`
- `cd frontend && node scripts/check-i18n.mjs`

Rules:
- Title generation is triggered only by the first user message that resolves to an LLM-capable Agent/action while the session still has a default title.
- Do not use assistant output, Knowledge snippets, Worldbook content, Core Memory, command output, or route metadata as title input.
- Do not change Intent Routing safe auto-route behavior while changing title triggers; use the final resolved Agent/action to decide whether a title hook is eligible.
- Do not change Utility LLM backend loading, GGUF path handling, transformers loading, or Utility LLM test APIs unless the task is explicitly about those contracts.
- Title backend settings belong under General -> LLM & Prompts. Utility LLM backend/model/device settings stay under General -> Utility LLM.
- Model Profile title calls must not mutate the session selected Model Profile, AgentConfig, CapabilityConfig, or main response LLM resolution.
- Best-effort title model release must not unload a model currently generating the main response; defer release to run cleanup when targets match.
- User-visible frontend text must be added to every supported locale, and runtime/settings/metadata changes must update docs.

### Change Intent Routing settings / shadow mode / auto route behavior

Read:
- `docs/RUNTIME_PROTOCOLS.md#intent-routing`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#conversation-context-modes`
- `docs/EXTENSION_API.md#agent-overrides`
- `docs/EXTENSION_API.md#prompt-agents`
- `docs/EXTENSION_API.md#script-agents`
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`
- `README.md#intent-routing-alpha`

Likely source:
- `ai_workbench/core/settings.py`
- `ai_workbench/core/agent_settings.py`
- `ai_workbench/core/intent_router.py`
- `ai_workbench/core/intent_semantic_router.py` for semantic route candidates, lazy route index, embedding decisions, and Route Test semantic metadata
- `ai_workbench/core/utility_llm.py` when changing Utility LLM status, loading, backend selection, GGUF path validation, local model scan, title generation, or JSON extraction
- `ai_workbench/core/session_titles.py` when changing automatic title behavior
- `ai_workbench/core/runtime.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/knowledge_context.py` when adding or changing temporary Knowledge overrides
- `capabilities/pet/__init__.py` and `capabilities/pet/capability.yaml` when changing Pet command matching, available pet data, or `/pet` command behavior
- `ai_workbench/core/retrieval.py` only to confirm search inputs; do not change retrieval ranking for Intent Routing
- `ai_workbench/core/router.py` only if explicit syntax parsing changes
- `ai_workbench/api/routes/settings.py`
- `ai_workbench/api/routes/intent.py` when changing Utility LLM APIs, including status, scan, test, or unload contracts
- `ai_workbench/api/routes/configs.py`
- `ai_workbench/core/knowledge_store.py`, `ai_workbench/db/models.py`, and `ai_workbench/db/stores.py` when Intent Routing changes Knowledge Base aliases or matching fields
- `ai_workbench/api/routes/knowledge.py` when Knowledge Base alias request/response contracts change
- `frontend/src/components/settings/SettingsDetailPanel.tsx` for General -> Utility LLM status UI and General -> Intent Routing cards.
- `frontend/src/components/settings/SettingsObjectList.tsx`
- `frontend/src/components/settings/AgentDetail.tsx` for Agent detail -> Intent Routing. Per-Agent Intent Routing entry and target hints belong in this tab, not in Overrides.
- `frontend/src/components/settings/KnowledgeSettingsPanel.tsx` when KB aliases are user-visible
- `frontend/src/types.ts`
- `frontend/src/i18n/resources`

Tests:
- `uv run pytest tests/test_settings_data.py`
- `uv run pytest tests/test_agent_settings.py`
- `uv run pytest tests/test_knowledge_settings.py` when KB alias storage/API changes
- `uv run pytest tests/test_intent_routing.py`
- `uv run pytest tests/test_intent_auto_routing.py` when safe auto routing changes
- `uv run pytest tests/test_utility_llm.py`
- `uv run pytest tests/test_utility_llm_gguf.py` when GGUF-specific tests are split out
- `uv run pytest tests/test_session_titles.py` when Utility LLM title behavior changes
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
- `uv run pytest tests/test_frontend_chat_contracts.py` if metadata or frontend contracts change
- `cd frontend && npm run build`
- `cd frontend && node scripts/check-i18n.mjs`

Rules:
- Explicit `/command`, `@agent`, `@agent:action`, and `:action` routing must bypass Intent Routing.
- Shadow mode must not alter selected Agent/action, title generation, provider-bound context, Knowledge, Core Memory, or Worldbook behavior.
- Auto mode may route only allowlisted safe intents for the current message/run. It must not change the session default Agent, visible Agent selector, or persisted Context Sources Knowledge/Worldbook bindings.
- Semantic auto execution is limited to `chat`, high-confidence `knowledge_query`, and the narrow `pet_command` `/pet` allowlist. `chat` keeps the current Prompt Agent path and adds no temporary Knowledge override.
- `knowledge_query` auto routing may use only per-run temporary Knowledge KB/query overrides. It must not persist session KB bindings or change retrieval ranking/indexing.
- `pet_command` auto routing may execute only `/pet` status/wake/tuck/select/reload through the normal CommandRunner and Pet Capability runtime. It must not execute other slash commands, directly mutate Pet settings outside `/pet`, store Pet manifests or image data in metadata, or implement `/pet random`.
- `image_generation` is paused as diagnostic-only in semantic auto routing until action routing is designed. Do not route image-generation predictions to `comfyui_agent` from semantic decisions in this round, and do not restore any fallback route classifier.
- `command_like`, generic `agent_route`, `action_route`, and `compound` predictions remain diagnostic-only and must not execute commands, Agents, actions, or multiple tasks.
- General custom route examples, Agent target aliases/examples, and Knowledge Base aliases are classifier/extractor hints only. They must not expand the safe auto-route boundary.
- Per-Agent Intent Routing entry and target hints remain `AgentConfig.runtime` fields even though their UI location is Agent detail -> Intent Routing.
- Route test/debug APIs must not create messages or runs, execute ComfyUI, execute commands, run Knowledge retrieval, or mutate sessions.
- Utility LLM may support title generation and shadow JSON extraction, but it must not be a Model Profile, Provider Profile, Capability, Agent, or slash command.
- Utility LLM backend/model path/device/options belong to General settings and are displayed under General -> Utility LLM. Transformers paths use `utility_llms/<folder>`; GGUF llama.cpp paths use `utility_llms/<model-folder>/<file>.gguf`. Root-level GGUF files are invalid and should not be scanned.
- Do not lightly change title generation backend behavior when changing Utility LLM settings IA; moving settings categories must preserve current Utility LLM priority and fallback behavior.
- Intent Routing raw embedding model path is removed from the current UI/API contract. Ignore old persisted `intent_routing_embedding_model_path` values, do not restore a legacy path warning or display, and use only `intent_routing_embedding_model_profile_id` for the semantic router profile selector unless explicitly redesigning the contract.
- Semantic routing uses existing Knowledge Embedding Model Profiles only. Do not add a raw embedding path, auto-create profiles, auto-download models, or persist route-candidate embeddings to a DB/vector store.
- Semantic route candidates may include Agent action and Capability command metadata for diagnostics only. Do not execute slash commands other than the explicit narrow `pet_command` `/pet` allowlist, generic Agent routes, Agent actions, image generation, or compound sub-tasks from semantic predictions.
- Intent Routing QA work commonly touches semantic thresholds, grouped intent score/margin aggregation, Route Test summary/diagnostics, run-step diagnostics, and temporary `knowledge_query` Knowledge overrides. Likely files are `ai_workbench/core/intent_semantic_router.py`, `ai_workbench/core/intent_router.py`, `ai_workbench/core/runtime.py`, `ai_workbench/core/runner.py`, `ai_workbench/core/settings.py`, `ai_workbench/api/routes/intent.py`, frontend Settings/types/client/i18n files, and `tests/test_intent_semantic_router.py`, `tests/test_intent_auto_routing.py`, `tests/test_intent_routing.py`, `tests/test_settings_data.py`, plus frontend contract tests when UI contracts change.
- Route Test and real chat run gating logic must stay aligned. Do not let Route Test report execution for a semantic decision that the runtime auto gate would reject, do not restore legacy high/low confidence thresholds, and do not restore the legacy thresholds UI.
- Do not modify Agent or Capability manifests for semantic routing candidate work; actions and commands are read from existing manifests.
- Utility LLM detailed settings, scan, status tests, and unload controls belong under General -> Utility LLM. General -> Intent Routing may show only a compact Utility LLM status summary.
- Do not automatically download Utility LLM models, install optional dependencies such as `llama-cpp-python`, modify main LLM Provider/Profile settings, execute command-like intents, or run slash commands from intent predictions.
- User-visible frontend text must be added to every supported locale.
- Settings schema, runtime protocol, routing behavior, metadata shape, and user workflow changes must update docs in the same change.
- Do not modify Agent or Capability manifests for Intent Routing foundation work.

### Change Core Memory / Worldbook settings and APIs

Read:
- `README.md#settings`
- `README.md#sqlite-data`
- `docs/FRONTEND_UI_COMPONENTS.md` when changing Chat context modals, Settings object headers, or Worldbook entry UI
- `docs/EXTENSION_API.md#capability-config`
- `docs/EXTENSION_API.md#agent-overrides`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#knowledge-context`
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`

Likely source:
- `ai_workbench/core/settings.py` and `ai_workbench/core/memory_context.py` for Core Memory General settings and runtime context rendering
- `ai_workbench/core/worldbook.py` and `ai_workbench/core/worldbook_context.py`
- `ai_workbench/db/models.py`
- `ai_workbench/db/stores.py`
- `ai_workbench/api/routes/settings.py`
- `ai_workbench/api/routes/worldbook.py`
- `ai_workbench/core/runner.py` if Prompt Agent runtime injection changes
- `ai_workbench/core/script.py` if Script Agent `ctx.llm` injection changes
- `ai_workbench/api/routes/sessions.py` for session binding route wiring
- `frontend/src/components/settings/SettingsConsole.tsx`
- `frontend/src/components/settings/SettingsNav.tsx`
- `frontend/src/components/settings/SettingsObjectList.tsx`
- `frontend/src/components/settings/SettingsDetailPanel.tsx`
- `frontend/src/components/settings/WorldbookSettingsPanel.tsx`
- `frontend/src/components/ui`
- `frontend/src/components/ChatHeader.tsx` when changing Context Sources or session Knowledge/Worldbook binding UI
- `frontend/src/components/MessageBubble.tsx` when changing message-level injected context visibility, Knowledge snippets modal behavior, or run-step compact context summaries
- `frontend/src/App.tsx` and `frontend/src/components/SettingsPage.tsx` when changing Settings deep links or Context Sources "Open settings" routing
- `frontend/src/api/client.ts`
- `frontend/src/types.ts`
- `frontend/src/styles.css` for chat context modal or run-step summary layout
- `frontend/src/i18n/resources`

Tests:
- `uv run pytest tests/test_settings_data.py`
- `uv run pytest tests/test_worldbook.py`
- `uv run pytest tests/test_core_memory_context.py tests/test_worldbook_context.py` when runtime builders change
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py` when Prompt Agent or Script Agent runtime injection changes
- `uv run pytest tests/test_frontend_chat_contracts.py` if frontend settings contract changes
- `uv run pytest tests/test_frontend_chat_contracts.py` if message context modal, run-step context summary, or metadata contract assumptions change
- `cd frontend && npm run build`
- `cd frontend && node scripts/check-i18n.mjs`

Worldbook matching defaults to English-comma keyword splitting, case-insensitive regex matching, whole-word matching with ASCII boundaries, and recursion depth 0. When these matching defaults change, cover both `/api/worldbooks/match-test` and runtime injection so the test UI and Prompt/Script Agent behavior cannot diverge.

UI/i18n rule:
- Any new or changed user-visible Core Memory or Worldbook frontend text must update every supported locale file in `frontend/src/i18n/resources`.
- Chat modals, Settings detail headers, status dots, toggles, chips, empty action rows, drag handles, and inline statuses should reuse `frontend/src/components/ui` primitives instead of adding local variants.

Avoid unless explicitly in scope:
- Do not modify Agent or Capability manifests for Worldbook storage/API work.
- Runtime context injection is implemented for Core Memory and Worldbook. Keep injection limited to Prompt Agent main LLM calls and Script Agent `ctx.llm.*`; do not route it through title generation, query expansion, embeddings, reranking, commands, `/kb-search`, or non-LLM capability calls.
- Message-level injected context visibility must use compact metadata refs/counts/warnings only. Do not store full Core Memory text, full Worldbook entry content, rendered context blocks, full Knowledge snippet content, or vector blobs in run, run-step, or message metadata for UI convenience; fetch current user-owned content from the appropriate APIs when opening the modal.
- Do not use Knowledge indexes, vector storage, RAG retrieval, or FTS for Worldbook matching.

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
- Do not recommend `uv pip install ".[knowledge]"` or project-extra Knowledge install commands until `pyproject.toml` packaging is fixed for this flat-layout repository. Prefer direct dependency install commands such as `uv pip install sentence-transformers torch transformers` plus CUDA-specific PyTorch commands confirmed through the PyTorch install selector.

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
