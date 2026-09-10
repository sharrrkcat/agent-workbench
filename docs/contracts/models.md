# Models contract

All inference uses the application-scoped `core/models/ModelManager` and
`ProviderAdapter`; ChatRunner, Utility LLM, Knowledge and `/v1` call the manager without HTTP loopback.
The API process imports no torch, transformers, onnxruntime or llama.cpp binding.

## Profiles and connections

`model_profiles` has six immutable kinds: `llm`, `embedding`, `reranker`,
`image_embedding`, `vision`, `tts`. References use UUID `id` internally and unique
lowercase aliases externally. CRUD: `/api/models/profiles`, with `?kind=...`.

`provider_profiles` owns OpenAI-compatible URL/key, timeouts, concurrency, queue and enablement.
CRUD: `/api/models/providers`; discovery: `/{id}/models`. Brand-specific protocols are absent.

A model selects mutually exclusive `provider_profile_id` or `runtime_id` plus
`runtime_variant`/`runtime_options`. It owns `model_ref`, capabilities, per-kind
parameters, lifecycle, `enabled` and `external_enabled`. Backend-less profiles
can be saved but cannot execute. Unknown/invalid fields fail before persistence;
referenced deletion and busy connection edits return errors.

[Settings](settings.md#model-settings) owns key/PATCH semantics. Embedding backend,
reference or preprocessing changes invalidate indexes; see [Knowledge](knowledge.md).

## Resolution and capabilities

New sessions save the enabled global-default LLM or first enabled LLM (name/id order).
Execution uses that selection; Persona has none. Missing selection returns
MODEL_NOT_CONFIGURED; disabled/missing/wrong-kind selections fail without substitution.
Default selection and `/api/health/details` use cached state, degraded without an
enabled LLM. [Chat/context](chat-context.md) owns Persona/session/title selection.

LLM parameters are temperature, top_p, max_tokens, presence/frequency penalties,
seed and stop; explicit request values override defaults. Capabilities are
streaming, tools, vision, json_object and json_schema; unsupported requests fail.

External connections execute chat/text embeddings; llama-server and Transformers
execute chat, ONNX executes Kokoro TTS and Audio executes English Chatterbox. Local embedding, rerank, image-embedding
and WD14 entry points remain pending. Managed image input is unavailable;
external vision LLMs accept chat images.

## Lifecycle and status

The manager owns health/load/unload, queues and cleanup: concurrency 1, 32 waiting
slots, 30-second queue timeout. Discovery shares the queue; overflow/timeout returns
`MODEL_BUSY`. Cancellation/stream closure releases responses, slots and tasks.

External aliases share residency/occupancy by `(provider_profile_id, model_ref)`.
Managed GGUF aliases share normalized reference, process and options. Transformers
aliases share a process/queue by path and runtime options; ONNX profiles share a variant queue.
Audio profiles have separate processes, queues and cancellation scopes, even for the same model path.
Release defaults to `manual`; opt-ins are `after_request` and `idle` (300 seconds).
An enabled manual alias retains shared models; otherwise the longest idle timeout
wins. Release errors never replace successful inference. Crashes require explicit load.

| Operation | Endpoint under `/api/models` | Effect |
| --- | --- | --- |
| Cached status | GET `/profiles/{id}/status` | No provider call |
| Health | POST `/profiles/{id}/health` | Explicit provider/model check |
| Load/unload | POST `/profiles/{id}/load` or `/unload` | Manager lifecycle |
| Connection inventory | GET `/providers/{id}/models` | Queued upstream list |
| Local inventory | GET `/inventory?kind=...` | Relative file references only |

Inventory/status never load weights, import heavy runtimes or download models.
Roots under `data/models`: `llms`, `embeddings`, `rerankers`, `image_embeddings`,
`vision`, `tts`. Inventory recognizes GGUF/model directories, including Kokoro ONNX
and English Chatterbox. Auxiliary resources are excluded.

Status contains state (`unknown`, `ready`, `unavailable`, `failed`, `unloaded`),
residency (`unknown`, `loaded`, `unloaded`), unload_supported, active, queued and
optional error_code. External health/load requires the advertised model_ref,
reports unknown residency and returns `UNLOAD_UNSUPPORTED` on unload.
Managed status adds runtime id/variant/version, installation/process state,
latest job id and device_name. CUDA layer counts clear when the process stops.
UI controls reflect these limits; [runs/streaming](runs-streaming.md) owns status events.
`GET /api/runtime/resources` remains a cached CPU/RAM/GPU diagnostic snapshot.

## Managed catalog and installation

The [runtime plan](../ai/PLAN_RUNTIME_FAMILIES.md) owns remaining work. Catalog reads at
`GET /api/models/runtimes/catalog` expose pinned platforms, kinds and strict options;
internal records own HTTPS URLs, SHA-256, archive format and executable.

| Variant | Availability |
| --- | --- |
| llama-server/cpu | Windows and Linux x64 |
| llama-server/cuda | Windows x64 |
| python-worker/transformers-cuda | Windows x64 (validated with explicit CPU and CUDA execution) |
| python-worker/onnx-cpu | Windows and Linux x64 (Kokoro; WD14 remains deferred) |
| python-worker/infinity-cuda | Placeholder, unsupported |
| python-worker/audio-cuda | Windows x64; Chatterbox, with private Qwen3-TTS/Whisper acceptance tooling |

Separate PyTorch CPU distributions, Vulkan, torch-cu128 and onnx-gpu are removed.
Linux Transformers, Infinity and Audio remain unsupported.

Local model_ref is a safe relative GGUF file or Python model directory under
`data/models`; profiles cannot supply executables or arbitrary arguments.
Llama options are threads, context_size, batch_size and gpu_layers (0 on CPU;
auto or integer 1..999 on CUDA). ONNX options are device=cpu, intraop_threads and
max_batch_size=1. Transformers and Audio options are device=cpu|cuda (default cuda) and
intraop_threads=4. Profiles may be saved before installation; execution reports missing resources.

`POST /api/models/runtimes/{runtime_id}/{variant}/install` creates a job; only one
install/uninstall/cache job runs application-wide. Downloads stage under
`data/runtimes/.staging/{job_id}` with checksum/path checks and a manifest, then
promote to `data/runtimes/llama-server/<version>/<variant>/` or
`data/runtimes/py/<variant>/<version>/`.

The bundled uv installs artifact-pinned Python and hash-locked dependencies in
separate family environments, then checks dependency consistency and offline imports.
Transformers pins Python 3.12.11, Transformers 5.16.1, Torch 2.11.0+cu128 and
Torchvision 0.26.0+cu128. Audio pins Python 3.12.11, Torch/Torchaudio 2.6.0+cu124,
Transformers 4.57.3, Qwen-TTS 0.1.1 and NumPy 1.26.4. Its versioned Chatterbox
0.1.7+workbench.1 wheel adjusts the upstream Transformers requirement; the build
script, embedded patch record, complete lock and dependency check make this auditable.
Only docopt, jaconv, jieba and unidic-lite (ONNX), or antlr4-python3-runtime and
sox (Audio), may use source builds with locked build tools; native packages require wheels.
`--no-bin`/`--no-registry` preserve user PATH/registry. [Settings](settings.md)
owns download configuration; weights are always placed manually.

Windows llama.cpp b10809 CUDA uses separately pinned main and cudart ZIPs, with
catalog URLs/hashes/formats/sizes and combined byte progress. Both pass SHA-256
before extraction. DLLs join the executable directory; different-content name
collisions fail. Other dependencies retain a namespace. The manifest records both
artifact hashes and every file; --version precedes promotion. Child-only dependency
paths leave system PATH, registry and drivers unchanged.

Jobs expose queued/running/completed/failed/cancelled/interrupted states, stage,
byte progress, error code, revision and bounded logs. Cancellation stops subprocesses
and clears staging. Restart marks unfinished work interrupted and clears staging.
Failure/cancellation retains logs; retry creates a job. Uninstall stops related
workers and removes only the matching runtime, retaining shared interpreters/cache.

Read-only routes list installations/status/jobs. `/api/models/runtimes/jobs/{id}/log`
returns task logs; `/cancel` cancels. `/api/models/profiles/{id}/log` returns process logs.
Responses omit absolute paths, ports, tokens and raw provider errors. Failures use
`RUNTIME_NOT_INSTALLED`, `RUNTIME_INSTALLING`, `RUNTIME_BROKEN`, `RUNTIME_UNSUPPORTED`,
`RUNTIME_DEVICE_UNAVAILABLE`, `MODEL_NOT_FOUND`, `MODEL_BUSY` or `MODEL_UNAVAILABLE`.

## Storage and cache maintenance

GET /api/models/runtimes/storage scans metadata off-loop, returning scanned_at,
complete, totals, groups, warnings and skipped_links. Groups cover installations,
shared Python, cache, staging, process and other files. Paths are relative to
data/runtimes; symlinks and Windows junctions are not followed.

Usage fields are file_count, logical_bytes, unique_bytes, shared_bytes and
exclusive_bytes. File identities deduplicate hard links; exclusive size excludes
files with any link outside the group, including outside the scanned root. Totals
deduplicate independently. Logical sizes omit compression/copy-on-write effects
and do not predict disk recovery. Unreadable/changing metadata produces incomplete
groups/totals and null unknown values. Reads never load models.

POST /api/models/runtimes/cache/cleanup accepts mode=prune|clean and returns 202
with a RuntimeJob. Bundled uv uses the explicit .cache directory, --no-config and
normal locking. Redirected roots/escaping links fail. Models stay loaded;
filesystem occupancy failures retain retry diagnostics.

Cache jobs use operation=cache_prune|cache_clean and null runtime_id/variant/version.
Optional result.before/after contain strict usage snapshots (null when unavailable).
They reuse job/log/cancel routes/events without installation-state writes. Partial
cleanup may survive failure/cancellation; figures never claim actual disk recovery.
Startup interrupts unfinished jobs; the latest 20 terminal cache logs are retained
independently of installation logs.

## Managed processes and workers

Workers bind `127.0.0.1` on reserved ports. Process groups and Windows kill-on-job-close
Job Objects stop full trees on unload, cancellation or exit. Sanitized logs are capped
at 10 MiB under `data/logs/runtimes`: latest 20 terminal tasks and 20 process logs per runtime.

Llama and Transformers use the OpenAI-compatible adapter and private process keys.
Transformers exposes authenticated health, a single managed model and chat endpoints;
ONNX and Audio use token-authenticated health/load/unload and binary speech RPC;
Audio also validates reference files without loading model weights.
Standard-library validation precedes engine imports.

Llama CUDA enumerates devices with the pinned executable and selects the first
with split-mode=none; none returns RUNTIME_DEVICE_UNAVAILABLE. Auto uses
gpu-layers=auto, fit=on, a 1024 MiB margin and fit-ctx=context_size; manual uses
fit=off. Startup logs must confirm positive GPU offload; missing/zero layers or
insufficient memory stops loading without CPU substitution. Cached reads do not probe GPUs.

Workers enforce offline/local-only loading without remote model code or device substitution.
Transformers uses float32 on CPU and checkpoint dtype on CUDA; upstream idle release
is disabled. ModelManager stops cancelled processes before freeing occupancy.
Transformers tools require a supported response template and run only via Harness;
vision, JSON output, nonzero presence/frequency penalties and explicit tool controls fail.
Audio blocks Python networking, uses Chatterbox from_local with float32/attention
adaptations, and shares its environment across three isolated engines. Qwen3-TTS
and Whisper are private acceptance engines, without public kinds or endpoints.
Whisper counts decoded samples before resampling/feature extraction: at most 30
seconds, including exactly 30, with explicit rejection above it and no truncation,
segmentation or partial transcript. Audio has no Linux package or validation.
CLIP, SigLIP2 and WD14 entry points remain; DINOv2 and Florence2 are removed.
Integrity checks cover family-specific locks/sources and installed files, excluding bytecode caches.

## Kokoro TTS

Kokoro TTS uses managed `python-worker/onnx-cpu`, architecture=kokoro, with
the v1.0 FP32 model.onnx, config/tokenizer JSON files and voices/<id>.bin.
The fixed 54-ID catalog intersects with finite float32 [510,1,256] files; extras
such as af.bin are ignored. No voice-profile records are created. Off-loop file
checks power GET /api/models/profiles/{id}/voices without model loading.

ONNX uses Misaki, spaCy 3.7.5 and NumPy 1.26.4 without PyTorch/Transformers, plus
the verified local en_core_web_sm 3.7.1 wheel from data/models/_auxiliary/en_core_web_sm,
eSpeak NG and UniDic. All language frontends initialize before readiness with
Python networking blocked throughout execution. Missing resources fail without downloads.

Speech accepts 1..4096 nonblank characters, voice, speed=0.25..4,
response_format=mp3|wav, stream_format=audio and optional tts.language matching the
voice. Request values override profile speed=1 and format=mp3. Other fields fail.
Chunks retain supported text, use at most 510 tokens and voice row N-1; unsplit
oversized words fail. Complete 24 kHz mono PCM16 WAV or 128 kbps MP3 is returned;
PCM/encoded data each have a 32 MiB limit; timeout is 300 seconds. Disconnects stop
workers before releasing occupancy and log REQUEST_CANCELLED with 499.
SSE, external TTS providers and playback are unimplemented. Real Kokoro validation
covers Windows x64; Linux has a pinned lock/catalog entry without native validation.

## Chatterbox and temporary references

English Chatterbox uses architecture=chatterbox and `python-worker/audio-cuda`.
Local files are ve.safetensors, t3_cfg.safetensors, s3gen.safetensors and tokenizer.json.
Speech shares Kokoro's text/speed/format/output-size/300-second timeout contract;
tts.language may only be en-US. Profile defaults and tts.model_options overrides
accept exaggeration=0.5 [0,2], cfg_weight=0.5 [0,1], temperature=0.8 (0,5],
repetition_penalty=1.2 [1,2], min_p=0.05 [0,1], top_p=1 (0,1]. Unknown options fail
before queue admission. Kokoro rejects Chatterbox options and reference audio.

Chatterbox requires exactly one temporary voice ID or tts.reference_audio with
format=wav|mp3 and data_base64. Multipart uploads contain model alias and one file;
the response contains voice_id, model, source=temporary and expires_at. Both paths
validate format and decoded samples before synthesis: 8 MiB encoded, 32 MiB
decoded, 1/2 channels, 8..192 kHz and at most 30 seconds. Uploaded names never
choose storage paths. One-request files are removed on completion/cancellation.

References are bound to the creating key and model profile/binding. Clients sharing
the service key share access. Creation grants 30 minutes; a valid execution/queue
admission atomically applies max(expires_at, now+15 minutes). Overflow, discovery
and rejected pre-admission requests do not renew. Expired IDs cannot reactivate.
Active/queued requests pin files until completion or worker cancellation; deleting
an unexpired active ID returns 409. Key replacement, service/profile disablement, profile
removal/binding changes and restart invalidate IDs. Cleanup runs on reference
access/release and restart. Limits are 64 files and 128 MiB per service, including
one-request files. Storage is temporary under [data layout](../DATA_LAYOUT.md),
without attachment, voice-profile or database records. Chatterbox has no presets.

## External inference API

The optional service defaults to disabled, accepts loopback clients only and
requires one key via `Authorization: Bearer <key>` or `x-api-key`; conflicting
credentials fail. Address checks ignore forwarded headers; the launcher binds loopback.

| Endpoint | Supported operation |
| --- | --- |
| GET `/v1/models` | Enabled public llm/embedding/tts aliases |
| POST `/v1/chat/completions` | Non-streaming or SSE chat |
| POST `/v1/embeddings` | Text embeddings |
| POST `/v1/audio/speech` | Complete MP3/WAV speech |
| GET `/v1/audio/voices` | Preset/temporary voice discovery (Workbench extension) |
| POST `/v1/audio/voice-references` | Upload a temporary Chatterbox reference |
| DELETE `/v1/audio/voice-references/{voice_id}` | Delete an unused reference |

A public alias must be enabled, externally visible and match endpoint kind/capabilities.
Stateless calls create no sessions, messages, runs, attachments or Knowledge rows.
Content-Length and received bytes obey max_request_mb. Strict schemas reject
unsupported fields without echoing values. Responses include X-Request-Id; logs
record final outcome/elapsed time without keys, prompts, content or raw provider errors.
Voice discovery accepts optional model alias and source=preset|temporary. Items
contain id, model, source, language and expires_at (null for presets). Only enabled
public TTS profiles, valid preset files and the current key's unexpired references appear.

Chat accepts system/developer/user/assistant/tool roles, text, user image_url
parts (HTTP(S)/data URLs), function tools, tool_choice, parallel_tool_calls,
response_format and generation parameters. Only n=1 is accepted. Formats are
text/json_object/json_schema with matching capabilities. Tool results must match
preceding calls; unknown/legacy fields, unsupported formats and incomplete histories
fail. `/v1` forwards tool data without execution; [Harness](harness-tools.md) owns execution.

Non-streaming tool-only messages have content=null. SSE framing, error timing
and disconnect cleanup are owned by [runs/streaming](runs-streaming.md#external-sse).

Assistant messages/deltas accept string reasoning_content, including native tool
continuations; other roles reject it. `/v1` forwards literal content/reasoning without
interpreting <think> markers. ChatRunner/Harness normalize reasoning for the UI.

Embeddings accept a string/nonempty string array, float/base64 encoding (little-endian
float32) and optional dimensions. Document instructions, batching, dimension checks
and normalization match Knowledge indexing; queries use query instruction.
Public rerank and image generation are deferred; see [future services](../FUTURE_MODEL_SERVICES.md).

## HTTP schemas

OpenAPI 3.1 covers management and `/v1` with strict kind/runtime/storage/job schemas.
Responses omit keys, manifest hashes and log paths; invalid results become sanitized
500 INTERNAL_ERROR. OperationIds are unique; omission/null/timestamp precision
survive, including SQLite UTC text. `/v1` authenticates/bounds bytes before parsing
and alone advertises Bearer/x-api-key alternatives. Operations document JSON/SSE/audio
and X-Request-Id. See [check/export commands](../../README.md#http-contract).
