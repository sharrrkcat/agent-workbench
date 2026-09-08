# Worldbook and Knowledge management

Accepted 2026-09-08. Historical UI baseline: 768b335d, removed by 6ad6d044.
The current simplification plan and domain contracts retain architectural ownership.
Status: implemented and verified.

## Implementation

- [x] Typed resource CRUD, Worldbook reorder/match and Knowledge attachment/chunk APIs.
- [x] Validate Worldbook updates before persistence; preserve invalidation until
  affected sources are rebuilt and set empty after the final source is deleted.
- [x] Full bounded attachment indexing and actual-file previews; Knowledge,
  message parts, Persona avatars and active snapshots protect attachment references.
- [x] Inline list/detail navigation with local selection and independent drafts.
- [x] Restore the historical Worldbook entry-card structure, pointer/touch/keyboard
  handle ordering, isolated enabled saves and bounded matching diagnostics.
- [x] Combine Knowledge source creation/listing, text/file input, per-file retry,
  preview/chunks, manual rebuild and search. No directory scanning or origins.
- [x] Complete retained global settings, collapsed advanced fields and both locales.
- [x] Complete behavioral, browser and repository quality gates.

## Changed modules

- Backend: Worldbook validation/store/routes; Knowledge preparation, service,
  store/status and routes; attachment reference collection, deletion and cleanup
  callers. No schema migration or data conversion.
- Frontend: domain clients/types; SettingsPage/App leave guard; WorldbookPanel
  and KnowledgePanel composed from domain detail, entry/source, test and settings
  components; shared resource fields/feedback and scoped CSS; en/zh-CN locales.
- Tests: resource management API/store tests, frontend contract/rendering tests
  and Playwright workflows using the isolated presentation fixture.
- Docs: Knowledge, Chat/Context and Settings contracts plus this record.

Changed files, grouped by directory (braces enumerate filenames):

```text
ai_workbench/api/routes/{attachments,data,knowledge,personas,sessions,worldbook}.py
ai_workbench/core/{attachments,conversation_history,knowledge_indexing,
  knowledge_service,knowledge_settings,knowledge_store,storage_maintenance,worldbook}.py
ai_workbench/db/stores.py
frontend/src/{App,main}.tsx
frontend/src/{api,types}/{knowledge,worldbook}.ts
frontend/src/components/SettingsPage.tsx
frontend/src/components/settings/{KnowledgePanel,WorldbookPanel}.tsx
frontend/src/components/settings/resources/{ResourceUI.tsx,resources.css}
frontend/src/components/settings/worldbook/{WorldbookDefaults,WorldbookDetail,
  WorldbookEntries,WorldbookEntryCard,WorldbookMatch}.tsx
frontend/src/components/settings/knowledge/{AddKnowledgeSource,KnowledgeDefaults,
  KnowledgeDetail,KnowledgeModelSelect,KnowledgeSearch,KnowledgeSourceDetail,KnowledgeSources}.tsx
frontend/src/i18n/resources/{en,zh-CN}/{knowledge,settings,worldbook}.json
frontend/scripts/{test-all,test-resource-management}.mjs
frontend/tests/resource-management.spec.ts
tests/{presentation_smoke_server,test_resource_management}.py
docs/AI_CONTEXT.md
docs/contracts/{chat-context,knowledge,settings}.md
docs/RESOURCE_MANAGEMENT_PLAN.md
```

## Workflow and limitations

Resources open inline; new saves open Entries/Sources. Entry layout follows
the old component's element order while adopting current colors and fields.
Settings/entry drafts survive internal tabs. Uploads run sequentially, show
partial failures and reuse uploaded attachments when retried. Source content
is read-only. Workspace paths are available through the existing API only.

No origins, directory scans, multiple chunk profiles, background jobs, model
downloads, independent model registries, or legacy compatibility are restored.
File import supports the existing UTF-8 text attachment extensions, not PDF/Office
parsing. Resource deletion respects Persona conflicts; session additions keep
their existing behavior. Model availability and real inference remain runtime
concerns; automated verification uses deterministic adapters.

## Verification (2026-09-08)

- `uv run --no-sync pytest -q --tb=short`: final full suite, 326 passed in 165.38s.
  Resource tests cover memory/SQLite validation before write, preview/chunks,
  complete >1 MiB attachment indexing, limits/encoding/empty input, reference
  protection across all owners, partial invalidation and empty-base deletion.
- Frontend `npm test`: passed, including resource API payloads, input projections,
  old card structure, nullable fields and bilingual missing-model states.
- Frontend `npm run build`: passed (TypeScript and Vite).
- `npx playwright test --max-failures=1`: 34 passed, including existing chat and
  runtime pages plus the initial 10 resource workflows. After adding the final
  binding workflow, `npx playwright test resource-management.spec.ts
  --max-failures=1`: all 11 resource workflows passed in 22.0s.
- Browser checks cover en/zh-CN at 1366x900 and 390x844; independent drafts,
  enable rollback, mouse/keyboard/touch sorting and touch cancellation, stale
  previews, sequential partial upload retries, cleanup, rebuild/delete, search,
  advanced/nullable settings and invalid input. The final workflow uses both
  Persona and session editors and verifies actual chat-context injection.
  Desktop/mobile expanded cards, lists, source dialogs and search screenshots
  were inspected; tested containers have no horizontal overflow. Screenshots
  are generated under frontend/test-results.
- Backend compileall, docs size, workspace audit and diff checks passed.
  The audit reports database integrity OK at 0010_runtime_maintenance.
- Started the built application with `scripts/run_app.py --no-open --port 8765`.
  GET /api/health and /settings?tab=worldbook return 200. No schema revision,
  data conversion, real-model inference or model download was performed.
