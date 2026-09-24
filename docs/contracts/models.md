# Models contract

ChatRunner, Utility LLM, Knowledge and `/v1` share `core/models/ModelManager` without HTTP loopback.
The API process imports no torch, transformers, onnxruntime or llama.cpp binding.

## Profiles and sources

`model_profiles` has six immutable kinds: llm, embedding, reranker, image_embedding, vision and tts.
References use UUID ids internally and unique lowercase aliases externally. CRUD: `/api/models/profiles`, with `?kind=...`.
`provider_profiles` stores name, enablement, connection and timestamps; connections own URL/key, timeouts and queue limits.
Only OpenAI-compatible is supported. CRUD: `/api/models/providers`; optional discovery: `/{id}/models`.
GET/PATCH `/api/models/local-runtime/settings` owns enabled/download in appmetadatarecord.local_runtime_settings; enabled defaults true, identity/name are fixed.

Model source is a strict nullable union:
- null: a saveable unbound draft; execution returns MODEL_NOT_CONFIGURED before admission/transport.
- {type: provider, provider_profile_id}: provider LLM/text-embedding only.
- {type: local, execution_options, lifecycle}: local LLM/TTS/WD14 only; engine defaults populate omitted local fields.

Profiles own model_ref, capabilities, parameters, enabled and external_enabled. PATCH omission preserves source; null unbinds;
a supplied source replaces it. Removed fields/combinations, busy connection edits and referenced provider deletion fail; edits invalidate clients/status.
[Settings](settings.md#model-settings) owns secrets/PATCH semantics; [Knowledge](knowledge.md) owns index invalidation.

## Resolution and capabilities

New sessions save the enabled default LLM or first enabled LLM (name/id order); execution uses that selection.
Missing configuration returns MODEL_NOT_CONFIGURED; disabled/missing/wrong-kind selections fail without substitution.
Default selection and `/api/health/details` are cached, degraded without an enabled LLM; [chat/context](chat-context.md) owns Persona/session/title selection.
LLM parameters are temperature, top_p, max_tokens, presence/frequency penalties, seed and stop;
explicit request values override defaults. Capabilities are streaming, tools, vision, json_object and json_schema.
Providers execute chat/text embeddings, llama-server/Transformers chat, ONNX Kokoro/WD14 and Audio Chatterbox/Qwen3-TTS Base.
Vision-capable LLMs accept chat images through providers, GGUF and Transformers.
Local embedding/rerank and complete image-embedding integration remain pending; rerank/image-embedding profiles stay unbound.

## Lifecycle and status

Queues are namespaced by source; provider/local defaults are concurrency 1, 32 waiting slots and 30-second queue timeout.
Provider limits/discovery share one provider queue; overflow/timeout returns MODEL_BUSY. Cancellation/stream closure releases occupancy.
Provider aliases share status/occupancy by provider id and model_ref. GGUF aliases share normalized
main-model/projector paths and device, process and identical options. Transformers share by path/options; Kokoro shares an engine queue.
Audio and WD14 profiles have separate processes, queues and cancellation scopes, even for the same path.
Local models load automatically with manual release by default, or after_request/idle (300 seconds).
An enabled manual alias retains shared weights; otherwise the longest idle timeout wins. Release errors preserve successful inference.
Local process crashes require explicit load; provider failures permit another request.

| Operation | Endpoint under `/api/models` | Effect |
| --- | --- | --- |
| Cached status | GET `/profiles/{id}/status` | No transport call |
| Local health/load/unload | POST `/profiles/{id}/{health,load,unload}` | Local lifecycle; provider bindings return 422 UNSUPPORTED_CAPABILITY |
| Provider discovery | GET `/providers/{id}/models` | Optional queued list; never an inference preflight |
| Local inventory | GET `/inventory?kind=...` | Relative file references only |
| Directory information | GET `/inspect?kind=image_embedding&model_ref=...` | SigLIP metadata, independent of installation |

Inventory/status never load weights, import heavy runtimes or download models. Roots under data/models are
llms, embeddings, rerankers, image_embeddings, vision and tts; inventory recognizes GGUF/model directories, Kokoro, WD14 and Audio.
Qwen3-TTS 12Hz Base needs checkpoint/generation config and text/nested speech tokenizers; unsupported types fail before imports; auxiliary resources/tokenizers are excluded.
Status has state (unknown/ready/unavailable/failed/unloaded), residency, unload_supported, active, queued and error_code.
Providers start unknown; inference sets ready/clears errors or failed on upstream errors; discovery, validation, queue rejection/cancellation preserve availability.
Manual IDs need not appear in discovery; runtime=null, residency=unknown, unloading unsupported.
Local status adds engine, version, installation/process state, latest job id and device_name; CUDA counts clear on stop.
[runs/streaming](runs-streaming.md) owns source metadata and events. Local process logs reject provider bindings without transport.

## Managed catalog and installation

`GET /api/models/local-runtime/catalog` exposes one Windows x64 release (1.0.0), engines and strict option schemas.
Linux and local embedding/rerank/image-embedding remain deferred;
see [future services](../FUTURE_MODEL_SERVICES.md#local-engine-and-platform-expansion).

GGUF selects llama-server, LLM directories select Transformers, TTS architecture selects Kokoro/Chatterbox/Qwen3-TTS Base, vision selects WD14.
model_ref is a safe relative path under data/models. Profiles cannot supply executables/arguments and may be saved before installation.
source.execution_options selects CPU or CUDA; capable engines default to CUDA, Kokoro/WD14 to
CPU only. Llama accepts threads, context_size, batch_size, nullable mmproj_ref and gpu_layers
(0 on CPU; auto or integer 1..999 on CUDA). Python options are intraop_threads=4;
Kokoro/WD14 add max_batch_size=1. Unavailable CUDA fails without CPU substitution.
GGUF vision requires a safe relative mmproj_ref under data/models; text-only profiles require null.
Inventory returns same-directory mmproj_refs candidates. CPU disables projector GPU offload; CUDA uses the main model's device.

GET `/api/models/local-runtime` returns installation; POST `/install`, `/repair` or `/uninstall` returns a RuntimeJob.
One installation/cache task runs application-wide. Installation changes require idle local requests, block admission and stop local processes;
cache cleanup preserves loaded models. File operations run off-loop; provider inference and model queues remain independent.

Downloads stage under data/runtimes/.staging/{job_id}, then promote to local/<version> with env/, native/cpu/ and native/cuda/.
installation.json records Python/CPU/CUDA entry paths and dependency identity, bound by manifest_sha256. Identity covers platform/architecture,
pinned Python, package pins/hashes and native hashes; formatting/order, comments, workers, release labels and download metadata do not affect it.
Startup, reads, repeat install and process entry resolution check metadata schema/digest/dependencies and entry containment/existence,
without environment scans or engine/GPU probes; other dependency edits remain undetected. Availability reads preserve job state;
restored files/dependencies recover on refresh/restart. Failed/interrupted jobs and old manifests require explicit repair, without data conversion/reset.
Paths use the recorded version. Finalizing validates/promotes entries; healthy install returns already_installed, while repair always rebuilds.

Bundled uv installs pinned Python 3.12.11 and one hash lock: Torch/Torchaudio 2.11.0+cu128,
Torchvision 0.26.0+cu128, Transformers 5.16.1, NumPy 1.26.4, ONNX Runtime 1.23.2 and Misaki/spaCy/Thinc dependencies.
scripts/build_runtime_wheels.py reproduces Chatterbox metadata, Qwen source/metadata and Misaki offline-input patches with embedded records.
Only docopt, jieba, unidic-lite, antlr4-python3-runtime and sox allow source builds with locked tools; native packages require wheels.
Installation checks dependencies, five isolated offline engine imports and native programs without weights/GPU; user PATH/registry stay untouched.
[Settings](settings.md) owns download configuration.

Both llama.cpp b10809 CPU/CUDA programs are included; CUDA's pinned main/cudart ZIPs use combined byte progress.
Native archives are SHA-256 checked before extraction and on reuse from .cache/workbench-artifacts.
Llama's CUDA 12.4 DLLs stay beside its executable, separate from Torch CUDA 12.8; different-content DLL collisions fail.
Native --version checks precede promotion; dependency paths apply only to child processes.

Jobs expose state, stage, byte progress, error code, revision and bounded logs. Cancellation stops subprocesses and awaits file operations
before clearing staging; restart interrupts unfinished jobs and clears staging. Failed/cancelled logs persist; retries create jobs.
Uninstall stops workers and removes the recorded installation, retaining caches/models. Under `/api/models/local-runtime`, GET `/jobs`,
`/jobs/{id}` and `/jobs/{id}/log` expose history/details/logs; POST `/jobs/{id}/cancel` cancels. `/api/models/profiles/{id}/log` returns process logs.
Runtime/job/storage responses have no provider reference. Responses omit absolute paths, ports, tokens and raw provider errors.
Failures use RUNTIME_NOT_INSTALLED, RUNTIME_INSTALLING, RUNTIME_BROKEN, RUNTIME_UNSUPPORTED, RUNTIME_DEVICE_UNAVAILABLE,
MODEL_NOT_FOUND, MODEL_BUSY or MODEL_UNAVAILABLE.

## Storage and cache maintenance

GET `/api/models/local-runtime/storage` scans metadata off-loop, returning scanned_at, complete, totals, groups, warnings and skipped_links.
Groups cover installations, shared Python, cache, staging, process and other files under data/runtimes; links/junctions are not followed.
Usage is file_count, logical_bytes, unique_bytes, shared_bytes and exclusive_bytes. File identities deduplicate hard links;
exclusive size excludes outside links and totals deduplicate independently. Logical sizes omit compression/copy-on-write, never predicting disk recovery.
Unreadable/changing metadata yields incomplete groups/totals and null unknown values; reads never load models.
POST `/api/models/local-runtime/cache/cleanup` accepts mode=prune|clean and returns 202/RuntimeJob. Bundled uv uses explicit .cache,
--no-config and normal locking; redirected roots/escaping links fail. Models remain loaded; occupancy failures retain retry diagnostics.
Cache jobs use operation=cache_prune|cache_clean, version=null and optional result.before/after storage snapshots (null when unavailable);
installation jobs require a version. Shared job/log/cancel routes/events leave installation state untouched; partial cleanup may survive failure/cancellation.
Startup interrupts unfinished jobs; 20 terminal cache logs are retained independently.

## Managed processes and workers

Workers publish readiness atomically on loopback. Process groups/Windows kill-on-job-close Job Objects stop full trees on unload, cancellation or exit.
Sanitized logs in `data/logs/runtimes` have a 10 MiB cap; retention keeps 20 terminal task and process/load-attempt logs per runtime, plus active logs.
Load/health/Audio references check installation entries; loaded inference/status use cached availability. Workers execute application sources
in the installed interpreter: reload picks up changes without reinstalling; source failures affect model loading, not installation validity.
Model logs expose the latest attempt, including pre-spawn failures; UTC records share load_id through startup environment/private headers.
`duration_ms`/`elapsed_ms` measure monotonic wall time; `cpu_duration_ms`/`cpu_elapsed_ms` count all threads in the emitter, excluding children.
CPU time includes concurrent work, can exceed wall time and is not I/O time. Totals include queueing/cleanup, end before inference; overlapping stages must not be summed.
Host stages cover entry/resources, CUDA probe, spawn/readiness, load RPC and advertisement; workers time imports, device, processor/model and post-load setup.
Import stages separate Transformers symbols/serving and Kokoro libraries; Kokoro also times resources, ONNX and language build/warmup.
Imports include transitive/cache effects. Reuse/outcomes are logged without content/credentials; logging failures are nonfatal.
Llama/Transformers use private-key OpenAI health/models/chat with model-advertisement checks; ONNX/Audio use private-token RPC.
Audio reference validation needs no weights; stdlib validation precedes engine imports.
Llama CUDA selects the first enumerated device with split-mode=none; none returns RUNTIME_DEVICE_UNAVAILABLE.
Auto uses gpu-layers=auto, fit=on, a 1024 MiB margin and fit-ctx=context_size; manual uses fit=off.
Logs must confirm positive GPU offload; missing/zero layers or insufficient memory stop loading without CPU substitution.
Cached reads do not probe GPUs. Workers enforce offline/local-only loading without remote code or device substitution.
Transformers uses float32 CPU/checkpoint dtype CUDA, disables upstream idle release and stops its process before releasing cancelled occupancy;
llama-server cancels only the request. Tools require a supported response template and Harness. Native AutoModel/AutoProcessor/chat templates
process images; readiness reports vision capability. JSON output, nonzero presence/frequency penalties and explicit tool controls fail.
Audio blocks Python networking; Chatterbox uses from_local with float32/attention adaptations, Qwen uses float32 CPU/bfloat16 CUDA and SDPA.
Whisper is private acceptance only: decoded samples before resampling/features must fit 30 seconds inclusive; no truncation, segmentation or partial transcripts.

## WD14 image tagging

Vision uses architecture=wd14, task=tags and thresholds={general:0.35, character:0.85}; vision.batch_size is removed.
Manual directories under data/models/vision require only model.onnx and selected_tags.csv. Inventory/status/load checks
confirm existence and path containment, never model hashes, sizes, revisions, config, metadata or fixed dimensions/tag counts.
Normal worker loading reads CSV order/categories and actual ONNX input/output names and spatial dimensions; errors fail loading/inference.
ModelManager.vision accepts a strict VisionRequest and validates the entire batch off-loop before queueing/loading.
POST /v1/images/tags accepts model alias, images (1..16 inline base64 static PNG/JPEG/WebP data URLs) and optional thresholds.
Remote URLs, paths, attachments and animations are unsupported. Omitted/null thresholds or members inherit the profile;
explicit values must be finite numbers in [0,1], including zero. Overrides leave saved defaults unchanged.
Incoming HTTP and original/normalized private JSON bodies are limited to 32 MiB, in addition to max_request_mb; decoded and
square-padded image areas are at most 64 million pixels. Decode/EXIF orientation/white alpha compositing produce RGB PNG.
The worker centers each image on a white square, resizes bicubically to the model dimensions and uses NHWC BGR float32 0..255.
One CPU ONNX Session executes batch one sequentially within the request's lease. CSV/output mapping must match exactly;
ratings are excluded, all general/character scores meeting thresholds are returned, sorted descending with CSV tie order.
Responses are {object:list, model, data:[{object:image.tags, index, tags:[{name,category,score}]}]}; indices match input order.
Names remain unchanged; empty tags are valid. Any failure rejects the entire synchronous batch; there is no partial result or SSE.
VisionResult has strict outputs and nullable InferenceUsage: input_images/input_tokens/output_tokens/total_tokens are reserved nonnegative integers.
Counts remain unset and usage is omitted publicly; no collection/persistence or LLM usage changes.
WD14 lazily initializes in the shared ONNX control server, independently of Kokoro language resources, with Python networking blocked.
Cancellation stops its worker before queue release; manual/after_request/idle release and explicit crash recovery follow the shared lifecycle.
Support is Windows x64 CPU; wd-swinv2-tagger-v3 is the verified checkpoint. Other WD14-family checkpoints need their own acceptance.
Video, frame sampling and aggregation are excluded; no tagging page, chat integration or Harness tool is implemented.

## SigLIP single-tower foundations

GET `/api/models/inspect` requires kind=image_embedding and a safe relative model_ref. It reads only config.json,
preprocessor_config.json and tokenizer_config.json, without installation, weights, hashing, inference imports or GPU probes.
It returns declared image/text dimensions, processor/text settings and diagnostics; absent/invalid fields stay null.
model_type=siglip2 identifies NaFlex; siglip identifies a FixRes-compatible structure, without proving training generation.
Missing directories return 404; unsafe/escaping paths return 422. Missing/corrupt/unknown configurations retain partial information and allow unbound drafts.

`core/models/siglip.py` provides SiglipModelUse.prepare and SiglipTowerClient independently of ModelManager binding.
Preparation computes `model_revision=sha256:<hex>` off-loop once per use object, over a version marker and sorted, length-framed relative names/content.
It covers the selected complete dual-tower safetensors (single file or indexed shards), index, model/processor/tokenizer configuration,
tokenizer.json and consumed optional token maps. README, model-ready.json, unused files and absolute paths are excluded.
This identifies actual bytes; there are no preset hashes/sizes, per-file verification manifests or tensor-key checks.
Both towers share the prepared object. Keep files immutable during its lifetime; after whole-model release prepare a new object to recompute identity.

Each client owns one fixed image/text worker with private-token health/embed RPC (1..16 inputs), process-tree cleanup and bounded logs.
Close/cancel stops that process; callers own serialization and release. Options default to CUDA, four threads and batch size one (1..16).
CUDA uses FP16, CPU FP32, without device substitution. Only the target Siglip/Siglip2 VisionModel or TextModel is instantiated from local safetensors.
PIL processors use model settings; tokenizer.json loads directly without conversion, new dependencies or remote code.
Static inline PNG/JPEG/WebP use shared EXIF/white/RGB normalization, a 32 MiB body limit and 64 million actual pixels; WD14 retains square-area limits.
Text pads/truncates to the native text configuration's position limit, preserves special tokens and applies declared lowercase; no instructions or translation.
pooler_output becomes float32 L2-normalized vectors in input order. The process boundary checks count, dimensions and finite nonzero values.
Results include vectors, dimensions, model_revision, vector_space_id and tower/device/dtype metadata; InferenceUsage and InferenceTiming remain null.
vector_space_id includes revision, pipeline/library versions, effective preprocessing/tokenization, native dimensions, pooling and normalization, excluding tower/device/residency.
No usage/timing collection, persistence, profile binding, tower switching, settings UI, public embeddings or image indexing is implemented.
NaFlex siglip2-so400m-patch16-naflex has CUDA/native-reference acceptance; FixRes has automated tests only and CPU has no real-inference compatibility claim.

## Kokoro TTS

Kokoro uses CPU ONNX, architecture=kokoro, v1.0 FP32 model.onnx, config/tokenizer JSON and voices/<id>.bin.
The 54-ID catalog intersects with finite float32 [510,1,256] files; extras such as af.bin are ignored.
No voice-profile records are created; off-loop file checks power GET /api/models/profiles/{id}/voices without loading weights.

The shared environment supplies Misaki, spaCy 3.7.5, NumPy 1.26.4, eSpeak NG and
UniDic. Kokoro loads the manually supplied en_core_web_sm 3.7.1 pipeline directory
under data/models/_auxiliary/en_core_web_sm and passes it explicitly to Misaki.
All language frontends initialize before readiness with Python networking blocked.
Missing/corrupt language resources fail Kokoro loading without downloading files,
changing the shared environment or preventing other engines from running.

Speech accepts 1..4096 nonblank characters, voice, speed=0.25..4,
response_format=mp3|wav, stream_format=audio and optional tts.language matching the
voice. Request values override profile speed=1 and format=mp3. Other fields fail.
Chunks retain supported text, use at most 510 tokens and voice row N-1; unsplit
oversized words fail. Complete 24 kHz mono PCM16 WAV or 128 kbps MP3 is returned;
PCM/encoded data each have a 32 MiB limit; timeout is 300 seconds. Disconnects stop
workers before releasing occupancy and log REQUEST_CANCELLED with 499.
SSE, provider TTS and playback are unimplemented. Local execution supports Windows x64 only.

## Audio TTS and temporary references

English Chatterbox (architecture=chatterbox) uses the Audio worker and Kokoro's text/speed/format/size/timeout contract.
Local files: ve.safetensors, t3_cfg.safetensors, s3gen.safetensors, tokenizer.json; tts.language accepts only en-US.
Profile defaults and tts.model_options accept exaggeration=0.5 [0,2], cfg_weight=0.5 [0,1], temperature=0.8 (0,5],
repetition_penalty=1.2 [1,2], min_p=0.05 [0,1], top_p=1 (0,1]. Chatterbox has no presets.

Qwen3-TTS 12Hz Base (architecture=qwen3tts) shares the Audio output contract.
Main defaults: do_sample=true, temperature=0.9, top_p=1, top_k=50, repetition_penalty=1.05, max_new_tokens=2048.
Temperature/penalty are finite and positive; top_p is (0,1], top_k is an integer >=0, max_new_tokens is 1..8192.
Input is passed whole; the token cap may stop speech early. Secondary-codebook sampling stays enabled at temperature=0.9, top_p=1, top_k=50.
Strict architecture-specific profile/request schemas reject other-architecture options before staging/admission.
Omitted/null request options inherit the profile. OpenAPI describes defaults, meanings and restrictions.
Both Audio architectures accept seed=null or a strict integer 0..4294967295 in profiles and tts.model_options.
Profile seed defaults to null (unfixed); 0 is valid. Seeded requests scope and restore Python/NumPy/PyTorch CPU/current-CUDA
random states across conditioning, all chunks and encoding, including errors. Unfixed requests advance normally; identical audio is not guaranteed.
Qwen accepts en-US/en-GB (English), zh-CN, ja-JP, ko-KR, de-DE, fr-FR, ru-RU,
pt-BR, es-ES and it-IT; omission/null/auto selects Auto. Hindi is unsupported.
Base has no presets; English/Chinese 0.6B Base is verified on CPU/CUDA. Other sizes are unverified; CustomVoice/VoiceDesign are deferred.
Automatic transcripts can be ambiguous for short Chinese clones; pronunciation fidelity still needs listening review.

Chatterbox/Qwen require exactly one temporary voice ID or tts.reference_audio={format=wav|mp3,data_base64}.
Multipart uploads contain model alias and one file; responses contain voice_id, model, source=temporary and expires_at.
Before synthesis, both validate 8 MiB encoded/32 MiB decoded, 1/2 channels, 8..192 kHz and at most 30 seconds.
Uploaded names never choose storage paths.
One-request files are removed on completion/cancellation. Kokoro rejects references and model_options.
Qwen accepts optional reference_text (1..4096 nonblank characters) in uploads/inline references: absence uses speaker embeddings, presence audio/transcript conditioning.
Transcripts stay in reference memory until cleanup, are never returned/logged, and are not generated by ASR.

References bind to the key, profile/reference, local source, engine, execution options and release version.
Release policies and generation parameters, including seed, do not define identity; clients sharing the key share access.
Creation grants 30 minutes; valid execution/queue admission atomically applies max(expires_at, now+15 minutes).
Overflow, discovery and pre-admission rejection do not renew. Expired IDs cannot reactivate.
Active/queued requests pin files through completion/cancellation; deleting an unexpired active ID returns 409.
Key replacement, service/profile disablement, profile removal/binding changes and restart invalidate IDs; access/release/restart trigger cleanup.
Limits are 64 files/128 MiB per service, including one-request files. [Data layout](../DATA_LAYOUT.md) owns storage; no attachment, voice-profile or database records are created.

## External inference API

The service defaults disabled and requires loopback clients plus one key via `Authorization: Bearer <key>` or `x-api-key`.
Conflicting credentials fail. Address checks ignore forwarded headers; the launcher binds loopback.

| Endpoint | Supported operation |
| --- | --- |
| GET `/v1/models` | Enabled public llm/embedding/tts/vision aliases; optional kind filter, no weight loading |
| POST `/v1/chat/completions` | Non-streaming or SSE chat |
| POST `/v1/embeddings` | Text embeddings |
| POST `/v1/images/tags` | Static WD14 image tagging (Workbench extension) |
| POST `/v1/audio/speech` | Complete MP3/WAV speech |
| GET `/v1/audio/voices` | Preset/temporary voice discovery (Workbench extension) |
| POST `/v1/audio/voice-references` | Upload a temporary Chatterbox/Qwen Base reference |
| DELETE `/v1/audio/voice-references/{voice_id}` | Delete an unused reference |

Public aliases must be enabled, visible and match endpoint kind/capabilities; stateless calls create no session/message/run/attachment/Knowledge rows.
Content-Length/received bytes obey max_request_mb; strict schemas reject unsupported fields without echoing values.
Responses include X-Request-Id; logs record outcome/time without keys, prompts, content or raw provider errors.
Voice discovery accepts optional model/source=preset|temporary and returns id, model, source, language (null for Qwen) and expires_at (null for presets).
Only enabled public TTS profiles, valid preset files and the current key's unexpired references appear.

Chat accepts system/developer/user/assistant/tool roles, text, user image_url parts, function tools,
tool_choice, parallel_tool_calls, response_format and generation parameters. Only n=1 is accepted.
Formats are text/json_object/json_schema with matching capabilities. Tool results must match preceding calls;
unknown fields, unsupported formats and incomplete histories fail. `/v1` forwards tools; [Harness](harness-tools.md) executes them.
Provider image URLs/details pass through. Local images require inline data URLs and detail=auto; other values return UNSUPPORTED_CAPABILITY.
Local input supports static PNG/JPEG/WebP. ModelManager uses Pillow off-loop to decode, apply EXIF orientation,
fill transparency white and convert to RGB PNG; original attachments stay unchanged. Invalid images return INVALID_IMAGE.
The complete local JSON body, including defaults and converted image data, is limited to 32 MiB before admission;
REQUEST_TOO_LARGE is explicit. External requests also obey max_request_mb. Qwen3.5-0.8B GGUF/Transformers CPU/CUDA
acceptance covers image content, multiple-image order, historical follow-up, streaming and cancellation; other checkpoints are unverified.

Non-streaming tool-only content=null; [runs/streaming](runs-streaming.md#external-sse) owns SSE framing, error timing and disconnect cleanup.

Assistant messages/deltas accept string reasoning_content, including native tool
continuations; other roles reject it. `/v1` forwards literal content/reasoning without
interpreting <think> markers. ChatRunner/Harness normalize reasoning for the UI.

Embeddings accept a string/nonempty string array, float/base64 (little-endian float32) and optional dimensions.
Document instructions, batching, dimension checks and normalization match Knowledge indexing; queries use query instruction.
Public rerank and image generation are deferred; see [future services](../FUTURE_MODEL_SERVICES.md).

OpenAPI 3.1 covers management and `/v1`; [check/export commands](../../README.md#http-contract) verify schemas and JSON/SSE/audio responses.
Reads omit keys, manifest hashes and log paths; invalid results become sanitized 500 INTERNAL_ERROR. Omission/null and timestamp precision survive.
