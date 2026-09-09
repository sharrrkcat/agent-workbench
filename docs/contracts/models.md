# Models contract

All inference uses the application-scoped `core/models/ModelManager` and
`ProviderAdapter`. ChatRunner, Utility LLM, Knowledge and `/v1` call the manager
directly. Internal callers do not loop back through the application's HTTP API.
The API process imports no torch, transformers, onnxruntime or llama.cpp binding.

## Profiles and connections

`model_profiles` has one schema/store with six kinds: `llm`, `embedding`,
`reranker`, `image_embedding`, `vision`, `tts`. Internal references use UUID `id`;
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

New sessions save the enabled global-default LLM or first enabled LLM (name, id
order). Execution uses that selection; Persona has none. Missing selection returns
MODEL_NOT_CONFIGURED; disabled, missing or wrong-kind selections fail without
substitution. Default selection never calls providers. `/api/health/details`
uses the same selection and cached status, degraded without an enabled LLM.
Persona/session behavior and the title selector belong to [chat/context](chat-context.md).

LLM parameters are temperature, top_p, max_tokens, presence/frequency penalties,
seed and stop; explicit request values override defaults. Capabilities are
streaming, tools, vision, json_object and json_schema; unsupported requests fail.

External connections execute chat/text embeddings; llama-server executes chat.
Python workers execute embedding, rerank, image embedding, vision and TTS.
Standalone vision/image_embedding differs from LLM image input. Managed llama
image input awaits projector support; external vision LLMs accept chat images.

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
`image_embeddings`, `vision` and `tts`. Inventory recognizes GGUF files and model
directories; TTS requires the Kokoro ONNX layout. Auxiliary models are not listed.

Status contains state (`unknown`, `ready`, `unavailable`, `failed`, `unloaded`),
residency (`unknown`, `loaded`, `unloaded`), unload_supported, active, queued and
optional error_code. External health/load requires the exact advertised
model_ref, means ready with unknown residency, and cannot unload weights;
unload returns `UNLOAD_UNSUPPORTED`. UI controls reflect these limits.
Managed status adds runtime id/variant/version, installation/process state and
latest job id. CUDA status also reports device_name, gpu_layers_loaded and
gpu_layers_total, clearing them when the process stops. Global status events
are defined in [runs/streaming](runs-streaming.md).
`GET /api/runtime/resources` remains a cached CPU/RAM/GPU diagnostic snapshot.

## Managed catalog and installation

`GET /api/models/runtimes/catalog` exposes a code-owned, version-pinned catalog,
platform/architecture support, model kinds and strict options schemas. Internal
catalog records own HTTPS artifact URLs, SHA-256, archive format and executable.

| Enabled variant | Platforms |
| --- | --- |
| llama-server/cpu | Windows and Linux x64 |
| llama-server/cuda | Windows x64 |
| python-worker/torch-cpu | Windows and Linux x64 |
| python-worker/onnx-cpu | Windows and Linux x64 |

Vulkan, torch-cu128, onnx-gpu and Linux CUDA remain visibly unsupported.

Llama model_ref is a safe relative GGUF path; Python model_ref is a safe relative
directory, both under `data/models`. Profiles cannot supply an executable or
arbitrary command-line argument. Llama options are threads, context_size,
batch_size and gpu_layers (strict zero on CPU; auto or strict integer 1..999
on CUDA, default auto); worker options are device=cpu,
intraop_threads and max_batch_size (fixed 1 for ONNX CPU). Saving before installation is allowed;
execution reports the missing runtime/model.

`POST /api/models/runtimes/{runtime_id}/{variant}/install` creates a job. Only
one installation, uninstallation or cache-maintenance job runs application-wide. Artifacts stream to
`data/runtimes/.staging/{job_id}`, undergo checksum/path checks and receive an
installation manifest before promotion to:

```text
data/runtimes/llama-server/<version>/<variant>/
data/runtimes/py/<variant>/<version>/
```

The bundled application uv installs pinned Python into runtime-owned storage,
creates the worker venv and installs hash-locked dependencies. ONNX CPU permits
only docopt, jaconv, jieba and unidic-lite source builds with locked build tools;
native packages require wheels. `--no-bin` and
`--no-registry` avoid user PATH/registry changes. Download configuration is
owned by [settings](settings.md); weights are always placed manually.

Windows CUDA uses llama.cpp b10809's CUDA 12.4 main ZIP and separately pinned
cudart ZIP. Catalog additional_artifacts owns the latter's URL, hash, format
and size. Both downloads must pass SHA-256 before extraction. Combined byte
progress covers both packages. Dependency DLLs join the executable directory;
different-content filename collisions fail. Other dependency files retain a
namespaced directory. The manifest records both artifact hashes and every
installed file. A --version check precedes promotion. Dependencies are scoped
to the child process; system PATH, registry and drivers are not modified.

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
`RUNTIME_BROKEN`, `RUNTIME_UNSUPPORTED`, `RUNTIME_DEVICE_UNAVAILABLE`, `MODEL_NOT_FOUND`, `MODEL_BUSY` or
`MODEL_UNAVAILABLE`.

## Storage and cache maintenance

GET /api/models/runtimes/storage performs an on-demand, metadata-only scan in
a background thread. It returns scanned_at, complete, totals, groups, warnings
and skipped_links. Groups cover each runtime installation directory, shared
Python, cache, staging, process files and other files. Paths are relative to
data/runtimes; symbolic links and Windows directory junctions are not followed.

Usage fields are file_count, logical_bytes, unique_bytes, shared_bytes and
exclusive_bytes. File identities deduplicate hard links. Exclusive size requires
all OS-reported hard links to belong to the group, including links outside the
scanned root in the exclusion. Totals deduplicate independently of the rows.
These are logical file sizes, not allocated disk bytes or exact free-space
predictions; compression and copy-on-write sharing are not measured.
Unreadable or changing metadata makes the affected group and totals incomplete,
with unknown usage fields represented by null. Reads do not load models.

POST /api/models/runtimes/cache/cleanup accepts only mode=prune|clean and returns
202 with a RuntimeJob. The bundled uv runs cache prune/clean with an explicit
managed cache directory, --no-config and normal uv locking. Redirected roots or
escaping cache links fail validation. Cleanup is limited to .cache and does not
unload models. Filesystem occupancy failures retain diagnostics for retry.

Cache jobs use operation=cache_prune|cache_clean and null runtime_id, variant
and version. Optional result.before/after hold strict usage snapshots; missing
accounting is null. They reuse job/log/cancel routes and global job events,
without installation state writes. Cancellation/failure may leave partial
cleanup; before/after figures are never presented as actual disk recovery.
Startup marks unfinished cache jobs interrupted. Latest 20 terminal cache logs
are retained independently of runtime installation logs.

## Managed processes and workers

Workers bind `127.0.0.1` on dynamically reserved ports. The supervisor owns
process groups and Windows kill-on-job-close Job Objects, stopping full process
trees on unload, cancellation or application exit. Logs are sanitized, capped
at 10 MiB, and retained under `data/logs/runtimes`: latest 20 terminal task logs
and 20 process logs per runtime.

Llama-server uses the existing OpenAI-compatible adapter and a per-process key
stored only in its private process directory. Python workers use token-authenticated
`GET /health` and `POST /load`, `/unload`, `/embed`, `/rerank`, `/image-embed`,
`/vision` and binary `/speech` endpoints. Standard-library validation precedes engine imports.

CUDA load enumerates devices using the pinned executable and selects the first
CUDA device with split-mode=none. No usable device returns RUNTIME_DEVICE_UNAVAILABLE.
Automatic offload uses gpu-layers=auto, fit=on, a 1024 MiB margin and fit-ctx
equal to the configured context size. Manual layers use fit=off. Before ready,
the pinned startup log must confirm at least one layer on GPU; zero/missing
offload or insufficient memory fails loading and stops the process. There is
no CPU substitution. Cached status/catalog reads do not probe GPU hardware.

Workers set HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE, use local_files_only, reject
unsafe paths and accept images only as bounded PNG/JPEG/WebP data URLs. They
fetch neither image URLs nor model weights, and never execute remote model code.
Supported CPU engines are transformers text embeddings, sequence-classification
reranking, CLIP, SigLIP2, DINOv2, Florence2 and WD14. Embeddings use attention-mask
mean pooling with a 512-token limit. Rerank needs a trained classification head;
WD14 needs model.onnx and selected_tags.csv, without requiring config.json.
Integrity checks cover the dependency lock, worker source fingerprint and
installed file list, excluding generated bytecode caches.

Manual b10809 validation covers Windows x64, RTX 3050 Laptop GPU and MiniMind
(2026-09-08), not Linux/other GPUs. See [README](../../README.md#verification).

## Kokoro TTS

TTS supports only managed `python-worker/onnx-cpu`, architecture=kokoro, with
the v1.0 FP32 model.onnx, config/tokenizer JSON files and voices/<id>.bin.
The fixed 54-ID catalog intersects with finite float32 [510,1,256] files; extras
such as af.bin are ignored. No voice-profile records are created. Off-loop file
checks power GET /api/models/profiles/{id}/voices without model loading.

The ONNX environment uses Misaki, spaCy 3.7.5 and NumPy 1.26.4 without PyTorch or
Transformers. It installs the checksum-verified local en_core_web_sm 3.7.1 wheel
from data/models/_auxiliary/en_core_web_sm alongside eSpeak NG and UniDic.
All language frontends initialize before readiness with Python networking blocked,
as during execution. Missing resources fail without downloads.

Speech accepts 1..4096 nonblank characters, voice, speed=0.25..4,
response_format=mp3|wav, stream_format=audio and optional tts.language matching the
voice. Request values override profile speed=1 and format=mp3. Other fields fail.
Chunks retain supported text, use at most 510 tokens and voice row N-1; unsplit
oversized words fail. Complete 24 kHz mono PCM16 WAV or 128 kbps MP3 is returned;
PCM and encoded data each have a 32 MiB limit. Timeout is 300 seconds. Disconnects
stop the worker before releasing occupancy and log REQUEST_CANCELLED with 499.
SSE, cloning, external TTS providers and application playback are unimplemented.
Real Kokoro installation and inference validation covers Windows x64. Linux x64
has a pinned dependency lock and catalog entry, without native runtime validation.

## External inference API

The optional service is disabled by default, accepts loopback clients only and
requires one configured key. Authenticate with `Authorization: Bearer <key>` or
`x-api-key`; conflicting credentials fail. Client-address checks are independent
of forwarded headers. The official launcher binds loopback only.

| Endpoint | Supported operation |
| --- | --- |
| GET `/v1/models` | Enabled public llm/embedding/tts aliases |
| POST `/v1/chat/completions` | Non-streaming or SSE chat |
| POST `/v1/embeddings` | Text embeddings |
| POST `/v1/audio/speech` | Complete MP3/WAV speech |
| GET `/v1/audio/voices` | Preset voice discovery (Workbench extension) |

A public alias must be enabled, externally visible and match the endpoint kind
and requested capabilities. Stateless calls create no sessions, messages, runs,
attachments or Knowledge rows; global status and access logs remain observable.
Both Content-Length and actual received bytes are bounded by max_request_mb.
Strict schemas reject unsupported fields without echoing request values.
Responses include X-Request-Id. Logs exclude keys, prompts, image/model content
and raw provider errors, and record final stream outcome and elapsed time.
Voice discovery accepts model alias and source=preset|temporary (temporary is
empty). Items contain id, model, source, language and expires_at=null; only enabled
public TTS profiles and valid preset files appear.

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

Assistant messages and streaming deltas accept optional string reasoning_content
through the shared OpenAI-compatible adapter. /v1 forwards that field and preserves
literal content, without interpreting <think> markers. Internal ChatRunner/Harness
normalize reasoning separately for the conversation view. Structured reasoning
may accompany native tool continuations; other message roles reject the field.

Embeddings accept a string or nonempty string array. encoding_format is float
or base64 (little-endian float32), with optional dimensions. The manager applies
the profile's document instruction, batching, dimension validation and
normalization, shared with Knowledge indexing; queries use query instruction.
Public rerank and image generation are deferred; see [future services](../FUTURE_MODEL_SERVICES.md).
## HTTP schemas

OpenAPI 3.1 covers management and `/v1`, strict per-kind/runtime schemas, storage
and jobs. Public responses omit keys, manifest hashes and log paths. Invalid JSON
results become sanitized 500 INTERNAL_ERROR. OperationIds are unique; omission,
null and timestamp precision survive, including SQLite's unzoned UTC text.
Manual `/v1` parsing authenticates and bounds bytes before validation. Only `/v1`
advertises Bearer/x-api-key alternatives; matching credentials are required when
both are supplied. Operations document JSON, SSE or audio and X-Request-Id.
See [README](../../README.md#http-contract) for isolated check/export commands.
