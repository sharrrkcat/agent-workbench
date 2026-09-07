# Session configuration and Pet foundations

Accepted 2026-09-07. This is a new plan after the completed Phases 0-5.
It supersedes the Persona configuration, binding and Pet decisions in the
[historical roadmap](WORKBENCH_REFACTOR_ROADMAP.md). The owning contracts
describe implemented behavior; this document tracks the implementation rounds.

## Round A: session configuration

Status: complete.

- [x] Reduce Persona data to identity, avatar, prompt and resource bindings.
- [x] Select the session model or global default; session generation fields
  override model parameters. Context belongs to the session, defaulting to history.
- [x] Always include the current speaker's nonempty system prompt.
- [x] Make Harness a session boolean, default off. New sessions allow all
  currently registered tools; switches persist an explicit allowlist, including [].
- [x] Combine current speaker bindings with independent session additions,
  preserving order and deduplicating only the effective list.
- [x] Verify APIs, snapshots, approvals, SQL/memory parity and desktop/mobile UI.
- [x] Upgrade the actual test database and record all quality gates.

`0008_chat_configuration` recreates Persona/session tables and discards affected
Persona/member/resource bindings, messages, runs, steps, events and snapshots.
It seeds only the reduced Chat/Translate identities and prompts. Knowledge,
Worldbook, models, runtime records and application settings survive. There is
no old-data conversion or compatibility path. Files are untouched.

## Round B: Pet foundations

Status: complete.

- [x] Remove the Codex sprite renderer, overlay, settings entry and all package
  discovery/import/selection/deletion/asset-serving flows.
- [x] Retain GET/PATCH /api/pets/settings with only position (mode, x, y).
- [x] Retain dimension-independent dragging with a persistence callback and
  a presentation-independent current-session run/step/progress selector.
- [x] Reuse run events; mount no Pet UI and perform no package loading/polling.
- [x] Verify removed routes, strict settings, dragging, task state and UI navigation.
- [x] Verify the actual test database at head and record all quality gates.

`0009_pet_foundation` discards the disposable app_settings object, resetting
General, Core Memory and Pet to current defaults. It changes no business tables
and leaves every file directory, including data/pet, intact. The new Pet's
appearance, resource format and animation are deferred.

## Round C: concrete model selection

Added 2026-09-07. Status: complete.
This replaces Round A's session/global model-selection rule.

- [x] New sessions save the enabled global-default LLM, otherwise the first
  enabled LLM in profile-list order. No eligible model leaves selection empty.
- [x] Remove Global default from both chat selectors and share their model,
  disabled, missing and empty states. Later default edits preserve saved choices.
- [x] Run only the selected session model; an explicit invalid model is never
  substituted. Keep auxiliary-title selection independent.
- [x] Verify defaults, missing/disabled models, explicit choices, persistence
  and both locales; rerun all quality gates.

## Defaults and acceptance

Harness controls model tool use. Direct calls still require the same session
allowlist but not Harness enablement; approvals and execution limits remain.
Disabling/re-enabling Harness preserves tool selection. New catalog entries do
not rewrite an existing session's allowlist. Running/approval snapshots are fixed.

Resource additions remain independent even when duplicated by Persona bindings.
Changing speaker changes only the Persona contribution. Clearing additions never
removes Persona resources. Resource enablement and retrieval/matching limits apply.

Each round runs full backend tests and compileall; frontend npm test/build;
docs size, workspace audit and diff checks. Migration tests use temporary roots
and verify foreign keys, repeat upgrades and file preservation. Browser checks
cover English/Chinese, desktop/mobile and the changed workflows. The user verified
the current page and explicitly waived further computer-use smoke on 2026-09-07;
remaining verification uses automated tests and the production build. Results, changed
modules, API/workflow changes and remaining limitations are recorded below.

## Verification records

### Round A (2026-09-07)

- Changed chat/session/Persona schemas, services, stores and API routes;
  configuration fields, Persona/session editors, domain types/clients, locales;
  added 0008, configuration tests and frontend field/API tests; updated contracts,
  README, task cards and entry documents.
- `uv run --no-sync pytest -q --tb=short`: 237 passed. `python -m compileall -q
  ai_workbench`, frontend `npm test`/`npm run build`, docs size, workspace audit
  and `git diff --check` passed.
- Actual database upgraded 0007 -> 0008; integrity and foreign keys passed.
  42,136 protected files retained identical paths, lengths and modification times.
- Browser at 1366x900 and 390x844 verified Harness defaults, switches, save/reopen,
  resource sections, locked Persona bindings, extra-resource persistence and
  speaker changes. Both locales passed deterministic frontend rendering tests.
- API/workflow changes are the session-owned configuration and additive bindings
  above. No real inference backend was used; browser checks used isolated fixture
  data and a deterministic adapter. Pet removal belongs to Round B.

### Round B (2026-09-07)

- Removed core/pet_service.py, frontend PetOverlay/PetSprite/usePetData,
  PetSettingsPanel and Pet locale resources. Updated api/main.py, deps.py,
  routes/pets.py, core settings/runtime, SQL settings persistence and migration
  helpers; added alembic/versions/0009_pet_foundation.py. Updated frontend
  App, settings navigation/client/types, usePetPosition, petState and styles;
  added tests/test_pet_foundation.py and frontend/scripts/test-pet-foundation.mjs.
- The prior task's `uv run --no-sync pytest -q --tb=short` passed 240 tests;
  the combined verification with Round C passed 246. Frontend `npm test` and
  `npm run build`, backend compileall, docs size, workspace audit and diff checks
  passed. Automated checks cover removed routes, strict shared settings,
  dragging/cancellation, task-state ordering and six-entry settings navigation.
- On resuming, the actual database was already at 0009. A repeated Alembic
  upgrade preserved all 26 inspected tables' records and 45,445 protected files
  with identical paths, lengths and modification times. Integrity and foreign
  keys passed. The isolated 0008 -> 0009 migration test verifies the settings
  reset, other-record/file preservation and repeat-upgrade persistence.
- API/workflow: only GET/PATCH /api/pets/settings remains; package routes return
  404 and invalid methods on the retained endpoint return 405. The frontend
  neither mounts nor fetches Pet content. Position dragging and task-state
  interfaces remain; appearance, assets and animations are deferred.
- The user confirmed the current page and waived further computer-use smoke.
  No real-model inference was performed in this round.

### Round C (2026-09-07)

- Changed core/models/manager.py, core/chat_service.py, core/chat_runner.py,
  core/harness/agent_loop.py, api/routes/health.py and core/schema/persona.py;
  frontend ChatHeader, personas/ConfigurationFields, types/chat and both
  locales' personas/llm resources. Added model-selection behavior to
  tests/test_chat_configuration.py and frontend/scripts/test-session-settings.mjs;
  updated tests/test_phase3_personas.py, the chat/models/settings contracts,
  AI_CONTEXT, README and this plan.
- POST /api/sessions now stores the default or first eligible concrete model;
  PATCH null clears selection and no longer means global inheritance.
  model_source reports session. Both selectors share real profile options and
  empty/unavailable states. Health diagnostics use the same creation default.
  No settings fields, routes or schema revision were added.
- `node scripts/test-session-settings.mjs`, frontend `npm test` and
  `npm run build` passed. Final `uv run --no-sync pytest -q --tb=short`:
  246 passed in 120.22s. Backend verification covers memory/SQLite persistence,
  missing/disabled/wrong-kind defaults, explicit choices, empty catalogs,
  existing-session stability and health diagnostics. `uv run --no-sync python
  -m compileall -q ai_workbench`, `uv run --no-sync python scripts/check_docs_size.py`,
  `uv run --no-sync python scripts/audit_workspace.py --check` and
  `git -c core.safecrlf=false diff --check` passed.
- Model initialization uses the profile catalog only; it does not probe runtime
  readiness or substitute models during inference. Existing unselected sessions
  require an explicit model choice. No real-model or additional computer-use
  smoke was run. Local server startup through Start-Process was rejected by
  automatic approval with "blocked by policy"; no local server was started.
