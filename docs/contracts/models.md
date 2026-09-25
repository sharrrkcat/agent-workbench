# Models contract

ChatRunner, Utility LLM, Knowledge and `/v1` share `core/models/ModelManager` without HTTP loopback or API-process inference imports.

## Profiles and sources

`model_profiles` has immutable llm/embedding/reranker/image_embedding/vision/tts kinds, internal UUIDs and unique lowercase public aliases; CRUD: `/api/models/profiles?kind=...`.
`provider_profiles` owns name, enablement, timestamps and OpenAI-compatible URL/key, timeouts and queue limits; CRUD: `/api/models/providers`, optional discovery: `/{id}/models`.
GET/PATCH `/api/models/local-runtime/settings` owns enabled/download in appmetadatarecord.local_runtime_settings; enabled defaults true, identity/name are fixed.

Model source is a strict nullable union:
- null: a saveable unbound draft; execution returns MODEL_NOT_CONFIGURED before admission/transport.
- {type: provider, provider_profile_id}: provider LLM/text-embedding only.
- {type: local, execution_options, lifecycle}: local LLM/TTS/WD14/SigLIP/text embedding/reranker; engine defaults populate omitted local fields.

Profiles own model_ref, capabilities, parameters, enabled and external_enabled. PATCH preserves omitted source, null unbinds, supplied source replaces; edits invalidate clients/status. Invalid combinations, busy edits and referenced provider deletion fail.
[Settings](settings.md#model-settings) owns secrets/PATCH semantics; [Knowledge](knowledge.md) owns index invalidation.

## Resolution and capabilities

New sessions save the enabled default LLM or first enabled LLM (name/id order). Missing configuration returns MODEL_NOT_CONFIGURED; unavailable/wrong-kind selections fail without substitution.
Default selection and `/api/health/details` are cached, degraded without an enabled LLM; [chat/context](chat-context.md) owns Persona/session/title selection.
LLM parameters: temperature, top_p, max_tokens, presence/frequency penalties, seed, stop; requests override defaults. Capabilities: streaming, tools, vision, json_object, json_schema.
Providers execute chat/text embeddings; local engines provide chat, TTS, tagging, Sentence Transformers embeddings/reranking and SigLIP vectors. Vision-capable LLMs accept images through providers, GGUF and Transformers.

## Lifecycle and status

Source queues default to concurrency 1, 32 waiting slots and 30-second timeout; provider discovery shares its queue. Overflow/timeout returns MODEL_BUSY; cancellation/stream closure releases occupancy.
Provider aliases share status/occupancy by provider id and model_ref. GGUF shares normalized model/projector paths, device, process and identical options; Transformers shares path/options, Kokoro an engine queue.
Audio, WD14, SigLIP, text embedding and reranker profiles have separate processes, queues and cancellation scopes, even for the same path.
Local models autoload with manual release by default, or after_request/idle (300 seconds). Enabled manual aliases retain shared weights; otherwise the longest idle timeout wins.
Release errors preserve successful inference. Local crashes require explicit load; provider failures permit another request.

| Operation | Endpoint under `/api/models` | Effect |
| --- | --- | --- |
| Cached status | GET `/profiles/{id}/status` | No transport call |
| Local health/load/unload | POST `/profiles/{id}/{health,load,unload}` | Local lifecycle; provider bindings return 422 UNSUPPORTED_CAPABILITY |
| Provider discovery | GET `/providers/{id}/models` | Optional queued list; never an inference preflight |
| Local inventory | GET `/inventory?kind=...` | Relative file references only |
| Directory information | GET `/inspect?kind=embedding\|image_embedding\|reranker&model_ref=...` | Configuration metadata, independent of installation |

Inventory/status never load weights, import heavy runtimes or download models. Roots are data/models/{llms,embeddings,rerankers,image_embeddings,vision,tts}.
Inventory recognizes GGUF/model directories, Kokoro, WD14, Audio, SigLIP, Sentence Transformers embeddings and CrossEncoder roots, excluding their component directories.
Qwen3-TTS 12Hz Base needs checkpoint/generation config and text/nested speech tokenizers; unsupported types fail before imports; auxiliary resources/tokenizers are excluded.
Status has state (unknown/ready/unavailable/failed/unloaded), residency, unload_supported, active, queued and error_code.
Providers start unknown; inference sets ready/clears errors or failed on upstream errors. Discovery/validation/queue rejection/cancellation preserve availability; manual IDs need not appear in discovery. runtime=null, residency=unknown, unloading unsupported.
Local status adds engine, version, installation/process state, latest job id and device_name; CUDA counts clear on stop.
[runs/streaming](runs-streaming.md) owns source metadata and events. Local process logs reject provider bindings without transport.

## Managed catalog and installation

`GET /api/models/local-runtime/catalog` exposes one Windows x64 release (1.0.0), engines and strict option schemas. Linux remains [deferred](../FUTURE_MODEL_SERVICES.md#local-engine-and-platform-expansion).

GGUF selects llama-server, LLM directories select Transformers, TTS architecture selects Kokoro/Chatterbox/Qwen3-TTS Base, vision selects WD14 and local rerankers select cross-encoder.
model_ref is a safe relative path under data/models. Profiles cannot supply executables/arguments and may be saved before installation.
source.execution_options selects CPU or CUDA; capable engines default to CUDA, Kokoro/WD14 to CPU only.
Llama accepts threads, context_size, batch_size, nullable mmproj_ref and gpu_layers (0 on CPU; auto or integer 1..999 on CUDA). Python options are intraop_threads=4;
Kokoro/WD14 add max_batch_size=1; SigLIP/text embeddings/rerankers allow 1..16 (default 1). Unavailable CUDA fails without CPU substitution.
GGUF vision requires a safe relative mmproj_ref; text-only profiles require null. Inventory suggests same-directory projectors; CPU disables projector GPU offload and CUDA uses the main device.

GET `/api/models/local-runtime` returns installation; POST `/install`, `/repair` or `/uninstall` returns a RuntimeJob.
One installation/cache task runs application-wide. Installation changes require idle requests, block local admission and stop workers; cache cleanup preserves loaded models. File work runs off-loop; providers and model queues remain independent.

Downloads stage under data/runtimes/.staging/{job_id}, then promote to local/<version> with env/, native/cpu/ and native/cuda/.
installation.json records Python/CPU/CUDA entries and manifest_sha256-bound identity: platform/architecture, Python, package pins/hashes and native hashes. Formatting/order, comments, workers, release labels and download metadata do not affect identity.
Startup/reads/repeat install/entry resolution check metadata schema/digest/dependencies and entry containment/existence, without environment scans or engine/GPU probes; other dependency edits remain undetected.
Availability reads preserve jobs; restored files/dependencies recover on refresh/restart. Failed/interrupted jobs and old manifests require explicit repair, without conversion/reset.
Paths use the recorded version. Finalizing validates/promotes entries; healthy install returns already_installed, while repair always rebuilds.

Bundled uv installs Python 3.12.11 with one hash lock: Torch/Torchaudio 2.11.0+cu128, Torchvision 0.26.0+cu128,
Transformers 5.16.1, Sentence Transformers 6.1.0, NumPy 1.26.4, ONNX Runtime 1.23.2 and Misaki/spaCy/Thinc. Only docopt, jieba, unidic-lite, antlr4-python3-runtime and sox build from locked sources; native packages require wheels.
scripts/build_runtime_wheels.py reproduces Chatterbox, Qwen and Misaki patches; their +workbench.* versions, hashes, WORKBENCH_PATCH.json and patch payloads are fixed artifact identity, independent of branding.
After dependency checks, a pinned offline source patch defers auto_factory's GenerationMixin import, replacing its file to preserve hard-linked caches; package pins and installation identity stay unchanged.
Python incrementally compiles Lib/site-packages before six isolated offline engine imports and native checks, without weights/GPU. Dependency changes require Repair; source-only preparation follows the [README](../../README.md#verification). User PATH/registry stay untouched; [Settings](settings.md) owns downloads.

Both llama.cpp b10809 CPU/CUDA programs are included; CUDA main/cudart ZIPs share byte progress and archive hash checks before extraction/cache reuse.
Llama CUDA 12.4 DLLs stay beside its executable, separate from Torch CUDA 12.8; different-content collisions fail. Native --version checks precede promotion; dependency paths affect only children.

Jobs expose state, stage, bytes, error, revision and bounded logs. Cancellation stops subprocesses and awaits file work before clearing staging; restart interrupts unfinished jobs/clears staging. Failed/cancelled logs persist; retries create jobs.
Uninstall stops workers/removes the recorded installation, retaining caches/models. Under `/api/models/local-runtime`, GET `/jobs`, `/jobs/{id}`, `/jobs/{id}/log` expose history/details/logs; POST `/jobs/{id}/cancel` cancels. `/api/models/profiles/{id}/log` returns process logs.
Runtime/job/storage responses omit provider references, absolute paths, ports, tokens and raw provider errors; failures use RUNTIME_NOT_INSTALLED, RUNTIME_INSTALLING, RUNTIME_BROKEN, RUNTIME_UNSUPPORTED, RUNTIME_DEVICE_UNAVAILABLE, MODEL_NOT_FOUND, MODEL_BUSY or MODEL_UNAVAILABLE.

## Storage and cache maintenance

GET `/api/models/local-runtime/storage` scans metadata off-loop, returning scanned_at, complete, totals, groups, warnings and skipped_links for installations/shared Python/cache/staging/process/other files under data/runtimes, without following links/junctions.
Usage includes file_count, logical_bytes, unique_bytes, shared_bytes and exclusive_bytes. File identities deduplicate hard links; exclusive size excludes outside links and totals deduplicate independently. Logical sizes omit compression/copy-on-write and do not predict disk recovery.
Unreadable/changing metadata yields incomplete groups/totals and null unknown values; reads never load models.
POST `/api/models/local-runtime/cache/cleanup` accepts mode=prune|clean and returns 202/RuntimeJob. Bundled uv uses explicit .cache,
--no-config and normal locking; redirected roots/escaping links fail. Models remain loaded; occupancy failures retain retry diagnostics.
Cache jobs use operation=cache_prune|cache_clean, version=null and optional result.before/after storage snapshots (null when unavailable);
installation jobs require a version. Shared job/log/cancel routes/events leave installation state untouched; partial cleanup may survive failure/cancellation.
Startup interrupts unfinished jobs; 20 terminal cache logs are retained independently.

## Managed processes and workers

Workers publish readiness atomically on loopback. Process groups/Windows kill-on-job-close Job Objects stop full trees on unload, cancellation or exit.
Sanitized logs in `data/logs/runtimes` have a 10 MiB cap; retention keeps 20 terminal task and process/load-attempt logs per runtime, plus active logs.
Load/health/Audio references check installation entries; loaded inference/status use cached availability. Workers run application sources in the installed interpreter; reload applies source changes without reinstalling, and source failures affect model loading only.
Model logs expose the latest attempt, including pre-spawn failures; UTC records share load_id through COGITA_LOAD_TRACE and the private X-Cogita-Load-Trace header.
`duration_ms`/`elapsed_ms` measure monotonic wall time; `cpu_duration_ms`/`cpu_elapsed_ms` count all threads in the emitter, excluding children.
CPU time includes concurrent work, can exceed wall time and is not I/O time. Totals include queueing/cleanup, end before inference; overlapping stages must not be summed.
Host stages cover entry/resources, CUDA probe, spawn/readiness, load RPC and advertisement; workers time imports, device, processor/model and setup, with separate Transformers symbols/serving and Kokoro libraries/resources/ONNX/language build/warmup.
SigLIP worker startup shares the host load_id and times individual imports, lazy class imports, device checks, processors/tokenizer, processing identity, weights, device transfer and readiness.
Imports include transitive/cache effects. Reuse/outcomes are logged without content/credentials; logging failures are nonfatal.
Llama/Transformers use private-key OpenAI health/models/chat with model-advertisement checks; other workers use private-token RPC. Audio reference validation needs no weights; stdlib validation precedes engine imports.
Llama CUDA selects the first device with split-mode=none; none returns RUNTIME_DEVICE_UNAVAILABLE. Auto uses gpu-layers=auto, fit=on, a 1024 MiB margin and fit-ctx=context_size; manual uses fit=off.
Logs must confirm positive GPU offload; missing/zero layers or insufficient memory stop loading without CPU substitution.
Cached reads do not probe GPUs. Workers enforce offline/local-only loading without remote code or device substitution.
Transformers uses float32 CPU/checkpoint dtype CUDA, disables upstream idle release and stops its process before releasing cancelled occupancy;
llama-server cancels only the request. Tools require a supported response template and Harness. Native AutoModel/AutoProcessor/chat templates
process images; readiness reports vision capability. JSON output, nonzero presence/frequency penalties and explicit tool controls fail.
Audio blocks Python networking; Chatterbox uses from_local with float32/attention adaptations, Qwen uses float32 CPU/bfloat16 CUDA and SDPA.
Whisper is private acceptance only: decoded samples before resampling/features must fit 30 seconds inclusive; no truncation, segmentation or partial transcripts.

## Local text embeddings

Local embedding selects sentence-transformers, using the native ordered pipeline with offline loading and trust_remote_code=False.
Inspect reads configuration JSON only: modules, pooling/prompt inclusion, projection dimensions, normalization, cosine/dot similarity,
effective token limit, declared prompts and diagnostics. The limit respects both backbone and tokenizer constraints.
Required missing/uninterpretable semantics, unknown modules or explicit processing limits beyond native capacity block loading with UNSUPPORTED_CAPABILITY; drafts remain saveable. Automatic mean-pooling construction is prohibited.
Local parameters contain only nullable query_prompt_name/document_prompt_name; null resolves automatically from declared templates.
Query priority is query, web_search_query, then the declared default; otherwise choices need explicit selection. Documents use document, passage, corpus, then the declared default; absent those, no prompt.
Original text/purpose cross the adapter boundary; native processing applies prompts/pooling/normalization once. Providers retain their own parameters.
Defaults are CUDA/checkpoint dtype, four threads, batch one, manual release; CPU uses float32. Batches allow 1..16; startup/inference timeouts are 300 seconds.
Cancellation stops the worker before releasing occupancy. Invalid/nonfinite/zero vectors fail the whole request; dimensions must match native output.
EmbeddingResult carries effective similarity internally; [Knowledge](knowledge.md) uses native cosine/dot and preserves vector normalization.
No inventory/inspection/load/status/acceptance path hashes model files or creates manifests/fingerprints. Files remain immutable while loaded; same-path replacement requires explicit unload/reload and Knowledge reindexing.
Harrier-oss-v1-0.6b is the sole accepted real checkpoint: CUDA/native BF16 comparison, float/base64, mixed lengths, retrieval and reload;
CPU acceptance covers short-text service inference/release. Its configuration resolves 1024 dimensions, lasttoken/L2, 32768 tokens,
web_search_query and no document prompt. These are observations, not model/backbone/dimension allowlists.
Other checkpoints require representative acceptance even when metadata is understood. [README](../../README.md#verification) owns smoke commands and tolerances.

## Local reranking

Local reranker selects cross-encoder and native Sentence Transformers CrossEncoder with offline/local-only loading and trust_remote_code=False.
Directory metadata selects joint-input single-score classification, explicit Transformer/LogitScore or a native scalar projection; no checkpoint/backbone allowlists or inferred causal scoring tokens.
Inspect reports architecture, pipeline, scoring/activation, effective model/tokenizer limit and diagnostics without loading. Missing scoring/templates, custom code, multiclass selection and other architectures block loading; drafts remain saveable.
Parameters are empty; CPU/CUDA precision, threads, batch 1..16 (default 1), manual release and 300-second timeouts follow text embeddings.
Native prompts, templates, tokenization, truncation, scoring and activation run once. One finite score per original document is required; malformed output fails the whole request.
No model file hashes, fingerprints or manifests are created. Same-path replacement requires unload/reload, without rebuilding embedding indexes.
POST `/v1/rerank` accepts model alias, nonblank query, 1..2048 nonblank string documents, nullable positive top_n and return_documents=false.
All inputs are scored before top_n; omitted/null returns all. Response: {model, results:[{index,relevance_score,document?:{text}}]}, descending with original-index ties and original optional text.
Scores retain native semantics, without a universal probability guarantee or fabricated usage. Incoming/private bodies are limited to 32 MiB; public requests also obey max_request_mb.
Public failures are explicit; Knowledge retains RRF fallback. mxbai-rerank-base-v2 has CUDA/native/RAG and short CPU acceptance; other checkpoints/architectures require acceptance/implementation. [README](../../README.md#verification) owns commands and tolerances.

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

## SigLIP image and text embeddings

Image-embedding parameters contain only strict unload_other_tower_on_call=true; architecture, dimensions, normalize and batch_size are removed.
GET `/api/models/inspect?kind=image_embedding&model_ref=...` reads only config.json, preprocessor_config.json and tokenizer_config.json,
without installation, weights, hashing, inference imports or GPU probes. It returns declared dimensions, processor/text settings and diagnostics;
absent/invalid fields stay null. model_type=siglip2 identifies NaFlex; siglip identifies FixRes compatibility without proving training generation.
Missing directories return 404; unsafe/escaping paths return 422. Missing/corrupt/unknown configurations allow partial information and saved drafts.

ModelManager.image_embed(profile_id, ImageEmbeddingRequest) and public calls normalize/validate the whole batch before admission or tower changes.
One SiglipAdapter owns a shared SiglipModelUse and at most two fixed-tower clients. Inference, explicit load and health share one FIFO queue:
concurrency 1, 32 waiting slots, 120-second wait. Startup/inference timeouts are 300 seconds. Profiles sharing paths remain isolated.
With the switch on, the other tower's process tree exits before target reuse/load; off permits both towers to reside, with serial requests and no preloading.
Normal switching retains identity, including the gap with no resident tower. Whole release or loss of the final tower through cancellation/failure clears it.
Waiting cancellation preserves residency. Executing cancellation, timeout or failure cleans the affected tower before queue release, retaining a healthy other tower.
Cancellation permits automatic reloading; a failed tower requires explicit load. Automatic/whole release retains failure markers; healthy towers can still execute.
Manual release is default. after_request releases both after inference and queue drain; idle starts at load/inference completion (default 300 seconds), not health.
Edits, unbinding, disablement, deletion and runtime maintenance require idle queues and release both towers/identity; shutdown stops all processes.
Status/events include image/text process state, residency, failure, active_tower and cached revision/space/dimensions. Reads never hash or load weights.
`POST /profiles/{id}/load` requires {tower:image|text}; health only probes existing towers. `/profiles/{id}/log?tower=...` selects a tower;
other kinds reject tower on load/log. Unload always releases the whole profile. [Settings](settings.md#model-settings) owns the editor and menus.

Preparation hashes once per use object off-loop: model_revision=sha256:<hex> covers the fixed workbench-siglip-model-v1 marker and sorted, length-framed relative names/content.
Inputs are complete selected dual-tower safetensors (single file or indexed shards), index, model/processor/tokenizer configuration, tokenizer.json and consumed token maps.
README, model-ready.json, unused files and absolute paths are excluded. No preset hashes/sizes, per-file verification manifests or tensor-key checks exist.
Both towers share this identity; keep files immutable until whole release. vector_space_id includes revision, pipeline/library versions, effective preprocessing/tokenization,
native dimensions, pooling and normalization; tower/device/residency do not affect it. Tower loading checks shared space/dimension agreement.
Each client uses private-token health/embed RPC, process-tree cleanup and bounded logs. CUDA is FP16 and CPU FP32, with no device substitution.
Only the target Siglip/Siglip2 VisionModel or TextModel loads local safetensors. PIL processors honor model settings; a SigLIP-local tokenizer subclass preserves native from_pretrained handling and loads tokenizer.json directly without the redundant backend deep copy, conversion or remote code.
Text pads/truncates to the native position limit, preserves special tokens and declared lowercase, without instructions/translation. pooler_output becomes float32 L2 unit vectors;
the process boundary checks count, dimensions and finite nonzero values. API preparation and normalization are not repeated in the parent process.
Internal SiglipResult includes vectors, native dimensions, revision/space and tower/device/dtype. InferenceUsage/InferenceTiming remain null;
queue/load-switch/preprocess/inference/total timing and usage are reserved without collection or persistence.

`POST /v1/images/embeddings` accepts model, required input_type=image|text, input (one string or 1..16 strings), encoding_format=float|base64.
Static PNG/JPEG/WebP data URLs use EXIF/white/RGB normalization and 64 million actual pixels; WD14 retains square-area limits. Paths/remote URLs/animations are rejected.
Original and normalized private JSON have a 32 MiB cap; public requests also obey max_request_mb. Token arrays, mixed objects and dimensions/normalization overrides fail.
Response: {object:list, model, input_type, dimensions, model_revision, vector_space_id, data:[{object:embedding,index,embedding}]}.
Base64 is little-endian float32; ordering is preserved and batches succeed or fail whole, without SSE, partial results or public usage/timing.
No image indexes, internal consumer UI or remote image-embedding providers are implemented.
NaFlex siglip2-so400m-patch16-naflex has CUDA/native-reference and short API acceptance. FixRes has automated tests only; CPU has no real-inference compatibility claim.
Extended CUDA switching, dual residency, cancellation/failure recovery, identity and release are verified on that NaFlex checkpoint. The 20-switch/10-pair matrix requires an explicit user request and is excluded from routine regression, CI and default acceptance.

## Kokoro TTS

Kokoro CPU ONNX uses architecture=kokoro, v1.0 FP32 model.onnx, config/tokenizer JSON and voices/<id>.bin. Its 54-ID catalog selects finite float32 [510,1,256] files, ignoring extras such as af.bin.
GET /api/models/profiles/{id}/voices checks files off-loop without loading weights or creating voice records.
The environment supplies Misaki, spaCy 3.7.5, NumPy 1.26.4, eSpeak NG and UniDic; Misaki uses manually supplied en_core_web_sm 3.7.1 at data/models/_auxiliary/en_core_web_sm.
All language frontends initialize offline before readiness. Missing/corrupt resources fail only Kokoro loading, without downloads or environment changes.
Speech accepts 1..4096 nonblank characters, voice, speed=0.25..4, response_format=mp3|wav, stream_format=audio and matching tts.language; requests override speed=1/format=mp3, other fields fail.
Chunks retain supported text, use at most 510 tokens and voice row N-1; oversized unsplit words fail. Output is complete 24 kHz mono PCM16 WAV or 128 kbps MP3, with 32 MiB PCM/encoded limits and 300-second timeout.
Disconnects stop workers before queue release and log REQUEST_CANCELLED/499. Windows x64 only; SSE, provider TTS and playback are unimplemented.

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
Qwen accepts en-US/en-GB (English), zh-CN, ja-JP, ko-KR, de-DE, fr-FR, ru-RU, pt-BR, es-ES and it-IT; omission/null/auto selects Auto. Hindi is unsupported.
Base has no presets; English/Chinese 0.6B Base is verified on CPU/CUDA. Other sizes are unverified; CustomVoice/VoiceDesign are deferred.
Automatic transcripts can be ambiguous for short Chinese clones; pronunciation fidelity still needs listening review.

Chatterbox/Qwen require exactly one temporary voice ID or tts.reference_audio={format=wav|mp3,data_base64}.
Multipart uploads contain model alias and one file; responses contain voice_id, model, source=temporary and expires_at.
Before synthesis, both validate 8 MiB encoded/32 MiB decoded, 1/2 channels, 8..192 kHz and at most 30 seconds. Uploaded names never choose storage paths.
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

The service defaults disabled and requires loopback clients plus one key via `Authorization: Bearer <key>` or `x-api-key`; conflicts fail. Address checks ignore forwarded headers; the launcher binds loopback.

| Endpoint | Supported operation |
| --- | --- |
| GET `/v1/models` | Enabled public model aliases; optional kind filter, no weight loading |
| POST `/v1/chat/completions` | Non-streaming or SSE chat |
| POST `/v1/embeddings` | Text embeddings |
| POST `/v1/rerank` | Native CrossEncoder text-pair scoring (Cogita extension) |
| POST `/v1/images/tags` | Static WD14 image tagging (Cogita extension) |
| POST `/v1/images/embeddings` | SigLIP image/text embeddings (Cogita extension) |
| POST `/v1/audio/speech` | Complete MP3/WAV speech |
| GET `/v1/audio/voices` | Preset/temporary voice discovery (Cogita extension) |
| POST `/v1/audio/voice-references` | Upload a temporary Chatterbox/Qwen Base reference |
| DELETE `/v1/audio/voice-references/{voice_id}` | Delete an unused reference |

Discovery reports owned_by=cogita. Public aliases must be enabled, visible and match endpoint kind/capabilities; stateless calls create no session/message/run/attachment/Knowledge rows.
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

Assistant messages/deltas accept string reasoning_content, including native tool continuations; other roles reject it.
`/v1` forwards literal content/reasoning without interpreting <think> markers. ChatRunner/Harness normalize reasoning for the UI.

Text embeddings accept string/nonempty string arrays, float/base64 (little-endian float32), optional dimensions and purpose=query|document (default document). Local dimensions must be omitted or native (otherwise 422); processing matches Knowledge and disconnects cancel inference.
Other reranker architectures and image generation remain [future services](../FUTURE_MODEL_SERVICES.md).

OpenAPI 3.1 covers management and `/v1`; [check/export commands](../../README.md#http-contract) verify schemas and JSON/SSE/audio responses.
Reads omit keys, manifest hashes and log paths; invalid results become sanitized 500 INTERNAL_ERROR. Omission/null and timestamp precision survive.
