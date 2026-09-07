# Models contract

All inference uses the application-scoped `core/models/ModelManager` and
`ProviderAdapter`. ChatRunner, Utility LLM, Knowledge and `/v1` call the manager
directly. Internal callers do not loop back through the application's HTTP API.
The API process imports no torch, transformers, onnxruntime or llama.cpp binding.

## Profiles and connections

`model_profiles` has one schema/store with five kinds: `llm`, `embedding`,
`reranker`, `image_embedding`, `vision`. Internal references use UUID `id`;
external requests use the unique lowercase `alias`, without prefixes or UUID
lookup. Kind is immutable. CRUD uses `/api/models/profiles`, with `?kind=...`.

`provider_profiles` holds `protocol=openai_compatible`, `base_url`, optional key,
timeouts, concurrency, queue limits and enablement. CRUD and model discovery use
`/api/models/providers` and `/{id}/models`. There are no brand-specific protocols.

A model selects either `provider_profile_id` or `runtime_id` plus
`runtime_variant`/`runtime_options`. It also owns `model_ref`, capabilities,
per-kind parameters, lifecycle, `enabled` and `external_enabled`. Backend
bindings are mutually exclusive. A backend-less profile can be saved but cannot
execute. Unknown fields and invalid parameter/capability combinations fail
before persistence. Referenced deletion and busy connection edits return errors.

Key reads and PATCH semantics belong to [settings](settings.md#model-settings).
Changing an embedding backend, reference or preprocessing configuration
invalidates associated indexes; see [Knowledge](knowledge.md).

## Resolution and capabilities

Chat selects session model override, then current Persona model, then the
global default. Missing selection returns `MODEL_NOT_CONFIGURED`. Disabled,
missing or wrong-kind profiles fail explicitly without model substitution.
Persona/session behavior and the auxiliary title selector are owned by
[chat/context](chat-context.md).

LLM generation parameters are temperature, top_p, max_tokens, presence/frequency
penalties, seed and stop. Explicit request fields override profile defaults.
Capabilities are streaming, tools, vision, json_object and json_schema;
unsupported requests return `UNSUPPORTED_CAPABILITY`.

External OpenAI-compatible connections execute chat and text embeddings.
Managed llama-server executes LLM chat. Python workers execute embedding,
rerank, image embedding and vision. Standalone vision/image_embedding kinds
are distinct from an LLM's image-input capability. Managed llama image input
is unavailable until projector support is implemented; external vision-capable
LLMs accept the current chat image-input protocol.

## Lifecycle and status

The manager owns health/load/unload, provider queues and cleanup. Defaults are
concurrency 1, 32 waiting slots and 30 seconds queue timeout. Model discovery
shares the provider queue. Queue overflow/timeout returns `MODEL_BUSY`.
Cancellation or stream closure releases upstream responses, slots and tasks.

External aliases share residency/occupancy by `(provider_profile_id, model_ref)`.
Managed GGUF aliases share normalized reference, process and options. Python
profiles share a variant queue while loading/unloading independently.
Release defaults to `manual`; `after_request` and `idle` (300 seconds by default)
are opt-in. An enabled manual alias keeps a shared model resident; otherwise
the longest idle timeout wins. Automatic release errors are diagnostic and do
not replace successful inference. Managed crashes require explicit load.

| Operation | Endpoint under `/api/models` | Effect |
| --- | --- | --- |
| Cached status | GET `/profiles/{id}/status` | No provider call |
| Health | POST `/profiles/{id}/health` | Explicit provider/model check |
| Load/unload | POST `/profiles/{id}/load` or `/unload` | Manager lifecycle |
| Connection inventory | GET `/providers/{id}/models` | Queued upstream list |
| Local inventory | GET `/inventory?kind=...` | Relative file references only |

Inventory/status reads never load weights, import heavy runtimes or download
models. Local roots under `data/models` are `llms`, `embeddings`, `rerankers`,
`image_embeddings` and `vision`. Inventory recognizes GGUF files and model
directories containing `config.json` or `model.onnx`.

Status contains state (`unknown`, `ready`, `unavailable`, `failed`, `unloaded`),
residency (`unknown`, `loaded`, `unloaded`), unload_supported, active, queued and
optional error_code. External health/load requires the exact advertised
model_ref, means ready with unknown residency, and cannot unload weights;
unload returns `UNLOAD_UNSUPPORTED`. UI controls reflect these limits.
Managed status adds runtime id/variant/version, installation/process state and
latest job id. Global status events are defined in [runs/streaming](runs-streaming.md).
`GET /api/runtime/resources` remains a cached CPU/RAM/GPU diagnostic snapshot.

## Managed catalog and installation

`GET /api/models/runtimes/catalog` exposes a code-owned, version-pinned catalog,
platform/architecture support, model kinds and strict options schemas. Internal
catalog records own HTTPS artifact URLs, SHA-256, archive format and executable.
Enabled variants are `llama-server/cpu` and `python-worker/torch-cpu` on Windows
and Linux x64. CUDA, Vulkan, torch-cu128 and onnx-gpu remain visibly unsupported.

Llama model_ref is a safe relative GGUF path; Python model_ref is a safe relative
directory, both under `data/models`. Profiles cannot supply an executable or
arbitrary command-line argument. Llama options are threads, context_size,
batch_size and gpu_layers (zero on CPU); worker options are device=cpu,
intraop_threads and max_batch_size. Saving before installation is allowed;
execution reports the missing runtime/model.

`POST /api/models/runtimes/{runtime_id}/{variant}/install` creates a job. Only
one installation/uninstallation job runs application-wide. Artifacts stream to
`data/runtimes/.staging/{job_id}`, undergo checksum/path checks and receive an
installation manifest before promotion to:

```text
data/runtimes/llama-server/<version>/<variant>/
data/runtimes/py/<variant>/<version>/
```

The bundled application uv installs pinned Python into runtime-owned storage,
creates the worker venv and installs hash-locked dependencies. `--no-bin` and
`--no-registry` avoid user PATH/registry changes. Download configuration is
owned by [settings](settings.md); weights are always placed manually.

Jobs expose queued/running/completed/failed/cancelled/interrupted states, stage,
byte progress, error code, revision and bounded logs. Cancellation stops the
subprocess and clears staging. Restart marks unfinished jobs/installations
interrupted and clears owned staging. Failed/cancelled jobs retain their log;
retry starts a new job. Uninstall stops related workers, removes only the
matching runtime directory and marks it not_installed. Shared interpreters and
download cache remain available to other variants.

Read-only routes list installations, per-runtime status, jobs and job details.
`/api/models/runtimes/jobs/{id}/log` returns a task log; `/cancel` requests
cancellation. `/api/models/profiles/{id}/log` returns managed process logs.
Responses omit absolute paths, ports, process tokens and raw provider errors.
Runtime failures use `RUNTIME_NOT_INSTALLED`, `RUNTIME_INSTALLING`,
`RUNTIME_BROKEN`, `RUNTIME_UNSUPPORTED`, `MODEL_NOT_FOUND`, `MODEL_BUSY` or
`MODEL_UNAVAILABLE`.

## Managed processes and workers

Workers bind `127.0.0.1` on dynamically reserved ports. The supervisor owns
process groups and Windows kill-on-job-close Job Objects, stopping full process
trees on unload, cancellation or application exit. Logs are sanitized, capped
at 10 MiB, and retained under `data/logs/runtimes`: latest 20 terminal task logs
and 20 process logs per runtime.

Llama-server uses the existing OpenAI-compatible adapter and a per-process key
stored only in its private process directory. Python workers use token-authenticated
`GET /health` and `POST /load`, `/unload`, `/embed`, `/rerank`, `/image-embed`,
`/vision` endpoints. Standard-library request validation precedes engine imports.

Workers set HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE, use local_files_only, reject
unsafe paths and accept images only as bounded PNG/JPEG/WebP data URLs. They
fetch neither image URLs nor model weights, and never execute remote model code.
Supported CPU engines are transformers text embeddings, sequence-classification
reranking, CLIP, SigLIP2, DINOv2, Florence2 and WD14. Embeddings use attention-mask
mean pooling with a 512-token limit. Rerank needs a trained classification head;
WD14 needs model.onnx and selected_tags.csv, without requiring config.json.
Integrity checks cover the dependency lock, worker source fingerprint and
installed file list, excluding generated bytecode caches.

## External inference API

The optional service is disabled by default, accepts loopback clients only and
requires one configured key. Authenticate with `Authorization: Bearer <key>` or
`x-api-key`; conflicting credentials fail. Client-address checks are independent
of forwarded headers. The official launcher binds loopback only.

| Endpoint | Supported operation |
| --- | --- |
| GET `/v1/models` | Enabled public llm/embedding aliases |
| POST `/v1/chat/completions` | Non-streaming or SSE chat |
| POST `/v1/embeddings` | Text embeddings |

A public alias must be enabled, externally visible and match the endpoint kind
and requested capabilities. Stateless calls create no sessions, messages, runs,
attachments or Knowledge rows; global status and access logs remain observable.
Both Content-Length and actual received bytes are bounded by max_request_mb.
Strict schemas reject unsupported fields without echoing request values.
Responses include X-Request-Id. Logs exclude keys, prompts, image/model content
and raw provider errors, and record final stream outcome and elapsed time.

Chat accepts system/developer/user/assistant/tool roles; plain text; user
image_url parts using HTTP(S) or image data URLs; function tools, tool_choice,
parallel_tool_calls, response_format and generation parameters. Only n=1 is
accepted. Formats are text/json_object/json_schema with matching capabilities.
Tool results must match preceding assistant calls. Unknown fields, legacy
function-call fields, unsupported formats and incomplete histories are rejected.
Tool definitions/calls/results are forwarded as data and never executed by
`/v1`. Internal execution belongs to [harness/tools](harness-tools.md).

Non-streaming tool-only messages have content=null. SSE framing, error timing
and disconnect cleanup are owned by [runs/streaming](runs-streaming.md#external-sse).

Embeddings accept a string or nonempty string array. encoding_format is float
or base64 (little-endian float32), with optional dimensions. The manager applies
the profile's document instruction, batching, dimension validation and
normalization, shared with Knowledge indexing; queries use query instruction.
Public rerank and image generation are deferred; see [future services](../FUTURE_MODEL_SERVICES.md).
