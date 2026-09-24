# Task: Frontend UI

Read [settings](../contracts/settings.md), [chat/context](../contracts/chat-context.md),
[runs/streaming](../contracts/runs-streaming.md) and the affected domain contract.

## Source map

Paths below are under frontend/src:

- styles.css owns Tailwind 4/Mira tokens, bundled Inter and scoped application
  layout/content rules. components/ui/ owns shared Base UI/Mira controls and
  their styling; lib/utils.ts exports the class utility.
  frontend/components.json configures generation; Vite/TypeScript and the test
  loader share the @/ alias. Current layout limits belong to
  [Settings](../contracts/settings.md#frontend-styling-foundation).
- types/ and api/ contain domain types/clients; api/http.ts and api/url.ts own transport.
- store/useWorkbenchStore.ts composes store/workbench/ actions and mergeState;
  store/messageStream.ts handles deltas. store/useModelsStore.ts and
  hooks/useModelEvents.ts handle global events.
- components/SessionSidebar.tsx and ChatHeader.tsx compose the home navigation.
  components/ChatView.tsx owns the session-scoped MessageScroller; components/messages/
  compose replies, disclosure anchors and approvals. ChatInput.tsx owns the composer.
- components/SettingsPage.tsx composes components/settings/ domain panels and the
  shared shell. SettingsSidebar.tsx uses grouped routes from settings/navigation.ts;
  settings/SettingsView.tsx retains inactive subpages and hides their overlays.
  components/settings/models/ contains model/provider editors; LocalRuntimePanel.tsx
  owns installation details. components/personas/ contains session editors.
- App.tsx owns committed routes and guarded history replay; ResourceUI.tsx in
  components/settings/resources/ owns async resource leave guards and invalid-field
  expansion. hooks/useConfirmDialog.tsx owns local promise-based confirmations.
- components/pet/usePetPosition.ts and components/pet/petState.ts contain
  dragging and task-state foundations.

## Verification

Follow the [i18n guide](../../frontend/src/i18n/README.md) for bilingual UI copy.
Run `npm test` and `npm run build` in frontend. The scripts load actual TypeScript
module graphs through scripts/module-loader.mjs and mock API/component boundaries;
do not match source formatting as behavior. Focused scripts cover session settings,
resource management, chat presentation, model streams, runtime maintenance and Harness.
test-confirm-dialog.mjs covers acceptance, cancellation, overlapping requests, hidden owners and unmount.
test-contracts.mjs covers settings route defaults and round trips.
test-module-loader.mjs covers real TS/TSX/JSON alias imports and shared API mocks.
style-foundation.spec.ts renders the real Button with production CSS on the existing
fixture server, checking dark colors, focus, disabled/override behavior and local
font loading in both locales and viewports. controls.spec.ts mounts the real App
with production CSS in English/Chinese at 1366x900 and touch-enabled 390x844. It
covers keyboard/labels, 44px targets, nested overlays and focus, retained drafts,
validation, busy locks, async navigation/history, attachments, IME and approvals.
app-layout.spec.ts covers sidebar scrolling/menus, deletion, drawer focus, Markdown,
composer growth, disclosure position and breakpoint/short viewport behavior.
chat-presentation.spec.ts and vision-input.spec.ts retain streaming and image workflows.
settings-layout.spec.ts covers all 11 grouped pages, collapsed menus, direct links, history, resource
leave guards, retained drafts/hidden dialogs, shared navigation and responsive scroll regions.
Browser cases providers.spec.ts, model-sources.spec.ts, qwen-tts.spec.ts and runtime-maintenance.spec.ts
cover provider keys/sources, optional discovery, architecture defaults and installation/cache workflows.
test-wd14.mjs and wd14.spec.ts cover WD14 source/CPU defaults, inventory/manual references,
threshold validation/round trips and lifecycle controls in both locales and desktop/touch viewports.
Check stale responses, session isolation, approval visibility, draft persistence
and nullable/empty values when affected. Layout/workflow changes also require
desktop/mobile browser checks in both locales; fixture setup and commands are
in the [README](../../README.md#verification).
