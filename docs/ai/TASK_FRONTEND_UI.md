# Task: Frontend UI

Read first:

- `../contracts/message-parts.md`
- `../contracts/runtime-streaming.md`
- `../contracts/settings-general.md`
- `../contracts/pet.md`
- `../contracts/managed-runtime.md`
- `../contracts/harness-tools.md`

Likely sources: `frontend/src/types.ts`, `frontend/src/api/client.ts`,
`frontend/src/store/useWorkbenchStore.ts`, chat components, SettingsPage,
PetOverlay, `store/useModelsStore.ts`, `store/messageStream.ts`,
`components/settings/ModelsPanel.tsx`, and both locale trees.

Runtime catalog/jobs live in useModelsStore and RuntimesPanel. useModelEvents
subscribes to global events independently of the selected chat session.

Keep the UI limited to Chat, Models, Personas, Knowledge, Worldbook, General,
Tools, and Pet.
Render messages from generic parts and run progress from stable step kinds.
PersonasPanel edits prompt Personas and default context bindings; the chat
header/session dialog selects current speakers and explicit overrides.
Update both locales and run `npm run build`, `npm run check:i18n`,
`npm run test:phase1-contracts`, `npm run test:knowledge-citations`, and
`npm run test:url`, `npm run test:model-stream`, and `npm run test:harness`.
ToolsPanel and RunPanel share direct-call and approval state. Tool parts render
as data, all labels use both locales, and stale events/responses must not cross
sessions or reopen a completed approval.
