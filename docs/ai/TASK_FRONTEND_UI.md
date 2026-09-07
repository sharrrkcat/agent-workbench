# Task: Frontend UI

Read [settings](../contracts/settings.md), [chat/context](../contracts/chat-context.md),
[runs/streaming](../contracts/runs-streaming.md) and the affected domain contract.

Types live in frontend/src/types by domain. frontend/src/api has matching
domain clients plus http.ts for requests/errors and url.ts for URL handling.
There is no aggregate types.ts or api/client.ts import path.

useWorkbenchStore composes workbench/sessionActions, messageActions, runActions,
runtimeEvents and mergeState into one Zustand store. Preserve atomic updates,
microsecond timestamp ordering, approval state and isolation after session
switches. messageStream owns sequence-based text merging. useModelsStore and
useModelEvents own global model/runtime progress even without a session.

SettingsPage owns seven entries and composes independent domain panels.
settings/models splits profile/connection lists and editors, external service,
field controls and feedback; RuntimesPanel owns the runtime view. Shared fields
must not import SettingsPage. Existing navigation and Models tab drafts persist.

MessageBubble composes messages/MessageActions and MessageParts. PetOverlay
composes pet/usePetData, usePetPosition and petState with the existing PetSprite.
Keep tool output as data and active approval/cancellation visibly actionable.
Persona editing and session overrides use the existing personas components.

All UI copy uses both locale trees. Custom content, prompts, tool payloads and
ids are not translated. Run `npm test` and `npm run build` in frontend. Tests
load actual TypeScript module graphs through scripts/module-loader.mjs and
mock API/component boundaries; do not match source formatting as behavior.
Use desktop/mobile browser checks for layout or workflow changes.
