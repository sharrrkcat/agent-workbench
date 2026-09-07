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

The [run guide](README_RUN.md) also covers portable packaging. The builder writes
under build/ and bundles application code, migrations, frontend assets and docs;
it excludes local data, dependencies, credentials and model weights.

## Configure models

In **Settings > Models**, choose one backend:

1. **External connection:** add an OpenAI-compatible base URL, optional key and
   queue/timeout settings under Connections. Create a profile with the exact
   model reference advertised by that connection.
2. **Managed runtime:** install an enabled CPU runtime under Runtimes, place
   model weights manually under data/models, then create a managed profile with
   that runtime, variant and inventory reference.

Each profile has one of five kinds, an internal UUID, a unique public alias,
capabilities, parameters and lifecycle settings. Choose the default chat model
and optionally a separate auxiliary model. New sessions select and save that
default, or the first enabled LLM when it is unavailable. Both chat selectors
show concrete models; changing the default preserves existing session selections.
Titles use only the auxiliary
selection and remain unchanged when it is missing or fails.

| Kind | Local inventory root | Managed backend |
| --- | --- | --- |
| llm | data/models/llms | llama-server, GGUF |
| embedding | data/models/embeddings | Python worker |
| reranker | data/models/rerankers | Python worker |
| image_embedding | data/models/image_embeddings | Python worker |
| vision | data/models/vision | Python worker |

Inventory returns references relative to data/models, for example
`llms/example.gguf`. Python models use native Transformers checkpoints; WD14
uses model.onnx plus selected_tags.csv. Image input to chat requires an external
vision-capable LLM; managed llama projector support is not implemented.

Runtime installation is supported for Windows/Linux x64 CPU variants.
CUDA/Vulkan/GPU worker entries remain unavailable. Install/cancel/retry/uninstall,
job progress and bounded logs are available in Runtimes. Download settings
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

## External API

In **Models > External service**, configure a key and enable the service. Mark
LLM/embedding profiles externally visible. Requests use public aliases, not
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

## Settings and storage

The six settings entries are General, Models, Personas, Knowledge, Worldbook
and Tools. Each has one owner; [settings](docs/contracts/settings.md) lists
APIs, editable fields and key omission/clearing semantics. Keys are omitted from
management reads but remain unencrypted in local storage. Logs omit credentials
and request/model content.

The previous Codex Pet and package import are removed. Position settings,
dragging and task-state interfaces remain for a future Pet; existing Pet files
are retained without loading or serving them.

Alembic alone manages SQLite. Current head is `0009_pet_foundation`. Revision
0008 resets disposable Personas, sessions, their bindings, messages and runs to
the reduced configuration schema. Revision 0009 resets General, Core Memory and
Pet settings. Models, Knowledge, Worldbook and runtime records survive both.
Empty databases upgrade to head;
nonempty unversioned databases are rejected and destructive downgrade is unsupported.

Model files, attachments, runtimes and other data directories are never deleted
by schema revisions. The default database is data/agent_workbench.db;
AGENT_WORKBENCH_DATABASE_URL overrides it. See [data layout](docs/DATA_LAYOUT.md)
and [.env.example](.env.example) for paths and explicit maintenance commands.

## Verification

```powershell
uv run pytest -q
uv run python -m compileall -q ai_workbench
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

Before changing code, read [AI context](docs/AI_CONTEXT.md), the
[current plan](docs/WORKBENCH_SIMPLIFICATION_PLAN.md) and the owning contract.
