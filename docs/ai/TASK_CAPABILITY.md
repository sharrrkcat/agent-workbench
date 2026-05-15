# Task: Capability

## Read first

- `docs/EXTENSION_API.md#capabilities`
- `docs/EXTENSION_API.md#capability-config`
- `docs/EXTENSION_API.md#output-payloads`
- `docs/CAPABILITY_DEVELOPMENT.md`
- `docs/EXTENSION_ARCHITECTURE.md` for reusable tool or integration design.
- `docs/generated/REGISTRY.md#capabilities` when manifests change or command
  registry details matter.

## Likely source

- `capabilities/<capability_id>/capability.yaml`
- `capabilities/<capability_id>/__init__.py`
- `ai_workbench/core/capability_registry.py`
- `ai_workbench/core/capability_runtime.py`
- `ai_workbench/core/capabilities.py` only when command/runtime behavior changes.
- Frontend message rendering files only when output renderer behavior changes.

## Tests

- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_capabilities.py` if present.
- `uv run pytest tests/test_script_agent.py` when Script Agent capability calls change.
- `uv run pytest tests/test_frontend_chat_contracts.py` for output metadata/rendering contracts.
- `cd frontend && npm run build` when frontend output rendering changes.

## Avoid

- Do not add slash command aliases to Agents.
- Do not make a Capability decide conversational style.
- Do not store durable outputs only as temporary remote URLs.
- Do not require real external services in automated tests.
- Do not reimplement Knowledge retrieval/indexing inside the thin `knowledge`
  Capability.

## Docs and i18n

- Capability manifest, config, method, command, or output shape changes update
  `docs/EXTENSION_API.md`.
- Streaming, run lifecycle, or event changes update `docs/RUNTIME_PROTOCOLS.md`.
- New complex integration patterns update `docs/EXTENSION_ARCHITECTURE.md`.
- Capability manifest changes require generated registry regeneration.
- User-visible frontend text changes require all supported locale files.
