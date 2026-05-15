# Task: Runtime

## Read first

Read only the entries needed for the specific change; this list is an on-demand
map, not a requirement to read every file in full.

- `../contracts/runtime-streaming.md` for message streaming.
- `../contracts/runtime-run-lifecycle.md` for runs, steps, metadata, and cancel.
- `../contracts/runtime-llm-resolution.md` for main LLM resolution.
- `../contracts/provider-status.md` for Provider/Profile status and memory release.
- `../contracts/attachments-vision.md` for attachments and vision.
- `../contracts/utility-llm.md` for session title or Utility LLM behavior.
- `../contracts/intent-routing.md` for Intent Routing behavior.
- `../contracts/knowledge.md` for Knowledge context injection.
- `../contracts/memory-worldbook.md` for Core Memory and Worldbook injection.
- `../EXTENSION_API.md#script-context-api` when Script Agent ctx behavior changes.
- `../EXTENSION_API.md#output-payloads` when output shapes or renderers change.

## Likely source

- `ai_workbench/core/router.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/script.py`
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/events.py`
- `ai_workbench/core/llm_config.py`
- `ai_workbench/core/provider_status.py`
- `ai_workbench/core/runtime_memory.py`
- `ai_workbench/api/routes/runtime.py`
- `frontend/src/store/useWorkbenchStore.ts`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/components/ChatHeader.tsx`

## Tests

- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
- `uv run pytest tests/test_provider_status.py`
- `uv run pytest tests/test_runtime_memory.py` for memory release changes.
- `uv run pytest tests/test_file_http_attachments.py` for attachment changes.
- `uv run pytest tests/test_frontend_chat_contracts.py` for frontend contract changes.
- `cd frontend && npm run build` when frontend changes.

## Avoid

- Do not copy full topic contracts into this task card; update the relevant
  `../contracts/*.md` file instead.
- Do not change routing or command registry for run-step display work.
- Do not make internal `ctx.llm.stream` visible unless routed through public output APIs.
- Do not delete model files, knowledge bases, indexes, sessions, settings, or
  attachments from memory release paths.
- Do not generalize provider unload beyond providers with reliable unload APIs.

## Docs and i18n

- WebSocket events, run/run_step fields, model resolution, provider status,
  runtime memory, attachments, vision, Intent Routing, Knowledge, Utility LLM,
  Core Memory, or Worldbook changes update the owning contract under
  `../contracts/`.
- `../RUNTIME_PROTOCOLS.md` stays a short runtime index and summary.
- Script ctx or output payload API changes update `../EXTENSION_API.md`.
- User-visible frontend text changes require every supported locale.
