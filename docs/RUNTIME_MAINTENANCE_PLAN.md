# Runtime maintenance and Windows CUDA

Accepted 2026-09-08. Status: complete.
This round follows the completed session/Pet and conversation presentation work.

## Delivery

- [x] Metadata-only storage totals and per-directory accounting, with hard-link
  deduplication, exclusive-size estimates and explicit incomplete results.
- [x] Manual uv cache prune/clean, shared maintenance job ownership, durable
  before/after results, cancellation and bounded logs.
- [x] 0010_runtime_maintenance recreates disposable runtime_jobs and clears
  installation job references; installation state and all files survive.
- [x] Windows x64 llama.cpp b10809 CUDA 12.4 main and runtime DLL artifacts,
  independent checksums, complete installation manifests and combined progress.
- [x] Single-GPU auto-fit or explicit offload layers, device checks and verified
  positive GPU offload before readiness, without changing configured context.
- [x] Bilingual runtime storage/maintenance controls and CUDA profile options.
- [x] Full automated checks, actual database upgrade/file preservation and
  existing local GGUF inference on the RTX 3050.

Vulkan, Python GPU variants, Linux CUDA, multi-GPU controls and model downloads
are deferred. Runtime directories, shared Python and uv file sharing remain
the storage model. Cache cleanup is explicit and never includes other data roots.

## Interfaces

GET /api/models/runtimes/storage returns on-demand timestamped accounting.
POST /api/models/runtimes/cache/cleanup accepts mode=prune|clean and returns a
maintenance job. Existing job/log/cancel routes and global events carry cache
jobs with null runtime identity and typed before/after results.

CUDA gpu_layers is auto or an integer from 1 through 999. Automatic fitting
keeps a 1024 MiB margin and the configured context floor; manual mode disables
fitting. Cached runtime status includes the device and observed offload layers.

## Verification

Results, changed modules, commands and remaining limitations are recorded here
as each implementation step completes.

- Initial backend verification: `uv run --no-sync pytest -q
  tests/test_runtime_maintenance.py tests/test_phase2b_runtime.py --tb=short`:
  48 passed. Covers storage identity, hard links outside the target, junctions,
  unknown/changed metadata, cache cancellation/failure and SQL job recovery.
- Actual database upgraded 0009 -> 0010: 3 disposable jobs removed, 28 other
  tables and 2 installation records preserved apart from their job references.
  45,445 data files retained paths, lengths and modification times. Integrity,
  foreign keys and a repeated upgrade passed.
- `uv run --no-sync python -m scripts.smoke_cuda_runtime --model-ref
  llms/MiniMindGGUF/minimind-3.q8.gguf` installed both pinned artifacts and passed
  on RTX 3050 Laptop GPU, driver 581.94. Automatic mode offloaded 9/9 layers with
  context 4096; nonstreaming and 34 streaming chunks completed with length finish.
  Unload/reload passed, manual mode offloaded 1/9 layers and final state was unloaded.
  The b10809 core INFO callback requires trace verbosity 4; that level and disabled
  colors are now covered by startup tests. No model weights were downloaded.
- Frontend `npm test` and `npm run build` passed. `npx playwright test
  tests/runtime-maintenance.spec.ts`: 10 passed across English/Chinese and
  1366x900/390x844. Screenshots and overflow checks cover storage details,
  confirmation, preserved installation, cancellation/retry, unknown statistics
  and CUDA automatic/manual save/reopen. The browser fixture uses temporary roots.
- Final `uv run --no-sync pytest -q --tb=short`: 316 passed in 134.56s.
  This includes native bundled-uv cleanup preserving installed hard links,
  repeated cancellation/shutdown coordination and missing offload diagnostics.
  Backend compileall, frontend tests/build, docs size, workspace audit and
  `git -c core.safecrlf=false diff --check` passed.
- The local app serves http://127.0.0.1:8000; health reports database=ok and
  schema_revision=0010_runtime_maintenance. Its storage API returned complete
  accounting for 41,009 runtime files: 8,039,731,116 logical bytes and
  4,674,928,807 bytes after hard-link deduplication. Cache accounting was
  3,392,515,989 logical bytes, 3,364,802,309 shared and 27,713,680 exclusive.
  The CUDA installation occupies 1,166,435,235 logical bytes across 56 files.

## Changed files

- Backend: api/routes/runtimes.py; core/models/manager.py and schema.py;
  core/models/runtimes/{schema,catalog,store,supervisor,adapters}.py plus new
  storage.py and cuda.py. All paths in this item are below ai_workbench/.
- Database: ai_workbench/db/{models,migrations}.py and
  alembic/versions/0010_runtime_maintenance.py. Runtime jobs gain nullable
  identity and typed JSON results; no other table is recreated.
- Frontend below frontend/src/: types/models.ts, api/models.ts,
  store/useModelsStore.ts, components/settings/{RuntimesPanel,RuntimeStoragePanel}.tsx,
  components/settings/models/{ProfileEditor,ProfilesTab,CudaLayersField}.tsx,
  styles.css and both i18n/resources locales' llm.json.
- Verification: tests/{test_runtime_maintenance,test_llama_cuda,test_phase2b_runtime,
  test_pet_foundation,presentation_smoke_server,runtime_browser_fixture}.py;
  frontend/scripts/{test-all,test-runtime-maintenance}.mjs;
  frontend/tests/runtime-maintenance.spec.ts; scripts/smoke_cuda_runtime.py.
- Documentation: README.md; docs/{AI_CONTEXT,DATA_LAYOUT,RUNTIME_PROTOCOLS,
  RUNTIME_MAINTENANCE_PLAN}.md; docs/ai/TASK_RUNTIME.md;
  docs/contracts/{models,settings,runs-streaming}.md.

## Limits

Real GPU validation used Windows x64, RTX 3050 and the existing MiniMind GGUF.
Other hardware and Linux execution were not exercised on this host. Deferred
variants remain unsupported. Storage figures are logical metadata estimates;
compression and copy-on-write allocation are not measured. Cache cleanup remains
manual and may be partial on cancellation or file occupancy errors. Application
settings gain no new persistent fields. Run the explicit CUDA smoke script with
Workbench stopped so that only one supervisor owns the runtime directory.
