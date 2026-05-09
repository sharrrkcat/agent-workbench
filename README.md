# Agent Workbench

v0.1.0-alpha Technical Alpha for a lightweight personal AI workbench.

The app looks like a small chat client, but messages can route to callable Agents and slash Commands:

- Plain text goes to the current session default Agent.
- `@translate 你好` invokes a specific Agent.
- `@translate:formal` invokes a specific Agent action.
- `/base64 hello` invokes a global Command exposed by a Capability.

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

LLM config resolution now uses one shared path for Prompt Agents, Script Agent `ctx.llm.generate`, diagnostics, and model listing.

Priority, highest first:

- per-invocation explicit override
- session LLM Profile override, when the Agent allows it
- Agent manifest `llm.profile`
- Agent manifest legacy `model` fields
- persisted `llm` CapabilityConfig `default_profile`
- persisted direct `llm` CapabilityConfig from Settings
- `.env` / process environment fallback: `AGENT_WORKBENCH_LLM_BASE_URL`, `AGENT_WORKBENCH_LLM_API_KEY`, `AGENT_WORKBENCH_LLM_MODEL`, `AGENT_WORKBENCH_LLM_TIMEOUT`
- `llm` capability manifest defaults

The Chat composer has a custom dark session model selector beside Send. `Default` means the current Agent manifest or global fallback resolves the model. Selecting an enabled saved LLM Profile stores `session.llm_profile_id` and overrides LLM Agents in that session unless the Agent opts out. The dropdown hides disabled profiles and highlights the selected item.

When the session model changes, the app inserts a centered `model_changed` separator before the next user message. This separator is persisted for UI history but is filtered out of LLM context.

## Basic Usage

Create a session, then try:

```text
hello
@translate 你好
@translate:formal
/base64 hello
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

When a session still has a default title such as `Session 1`, the core runtime makes one simple best-effort attempt to generate a short title after the first successful user interaction. It uses only the current user message and the first readable output from that run, not the full session history. If title generation fails or no LLM can be resolved, the original title is kept and the main conversation still succeeds. There is no title history, regenerate button, or separate title model setting in this alpha.

## Agent Avatars

Agent image avatars can live beside the Agent manifest. Directory avatars take priority over `agent.yaml`:

```text
agents/my_agent/avatar.png
agents/my_agent/avatar.jpg
agents/my_agent/avatar.jpeg
agents/my_agent/avatar.webp
agents/my_agent/avatar.svg
agents/my_agent/agent.png
agents/my_agent/agent.jpg
```

If no directory avatar exists, `avatar` in `agent.yaml` can be an emoji, an `http`/`https` image URL, a local path inside the Agent directory such as `./avatar.png`, or text such as `TA`. Local avatar paths must stay inside the Agent directory.

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

Provider Profiles hold connection details:

- Provider label: `openai_compatible`, `lm_studio`, `llama_cpp`, or `custom`.
- Base URL.
- API key.
- Timeout.
- Enabled state and provider-specific metadata.

Model Profiles hold model selection and behavior defaults:

- Name: the display name shown in Settings, such as `My Qwen3 Local`.
- Provider Profile: the connection used for the model.
- Selected provider model: refresh models from the selected Provider Profile when the provider can list models.
- Manual Model ID override: the editable fallback field used as the real request model id, such as `ascat/Ministral-3-3b-it-ad`.
- Profile key: the stable key used by Agent manifests. In the current API this maps to the stored `alias` field.
- Capabilities: Vision, Tools, Reasoning, Streaming.
- Generation defaults: Temperature, Top P, Top K, Max tokens.
- Notes and enabled state.

Prefer choosing a refreshed provider model when available. Model ID remains editable for cases where the provider is offline, does not support model listing, or you need a custom alias.

Provider Profile status is available through `POST /api/llm-provider-profiles/status/refresh` or `POST /api/llm-provider-profiles/{id}/status/refresh`. Status is refreshed per Provider Profile, then mapped to every Model Profile that references it. Results include `checked_at`, provider reachability, model availability, warnings, and structured status codes such as `READY`, `PROVIDER_UNREACHABLE`, `MODEL_NOT_AVAILABLE`, `MODEL_MISMATCH`, and `MODEL_STATUS_UNKNOWN`. API keys are never returned.

Provider status behavior:

- LM Studio uses the native REST API derived from the Provider Profile base URL, for example `http://localhost:1234/v1` -> `http://localhost:1234/api/v1/models`. It parses model ids, display names, loaded instances, and capabilities. If the native API is unavailable, it falls back to OpenAI-compatible `/v1/models` as a partial/unknown status instead of incorrectly reporting a missing model.
- llama.cpp first probes router mode at the base origin `/models`. If that works, the router model list determines availability. If router mode is unavailable, it falls back to `/v1/models` single-server mode and treats a different served model as `MODEL_MISMATCH`; use `llama-server --alias <model_id>` for stable API model names.
- OpenAI-compatible providers use `/v1/models` to determine reachability and model id availability. They do not support unload.

Settings -> LLM follows the Settings Console three-column structure. The left Settings nav expands `LLM` into subpages, and the middle object list only shows the selected subpage:

- Defaults: choose the Default model profile.
- Provider Profiles, backed by `llm_provider_profiles`.
- Model Profiles, backed by the existing `llm_profiles` table for compatibility.

Existing LLM Profiles are migrated automatically. Legacy profile connection fields (`provider`, `base_url`, `api_key`, `timeout`) are moved into deduplicated Provider Profiles and the original `llm_profiles` rows become Model Profiles that reference those providers. The migration is idempotent and keeps capability flags and generation defaults. API/UI responses mask `api_key` as `********`; PATCHing `api_key: "********"` preserves the stored secret. Secrets are still stored as plaintext in SQLite in this alpha and are not encrypted yet.

The default model profile replaces the old editable Global fallback UI. Runtime resolution order is:

1. Session model override, when allowed.
2. AgentConfig runtime `llm_profile_id`.
3. Agent manifest `llm.profile`.
4. Default model profile.
5. Legacy global fallback from the `llm` CapabilityConfig.
6. Environment fallback.

The legacy global fallback and environment variables remain as compatibility fallback only. Desktop packaging changes and ComfyUI integration are not part of this round.

Reasoning is a profile-level output declaration. If Reasoning is enabled, Agent Workbench expects the profile to return reasoning content when available and may display it as a collapsed Thought section. If Reasoning is disabled, the profile is treated as a direct-answer model. This flag does not change model behavior by itself and does not inject provider-specific reasoning request parameters; those may be added later.

`supports_streaming=true` enables visible streaming for Prompt Agent replies after the current LLM call resolves to that profile. `supports_streaming=false` keeps the normal full-response path. If no profile is resolved and the app is only using the LLM CapabilityConfig or environment fallback, streaming is off unless the resolved config explicitly contains `supports_streaming=true`. Vision, Tools, and Reasoning are still capability/output flags only; JSON mode is not shown as a user-configurable capability for now because provider support differs and there is no unified runtime behavior yet.

Agent manifests can reference a profile by Profile key or id:

```yaml
llm:
  profile: myqwen3
  allow_session_override: false
  temperature: 0.2
  top_p: 0.9
  top_k: 40
  max_tokens: 2048
```

`allow_session_override` defaults to `true`. If it is `false`, the session model selector does not override that Agent; the Agent keeps using its manifest profile/model or fallback. The Agent dropdown marks these Agents as locked.

Agent replies store resolved request metadata under `llm_resolution` and response model metadata under `llm`. Assistant message badges prefer the actual model returned by the provider. If the actual model differs from the requested model id, the badge is marked as a mismatch and its title shows Provider, Requested, and Actual values. Old messages without actual model metadata still fall back to the previous profile/model label behavior.

Chat model status:

- The top status dot shows availability for the current resolved model. Clicking it refreshes all enabled Provider Profiles.
- Switching the active Agent or composer Model Profile refreshes the corresponding Provider Profile status.
- Opening the composer model dropdown does not perform network refresh. It only shows cached status dots.
- The bottom status bar shows the Provider Profile and requested model id that will be used for the next request. This is intentionally separate from the actual model recorded on a completed assistant message.

Model unload is only exposed to trusted script agent runtime through `ctx.llm.unload_model(...)`. There is no user-facing unload button or slash command. LM Studio unload uses native loaded instance ids from `/api/v1/models` and posts each instance to `/api/v1/models/unload`. llama.cpp single mode and OpenAI-compatible providers return `MODEL_UNLOAD_UNSUPPORTED`.

Prompt Agent replies also store `llm_metrics` in run and assistant message metadata. The Chat UI shows a compact line with output tokens, tokens per second, first-token latency for streaming responses, or total duration when first-token timing is unavailable. When a provider returns usage, those token counts are used. When usage is absent, completion tokens are estimated from output characters and displayed with a `~` prefix.

Prompt Agent replies can store reasoning output in assistant message metadata. Non-streaming OpenAI-compatible responses read `choices[0].message.reasoning_content`; streaming responses read `choices[].delta.reasoning_content` and keep it separate from normal answer content. Reasoning content is displayed above the answer as a collapsed Thought section when present, is persisted with the message, and is not included in future LLM context.

Streaming replies can be stopped from the composer. Cancelling a streaming run interrupts the active task and may preserve the partial assistant message with `metadata.interrupted=true`; failed streaming runs do not silently retry as non-streaming because that would hide provider streaming errors. If WebSocket events are unavailable, sending still falls back to the final HTTP response and message refresh, so the completed message remains visible after the request finishes.

The old manifest `model` field remains compatible:

```yaml
model:
  provider: openai_compatible
  base_url: http://localhost:1234/v1
  model: qwen2.5-3b-instruct
```

`model` is legacy. New Agents should prefer `llm.profile`.

Profile resolution errors are structured:

- `LLM_PROFILE_NOT_FOUND`
- `LLM_PROFILE_DISABLED`
- `LLM_PROFILE_INVALID`

## Settings

AgentConfig and CapabilityConfig now use manifest-declared `config_schema` fields. Unknown user config fields are rejected by the API.

Supported schema field types:

- `string`
- `text`
- `integer`
- `float`
- `boolean`
- `enum`
- `json`

If a manifest has no `config_schema`, Settings shows `No configurable fields` and does not allow arbitrary JSON edits.

The `llm` Settings card also shows resolved non-secret status:

- `base_url`
- `model`
- `timeout`
- whether an API key is set

The resolved status endpoint does not return API key plaintext.

Secret fields render as password inputs. API responses return the fixed mask `********` for set secrets. Sending `********` back in a PATCH keeps the stored value unchanged. Sending an empty string clears the secret because empty strings are omitted from the saved form payload in the current UI; API callers can send `""` explicitly if they want to persist an empty value.

Secret masking is API/UI masking only. Secrets are still stored as plaintext JSON in SQLite and are not encrypted yet.

Settings -> General stores local app settings in SQLite and exposes:

- max image size
- max file size
- max attachments per message
- max file context per file
- max total file context per message
- whether ordinary text file attachments are sent to Prompt Agent LLM context
- whether streaming `message_delta` events are persisted for debugging
- Context Rendering overrides for Group transcript and Command result context instructions

Use `GET /api/settings/general` and `PATCH /api/settings/general` to read and update these values. Unknown fields are rejected, and upload limits are enforced by the backend. File context settings only affect ordinary text/code/config files; image Vision input is still controlled by the selected model profile capability flags.

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

Settings -> Data shows the database path and size, the attachment directory, attachment count and size, orphan attachment count and size, optional last scan time, and the `Persist streaming message deltas` debugging toggle. The toggle is off by default; final messages, run steps, errors, and warnings are still stored. Use:

```text
GET /api/data/storage-stats
POST /api/data/attachments/scan-orphans
POST /api/data/attachments/cleanup-orphans
```

Cleanup requires `{"confirm": true}` and only deletes unreferenced local files inside the configured attachment directory. It does not reset data, browse folders, generate thumbnails, export/import data, or sync to cloud storage. Environment variables may still override runtime paths such as the SQLite database URL and attachment directory.

Reset local data with a dry run:

```powershell
uv run python scripts/reset_data.py
```

Actually delete the default SQLite file:

```powershell
uv run python scripts/reset_data.py --yes
```

The reset script only deletes file-backed SQLite databases in safe project or temp paths.

## Diagnostics

Health endpoints:

```text
GET /api/health
GET /api/health/details
GET /api/diagnostics
```

`/api/health` returns version, database status, and schema version. `/api/health/details` adds registry counts and a non-secret LLM config summary. It reports whether an API key is set, but never returns the plaintext key.

Settings -> Diagnostics calls `GET /api/diagnostics` and shows local runtime health without external probes:

- backend version, Python version, and uptime
- SQLite database status, schema version, and size
- attachment storage status, count, total size, and writability
- EventBus subscriber count, active WebSocket connections, active runs, and active tasks
- recent failed runs with short, truncated error messages
- LLM profile/config health without calling `/models`
- File and HTTP capability readiness from local configuration only

Diagnostics does not send telemetry, does not contact cloud services, does not expose API keys, and does not read file contents or make HTTP requests. LLM connection testing remains in Settings -> LLM through the explicit Test connection button.

Runs also have a lightweight event timeline:

```text
GET /api/runs/{run_id}/events
```

The timeline records events such as `run_started`, `run_step_created`, `run_step_updated`, `action_invoked`, `message_done`, `run_done`, `run_failed`, and `run_cancelled`. The frontend Runs panel can expand a run to show this timeline.

## Long Task Lifecycle MVP

Agent runs persist a lightweight lifecycle record that the chat UI renders as a compact step timeline. A run records status, current stage, progress message, cancellation state, timestamps, error details, and metadata. Run steps are stored separately with stable ordering, status, message, timestamps, error details, and metadata.

Prompt agents record the default path: Resolving agent, Building context, Resolving model, Calling LLM, Saving response, and Cleanup. Script agents record Resolving agent, Starting script, Running script, Saving response, and Cleanup; scripts can optionally report progress or custom steps through `ctx.run`.

`POST /api/runs/{run_id}/cancel` marks active runs as cancelling, requests cancellation from the active task registry, and leaves completed or failed runs unchanged. WebSocket events include run and step updates (`run_updated`, `run_step_created`, `run_step_updated`, `run_cancel_requested`, `run_completed`, `run_failed`) so chat can update the timeline live. Session message loads include related run and step payloads so completed, failed, or refreshed runs can still display their timeline.

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

Developer docs:

- [docs/AI_CONTEXT.md](docs/AI_CONTEXT.md) for AI/Codex task routing.
- [docs/EXTENSION_ARCHITECTURE.md](docs/EXTENSION_ARCHITECTURE.md) for designing complex integrations and workflow agents.
- [docs/EXTENSION_API.md](docs/EXTENSION_API.md) for Agent, Capability, Script ctx, and output contracts.
- [docs/RUNTIME_PROTOCOLS.md](docs/RUNTIME_PROTOCOLS.md) for streaming, run lifecycle, and LLM protocols.
- [docs/generated/REGISTRY.md](docs/generated/REGISTRY.md) for the generated Agent/Capability registry.

## Script Agents

Script Agents are local trusted Python code. They can call core helpers through `AgentContext`, including LLM helpers and Capabilities, but they are not sandboxed as untrusted code.

See [docs/AGENT_DEVELOPMENT.md](docs/AGENT_DEVELOPMENT.md) for Prompt Agent and Script Agent templates, the recommended `ctx.llm` and reply SDKs, `scripts/check_agents.py`, and command-line Agent testing with `scripts/run_agent.py`.

See [docs/CAPABILITY_DEVELOPMENT.md](docs/CAPABILITY_DEVELOPMENT.md) for Capability templates, command mapping, runtime method checks, `scripts/create_capability.py`, and command-line testing with `scripts/run_command.py`.

The development guides cover output rendering for `text`, `markdown`, `json`, `image`, `image_gallery`, `file_content`, `rich_content`, and interactive form blocks, plus common strict-check failures and a practical CLI debug workflow.

## File Attachments Alpha

User messages can include image and file attachments from the composer attachment button, drag-and-drop, or clipboard paste while the composer is focused. Browser support for pasted files is inconsistent; image paste is the most reliable path, and text file paste depends on the browser and OS clipboard format.

New uploads are stored under `data/attachments/images` or `data/attachments/files` by default, or under `AGENT_WORKBENCH_ATTACHMENTS_DIR` when configured. Message metadata stores local references instead of full base64 data:

```json
[
  {
    "id": "uuid",
    "type": "image",
    "mime_type": "image/png",
    "name": "image.png",
    "size": 12345,
    "uri": "local://attachments/<id>.png",
    "created_at": "2026-05-06T12:00:00",
    "width": 800,
    "height": 600
  },
  {
    "id": "uuid",
    "type": "file",
    "mime_type": "application/yaml",
    "name": "agent.yaml",
    "size": 1234,
    "uri": "local://attachments/<id>.yaml",
    "created_at": "2026-05-07T12:00:00"
  }
]
```

Existing legacy image attachments with `data_url` remain supported for display and vision input. No thumbnail files are generated in this version; the UI uses the original image URL for compact previews. Supported image MIME types are `image/png`, `image/jpeg`, `image/webp`, `image/gif`, and `image/svg+xml`. Image size, file size, and attachment count limits come from Settings -> General and are enforced by the backend.

Supported text/code/config extensions are `.txt`, `.md`, `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.json`, `.yaml`, `.yml`, `.toml`, `.xml`, `.html`, `.css`, `.env`, `.log`, `.csv`, `.sql`, `.sh`, `.ps1`, `.bat`, `.ini`, and `.cfg`. Unknown binary files are rejected in this alpha.

Attached images render as thumbnails in the composer and in user message bubbles. Text/code/config files render as file chips; clicking a stored text file chip opens an in-page preview modal that fetches `GET /api/attachments/{attachment_id}` and preserves the file text as returned. Local attachment serving only resolves files inside the attachment directory and does not auto-download files.

Prompt Agents can include ordinary text file attachment content in LLM context when Settings -> General enables `Send text file attachments to LLM`. The per-file and per-message context limits are applied before provider calls, and truncated files are marked in the generated context. When disabled, Prompt Agents add a lightweight placeholder and do not read or send text file contents. Vision behavior is unchanged: Prompt Agents send image attachments to the LLM only when the resolved LLM configuration for that run has `supports_vision=true`; local images are read from disk and converted to `data:image/...;base64,...` for the provider call. When Vision is disabled, image files are not read and image data is not passed to the LLM. The model receives the user text plus a lightweight placeholder such as `User attached 1 image, but the selected model does not support vision.`

Vision input currently uses OpenAI-compatible content parts and sends only images attached to the current user message:

```json
{
  "role": "user",
  "content": [
    { "type": "text", "text": "What is in this image?" },
    { "type": "image_url", "image_url": { "url": "data:image/png;base64,..." } }
  ]
}
```

Historical image attachments are not resent in LLM context yet. They remain stored in message metadata and render in the UI, but only their text or placeholder enters normal text context.

Use `/image-base64` or `/base64-encode-image` on a message with image attachments to return the selected attachment as JSON containing the data URL and raw base64. Pass a 1-based index to select another image, for example `/image-base64 2`. Use `/base64-image` or `/base64-to-image` to decode base64 back into a renderable image command output.

Script Agents can inspect the current input attachments through `ctx.input.attachments`. Helpers are available for trusted local agents:

```python
ctx.read_attachment_text(attachment)
ctx.read_attachment_bytes(attachment)
ctx.attachment_as_data_url(attachment)
await ctx.save_attachment_bytes(data, filename="result.txt", mime_type="text/plain")
await ctx.save_attachment_base64(data_base64, filename="result.png", mime_type="image/png", kind="image")
await ctx.reply_file_content(content, filename="agent.yaml", language="yaml")
```

Generated images and files should be saved through the attachment helpers and rendered with their returned local `url`, for example `await ctx.reply_images([{"url": attachment["url"]}])`. This keeps large base64 payloads out of message content and lets the normal attachment cleanup path track generated outputs.

The `echo_attachments` Script Agent is a small test agent for this API. Examples:

```text
@echo_attachments hello
@echo_attachments + image attachment
@echo_attachments + yaml file attachment
```

It echoes text, returns attached images as image outputs, and returns supported text/code/config attachments as `file_content`. It does not call an LLM.

Delete a message to remove any local attachment files that are no longer referenced by another message in that session. To scan SQLite metadata and remove orphan files, use:

```powershell
uv run python scripts/cleanup_attachments.py
uv run python scripts/cleanup_attachments.py --apply
```

## File, HTTP, And ComfyUI Capabilities

Settings -> General controls chat attachment uploads: maximum image upload size, maximum file upload size, maximum attachments per message, whether uploaded text files enter LLM context, and per-file/per-message LLM file context limits. Those settings apply to composer upload, drag-and-drop, paste, attachment serving, Prompt Agent file context, vision input, `file_content`, and the Echo Attachment Agent.

Settings -> Capabilities -> File Capability controls only active local path reads through `/read-file <path>` and `/read-image <path>`. It does not reuse or synchronize General upload limits. File Capability settings include allowed directories, maximum local text read size, maximum local image read size, allowed text extensions, and command toggles for `/read-file` and `/read-image`. Relative allowed directories resolve from the project root. Empty allowed directories can be saved and cause file read commands to reject every path. `/read-file` returns `file_content`, which preserves raw file text instead of rendering it as Markdown. `/read-image` returns normal image output with a data URL.

Settings -> Capabilities -> HTTP Capability controls only active network GET commands: `/http-get <url>`, `/fetch-page <url>`, and `/fetch-image <url>`. It does not affect chat uploads. HTTP settings include command toggles, allowed URL schemes, timeout seconds, text and image response size limits, redirect enablement, and maximum redirects. The runtime uses GET only. Text/page responses accept `text/*`, `application/json`, `application/xml`, `application/yaml`, and `application/x-yaml`; image fetches require `image/*`. No HTTP POST, PUT, or DELETE support is provided.

Settings -> Capabilities -> ComfyUI Capability stores a local ComfyUI REST base URL, request timeout, polling defaults, SSL verification, default image response mode, upload enablement, `workflows_dir`, `presets_dir`, and local write toggles for workflow/preset assets. It exposes reusable runtime methods for connection tests, workflow submission, non-blocking prompt status, queue/history reads, blocking convenience polling, output extraction, image fetching, interrupt, upload, object info, workflow library scanning, preset listing/loading, and preset validation. Preset YAML is documented in [docs/COMFYUI_PRESET_SCHEMA.md](docs/COMFYUI_PRESET_SCHEMA.md). It does not provide slash commands, a workflow editor, prompt enhancement, WebSocket progress, or real-service setup scripts.

ComfyUI Capability Alpha: automated tests use mocked REST responses and local temporary workflow/preset directories; they do not require ComfyUI to be installed or running. Real generation requires the user to run a ComfyUI service separately and provide API-format workflow JSON files.

ComfyUI Agent Alpha: `@comfyui_agent` provides a workflow/preset library, session recipe form, and real generation MVP. The recipe form edits only the current session runtime recipe, supports preset switching, and no longer exposes `input_mode` or the LLM user request; submitting the form silently saves only and does not generate. `@comfyui_agent:switch raw` and `@comfyui_agent:switch llm` control the stored input mode. `@comfyui_agent:raw` always writes `positive_prompt` and runs directly. `@comfyui_agent:llm` generates a positive prompt and either auto-runs or saves it for inspection depending on AgentConfig. `@comfyui_agent` uses the stored input mode, and `@comfyui_agent:run` executes the saved recipe without changing prompt or parameters. Generation fills an API-format workflow from manually mapped preset parameters, submits it to the user-running ComfyUI REST service, polls status, fetches output images, saves them as local attachments, and returns an attachment-backed image gallery. No img2img, upscale, variation/regenerate buttons, automatic mapping, workflow editor UI, or dynamic preset field refresh is included yet.

Permission hints and CapabilityConfig settings are local alpha safety controls and operator documentation, not a sandbox or full authorization system. Script Agents remain trusted local Python code and can call capabilities.

## Security Notes

This is a local trusted-user alpha. File and HTTP capabilities are powerful: they can read allowed local files and make network GET requests. Script Agents are trusted local Python code and can call capabilities. There is no sandbox, no per-run approval, and no per-agent permission UI yet. Only install agents and capabilities you trust.

## Current Limitations

- Technical Alpha, local-first only.
- No auth, users, roles, or permissions.
- No Alembic migrations.
- No secret encryption.
- No user-facing external app workflow integrations.
- No function calling, MCP, or LLM automatic tool selection.
- No attachment thumbnails, cloud upload, file search, file editing, OCR, PDF/Office parsing, archive extraction, or historical image resend yet.
- File and HTTP capabilities have lightweight allowlists and size limits, not a full sandbox or permission system.
- Script Agent visible streaming is not implemented yet; Script Agent LLM helpers still return final text.
- Thought display is intentionally read-only and collapsed by default; there is no composer-side reasoning toggle or reasoning effort control yet.
- WebSocket unavailable mode degrades to final HTTP refresh instead of live deltas.
- No model pool, GPU scheduling, or advanced model lifecycle management.
- Non-streaming run cancellation is best effort; blocking provider calls may finish before the task observes cancellation.
