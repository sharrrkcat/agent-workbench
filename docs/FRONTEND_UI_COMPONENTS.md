# Frontend UI components

The React client is intentionally small and local-first.

## Chat

`ChatView`, `ChatInput`, `MessageBubble`, `RunPanel`, and `SessionSidebar`
render generic sessions, message parts, and run events. All input is submitted
as text; no client-side parser or command palette is present. Streaming merges
sequence-numbered deltas and replaces drafts with the final message.

## Settings

`SettingsPage` exposes exactly General, Models, Knowledge, Worldbook, and Pet.
ModelsPanel contains unified profiles for five kinds, OpenAI-compatible
connections, global/auxiliary model selectors and external-service settings.
ChatHeader and Knowledge selectors share useModelsStore. Model parameters,
capabilities, release policy, status and inventory live in ModelsPanel.
Pet settings use the nested `/api/pets/settings` façade.

## Pet

`PetOverlay`, `PetSprite`, and `PetSettingsPanel` load state initially and
refresh after changes. Overlay sprite/bubble state derives from run status and
`RunStep.kind`; `WAITING_FOR_USER` is rendered as a confirmation state.

## Shared rules

Transport types are defined in `src/types.ts`; API calls live in
`src/api/client.ts`; chat state is in `useWorkbenchStore`, models in
`useModelsStore`, and delta reduction in `messageStream`. User-visible text
must be added to both locale trees. Run `npm run check:i18n` and the frontend
contract scripts for UI changes.
