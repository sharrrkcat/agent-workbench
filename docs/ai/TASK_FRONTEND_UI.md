# Task: Frontend UI

## Read first

- `../FRONTEND_UI_COMPONENTS.md`
- `../contracts/runtime-streaming.md` for chat stream rendering.
- `../contracts/runtime-run-lifecycle.md` for run step/timeline UI.
- `../contracts/attachments-vision.md` for attachment UI.
- `../contracts/settings-general.md` for General Settings UI.
- `../contracts/memory-worldbook.md` for Core Memory/Worldbook UI.
- `../EXTENSION_API.md#output-payloads` for output renderer changes.
- Relevant task card for the feature domain, such as Settings, Knowledge,
  Runtime, Intent Routing, or ComfyUI.

## Likely source

- `frontend/src/components/ui`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/components/ChatHeader.tsx`
- `frontend/src/components/settings`
- `frontend/src/store/useWorkbenchStore.ts`
- `frontend/src/api/client.ts`
- `frontend/src/types.ts`
- `frontend/src/styles.css`
- `frontend/src/i18n/resources`

## Tests

- `cd frontend && npm run build`
- `cd frontend && node scripts/check-i18n.mjs` when user-visible text changes.
- `uv run pytest tests/test_frontend_chat_contracts.py` when frontend expects
  backend metadata, message, run, output, or settings contracts.
- Domain-specific backend tests if UI changes require API/schema changes.

## Avoid

- Do not add one-off controls when `frontend/src/components/ui` has a reusable primitive.
- Do not change output payload shapes purely for a local renderer convenience.
- Do not store full Core Memory, Worldbook, Knowledge snippets, vectors, or large
  payloads in metadata for UI convenience; fetch details from APIs.
- Do not leave new visible strings hardcoded in JSX.

## Docs and i18n

- Reusable primitive expectations update `docs/FRONTEND_UI_COMPONENTS.md`.
- Output shape, streaming, run metadata, settings workflow, or attachment
  behavior changes update the relevant contract doc.
- User-visible text changes require every supported locale file.
