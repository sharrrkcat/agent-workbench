# Task: Frontend UI

Read first:

- `../contracts/message-parts.md`
- `../contracts/runtime-streaming.md`
- `../contracts/settings-general.md`
- `../contracts/pet.md`

Likely sources: `frontend/src/types.ts`, `frontend/src/api/client.ts`,
`frontend/src/store/useWorkbenchStore.ts`, chat components, SettingsPage,
PetOverlay, and both locale trees.

Keep the UI limited to Chat, Models, Knowledge, Worldbook, General, and Pet.
Render messages from generic parts and run progress from stable step kinds.
Update both locales and run `npm run build`, `npm run check:i18n`,
`npm run test:phase1-contracts`, `npm run test:knowledge-citations`, and
`npm run test:url`.
