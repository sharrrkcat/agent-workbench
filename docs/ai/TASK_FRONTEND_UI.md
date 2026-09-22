# Task: Frontend UI

Read [settings](../contracts/settings.md), [chat/context](../contracts/chat-context.md),
[runs/streaming](../contracts/runs-streaming.md) and the affected domain contract.

## Source map

Paths below are under frontend/src:

- styles.css owns the Tailwind 4/Mira tokens and bundled Inter entry;
  components/ui/button.tsx and lib/utils.ts are the generated foundation.
  frontend/components.json configures generation; Vite/TypeScript and the test
  loader share the @/ alias. Current layout limits belong to
  [Settings](../contracts/settings.md#frontend-styling-foundation).
- types/ and api/ contain domain types/clients; api/http.ts and api/url.ts own transport.
- store/useWorkbenchStore.ts composes store/workbench/ actions and mergeState;
  store/messageStream.ts handles deltas. store/useModelsStore.ts and
  hooks/useModelEvents.ts handle global events.
- components/ChatView.tsx and components/messages/ compose replies and approvals.
- components/SettingsPage.tsx composes components/settings/ domain panels;
  components/settings/models/ contains model/provider editors; LocalRuntimePanel.tsx
  owns installation details. components/personas/ contains session editors.
- components/pet/usePetPosition.ts and components/pet/petState.ts contain
  dragging and task-state foundations.

## Verification

Follow the [i18n guide](../../frontend/src/i18n/README.md) for bilingual UI copy.
Run `npm test` and `npm run build` in frontend. The scripts load actual TypeScript
module graphs through scripts/module-loader.mjs and mock API/component boundaries;
do not match source formatting as behavior. Focused scripts cover session settings,
resource management, chat presentation, model streams, runtime maintenance and Harness.
test-module-loader.mjs covers real TS/TSX/JSON alias imports and shared API mocks.
style-foundation.spec.ts renders the real Button with production CSS on the existing
fixture server, checking dark colors, focus, disabled/override behavior and local
font loading in both locales and viewports. Existing page-layout cases stay unchanged
while their missing layouts are reconstructed.
Browser cases providers.spec.ts, model-sources.spec.ts, qwen-tts.spec.ts and runtime-maintenance.spec.ts
cover provider keys/sources, optional discovery, architecture defaults and installation/cache workflows.
Check stale responses, session isolation, approval visibility, draft persistence
and nullable/empty values when affected. Layout/workflow changes also require
desktop/mobile browser checks in both locales; fixture setup and commands are
in the [README](../../README.md#verification).
