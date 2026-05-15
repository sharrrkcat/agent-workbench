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
profiles with reliable unload support, currently LM Studio paths.

Embedding and reranker local cache release is best-effort. ComfyUI memory
release is an external service request through ComfyUI `/free` with
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
