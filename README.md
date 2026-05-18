# Agent Workbench

v0.1.0-alpha Technical Alpha for a lightweight personal AI workbench.

The app looks like a small chat client, but messages can route to callable Agents and slash Commands:

- Plain text goes to the current session default Agent.
- `@translate 你好` invokes a specific Agent.
- `@translate:formal` invokes a specific Agent action.
- `/encode base64 hello` invokes a global Command exposed by a Capability.

The current alpha focuses on local-first chat routing, schema-aware settings, LLM diagnostics, run timelines, health checks, SQLite persistence, and basic operator scripts.

## Quick Start

Requirements:

- Python 3.10.11 or any Python 3.10+
- uv
- Node.js and npm for the frontend

Create a local env file:

```powershell
Copy-Item .env.example .env
```

Install backend dependencies:

```powershell
uv sync
```

Start the backend:

```powershell
uv run uvicorn ai_workbench.api.main:app --reload
```

Start the frontend in another shell:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL, usually `http://localhost:5173`.

## Environment

`.env.example` contains the local defaults:

```text
AGENT_WORKBENCH_DATABASE_URL=sqlite:///./data/agent_workbench.db
AGENT_WORKBENCH_LLM_BASE_URL=http://localhost:1234/v1
AGENT_WORKBENCH_LLM_API_KEY=
AGENT_WORKBENCH_LLM_MODEL=
AGENT_WORKBENCH_LLM_TIMEOUT=60
AGENT_WORKBENCH_ATTACHMENTS_DIR=./data/attachments
AGENT_WORKBENCH_FILE_ALLOWED_DIRS=
```

LLM config resolution uses one shared path for Prompt Agents, Script Agent
`ctx.llm.generate`, diagnostics, and model listing. Full resolution rules live
in [docs/contracts/runtime-llm-resolution.md](docs/contracts/runtime-llm-resolution.md).

The Chat composer has a custom dark session model selector beside Send. `Default` means the current Agent manifest or global fallback resolves the model. Selecting an enabled saved LLM Profile stores `session.llm_profile_id` and overrides LLM Agents in that session unless the Agent opts out. The dropdown hides disabled profiles and highlights the selected item.

When the session model changes, the app inserts a centered `model_changed` separator before the next user message. This separator is persisted for UI history but is filtered out of LLM context.

## Basic Usage

Create a session, then try:

```text
hello
@translate 你好
@translate:formal
/encode base64 hello
/encode qr hello
/free-memory all
```

Message action buttons use the same Agent action system as text calls.

Script Agents can also return interactive `action_form` blocks in rich content. Submitting a form invokes the target Agent action and passes validated field values to the Script Agent as `ctx.input.prefill`.

Message hover actions are available in Chat:

- User messages: Copy, Edit, Delete.
- Agent messages: Copy, Retry, Delete.

Copy uses the raw message content. Markdown replies copy Markdown source, JSON messages copy pretty JSON, and file content messages copy the returned file body only.

Delete only removes the selected message. It does not remove later messages and does not cascade-delete runs.

Agent Retry deletes the selected Agent message and all later messages, then regenerates from the source user message. User Edit updates the selected user message, deletes all later messages, then submits the edited content again. Retry and Edit both use the current session model resolution rules, so switching the composer model before retrying or editing affects the regenerated Agent reply and still records `llm_resolution` metadata.

Sessions can be deleted from the sidebar. Deleting a session is a hard delete in this alpha: its messages, runs, and run events are removed from SQLite.

Session titles can be renamed inline from the sidebar. Empty titles are not saved, and titles are limited to 120 characters.

When a session still has a default title such as `Session 1`, the core runtime can make one best-effort internal title attempt after the first user message that resolves to an LLM-capable Agent/action. Settings -> General -> LLM & Prompts owns title backend selection and title prompt settings. Full title and Utility LLM behavior is documented in [docs/contracts/utility-llm.md](docs/contracts/utility-llm.md).

## Intent Routing Alpha

Settings -> General -> Intent Routing adds an optional natural-language pre-route layer for ordinary messages. Explicit `/command`, `@agent`, `@agent:action`, and `:action` syntax always bypasses it. Shadow mode records compact predictions only; safe auto mode can execute only the documented `chat`, high-confidence Knowledge query override, and narrow Workbench Pet command paths.

The semantic router uses an existing Knowledge Embedding Model Profile, and Utility LLM may provide strict JSON slots for executable non-chat intents. Route Test is diagnostic-only and does not create messages/runs or mutate sessions.

Full contract: [docs/contracts/intent-routing.md](docs/contracts/intent-routing.md). Utility LLM details: [docs/contracts/utility-llm.md](docs/contracts/utility-llm.md).

## Agent Avatars

Agent image avatars can live beside the Agent manifest as `avatar.*` or
`agent.*` image files, and directory avatars take priority over `agent.yaml`.
If no directory avatar exists, manifest `avatar` can be an emoji, an
`http`/`https` URL, a local path inside the Agent directory, or fallback text.

## Local LM Studio

Start LM Studio or another OpenAI-compatible local service with an API endpoint like:

```text
http://localhost:1234/v1
```

Set `AGENT_WORKBENCH_LLM_MODEL` in `.env`, or configure the `llm` capability in Settings. Local LM Studio setups often do not require an API key; an empty key is allowed.

In Settings, LLM configuration is split under `LLM`:

- Defaults.
- Provider Profiles.
- Model Profiles.

## LLM Provider And Model Profiles

Provider Profiles hold connection details such as provider label, base URL, API key, timeout, enabled state, and provider-specific metadata. Model Profiles hold user-facing model selection and behavior defaults such as provider model id, stable profile key, capabilities, generation defaults, notes, and enabled state.

Provider status checks are available for configured providers and return structured reachability/model-availability information without exposing API keys. LM Studio, llama.cpp, and OpenAI-compatible providers each keep their existing status behavior.

Knowledge RAG v1 provides local embedding/reranker settings, embedding model profiles, Knowledge Bases, source indexing, retrieval search, session bindings, automatic context injection, and a thin Knowledge Capability. Full Knowledge contract: [docs/contracts/knowledge.md](docs/contracts/knowledge.md).

## Settings

Settings uses manifest-declared AgentConfig and CapabilityConfig `config_schema` fields. Unknown user config fields are rejected by the API, and secret fields are masked in API/UI responses while still stored as plaintext JSON in SQLite in this alpha.

Settings -> General stores local app settings for Files, Appearance fonts, LLM & Prompts, Memory, Utility LLM, and Intent Routing. Session title settings belong to LLM & Prompts; Utility LLM backend/model/device/options belong to Utility LLM; Intent Routing behavior, examples, Route Test, semantic profile selection, and compact Utility status live under Intent Routing.

Settings -> Appearance -> Fonts configures separate UI, message, and code fonts. Each font can use a single installed system font name, a single local custom font file, or a local custom font family folder under `data/assets/fonts/<folder>/`. Family folders may include `font.json` to declare Regular/Bold/Italic/variable faces; otherwise common filename suffixes such as `BoldItalic`, `Light`, and `SemiBold` are inferred. Local font files are served through generated asset ids, not arbitrary disk paths.

Settings -> Knowledge owns local RAG defaults, embedding model profiles, Knowledge Bases, and source indexing status. The Chat header Context Sources modal manages session Knowledge Base and Worldbook bindings. KB binding order is preserved for UI continuity but does not change Knowledge retrieval ranking.

Full contracts: [Knowledge](docs/contracts/knowledge.md), [Utility LLM](docs/contracts/utility-llm.md), and [Intent Routing](docs/contracts/intent-routing.md).

## SQLite Data

Default database path:

```text
data/agent_workbench.db
```

Override it with:

```text
AGENT_WORKBENCH_DATABASE_URL=sqlite:///./data/agent_workbench.db
```

The current schema version is stored in app metadata as `schema_version`.

This project still uses a lightweight schema version guard plus `SQLModel.metadata.create_all`. New tables can be created during startup, but there is no Alembic migration system yet.

Worldbook data is stored in SQLite and session bindings are managed from Context
Sources. Full Core Memory and Worldbook storage/matching rules live in
[docs/contracts/memory-worldbook.md](docs/contracts/memory-worldbook.md).

Settings -> Data shows the database path and size, the attachment directory, attachment count and size, orphan attachment count and size, optional last scan time, and the `Persist streaming message deltas` debugging toggle. The toggle is off by default; final messages, run steps, errors, and warnings are still stored. Use:

```text
GET /api/data/storage-stats
POST /api/data/attachments/scan-orphans
POST /api/data/attachments/cleanup-orphans
```

Cleanup requires `{"confirm": true}` and only deletes unreferenced local files inside the configured attachment directory. It does not reset data, browse folders, generate thumbnails, export/import data, or sync to cloud storage. Environment variables may still override runtime paths such as the SQLite database URL and attachment directory.

Reset local data with `uv run python scripts/reset_data.py`, or add `--yes` to
actually delete the default SQLite file. The reset script only deletes
file-backed SQLite databases in safe project or temp paths.

## Diagnostics

Health endpoints:

```text
GET /api/health
GET /api/health/details
GET /api/diagnostics
```

`/api/health` returns version, database status, and schema version. `/api/health/details` adds registry counts and a non-secret LLM config summary. It reports whether an API key is set, but never returns the plaintext key.

Settings -> Diagnostics calls `GET /api/diagnostics` and shows local runtime
health without external probes: backend and database status, attachment storage,
EventBus/WebSocket/run counts, recent failed runs, non-secret LLM config health,
and File/HTTP readiness from local configuration only.

Diagnostics does not send telemetry, does not contact cloud services, does not expose API keys, and does not read file contents or make HTTP requests. LLM connection testing remains in Settings -> LLM through the explicit Test connection button.

Runs also have a lightweight event timeline:

```text
GET /api/runs/{run_id}/events
```

The timeline records compact run and step events. The frontend Runs panel can
expand a run to show this timeline. Full event ownership lives in
[docs/contracts/runtime-run-lifecycle.md](docs/contracts/runtime-run-lifecycle.md).

## Long Task Lifecycle MVP

Agent runs persist a lightweight lifecycle record that the chat UI renders as a
compact step timeline. Runs support cancellation, cleanup warnings, compact
metadata, and WebSocket step updates. Full lifecycle, metadata, and event rules
live in [docs/contracts/runtime-run-lifecycle.md](docs/contracts/runtime-run-lifecycle.md).

This MVP includes ComfyUI Script Agent generation as a local trusted integration, but intentionally does not include a workflow editor, full Diagnostics/Run Trace page, background job queue, priority/retry/pause/resume controls, or complex command diff UI.

API errors use a structured shape:

```json
{
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "Run not found: example",
    "details": {}
  }
}
```

The frontend shows API failures in a visible error banner/status area instead of only logging them.

Run:

```powershell
uv run python scripts/check.py
```

It checks Python version, manifest loading, Agent/Capability/Command registries, SQLite initialization, `schema_version`, `create_app(use_memory=True)`, health endpoints, registry counts, and that health details do not leak API key plaintext.

## Development Checks

```powershell
uv run pytest
cd frontend
npm run build
cd ..
uv run python scripts/check.py
```

Developer docs: [docs/AI_CONTEXT.md](docs/AI_CONTEXT.md),
[docs/ai](docs/ai), [docs/EXTENSION_ARCHITECTURE.md](docs/EXTENSION_ARCHITECTURE.md),
[docs/EXTENSION_API.md](docs/EXTENSION_API.md),
[docs/RUNTIME_PROTOCOLS.md](docs/RUNTIME_PROTOCOLS.md), and
[docs/generated/REGISTRY.md](docs/generated/REGISTRY.md).

## Script Agents

Script Agents are local trusted Python code. They can call core helpers through `AgentContext`, including LLM helpers and Capabilities, but they are not sandboxed as untrusted code.

See [docs/AGENT_DEVELOPMENT.md](docs/AGENT_DEVELOPMENT.md) for Prompt Agent and Script Agent templates, the recommended `ctx.llm` and reply SDKs, `scripts/check_agents.py`, and command-line Agent testing with `scripts/run_agent.py`.

See [docs/CAPABILITY_DEVELOPMENT.md](docs/CAPABILITY_DEVELOPMENT.md) for Capability templates, command mapping, runtime method checks, `scripts/create_capability.py`, and command-line testing with `scripts/run_command.py`.

The development guides cover output rendering for `text`, `markdown`, `json`, `image`, `image_gallery`, `file_content`, `rich_content`, and interactive form blocks, plus common strict-check failures and a practical CLI debug workflow.

## File Attachments Alpha

User messages can include image and file attachments from the composer,
drag-and-drop, or clipboard paste. Uploads are stored under the configured
attachments directory and message metadata stores local references instead of
large base64 payloads.

Prompt Agents may include text attachments in LLM context when General settings
allow it. Vision input is sent only for current-message image attachments when
the resolved model supports vision. Script Agents can inspect input attachments
and save generated files through trusted ctx helpers. Full attachment, file
context, vision, and generated-file rules live in
[docs/contracts/attachments-vision.md](docs/contracts/attachments-vision.md).

Delete a message to remove any local attachment files that are no longer referenced by another message in that session. To scan SQLite metadata and remove orphan files, use:

```powershell
uv run python scripts/cleanup_attachments.py
uv run python scripts/cleanup_attachments.py --apply
```

## File, HTTP, Web Search, And ComfyUI Capabilities

Settings -> General controls chat attachment uploads: maximum image upload size, maximum file upload size, maximum attachments per message, whether uploaded text files enter LLM context, and per-file/per-message LLM file context limits. Those settings apply to composer upload, drag-and-drop, paste, attachment serving, Prompt Agent file context, vision input, and `file_content`.

Settings -> Capabilities -> File Capability controls only active local path reads through `/read-file <path>`. It does not reuse or synchronize General upload limits. File Capability settings include allowed directories, maximum local text/image/audio/video read sizes, allowed text extensions, and the command toggle for `/read-file`. Relative allowed directories resolve from the project root. Empty allowed directories can be saved and cause file read commands to reject every path. `/read-file` returns Message Parts for supported text, image, audio, and video files.

Settings -> Capabilities -> Codec Capability exposes `/encode` and `/decode`. It supports Base64 text, Base64URL tokens, URL component percent encoding, Unicode escapes, hex UTF-8 text, Base64 data URLs, image attachment encoding, and QR generation with `/encode qr <text>`. QR generation returns an attachment-backed PNG image part. QR decoding is not implemented. It does not fetch URLs, read local paths, transcode media, inspect JWTs, hash content, or inspect arbitrary binary files.

Settings -> Capabilities -> HTTP Capability controls only the active network GET command `/fetch-url <url>`. It does not affect chat uploads. `/fetch-url` auto-detects supported `text/*`, HTML, JSON, and `image/*` responses and returns the matching Message Part. HTTP settings include one command toggle, allowed URL schemes, timeout seconds, separate text and image response size limits, redirect enablement, and maximum redirects. No HTTP POST, PUT, DELETE, audio/video, remote media download/cache/proxy, HLS/DASH, livestream/radio/podcast extraction, OCR, ASR, TTS, or PDF parsing support is provided.

Settings -> Capabilities -> Web Search controls `/web-search <query>` for a user-running SearXNG service, defaulting to `http://localhost:8888`. It returns a markdown result list plus normalized JSON with query, provider, timestamp, results, and warnings. It does not fetch result page bodies, cache results, save to Knowledge, or inject web context into Prompt Agents.

Settings -> Capabilities -> ComfyUI Capability stores local ComfyUI connection, polling, workflow, and preset-library settings. Preset YAML is documented in [docs/COMFYUI_PRESET_SCHEMA.md](docs/COMFYUI_PRESET_SCHEMA.md). It does not provide slash commands, a workflow editor, prompt enhancement, WebSocket progress, or real-service setup scripts. Automated tests use mocks; real generation requires a user-running ComfyUI service and API-format workflow JSON files.

ComfyUI Agent Alpha: `@comfyui_agent` provides a workflow/preset library, session recipe form, and real generation MVP. The recipe form edits only the current session runtime recipe, supports preset switching, supports section/span layout metadata for compact forms, and no longer exposes `input_mode` or the LLM user request; submitting the form silently saves only, collapses the saved source form, and does not generate. `@comfyui_agent:switch raw` and `@comfyui_agent:switch llm` control the stored input mode. `@comfyui_agent:raw` always writes `positive_prompt` and runs directly. `@comfyui_agent:llm` generates a positive prompt with the configured default LLM operation and either auto-runs or saves it for inspection depending on AgentConfig. The default LLM operation can be `refine` or `fresh`; `@comfyui_agent:fresh` and `@comfyui_agent:refine` override that operation for one request without changing defaults. Refine/fresh prompt templates are configurable through the ComfyUI Agent config. `@comfyui_agent` uses the stored input mode, and `@comfyui_agent:run` executes the saved recipe without changing prompt or parameters. Generation fills an API-format workflow from manually mapped preset parameters, submits it to the user-running ComfyUI REST service, polls status, filters temporary/preview images by default, fetches formal output images, saves them as local attachments, and returns an attachment-backed image gallery. Agent config can optionally request ComfyUI memory release after generation; this requires the connected ComfyUI service to support `POST /free` and can make the next ComfyUI generation slower because models reload. No img2img, upscale, variation/regenerate buttons, automatic mapping, workflow editor UI, or dynamic preset field refresh is included yet.

## Workbench Pet

Settings -> Appearance -> Pet controls the local Workbench Pet overlay and
imports Codex-compatible `pet.json` plus `spritesheet.webp` pairs under
`data/pet/`. The `pet` Capability exposes `/pet`, `/pet status`, `/pet wake`,
`/pet tuck`, `/pet reload`, and `/pet select <pet_id>`; these commands update Pet
settings directly and do not call an LLM or create a Pet Agent.

Settings -> Appearance -> Chat status panel controls the compact Chat header
status pill. Runtime resource monitoring polls `GET /api/runtime/resources` when
enabled; provider/resource details are summarized in
[docs/contracts/provider-status.md](docs/contracts/provider-status.md).

Permission hints and CapabilityConfig settings are local alpha safety controls and operator documentation, not a sandbox or full authorization system. Script Agents remain trusted local Python code and can call capabilities.

## Security Notes

This is a local trusted-user alpha. File, HTTP, and Web Search capabilities are powerful: they can read allowed local files and make network GET requests. Script Agents are trusted local Python code and can call capabilities. There is no sandbox, no per-run approval, and no per-agent permission UI yet. Only install agents and capabilities you trust.

## Current Limitations

Technical Alpha, local-first only. No auth, roles, Alembic migrations, secret
encryption, user-facing external app workflows, function calling, MCP, automatic
tool selection, attachment thumbnails, cloud upload, file search/editing, OCR,
PDF/Office/archive parsing, historical image resend, model pool, GPU scheduling,
or advanced lifecycle management. File/HTTP allowlists are not a full sandbox.
Script Agent visible streaming is not implemented yet. Thought display is
read-only. WebSocket unavailable mode falls back to final HTTP refresh, and
non-streaming run cancellation remains best effort.
