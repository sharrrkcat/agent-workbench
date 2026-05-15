# Task: Agent

## Read first

- `docs/EXTENSION_API.md#agent-manifest`
- `docs/EXTENSION_API.md#prompt-agents`
- `docs/EXTENSION_API.md#script-agents`
- `docs/EXTENSION_API.md#script-context-api`
- `docs/AGENT_DEVELOPMENT.md`
- `docs/generated/REGISTRY.md#agents` when manifests change or registry details matter.
- `docs/RUNTIME_PROTOCOLS.md#llm-resolution` when LLM profile behavior changes.

## Likely source

- `agents/<agent_id>/agent.yaml`
- `agents/<agent_id>/agent.py`
- `ai_workbench/core/runner.py` only for Prompt Agent runtime behavior.
- `ai_workbench/core/script.py` only for Script Agent ctx behavior.
- `ai_workbench/core/run_lifecycle.py` when run steps or status behavior changes.

## Tests

- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_prompt_agent_execution.py` for Prompt Agent runtime changes.
- `uv run pytest tests/test_script_agent.py` for Script Agent or ctx changes.
- `cd frontend && npm run build` only when renderer/frontend behavior changes.

## Avoid

- Do not add slash commands to Agents; slash commands belong to Capabilities.
- Do not change Script Agent runtime for prompt-only manifest edits.
- Do not change manifest schema unless the API change requires new fields.
- Do not rely on provider function calling or automatic tool selection.
- Do not treat raw LLM JSON as trusted without script-side validation.

## Docs and i18n

- Agent manifest, action, override, ctx, or output payload changes update
  `docs/EXTENSION_API.md`.
- Runtime lifecycle, streaming, LLM resolution, or metadata changes update
  `docs/RUNTIME_PROTOCOLS.md`.
- Complex Agent/Capability split decisions update `docs/EXTENSION_ARCHITECTURE.md`.
- Agent manifest changes require generated registry regeneration.
- User-visible frontend text changes require all supported locale files.
