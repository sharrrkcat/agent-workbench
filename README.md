# Agent Workbench

A local-first chat workbench and OpenAI-compatible model gateway. Round 3
uses one ModelManager for chat, auxiliary tasks, Knowledge and external
requests, with optional catalog-pinned llama-server and Python worker
backends outside the API process.

## Start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js and npm.

```powershell
uv sync
Push-Location frontend
npm install
npm run build
Pop-Location
uv run python scripts/run_app.py --no-open
```

Open http://127.0.0.1:8765. Use --port 8766 if the port is occupied.
For frontend development, run the API on port 8000 and npm run dev in
frontend; Vite serves http://127.0.0.1:5173 with its API/WS proxy.

## Configure models

In Settings > Models:

1. Add a connection with an OpenAI-compatible API base URL, optional key,
   timeout and queue limits.
2. Add a model profile, choose its kind and connection, and enter the exact
   model reference advertised by the provider. Choose a unique public alias.
3. Set capability flags, generation/per-kind parameters and release policy.
   Health/load checks verify the connection and model.
4. Choose the default chat model and, optionally, a separate auxiliary model.
   A chat session can override the default.

There is one profile store for llm, embedding, reranker, image_embedding and
vision. External connections use the OpenAI-compatible protocol. Managed
profiles select a runtime and variant, while weights remain manual files under
data/models. LLM chat uses llama-server; text embeddings, reranking, image
embeddings and vision use the Python worker. Image input through a
vision-capable external LLM is also supported.

In Settings > Models > Runtimes, install the enabled CPU runtimes, inspect
job progress and logs, cancel or retry tasks, and uninstall a runtime. CUDA,
Vulkan and GPU worker variants are shown as unsupported until enabled for the
platform. Runtime settings configure only HTTPS artifact indexes/proxies;
model weights are never downloaded by the application.

Lifecycle defaults to manual release. External connections cannot report
weight residency or unload through the standard protocol; the UI shows
unknown residency and disables unload. Queue defaults are concurrency 1,
32 waiting requests and a 30-second queue timeout. Multiple aliases for the
same connection/model share occupancy. No model files are downloaded.

## Chat and Knowledge

Ordinary messages follow ChatRunner; registered `/tool_name` inputs invoke
built-in tools directly. Other prefixes such as @chat or :formal remain text.
Session/group transcript context, Memory,
Worldbook and Knowledge injection remain available. Persona defaults and
session overrides are resolved before each chat run; group sessions preserve
speaker metadata and generate one selected speaker response at a time. Enable
Harness in Persona/session settings and select allowed tools for a bounded
model tool loop. Files and network requests require explicit approval;
direct calls in Settings > Tools never trigger a model summary. See the
[harness contract](docs/contracts/harness-tools.md) for tools, limits and APIs.

Chat responses stream over WebSocket with stable message ids and sequenced
deltas. The completed message is authoritative. Title generation uses only
the explicitly selected auxiliary model, after the main model lease releases.
Missing or failed auxiliary configuration leaves the title unchanged.

Knowledge retains direct text/file/attachment sources, chunking, vector/FTS
retrieval, RRF, session bindings and automatic context injection. Embedding
and reranker selectors reference the same Models profiles. Document/query
preprocessing and lifecycle run through the manager. Changing vector
configuration invalidates affected indexes and requires reindexing. When
reranking is unavailable, retrieval keeps RRF order with diagnostic metadata.

## External API

Enable External service in Models, configure one API key, and mark selected
profiles visible to the external API. The service accepts localhost clients
only and is disabled by default.

| Endpoint | Behavior |
| --- | --- |
| GET /v1/models | Enabled public llm/embedding aliases |
| POST /v1/chat/completions | Non-streaming/SSE, function tool data, image_url and response_format |
| POST /v1/embeddings | Text/string arrays, float/base64 output |

Use Authorization: Bearer <key> or x-api-key. Model names are public aliases;
internal UUIDs are not accepted. Only n=1 and the documented request subset
are supported. Tool calls are forwarded, never executed. Unsupported
capabilities return errors without selecting another model.

Model management is under /api/models/providers, /profiles, /inventory and
/settings. The old LLM/per-kind/inference management routes, standalone vision
and multimodal endpoints are deleted. Public rerank and image services are
deferred. See [the external protocol](docs/contracts/stateless-inference.md).

## Settings and storage

General owns attachment limits, titles, Memory, appearance and Pet settings.
Models owns connections, all model profiles, model selectors and the external
service. Knowledge and Worldbook own their context/retrieval settings.

Keys are omitted from management reads, with presence flags instead. Omitting
a PATCH key retains it; an empty string clears it. Local key storage is not
encrypted. Logs exclude credentials and request/model content.

SQLite is managed solely by Alembic. Head 0005_phase3_personas adds Persona,
ordered session members, binding modes and private run snapshots after the
runtime schema and disposable
database recreation, without copying or converting records. Downgrade is
unsupported.
Empty databases upgrade to head; unversioned nonempty databases are rejected.

This project has no users/user data. Prolonged service downtime is acceptable.
Abandoned code has no compatibility implementation or configuration fallback.
Schema revisions never delete model files, attachments, runtimes or other
data directories. See [data layout](docs/DATA_LAYOUT.md).

The default database is data/agent_workbench.db, configurable with
AGENT_WORKBENCH_DATABASE_URL. Remaining environment paths are listed in
.env.example; model connection settings live in the database.

## Verification

```powershell
uv run pytest -q
uv run python -m compileall -q ai_workbench
uv run python scripts/check_docs_size.py
uv run python scripts/audit_workspace.py --check
Push-Location frontend
npm run build
npm run check:i18n
npm run test:model-stream
npm run test:phase1-contracts
npm run test:knowledge-citations
npm run test:url
Pop-Location
```

Backend tests use isolated roots, mock upstream HTTP plus real loopback
HTTP/SSE/WS transport tests. Runtime tests install/download only pinned runtime
artifacts into isolated roots; they do not download model weights. Frontend state
tests exercise sequence ordering, canonical completion, concurrent model
refreshes, runtime jobs and session isolation. Installed runtime smoke checks
are reported separately from deterministic tests.

Read [AI context](docs/AI_CONTEXT.md), then the
[refactor roadmap](docs/WORKBENCH_REFACTOR_ROADMAP.md) and owning contract
before changing code.
