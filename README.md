# Agent Workbench

A local chat workbench and OpenAI-compatible model service. One ModelManager
serves chat, auxiliary titles, Knowledge retrieval and external inference.
Prompt Personas and an optional bounded tool harness support ordinary and group
conversations. Local models run in managed llama-server/Python workers outside
the API process, or through an external OpenAI-compatible connection.

The project is in testing, without users or user data. It does not provide an
autonomous coding agent, extension/plugin discovery, model downloads or image
generation. The external API stays single-key and localhost-only.

## Start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+
or 22.12+ with npm. From a source checkout:

```powershell
uv sync
Push-Location frontend
npm ci
npm run build
Pop-Location
uv run python scripts/run_app.py --no-open
```

Open <http://127.0.0.1:8765>. Use `--port 8766` when that port is occupied.
Windows `start.bat` and Linux/macOS `bash start.sh` open the built application.
For development, start the API with `--port 8000`, then run `npm run dev` in
frontend. Vite serves <http://127.0.0.1:5173> with its API/WebSocket proxy.

See the [run guide](README_RUN.md) for launchers and portable packaging.

## Configure models

In **Settings > Models**, choose one backend:

1. **External connection:** add an OpenAI-compatible base URL, optional key and
   queue/timeout settings under Connections. Create a profile with the exact
   model reference advertised by that connection.
2. **Managed runtime:** install a supported runtime under Runtimes, place
   model weights manually under data/models, then create a managed profile with
   that runtime, variant and inventory reference.

Each profile has one of six kinds, an internal UUID, a unique public alias,
capabilities, parameters and lifecycle settings. Choose the default chat model
and optionally a separate auxiliary model. New sessions select and save that
default, or the first enabled LLM when it is unavailable. Both chat selectors
show concrete models; changing the default preserves existing session selections.
Titles use only the auxiliary
selection and remain unchanged when it is missing or fails.

| Kind | Local inventory root | Managed backend |
| --- | --- | --- |
| llm | data/models/llms | llama-server GGUF or Windows Transformers |
| embedding | data/models/embeddings | Infinity pending; external embeddings remain available |
| reranker | data/models/rerankers | Infinity pending |
| image_embedding | data/models/image_embeddings | Infinity pending |
| vision | data/models/vision | WD14 entry retained; ONNX integration pending |
| tts | data/models/tts | Kokoro ONNX CPU or English Chatterbox Windows Audio |

Inventory returns references relative to data/models, for example
`llms/example.gguf`. Native Transformers checkpoints use the managed
`python-worker/transformers-cuda` runtime and may explicitly select CPU execution;
the supplied validation model is `llms/Qwen3.5-0.8B-TF`. WD14 uses model.onnx plus
selected_tags.csv. Kokoro uses the
[ONNX speech layout](#offline-kokoro-speech). Image input to chat requires an external
vision-capable LLM; managed llama projector support is not implemented.

The [runtime catalog](docs/contracts/models.md#managed-catalog-and-installation)
lists supported CPU and Windows CUDA variants and platform limits. CUDA defaults
to automatic GPU layers with a fixed context floor; manual layers are available.
Loading requires a usable NVIDIA device and confirmed positive GPU offload.
Install/cancel/retry/uninstall, job progress and bounded logs are available in
Runtimes, alongside storage accounting and manual cache prune/clean. Shared hard
links are deduplicated; the displayed cleanup estimate is exclusive logical size,
not an exact disk-space promise. Clear cache preserves installed environments.
Download settings
configure runtime dependencies and artifact proxies only. No model weights are
downloaded. See [models](docs/contracts/models.md) for engine and platform limits.

Release defaults to manual. External health/load verifies the advertised model,
but standard OpenAI-compatible connections cannot report weight residency or
unload; the UI shows unknown residency and disables unload. Provider queues
default to concurrency 1, 32 waiting requests and 30-second queue timeout.

## Chat and tools

Personas own identity, avatar, prompt and Knowledge/Worldbook bindings.
Their nonempty system prompt is always included. New sessions start with Chat. Add members and
select the current speaker for group transcript conversations; each input
generates one selected speaker's reply. Sessions own model, context, generation
and Harness configuration. The current speaker's resources are always bound;
sessions may add resources. Clearing additions preserves Persona bindings.

Core Memory, Worldbook and Knowledge remain available in ordinary chat.
Knowledge supports text/file/attachment sources, chunking, vector/keyword
retrieval and optional reranking. Changing embedding configuration requires
reindexing. Unavailable reranking intentionally preserves RRF order.

Harness defaults off. Enable it in session settings and use the tool switches
to permit native model calls. New sessions select all current tools; disabling
and re-enabling Harness preserves those choices. Built-ins are read_file, web_search, fetch_url,
knowledge_search, base64_encode and base64_decode. File/network calls require
approval every time; waiting survives restart and resumes through explicit
approval, rejection or cancellation. Other input is blocked while waiting.

Direct calls use **Settings > Tools** or a registered slash tool. For example,
`/base64_encode hello` returns `aGVsbG8=` when that tool is enabled, without
a model summary or title. Multi-parameter tools require a JSON object, such as
`/read_file {"path":"data/knowledge/note.txt"}`. Unknown `/...`, `@...` and `:...`
prefixes are ordinary text. Tool results are rendered as data.
See [harness/tools](docs/contracts/harness-tools.md) for limits and APIs.

Each run appears as one reply with a collapsed processing history and its final
answer. Expand its time row to inspect reasoning and grouped commands, then expand
a command for arguments/results. General's **Show full processing history** opens
active processing by default; completed processing is collapsed in either mode.
Approvals remain visible. Cancellation/failure preserves incomplete output.
Delete/retry applies to the whole reply; retry replaces its later conversation.
The [chat contract](docs/contracts/chat-context.md#messages-and-attachments)
defines reply content; [runs/streaming](docs/contracts/runs-streaming.md#run-lifecycle)
defines processing visibility and elapsed time.

## External API

In **Models > External service**, configure a key and enable the service. Mark
LLM/embedding/TTS profiles externally visible. Requests use public aliases, not
internal UUIDs. The service is disabled by default, accepts loopback clients
only, and shares inference/lifecycle with internal callers without writing chat
or Knowledge records. It forwards tool definitions/calls and never executes tools.

The examples below are PowerShell. Set the key and aliases to your configuration:

```powershell
$apiBase = 'http://127.0.0.1:8765/v1'
$headers = @{ Authorization = 'Bearer YOUR_LOCAL_KEY' }
Invoke-RestMethod "$apiBase/models" -Headers $headers

$chatBody = @{
  model = 'chat-model'
  messages = @(@{ role = 'user'; content = 'Hello' })
} | ConvertTo-Json -Depth 10
Invoke-RestMethod "$apiBase/chat/completions" -Method Post -Headers $headers `
  -ContentType 'application/json' -Body $chatBody

$embeddingBody = @{ model = 'embedding-model'; input = @('First text', 'Second text') } | ConvertTo-Json
Invoke-RestMethod "$apiBase/embeddings" -Method Post -Headers $headers `
  -ContentType 'application/json' -Body $embeddingBody
```

For SSE with curl (use `curl.exe` on Windows):

```shell
curl -N http://127.0.0.1:8765/v1/chat/completions \
  -H 'Authorization: Bearer YOUR_LOCAL_KEY' -H 'Content-Type: application/json' \
  -d '{"model":"chat-model","messages":[{"role":"user","content":"Hello"}],"stream":true,"stream_options":{"include_usage":true}}'
```

Chat accepts the documented OpenAI subset, including n=1, function tool data,
user image_url parts and supported response_format capabilities. Embeddings
accept strings/string arrays with float or base64 output. Unsupported fields,
capabilities and unavailable models produce explicit errors without substitution.
[Models](docs/contracts/models.md#external-inference-api) owns request rules;
[runs/streaming](docs/contracts/runs-streaming.md#external-sse) owns SSE behavior.
Public rerank and image generation remain [future design records](docs/FUTURE_MODEL_SERVICES.md).

### Offline Kokoro Speech

Place the Kokoro v1.0 FP32 ONNX model, config/tokenizer JSON files and
`voices/<id>.bin` under `data/models/tts/Kokoro-82M-onnx`. The fixed catalog has
54 voices; extra files are ignored and missing/invalid voices are unavailable.
Place the supplied `en_core_web_sm-any-py3-none-any.whl` (model version 3.7.1)
under `data/models/_auxiliary/en_core_web_sm`. The installer validates its checksum
and installs it locally. Model weights and language models are never downloaded.

Install **python-worker / onnx-cpu** in Models > Runtimes, then create a TTS
profile with architecture Kokoro and model reference `tts/Kokoro-82M-onnx`.
The separate CPU environment includes language processors and MP3 encoding,
without PyTorch or Transformers. First load and synthesis work offline.

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
`GET /v1/audio/voices` is a Workbench extension; source=preset selects Kokoro voices.
OpenAI SDK speech calls use the standard fields.

### Offline Chatterbox Speech

On Windows x64, install **python-worker / audio-cuda** in Models > Runtimes.
Place the English ve.safetensors, t3_cfg.safetensors, s3gen.safetensors and
tokenizer.json files under `data/models/tts/chatterbox`. Create a TTS profile
using PyTorch Audio, model reference `tts/chatterbox`, and explicit CPU or NVIDIA
CUDA execution. Chatterbox has generation defaults in the editor and no preset voices.

Upload one WAV/MP3 reference (8 MiB, at most 30 decoded seconds) through the API:

```powershell
$voice = Invoke-RestMethod "$apiBase/audio/voice-references" -Method Post -Headers $headers `
  -Form @{ model = 'chatterbox'; file = Get-Item './reference.wav' }
$speechBody = @{ model = 'chatterbox'; input = 'Hello from my local voice.';
  voice = $voice.voice_id; response_format = 'wav' } | ConvertTo-Json
Invoke-WebRequest "$apiBase/audio/speech" -Method Post -Headers $headers `
  -ContentType 'application/json' -Body $speechBody -OutFile speech.wav
Invoke-RestMethod "$apiBase/audio/voice-references/$($voice.voice_id)" -Method Delete -Headers $headers
```

Temporary IDs are scoped to the key/profile, start with 30 minutes and gain at
least 15 remaining minutes when admitted for speech. Listing does not renew them.
Alternatively, omit voice and send `tts.reference_audio={format,data_base64}` for
one request. `tts.language` only accepts en-US; `tts.model_options` overrides
Chatterbox defaults. See [reference ownership and limits](docs/contracts/models.md#chatterbox-and-temporary-references).
Qwen3-TTS/Whisper are package acceptance engines; public APIs and Linux Audio are deferred.

## HTTP contract

All `/api` and `/v1` HTTP operations are described by OpenAPI 3.1 at
[/openapi.json](http://127.0.0.1:8765/openapi.json), with interactive documentation
at [/docs](http://127.0.0.1:8765/docs) and [/redoc](http://127.0.0.1:8765/redoc).
Ordinary JSON responses are validated at runtime. Public schemas omit keys,
private run snapshots and runtime log paths. Response validation failures return
a sanitized `500 INTERNAL_ERROR`. WebSocket behavior remains in the streaming contract.

```powershell
uv run python scripts/openapi.py check
uv run python scripts/openapi.py export --output build/openapi.json
```

Both commands use the application factory with temporary directories and memory
stores, without opening the real database, loading models or calling services.
Export is deterministic UTF-8 JSON. The generated file is a build artifact;
routes and Pydantic models remain its source, and frontend clients retain their
existing types. The check validates every HTTP operation against actual routes,
request/response schemas, runtime response validation, unique operationIds and
field-specific JSON exceptions. Missing coverage, unconstrained bodies and stale
exceptions fail the gate. Tests also validate actual JSON responses and SSE
frames against the served schema. Cross-field and saved-state checks remain
domain validators; OpenAPI does not replace them.

## Settings and storage

The six settings entries are General, Models, Personas, Knowledge, Worldbook
and Tools. Each has one owner; [settings](docs/contracts/settings.md) lists
APIs, editable fields and key omission/clearing semantics. Keys are omitted from
management reads but remain unencrypted in local storage. Logs omit credentials
and request/model content.

The previous Codex Pet and package import are removed. Position settings,
dragging and task-state interfaces remain for a future Pet; existing Pet files
are retained without loading or serving them.

Alembic alone manages SQLite. Empty databases upgrade to head;
nonempty unversioned databases are rejected and destructive downgrade is unsupported.
Revisions may reset disposable test records. The current schema revision and
individual reset effects are documented in [data layout](docs/DATA_LAYOUT.md#database-revisions).

Model files, attachments, runtimes and other data directories are never deleted
by schema revisions. The default database is data/agent_workbench.db;
AGENT_WORKBENCH_DATABASE_URL overrides it. See [data layout](docs/DATA_LAYOUT.md)
and [.env.example](.env.example) for paths and explicit maintenance commands.

## Verification

```powershell
uv run pytest -q
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

Backend tests use temporary roots, mock providers and real loopback HTTP/SSE/WS
transport. Frontend tests cover API payloads, settings, translation, streaming,
Persona/session isolation, model/runtime events, tool approval and Pet foundations.
Runtime installation and real-model/browser smoke checks are reported separately
from deterministic tests. Frontend source is organized by domain types/API,
explicit store actions and focused view components.

Browser checks for chat, runtime maintenance and resource management run with
`npm run test:browser` in frontend after a build. Install Chromium once with
`npx playwright install chromium`. Tests start and stop an isolated fixture
server on port 18767; WORKBENCH_BROWSER_PORT can select a free port. Screenshots
and failure traces are under frontend/test-results.

Explicit Kokoro installation and all-voice offline/SDK smoke checks use manually
placed files and write generated samples under build/tts-smoke:

```powershell
uv run python -m scripts.smoke_tts_runtime --install-only
uv run --with openai --with miniaudio python -m scripts.smoke_tts_runtime
```

Installation uses the application's bundled uv; run its command before the
temporary SDK environment. `--voice af_heart` limits the smoke test to one voice.
The smoke test isolates caches, decodes both formats and checks actual worker
termination on HTTP disconnect, followed by reload and another SDK request.

Windows Audio acceptance uses supplied Chatterbox, Qwen3-TTS and Whisper models:
`uv run python -m scripts.smoke_audio_runtime --reference ./reference.wav`.
Use a mono PCM16 24 kHz speech reference, stop Workbench first, and provide enough
RAM/VRAM. The command installs/verifies the pinned package, then checks both CPU
and CUDA, offline loading, MP3/WAV, references, cancellation/isolation and Whisper's
30-second boundary. `--install-only`, `--skip-install`, `--device cpu|cuda` and
`--engine chatterbox|qwen3tts|whisper` select stages. Reports/samples go to
build/audio-smoke; Linux is rejected. Rebuild the metadata-patched wheel with
`uv run python scripts/build_audio_wheel.py`; dependency upgrades require the full matrix.

For an explicit Windows CUDA installation/GPU check using a manually placed
GGUF, run `uv run --no-sync python -m
scripts.smoke_cuda_runtime --model-ref llms/<existing-model>.gguf`. This installs
CUDA if needed and exercises auto/manual load, chat, streaming and unload using
temporary in-memory model profiles; runtime installation/jobs remain persisted.
Stop Workbench before running this explicit smoke command. Record the hardware,
runtime version and model with its results; deterministic tests do not establish
real-provider behavior or cross-platform runtime compatibility.

Before changing code, read [AI context](docs/AI_CONTEXT.md), the owning contract
and relevant source/tests. [Documentation maintenance](docs/ai/DOCS_MAINTENANCE.md)
defines English-only documentation and active-plan completion rules.
