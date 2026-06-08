# Provider Status And Runtime Resources Contract

This contract owns Provider/Profile status, runtime memory release, and local
runtime resource snapshots.

## Status Values

Common model/profile status values:

- `READY`
- `PROVIDER_UNREACHABLE`
- `MODEL_NOT_AVAILABLE`
- `MODEL_MISMATCH`
- `MODEL_STATUS_UNKNOWN`
- `MODEL_NOT_LOADED` for LM Studio models that exist without loaded instances

Provider-level status is an aggregate across configured Model Profiles.
Model-level status is more specific and should be preferred for user-facing
model badges. A reachable provider with incomplete model evidence should not be
treated as ready.

Provider status refresh APIs return structured reachability and model
availability information without exposing API keys or secrets.

## API Index

| endpoint | purpose |
| --- | --- |
| `POST /api/llm-provider-profiles/status/refresh` | refresh status for all enabled Provider Profiles and mapped Model Profiles |
| `POST /api/llm-provider-profiles/{id}/status/refresh` | refresh one Provider Profile status |
| `GET /api/runtime/memory?session_id=<id>` | report runtime memory target availability |
| `POST /api/runtime/free-memory` | best-effort memory release for requested targets |
| `GET /api/runtime/resources` | cached local CPU/RAM/backend/GPU resource snapshot |

## Provider Behavior

LM Studio:

- First uses native `/api/v1/models` when available.
- Native responses may include `loaded_instances`.
- Status is green `READY` when the model exists and has loaded instances.
- Status is yellow `MODEL_NOT_LOADED` when the model exists without loaded
  instances.
- Missing or unreachable providers are red/unavailable statuses.
- Falls back to OpenAI-compatible model listing when native status is
  unavailable.
- Unload targets loaded matching instances when supported.

llama.cpp:

- Router mode reports a list of models.
- Single-server mode reports only the currently served model.
- Use `--alias` for a stable id.
- A single-server model mismatch reports `MODEL_MISMATCH`.

OpenAI-compatible providers:

- Support basic reachability/model-list status when the API exposes models.
- Are `READY` when the provider is reachable, `/v1/models` returns a parseable
  list, and the configured model id exists.
- Are unavailable/missing when the provider cannot be reached, profiles cannot
  be resolved, the target model id is absent, or model listing is incomplete.
- Do not expose portable loaded/unloaded pool semantics and should not produce a
  yellow unloaded status.

Internal providers:

- `internal_transformers` and `internal_llama_cpp` are Provider Profile source
  types for local model inventory. They scan fixed roots under `data/models`:
  `llms`, `embeddings`, and `rerankers`.
- Refresh/status checks are filesystem metadata and optional dependency
  availability checks only. They must not load model weights, initialize torch,
  initialize transformers pipelines, or initialize llama-cpp runtimes.
- `internal_transformers` lists model folders that look like HF,
  safetensors, sentence-transformers, or cross-encoder folders. It must not
  list pure GGUF files as transformers models.
- `internal_llama_cpp` lists `.gguf` files in the same three purpose roots.
- Internal model refs use purpose prefixes: `llm/...`, `embedding/...`, and
  `reranker/...`. Returned internal metadata may include `model_ref`,
  `display_name`, `kind`, `source=internal`, `backend`, and safe
  `relative_path`; it must not return absolute paths, file contents, secrets, or
  full directory trees.
- Internal Provider Profile UI may show the safe local models root
  (`data/models`), compact dependency/backend availability, CUDA/GPU
  availability when already reported by status APIs, copyable install command
  examples, selected runtime device or GPU layer settings, and refreshed model
  refs. It should not repeat embedding/reranker folder counts because refreshed
  inventory is the source of model visibility.
- `internal_transformers` status reports configured `local_runtime_device` and
  dependency/GPU availability when detectable. Selecting `cuda` or `mps` while
  the matching torch backend is unavailable returns a compact warning/status
  signal instead of failing Settings load.
- `internal_llama_cpp` status reports configured `llama_cpp_gpu_layers`.
  Non-zero GPU layer configuration means offload is requested; the status must
  not claim GPU readiness unless the llama-cpp-python backend can verify it.
- LLM Model Profiles may use only `llm/...` refs from internal providers.
  Status for those profiles reports provider enabled/disabled, model ref
  valid/invalid, model file/folder exists/missing, optional dependency
  available/unavailable, and loaded/unloaded when the local cache can be
  inspected.
- Embedding Model Profiles may use Provider Profiles independently of main LLM
  resolution. Internal embedding profiles use only `embedding/...` refs and
  report dependency/ref availability through compact status or test errors.
  External embedding profiles use provider reachability plus embedding test
  calls; status/test responses must not include API keys, absolute paths, raw
  provider payloads, or full directory trees.
- Reranker Model Profiles may use only internal Provider Profiles with
  `reranker/...` refs. Profile test/status paths report provider enabled state,
  ref validity, model existence, optional dependency availability, and loaded
  state where the local cache can be inspected. External reranker providers are
  not supported.
- Internal provider unload is best-effort cache release only. It may release
  cached `internal_transformers` or `internal_llama_cpp` LLM runtimes, and must
  never delete model files or user data. Unsupported, unavailable, or failed
  unload remains a cleanup/status outcome.
- `data/models/utility_llms` remains owned by the Utility LLM contract and is
  not scanned for Provider Profile inventory. If present, Provider Profile
  inventory may return a compact `legacy_utility_llms_not_scanned` warning.

## UI Usage

- Chat status dots and model dropdown cached status should prefer Model Profile
  status when available.
- The bottom status bar may show debug-oriented provider profile plus target and
  actual model details.
- Status refreshes after unload may emit `llm_provider_status_updated` when
  refresh succeeds.

## Runtime Memory Release

The runtime memory command/API targets are:

- `llm`
- `comfyui`
- `embedding`
- `reranker`
- `all`

`/free-memory <target>` calls the runtime memory control service and returns a
compact markdown result. Empty input returns usage:
`/free-memory [llm|comfyui|embedding|reranker|all]`.

`POST /api/runtime/free-memory` accepts:

```json
{"targets": ["llm"], "session_id": "..."}
```

and returns compact per-target results with status such as `freed`, `skipped`,
`busy`, `unavailable`, or `failed`.

Memory release is best-effort and never deletes model files, Knowledge Bases,
indexes, sessions, settings, attachments, or local user assets. Busy targets are
not force-released. In this alpha, manual LLM release is limited to provider
profiles with reliable unload support: LM Studio native unload and best-effort
internal LLM runtime cache release.
Future Stateless Inference image embedding and vision task caches must follow
the same best-effort/no-delete rule and are owned by
[stateless-inference.md](stateless-inference.md).

Embedding and reranker local cache release is best-effort and targets
provider-owned internal caches. The `embedding` target may release
local/internal embedding caches; external embedding providers have no local
cache and should be skipped or reported as no local cache. The `reranker`
target may release cached internal reranker runtimes and must never delete
model files, Knowledge data, or settings. ComfyUI memory release is an external
service request through ComfyUI `/free` with
`unload_models` and `free_memory` booleans. ComfyUI release failure is a cleanup
warning and must not turn an already successful image generation into a failed
run.

## Runtime Memory Availability API

`GET /api/runtime/memory?session_id=<id>` returns target availability summaries
with:

- `target`
- `available`
- `enabled`
- `reason`
- `status`

## Runtime Resources API

`GET /api/runtime/resources` returns a cached local resource snapshot for the
Chat header status panel. It may include:

- CPU
- RAM
- GPU/VRAM availability
- backend process memory
- `updated_at`

CPU/RAM and backend process memory use `psutil`. GPU/VRAM uses NVML-compatible
Python bindings when available. Missing or failed dependencies return
unavailable fields with compact reasons instead of failing the API.

Sampling is cached for a few seconds so Chat polling does not resample hardware
on every request.
