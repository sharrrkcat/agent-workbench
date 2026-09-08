# OpenAPI implementation

Accepted scope: all HTTP operations under /api and /v1, runtime JSON response
validation, deterministic export and automatic contract checks. Existing
frontend types/clients and WebSocket protocols remain in place. No migration.

## Round 1: foundations and external inference

- Added api/openapi.py, api/schemas/common.py and inference.py, scripts/openapi.py
  and tests/test_openapi.py. Updated api/main.py, routes/openai_compatible.py,
  pyproject.toml and uv.lock. The validator is a development dependency.
- Manual request schemas preserve the existing authentication, bounded body
  reader and sanitized errors. /v1 JSON outputs now have response models;
  security alternatives, SSE framing/examples and X-Request-Id are documented.
  Invalid application responses return a sanitized 500 INTERNAL_ERROR.
- `uv sync` succeeded. `uv run --no-sync pytest -q --tb=short`: 330 passed
  in 213.00s. Frontend npm test/build, backend compileall, docs size,
  workspace audit and git diff --check passed.
- The complete OpenAPI check intentionally reports remaining internal response
  and request definitions and open JSON fields. These are addressed in Round 2;
  no partial-coverage bypass is enabled. No actual model inference was used.

## Round 2: internal HTTP contracts

Completed 2026-09-08, continuing the interrupted implementation.

- Added api/schemas/models.py, chat.py, resources.py, system.py and attachments.py.
  Updated common.py, inference.py, api/openapi.py, api/main.py and all affected
  routes: models, runtimes, sessions, personas, messages, runs, tools, knowledge,
  worldbook, settings, attachments, data, health, runtime and openai_compatible.
  The existing typed Pet settings routes needed no change.
- Every ordinary JSON operation has runtime response validation, including
  202 runtime jobs. Public types omit keys, private run snapshots, installation
  manifest hashes and job log paths. Invalid response data becomes sanitized
  500 INTERNAL_ERROR; /v1 retains its request id and error access-log entry.
- Added concrete model-kind parameters, runtime options, message parts, session
  configuration, stored run-event variants, retrieval and resource diagnostics.
  core/json_data.py supplies finite recursive JSON; core/models/schema.py uses
  it for caller-supplied function/output schemas. Field-specific JSON uses are
  documented and audited by scripts/openapi.py, with no whole-body exceptions.
- Request documentation preserves manual parsing and merge-time validation.
  PATCH schemas describe omission, null, empty strings/arrays and immutable
  fields without changing domain error codes. Timestamps preserve microseconds,
  Z versus +00:00, and existing unzoned UTC model timestamps read from SQLite.
  Absent optional fields stay absent and explicit nulls remain present.
- Multipart upload, binary download, single Range, 200/206 headers and empty
  416 are documented. SSE remains text with generated chunk/error references,
  usage and terminal examples; only /v1 declares credential alternatives.
- API/workflow: added response validation and discoverable HTTP schemas. No
  new business route, setting, database revision, UI or frontend type source.

## Round 3: full contract acceptance

- scripts/openapi.py check/export validate OpenAPI 3.1, all 80 paths and 118 HTTP
  operations against actual routes, unique operationIds, model references,
  request/success structures, runtime response validation and precise JSON
  exceptions. Hidden business routes, undocumented bodies, arbitrary fields,
  blank schemas and stale exceptions fail the gate. There is no partial bypass.
- tests/openapi_assertions.py and tests/conftest.py validate existing domain
  tests' actual JSON and SSE frames against the served contract. Added
  tests/test_openapi_contracts.py alongside test_openapi.py for negative gates,
  isolation/export determinism, field omission, PATCH variants, every message
  part, public snapshots, 202 jobs, partial reindex, diagnostics and Range.
- README, AI_CONTEXT and the six owning contracts now describe the interfaces
  and commands. No seventh contract or checked-in static specification exists.
- Focused OpenAPI/protocol acceptance passed 36 tests; the subsequent expanded
  contract tests passed 21. Frontend npm test/build, compileall, OpenAPI check,
  docs size and workspace audit passed. Final full-suite result is recorded below.

### Final verification

Completed 2026-09-08.

- `uv run --no-sync pytest -q --tb=short --junitxml=build/openapi-pytest.xml`:
  352 passed in 352.61s. Automatic response checks covered 114 route/method
  pairs and 165 route/method/status combinations, including the deliberately
  invalid-response fixture. SSE frames and the attachment Range/body behavior
  passed. Every production HTTP operation passes static route/schema coverage.
- Frontend `npm test` and `npm run build` passed. The production build compiled
  2,088 modules; English/Chinese resources remained aligned. Backend
  `uv run --no-sync python -m compileall -q ai_workbench scripts/openapi.py` passed.
- `uv run --no-sync python scripts/openapi.py check` passed: OpenAPI 3.1.0,
  80 paths, 118 HTTP operations. `export --output build/openapi.json` succeeded;
  its 584,434 bytes match a fresh isolated application's schema. The tests also
  verify two byte-identical exports and equality with /openapi.json while
  database initialization, model loading and outbound HTTP are blocked.
- /openapi.json, /docs and /redoc returned 200 through the application factory.
  `uv run --no-sync python scripts/check_docs_size.py`, frontend
  `node scripts/check-doc-links.mjs`, `uv run --no-sync python
  scripts/audit_workspace.py --check` and `git -c core.safecrlf=false diff --check`
  passed. Audit found schema 0010_runtime_maintenance, valid SQLite integrity
  and foreign keys, no test model stubs and no workspace errors.
- Changed modules and API behavior are listed in Rounds 1-2 above. Tests/report
  additions and the six owning-contract updates are listed in Round 3. No
  implementation items or temporary coverage exceptions remain pending.

### Boundaries

Cross-field and saved-state checks remain domain validators; OpenAPI field types
do not replace them. Flexible tool/user JSON and metadata have finite JSON types
and exact documented exception paths. WebSocket transport remains in the existing
runs/streaming contract. Tests use isolated stores and deterministic adapters;
no real model inference, runtime installation or browser interaction was needed.
The frontend was not changed. Model/runtime/attachment directories are untouched
by this implementation; exports and the final test report belong under build/.
