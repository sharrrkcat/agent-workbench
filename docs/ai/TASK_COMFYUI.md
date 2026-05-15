# Task: ComfyUI

## Read first

- `docs/COMFYUI_PRESET_SCHEMA.md`
- `docs/EXTENSION_ARCHITECTURE.md#agent-vs-capability-decision-table`
- `docs/EXTENSION_ARCHITECTURE.md#configuration-ownership`
- `docs/EXTENSION_API.md#capabilities`
- `docs/EXTENSION_API.md#script-agents`
- `docs/EXTENSION_API.md#output-payloads`
- `docs/RUNTIME_PROTOCOLS.md#run-lifecycle`
- `docs/RUNTIME_PROTOCOLS.md#attachments-and-vision`
- `README.md#file-http-and-comfyui-capabilities`

## Likely source

- `capabilities/comfyui/capability.yaml`
- `capabilities/comfyui/__init__.py`
- `agents/comfyui_agent/agent.yaml`
- `agents/comfyui_agent/agent.py`
- ComfyUI workflow/preset asset directories configured through CapabilityConfig.
- `frontend/src/components/MessageBubble.tsx` for form/output rendering changes.
- `frontend/src/i18n/resources` for visible UI text.

## Tests

- `uv run python scripts/check_agents.py --strict`
- `uv run pytest tests/test_comfyui*.py` when present.
- `uv run pytest tests/test_script_agent.py` for Script Agent workflow changes.
- `uv run pytest tests/test_frontend_chat_contracts.py` for form/output metadata contracts.
- `cd frontend && npm run build` when frontend changes.

## Avoid

- Do not require a real ComfyUI service in automated tests.
- Do not treat GUI-format workflow JSON as API-format workflow JSON.
- Do not rewrite preset files when editing a per-session recipe.
- Do not store durable outputs only as service-side temporary URLs.
- Do not turn ComfyUI memory release failures into failed runs after generation succeeded.
- Do not add workflow editor, automatic mapping, img2img, upscale, or WebSocket
  progress unless explicitly in scope.

## Docs and i18n

- Preset YAML behavior changes update `docs/COMFYUI_PRESET_SCHEMA.md`.
- Capability/Agent config or output changes update `docs/EXTENSION_API.md`.
- Runtime generation, cleanup, attachment, or metadata changes update
  `docs/RUNTIME_PROTOCOLS.md`.
- User-visible frontend text changes require every supported locale.
