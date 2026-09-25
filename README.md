# Cogita

Local chat and an OpenAI-compatible model service. One ModelManager serves chat, titles, Knowledge and external inference. The Python package remains `ai_workbench`.
Prompt Personas and an optional bounded tool harness support ordinary/group conversations. Local models run in managed llama-server/Python workers outside the API process; external connections use the OpenAI-compatible protocol.

The project is in testing, without users or user data. It does not provide an autonomous coding agent, extension/plugin discovery, model downloads or image generation. The external API stays single-key and localhost-only.

## Start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+ or 22.12+ with npm and development dependencies:

```powershell
uv sync
Push-Location frontend
npm ci --include=dev
npm run build
Pop-Location
uv run python scripts/run_app.py --no-open
```

Open <http://127.0.0.1:8765>; use `--port 8766` if occupied. Windows `start.bat` and Linux/macOS `bash start.sh` open the built app.
For development, start the API with `--port 8000`, then run `npm run dev` in frontend. Vite serves <http://127.0.0.1:5173> with its API/WebSocket proxy.

See the [run guide](README_RUN.md) for launchers and portable packaging.

## Configure models

In **Settings > Models**, use the Model profiles, Providers, Local Runtime and External API sidebar pages:

1. **Local Runtime:** install the shared Windows x64 release once. Place model files manually under data/models, then select Local Runtime in a model. Its reference/architecture selects the engine; release policy defaults to manual.
2. **Providers:** add an OpenAI-compatible URL, optional key and queue/timeout settings, then select it and enter the model ID in a profile. Optional discovery supplies suggestions; unavailable or incomplete lists do not block manual IDs.

Profiles have one of six kinds, internal UUIDs, public aliases, capabilities and parameters; unbound drafts can be saved but cannot execute.
Choose default chat and optional auxiliary models. New sessions select the default or first enabled LLM; changing defaults preserves sessions.
Titles use only the auxiliary model and remain unchanged when it is missing or fails.

| Kind | Local inventory root | Local execution |
| --- | --- | --- |
| llm | data/models/llms | llama-server GGUF or Windows Transformers |
| embedding | data/models/embeddings | Native Sentence Transformers, Windows CUDA or CPU; external providers also supported |
| reranker | data/models/rerankers | Deferred |
| image_embedding | data/models/image_embeddings | SigLIP image/text towers, Windows CUDA or CPU |
| vision | data/models/vision | WD14-family ONNX CPU |
| tts | data/models/tts | Kokoro ONNX CPU or Chatterbox/Qwen3-TTS Base Windows Audio |

Inventory references are relative to data/models, such as `llms/example.gguf`; Transformers uses a model directory.
Enable Vision for image input. GGUF also requires its matching mmproj_ref; suggestions appear in the editor.
Chat accepts static PNG/JPEG/WebP through file selection, paste and drag/drop; selected historical images support follow-ups.
Local `/v1` images require inline data URLs and detail=auto, with a 32 MiB complete-request limit.
Provider image URLs/options pass through. Kokoro uses the [ONNX speech layout](#offline-kokoro-speech).

The [runtime catalog](docs/contracts/models.md#managed-catalog-and-installation) describes the shared Python environment and both native llama-server builds.
Execution options select CPU or NVIDIA CUDA; capable engines default to CUDA, Kokoro/WD14 to CPU. GGUF CUDA defaults to automatic GPU layers; manual layers are available.
CUDA requires a usable NVIDIA device; GGUF must confirm positive offload. Local Runtime provides installation/repair/uninstall, jobs/logs and cache prune/clean.
Storage deduplicates hard links; exclusive size estimates recovery. Cache cleanup preserves installations; download settings never fetch model weights.
Load/health/reference preparation checks entry/model availability without environment/cache scans. [Models](docs/contracts/models.md#managed-processes-and-workers) owns correlated host/worker timing.
Repair rebuilds dependencies; source-only worker updates reuse installation after reload/restart.

Local models expose health/load/unload. Providers start unknown, then ready/failed after inference with retry allowed; discovery/cancellation preserve availability. Default queues allow concurrency 1, 32 waiting requests and a 30-second timeout.

## Chat and tools

Personas own identity, avatar, mandatory system prompt and Knowledge/Worldbook bindings. New sessions start with Chat; added members support group transcripts, with one selected speaker per reply.
Sessions own model, context, generation and Harness settings, plus additions to the speaker's fixed resources; clearing additions preserves Persona bindings.

Chat supports Core Memory, Worldbook and Knowledge text/file/attachment sources, chunking and vector/keyword retrieval.
Embedding changes require reindexing; unavailable optional reranking intentionally preserves RRF order.

Harness defaults off; enable it and choose tools in session settings to permit native model calls.
New sessions select all current tools; toggling Harness preserves choices. Built-ins are read_file, web_search,
fetch_url, knowledge_search, base64_encode and base64_decode. File/network calls require approval every time;
waiting survives restart, blocks other input and resumes through approval, rejection or cancellation.

Direct calls use **Settings > Tools** or a registered slash tool. Enabled `/base64_encode hello` returns `aGVsbG8=`
without a model summary/title. Multi-parameter tools need JSON, such as `/read_file {"path":"data/knowledge/note.txt"}`.
Unknown `/...`, `@...` and `:...` prefixes are ordinary text; results render as data.
[Harness/tools](docs/contracts/harness-tools.md) owns limits and APIs.

Each run has one reply, collapsed processing history and final answer. Expand its time row for reasoning/commands,
then commands for arguments/results. **Show full processing history** opens active processing by default;
completed processing stays collapsed and approvals visible. Cancellation/failure preserves incomplete output.
Delete/retry affects the whole reply; retry replaces later conversation. [Chat](docs/contracts/chat-context.md#messages-and-attachments)
owns reply content; [runs/streaming](docs/contracts/runs-streaming.md#run-lifecycle) owns processing visibility/time.

## External API

In **Models > External API**, configure a key and enable the service. Mark LLM/embedding/TTS/vision/image_embedding profiles externally visible.
Requests use public aliases. The service defaults disabled, accepts loopback clients only and shares inference/lifecycle with internal callers
without writing chat or Knowledge records. It forwards tool definitions/calls and never executes tools.

The examples below are PowerShell. Set the key and aliases to your configuration:

```powershell
$apiBase = 'http://127.0.0.1:8765/v1'
$headers = @{ Authorization = 'Bearer YOUR_LOCAL_KEY' }
Invoke-RestMethod "$apiBase/models" -Headers $headers

$chatBody = @{
  model = 'chat-model'
  messages = @(@{ role = 'user'; content = 'Hello' })
} | ConvertTo-Json -Depth 10
Invoke-RestMethod "$apiBase/chat/completions" -Method Post -Headers $headers -ContentType 'application/json' -Body $chatBody

$embeddingBody = @{ model = 'embedding-model'; input = @('First text', 'Second text') } | ConvertTo-Json
Invoke-RestMethod "$apiBase/embeddings" -Method Post -Headers $headers -ContentType 'application/json' -Body $embeddingBody
```

For SSE with curl (use `curl.exe` on Windows):

```shell
curl -N http://127.0.0.1:8765/v1/chat/completions \
  -H 'Authorization: Bearer YOUR_LOCAL_KEY' -H 'Content-Type: application/json' \
  -d '{"model":"chat-model","messages":[{"role":"user","content":"Hello"}],"stream":true,"stream_options":{"include_usage":true}}'
```

Chat accepts the documented OpenAI subset, including n=1, tools, user image_url and supported response_format capabilities.
Embeddings accept strings/string arrays, float/base64, dimensions and purpose=query|document (default document).
Unsupported fields/capabilities and unavailable models produce explicit errors without substitution.
[Models](docs/contracts/models.md#external-inference-api) owns request rules;
[runs/streaming](docs/contracts/runs-streaming.md#external-sse) owns SSE behavior.
Public rerank and image generation remain [future design records](docs/FUTURE_MODEL_SERVICES.md).

### Offline text embeddings

Place a complete Sentence Transformers directory under data/models/embeddings, including modules.json and module configurations/weights.
Create a Text embedding profile, select its directory and review automatic processing information. Use **Local Runtime > Repair** if the installation lacks Sentence Transformers 6.1.0.
Defaults are CUDA/checkpoint dtype, four threads, batch one and manual release; CPU uses float32. Declared query/document prompt templates are selectable under advanced settings.
Harrier-oss-v1-0.6b resolves 1024 dimensions, last-token pooling, L2 normalization and 32768 tokens; queries use web_search_query and documents no prompt.
Missing/unsupported semantics permit saving but prevent loading. Local dimensions must match native output. Model files are never hashed.
Select this profile in Knowledge or use `/v1/embeddings`; set purpose=query for retrieval queries. Model replacement requires unload/reload and reindexing.
[Models](docs/contracts/models.md#local-text-embeddings) owns semantics and Harrier-only real-model acceptance; other checkpoints need representative acceptance.

### Offline WD14 image tagging

Place a WD14-family model.onnx and selected_tags.csv under data/models/vision/<directory>.
Create a Vision profile with Local Runtime and that relative reference; CPU/four threads and manual release are defaults.
Only file existence/path containment is checked; config.json, model hashes, revisions and fixed dimensions/tag counts are not required.
Enable external visibility and use the Cogita extension `POST /v1/images/tags`; discovery supports `GET /v1/models?kind=vision`.

```powershell
$image = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path './image.png')))
$tagBody = @{ model = 'wd14-local'; images = @("data:image/png;base64,$image")
  thresholds = @{ general = 0.35; character = 0.85 } } | ConvertTo-Json -Depth 4
Invoke-RestMethod "$apiBase/images/tags" -Method Post -Headers $headers -ContentType 'application/json' -Body $tagBody
```

Supply 1..16 static PNG/JPEG/WebP data URLs; no URLs, paths or attachments. Omitted/null thresholds inherit the profile;
finite values in [0,1], including zero, override it. Incoming and normalized private JSON are limited to 32 MiB
plus max_request_mb; decoded/square-padded images are limited to 64 million pixels. Each indexed data item contains
original general/character tags and scores in descending order; empty lists are valid and failures reject the whole batch.
Usage is reserved internally and omitted publicly. [Models](docs/contracts/models.md#wd14-image-tagging) owns the full contract.
Windows x64 CPU is supported; wd-swinv2-tagger-v3 is verified. Other family checkpoints need acceptance; video/frames are excluded.

### Offline SigLIP image and text embeddings

Place a standard local SigLIP-family Transformers directory under data/models/image_embeddings, with config.json,
preprocessor_config.json, tokenizer.json/tokenizer_config.json and complete single-file or indexed-shard safetensors weights.
Create an Image embedding profile with Local Runtime; selecting its directory automatically displays declared structure/dimensions and processing settings.
Unknown information stays pending until load; inspection errors do not block drafts. No manual architecture or dimension setting is required.
CUDA/FP16, four threads, batch size one and manual release are defaults; CPU/FP32 is available but has no real-inference acceptance.
The unload-other-tower switch defaults on: image calls stop the text tower and text calls stop the image tower before loading.
Turning it off allows both to remain resident; calls still run serially. Menus provide tower load/log actions and whole-profile unload.

```powershell
$siglipBody = @{ model = 'siglip-local'; input_type = 'text'; input = @('A red car', 'A blue sky') } | ConvertTo-Json
Invoke-RestMethod "$apiBase/images/embeddings" -Method Post -Headers $headers -ContentType 'application/json' -Body $siglipBody
# For images, use input_type='image' with input="data:image/png;base64,$image" from the example above.
```

Inputs are one string or 1..16 strings of a single modality. Images use static inline PNG/JPEG/WebP, 64 million actual pixels and 32 MiB request limits.
Responses include native dimensions, unit vectors, model_revision and vector_space_id; encoding_format=base64 returns little-endian float32.
Both towers share identity; SHA-256 identifies consumed files without preset hash/size comparisons. Files stay unchanged until whole-profile release.
NaFlex has CUDA API acceptance; FixRes has automated tests only. [Models](docs/contracts/models.md#siglip-image-and-text-embeddings) owns queue/error and acceptance limits.
Image indexing, remote providers and usage/timing collection remain deferred.

### Offline Kokoro Speech

Place the Kokoro v1.0 FP32 ONNX model, config/tokenizer JSON files and
`voices/<id>.bin` under `data/models/tts/Kokoro-82M-onnx`. The fixed catalog has
54 voices; extra files are ignored and missing/invalid voices are unavailable.
Manually unpack the en_core_web_sm 3.7.1 pipeline into `data/models/_auxiliary/en_core_web_sm`, with meta.json, config.cfg,
tokenizer, tok2vec/, tagger/ and vocab/ directly inside it. Missing/corrupt resources fail loading without downloads,
shared-environment changes or blocking installation/other engines.

Install the local runtime under Models > Local Runtime, then create a TTS model with
architecture Kokoro and reference `tts/Kokoro-82M-onnx`. Its ONNX execution stays
on CPU; language processors and MP3 encoding use the shared environment.

```powershell
Invoke-RestMethod "$apiBase/audio/voices?model=kokoro" -Headers $headers
$speechBody = @{ model = 'kokoro'; input = 'Hello, this is a voice test.';
  voice = 'af_heart'; response_format = 'wav'; speed = 1.0 } | ConvertTo-Json
Invoke-WebRequest "$apiBase/audio/speech" -Method Post -Headers $headers `
  -ContentType 'application/json' -Body $speechBody -OutFile speech.wav
```

Use `response_format=mp3` for MP3 (the default). The response is a complete audio
file; no chat or attachment record is created. `tts.language`, when supplied,
must match the voice. SSE and application playback are deferred.
`GET /v1/audio/voices` is a Cogita extension; source=preset selects Kokoro voices.

### Offline Chatterbox Speech

On Windows x64, install the local runtime in Models > Local Runtime. Place the English ve.safetensors,
t3_cfg.safetensors, s3gen.safetensors and tokenizer.json under `data/models/tts/chatterbox`.
Create a Chatterbox profile for `tts/chatterbox`, choose CPU/CUDA and set generation defaults; preset voices are unavailable.

Upload one WAV/MP3 reference (8 MiB, at most 30 decoded seconds) through the API:

```powershell
$voice = Invoke-RestMethod "$apiBase/audio/voice-references" -Method Post -Headers $headers `
  -Form @{ model = 'chatterbox'; file = Get-Item './reference.wav' }
$speechBody = @{ model = 'chatterbox'; input = 'Hello from my local voice.';
  voice = $voice.voice_id; response_format = 'wav';
  tts = @{ model_options = @{ seed = 12345 } } } | ConvertTo-Json -Depth 5
Invoke-WebRequest "$apiBase/audio/speech" -Method Post -Headers $headers `
  -ContentType 'application/json' -Body $speechBody -OutFile speech.wav
Invoke-RestMethod "$apiBase/audio/voice-references/$($voice.voice_id)" -Method Delete -Headers $headers
```

Temporary IDs bind to the key/profile, start with 30 minutes and gain at least 15 remaining minutes on admission.
Listing does not renew them. For one request, omit voice and send `tts.reference_audio={format,data_base64}`.
`tts.language` accepts only en-US; `tts.model_options` overrides defaults. See [reference limits](docs/contracts/models.md#audio-tts-and-temporary-references).

### Offline Qwen3-TTS Base Speech

Install the Windows local runtime, select **Qwen3-TTS (12Hz Base)**
and explicit CPU/CUDA execution. Place the complete checkpoint, including generation config,
text-tokenizer files and nested speech_tokenizer, under data/models/tts. The validated reference is
`tts/Qwen3-TTS-12Hz-0.6B-Base`; other sizes are unverified. CustomVoice/VoiceDesign and Linux remain deferred.

Qwen shares Chatterbox's reference APIs/TTL. Optional reference_text in the upload form or
tts.reference_audio enables full conditioning; absence uses speaker-embedding cloning.
Supply the recording's actual words; the service does not transcribe or persist transcripts.

```powershell
$voice = Invoke-RestMethod "$apiBase/audio/voice-references" -Method Post -Headers $headers `
  -Form @{ model = 'qwen'; file = Get-Item './reference.wav'; reference_text = 'Hello, this is a voice test.' }
$speechBody = @{ model = 'qwen'; input = 'Hello from Qwen.'; voice = $voice.voice_id;
  tts = @{ language = 'en-US'; model_options = @{ max_new_tokens = 2048; seed = 12345 } } } | ConvertTo-Json -Depth 5
Invoke-WebRequest "$apiBase/audio/speech" -Method Post -Headers $headers `
  -ContentType 'application/json' -Body $speechBody -OutFile speech.mp3
```

Language omission/auto selects automatically; ten languages exclude Hindi. Token limits can stop speech early.
Qwen has no presets; temporary voices have language=null. Both Audio architectures support optional seed=0..4294967295:
0 is valid; omitted/null request seeds inherit the profile, whose blank/null default leaves randomness unfixed.
Fixed seeds control randomness without guaranteeing identical audio. The editor/OpenAPI describe all controls.

## HTTP contract

OpenAPI 3.1 describes `/api` and `/v1` at [/openapi.json](http://127.0.0.1:8765/openapi.json), with interactive [/docs](http://127.0.0.1:8765/docs)
and [/redoc](http://127.0.0.1:8765/redoc). [Models](docs/contracts/models.md#external-inference-api) owns response validation and sanitization;
[runs/streaming](docs/contracts/runs-streaming.md) owns WebSockets.

```powershell
uv run python scripts/openapi.py check
uv run python scripts/openapi.py export --output build/openapi.json
```

Both commands use temporary directories/memory stores without real database/model/service access. Routes/Pydantic generate deterministic UTF-8 exports; frontend clients retain their types.
Checks enforce route/schema coverage, response validation, unique operationIds and scoped JSON exceptions. Tests validate JSON/SSE; domain validators own cross-field/saved-state rules.

## Settings and storage

Settings shares the home sidebar: three groups, six menus and 11 pages, with subpage URLs surviving refresh/back/forward.
The [settings contract](docs/contracts/settings.md) owns APIs, fields and key PATCH semantics; keys remain unencrypted locally and absent from reads. Logs omit credentials and request/model content.

Pet position, dragging and task-state foundations remain for a future UI; existing Pet files are retained without loading or serving them.

Alembic alone manages SQLite: empty databases upgrade to head; nonempty unversioned databases and destructive downgrades are rejected.
Revisions may reset disposable records but never delete model files, attachments, runtimes or other data directories.
[Data layout](docs/DATA_LAYOUT.md#database-revisions) owns revision/reset effects. The database defaults to data/cogita.db;
COGITA_DATABASE_URL overrides it. See [data layout](docs/DATA_LAYOUT.md) and [.env.example](.env.example) for paths and maintenance.

## Verification

```powershell
uv run pytest -q # Only when backend code changes
uv run python -m compileall -q ai_workbench
uv run python scripts/openapi.py check
uv run python scripts/check_docs_size.py
uv run python scripts/audit_workspace.py --check
Push-Location frontend
npm test
npm run build
Pop-Location
git diff --check
```

Backend tests use temporary roots, mock providers and loopback HTTP/SSE/WS; frontend tests cover domain payloads, settings, translation, streams/events and workflows. Installation/real-model/browser acceptance remains separate.

After a build, `npm run test:browser` checks bilingual desktop/touch home and settings layouts, grouped navigation/history, retained drafts, overlays, chat, images, controls, fonts and domain workflows.
For a focused layout check, use `npm run test:browser -- app-layout.spec.ts settings-layout.spec.ts`.
Install Chromium once with `npx playwright install chromium`. Tests use an isolated fixture server on port 18767 (override COGITA_BROWSER_PORT); screenshots/traces go to frontend/test-results.

Local-runtime smokes reuse installation and fail if repair is needed. Scripts offering --install-only install/confirm a release without inference; other scripts never install.
For offline runtime preparation, stop Cogita and wait for its workers to exit. Apply the pinned Transformers patch and one incremental bytecode pass using the installed interpreter, without installation or Repair:

```powershell
$runtimePython = (Resolve-Path 'data/runtimes/local/1.0.0/env/python.exe').Path
$sitePackages = Join-Path (Split-Path $runtimePython) 'Lib/site-packages'
& $runtimePython -I -B -X utf8 ai_workbench/workers/patch_transformers.py
if ($LASTEXITCODE -ne 0) { throw 'Runtime patch failed.' }
& $runtimePython -I -B -X utf8 -m compileall -q -j 4 -o 0 --invalidation-mode timestamp -e $sitePackages $sitePackages
if ($LASTEXITCODE -ne 0) { throw 'Runtime bytecode preparation failed.' }
```

Restore the previous Cogita launch after successful verification. `-B` suppresses incidental import-cache writes; explicit compileall still writes its caches. No cache clearing or forced recompilation is needed.
Kokoro uses manually placed files and writes all-voice offline/SDK samples under build/tts-smoke:

```powershell
uv run python -m scripts.smoke_tts_runtime --install-only
uv run --with openai --with miniaudio python -m scripts.smoke_tts_runtime
```

Installation uses bundled uv; run it before the temporary SDK environment. `--voice af_heart` selects one voice.
The smoke isolates caches, decodes both formats and checks worker termination on disconnect, reload and another SDK request.
WD14 CPU: `uv run python -m scripts.smoke_wd14_runtime --model-ref vision/wd-swinv2-tagger-v3`.
SigLIP routine CUDA: `uv run python -m scripts.smoke_siglip_runtime --model-ref image_embeddings/<directory>`.
Both require supplied directories and reuse installation. WD14 checks tagging API/lifecycle; the default SigLIP smoke checks image→text→image, reuse and unload.
Add SigLIP `--native-reference` to compare standalone towers with native FP16 CUDA outputs. Reports go to build/wd14-smoke or build/siglip-smoke.
SigLIP `--full-lifecycle` includes 20 switches and 10 dual-resident pairs and requires an explicit user request; exclude it from routine regression, CI and default acceptance. `--case switching|residency|cancellation|faults|identity|release` narrows that opt-in matrix; each run saves a separate lifecycle report, including failures.
[Models](docs/contracts/models.md#siglip-image-and-text-embeddings) owns acceptance limits. Bilingual desktop/touch settings: `npm run test:browser -- siglip.spec.ts wd14.spec.ts text-embeddings.spec.ts model-sources.spec.ts` in frontend.

Text embedding CUDA: `uv run python -m scripts.smoke_text_embedding_runtime --model-ref embeddings/harrier-oss-v1-0.6b --native-reference --expected-dimensions 1024`.
Run the same command with `--device cpu` and without `--native-reference` for short-text CPU inference/release. An explicit model reference is required; installation is reused.
CUDA runs native/application processes sequentially, comparing query/document float/base64 vectors, mixed lengths, retrieval and unload/reload.
BF16 acceptance requires cosine >=0.9998 and maximum absolute error <=0.005; reports go to build/text-embedding-smoke. No model hashes are calculated.

Routine Windows Audio acceptance uses supplied Chatterbox, Qwen3-TTS and Whisper models:
`uv run python -m scripts.smoke_audio_runtime --reference ./reference.wav --reference-text "Words in the recording"`.
Use mono PCM16 24 kHz speech, stop Cogita first, and provide enough RAM/VRAM. CUDA is the default.
The CUDA cases cover offline loading, MP3/WAV, Qwen cloning modes/languages, seed PCM comparisons, references, cancellation/isolation
and Whisper's 30-second boundary. `--engine chatterbox|qwen3tts|whisper` narrows engines; reports/samples go to build/audio-smoke; Linux is rejected.
Use `--device cpu` only for affected changes under the [acceptance policy](AGENTS.md#runtime-verification-and-acceptance); Kokoro remains CPU.
Rebuild patched wheels with `uv run python scripts/build_runtime_wheels.py`.
Run `data/runtimes/local/1.0.0/env/python.exe -I -B scripts/check_qwen_rope.py` for Qwen checkpoint/RoPE regression.

For Windows CUDA with an existing GGUF, run `uv run --no-sync python -m scripts.smoke_cuda_runtime --model-ref llms/<existing-model>.gguf`.
It requires --model-ref unless --install-only is explicit; it exercises auto/manual load, chat, streaming and unload
with temporary model profiles. Runtime installation/jobs remain persisted.
Stop Cogita before real-model checks and record hardware/runtime/model; deterministic tests do not establish runtime compatibility.
`uv run python -m scripts.smoke_llm_runtime --engine transformers` checks CPU/CUDA, streaming, tools and cancellation;
use --engine llama-server for GGUF. Add --vision for image-only/multiple images, historical follow-up, stream and cancellation checks.
GGUF vision also needs `--mmproj-ref llms/Qwen3.5-0.8B-GGUF/mmproj-F16.gguf`; Qwen3.5-0.8B files are the validated reference.
Image answers check fixture colors/order; reports go to build/llm-smoke. smoke_model_loading writes build/model-loading-smoke and defaults to LLM CPU/CUDA/Kokoro CPU; Audio CPU needs --backend chatterbox-cpu or --backend qwen3tts-cpu.

Before changing code, read [AI context](docs/AI_CONTEXT.md), the owning contract and relevant source/tests.
[Documentation maintenance](docs/ai/DOCS_MAINTENANCE.md) defines English-only documentation and active-plan completion rules.
