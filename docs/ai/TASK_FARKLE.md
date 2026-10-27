# Task: Farkle

Read the [Farkle contract](../contracts/farkle.md) for behavior and current limitations.
[Settings](../contracts/settings.md#frontend-styling-foundation) owns shared UI and
Playground navigation; the [Frontend task](TASK_FRONTEND_UI.md) maps those integration points.

## Source map

Game modules below are under [frontend/src/components/playground/farkle/](../../frontend/src/components/playground/farkle/):

- FarklePage.tsx composes navigation, dialogs, ordinary/custom setup, language,
  inventory actions, storage feedback and results. FarkleTable.tsx connects the
  reducer to input, animations and the scene; FarkleHud.tsx and TurnNotice.tsx present scores and turns.
- state.ts owns match/turn transitions and input ownership; scoring.ts evaluates
  scoring subsets and wildcards. dice.ts owns type identities, integer face weights,
  difficulty and face sampling; input.ts owns directional navigation.
- DiceChooser.tsx and DiceRow.tsx share selection controls, previews and probability
  cards; DiceShop.tsx reuses rows for immediate trading. loadout.ts owns six-die balancing,
  the full catalog pool and the ordinary player preference; customGame.ts owns custom
  configuration including both loadouts, target validation and match setup types.
- economy.ts owns levels, inventory, trading, maintenance actions and reward settlement;
  rewards.ts groups result rewards and useInventory.ts handles persistence/retry.
- settings.ts and useFarkleSettings.ts own opponent-mode preferences and retries;
  storage.ts clears the four game-owned browser keys.
- opponentDice.ts selects loadouts from the catalog/calibration artifact.
  ai.ts computes turn values; ai.worker.ts owns worker messages; useOpponent.ts
  coordinates worker lifetime, failure/retry and opponentPlayback.ts operation timing.
- scene.ts, layout.ts and playback.ts own Three.js rendering, camera/storage framing
  and baked-pose playback. geometry.ts, materials.ts and tableMaterial.ts own shared
  dice geometry, previews, face textures and table materials.

Integration lives in [App.tsx](../../frontend/src/App.tsx),
[PlaygroundPage.tsx](../../frontend/src/components/playground/PlaygroundPage.tsx) and
[navigation.ts](../../frontend/src/components/playground/navigation.ts).
[styles.css](../../frontend/src/styles.css) owns scoped game layout/HUD styles.
Follow the [i18n guide](../../frontend/src/i18n/README.md) for both locale resources.

## Data artifacts

- [rolls.json](../../frontend/src/components/playground/farkle/rolls.json) is the checked-in
  trajectory library. [bake-farkle.mjs](../../frontend/scripts/bake-farkle.mjs) owns its
  seeded offline Rapier recipe; [rendering rules](../contracts/farkle.md#table-rendering-and-trajectories)
  define simulation, playback and resource-lifecycle boundaries.
- [calibration.json](../../frontend/src/components/playground/farkle/calibration.json) is
  the frozen named-combination table. Its provenance, selection labels and import/validation
  boundaries belong to [Calibration](../contracts/farkle.md#calibration).

## Verification

Use the [README verification commands](../../README.md#verification) for frontend
tests/build, browser acceptance and trajectory regeneration. Routine tests verify
checked-in artifacts; regenerate trajectories only when their recipe/artifact changes.

Focused scripts under [frontend/scripts/](../../frontend/scripts/):

- test-farkle.mjs: scoring partitions, wildcard limits, turn/batch transitions,
  input ownership, stale AI rejection, reset cancellation, navigation, trajectories,
  camera projection/storage clearance under all four rectangular symmetries,
  closed circular-face geometry, deterministic textures and rendering cleanup.
- test-farkle-rolls.mjs: artifact validity, seeded reproduction, interpolated
  floor/dice contacts, settling and per-count recent history.
- test-farkle-economy.mjs: all ten reward schedules, trading, ownership clipping, inventory maintenance and
  safe-integer boundaries, scoped cache removal/retry, face weights and zero-probability
  faces, uniform sampling/caps, the twenty-type reward pool and browser storage.
- test-farkle-opponent.mjs: frozen calibration validity, named probabilities,
  interval boundaries, original random parity, unrestricted loadouts and local settings.
- test-farkle-custom.mjs: six-die balancing, replacement order, independent custom storage, full pools and safe integer targets.
- test-farkle-ai.mjs: bounded large-target computation against full-goal values,
  extreme Weighted loadouts, exact turn values, conservative difficulty, identity-sensitive
  selections, complete banking, hot dice and pausable operation timing.

Browser coverage uses production UI with deterministic draws/rolls in both locales
and desktop/touch layouts:

- [farkle-hud.spec.ts](../../frontend/tests/farkle-hud.spec.ts): five/six-digit totals
  and rounds, four-digit selections, unbroken row labels, longer wrapped values and HUD sizing.
- [farkle.spec.ts](../../frontend/tests/farkle.spec.ts): ordinary levels and custom
  flows; independent ordinary/custom player preferences and unrestricted custom loadouts; target validation,
  contextual errors, mode descriptions, selected-row highlights and short-screen scrolling.
  Gameplay covers selection/wildcards, batches, rerolls, passes, Bust, automatic camera/AI
  ownership, visible thinking/selection timing, return-to-B pause, pause/retry/cancellation,
  victory, replay, custom reward exclusion, table entry and turn notices.
  Storage covers inventory/rewards/loadouts, quantity limits, drafts, read/save retries,
  immediate shop trades, fixed-snapshot retries, next-game ownership clipping, shared language persistence, inventory maintenance and
  scoped cache reset including failed removals, pending writes and cancellation.
  Presentation covers probability cards, all 22 appearances, circular Heavenly faces with
  a Maltese cross and numeric hover hint, English-name ordering in either locale,
  inventory/chooser/shop columns, owned-type-dependent chooser width and grouped results,
  short-screen reward scrolling, large scores and overlay isolation.

[playground.spec.ts](../../frontend/tests/playground.spec.ts) and
[test-playground.mjs](../../frontend/scripts/test-playground.mjs) cover shared route/history,
leave guards, startup, draft cleanup, queued-message return and late-response isolation.
