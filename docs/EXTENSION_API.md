# Extension API

## Purpose

This document is the compact contract for writing Agents, Capabilities, Script Agent code, and output payloads.

For architecture decisions about whether to build an Agent, a Capability, or both, read `docs/EXTENSION_ARCHITECTURE.md` first.

## Agent Manifest

| field | applies to | meaning | notes |
| --- | --- | --- | --- |
| `id` | all Agents | Global Agent id. | Must be unique and match the directory in strict checks. |
| `name` | all Agents | Display name. | Can be overridden locally. |
| `type` | all Agents | `prompt` or `script`. | Controls runtime path. |
| `description` | all Agents | Short display/help text. | Optional. |
| `avatar` | all Agents | Text or local image reference. | Optional. |
| `entry` | script | Python file entry point. | Required for script Agents; must stay inside Agent dir. |
| `actions` | all Agents | User-callable entry points. | Must include `default`; ids are unique per Agent. |
| `prompt` | prompt | System prompt base text. | Runtime appends action instruction when present. |
| `capabilities` | all Agents | Capability ids the Agent expects. | Prompt Agents that use LLM should declare `llm`. |
| `llm.profile` | prompt, LLM scripts | Model Profile id or alias. | Participates in LLM resolution. |
| `llm.allow_session_override` | prompt, LLM scripts | Whether session model override can win. | Defaults to true when `llm` exists. |
| `context_policy` | all Agents/actions | Core-built context scope. | Action policy can override Agent policy. |
| `model_lifecycle` | all Agents | Load/unload policy. | Unload is best effort. |
| `config_schema` | all Agents | User-editable local config fields. | Stored as AgentConfig `user_config`. |

Minimal Prompt Agent:

```yaml
id: demo_prompt
name: Demo Prompt
type: prompt
actions:
  - id: default
    label: Chat
prompt: |
  Reply concisely.
capabilities:
  - llm
llm:
  profile: local-default
context_policy:
  mode: current_message
model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

Minimal Script Agent:

```yaml
id: demo_script
name: Demo Script
type: script
entry: agent.py
actions:
  - id: default
    label: Run
context_policy:
  mode: current_message
model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
```

### Action fields

| field | meaning | notes |
| --- | --- | --- |
| `id` | Action id. | `default` is required. |
| `label` | Button/display label. | Strict checks require label or description. |
| `description` | Short help text. | Useful for generated registry and UI. |
| `instruction` | Prompt Agent action instruction. | Appended to the Agent prompt for that action. |
| `input_schema` | Action input metadata. | Not a model function-call schema. |
| `context_policy` | Action-specific context. | Overrides Agent context policy. |
| `llm` | Action-specific LLM settings. | Merged over Agent `llm`. |
| `attach_to` | UI attachment hint. | Used by message actions when present. |
| `callable` | Whether action is user-callable. | Defaults to true. |

Text routing supports two Agent action forms:

- `@agent_id:action args` explicitly invokes `action` on `agent_id`.
- `:action args` invokes `action` only on the current session default Agent.

The `:action` shortcut does not infer from previous messages, recent Agent calls, or other Agents. If the current session default Agent lacks the named action, routing returns a structured error instead of treating the input as ordinary text. Use full `@agent_id:action` messages for buttons, saved shortcuts, and cross-Agent calls.

Actions with `callable: false` are internal Agent entry points. They are excluded from user-facing composer autocomplete and direct text/API user invocation returns a clear not-callable error. Trusted internal `action_form` submission may still target a non-callable action declared by the original form block.

### Config schema fields

| field | meaning |
| --- | --- |
| `name` | Config key. |
| `type` | `string`, `text`, `integer`, `float`, `boolean`, `enum`, or `json`. |
| `label` | Settings display label. |
| `required` | Whether user config must provide a value when no default exists. |
| `default` | Manifest default value. |
| `description` | Settings help text. |
| `options` | Required for `enum`. |
| `secret` | Masks stored/displayed values. |
| `minimum` / `maximum` | Numeric bounds. |

Enum config fields with manifest defaults should render concrete enum values in Settings, not an `unset` business option. Clearing a local config override is separate from choosing an enum value; empty/null enum patches are treated as removing the override and returning to the manifest default, while strings such as `unset` are invalid unless explicitly listed in `options`.

## Agent Overrides

- Manifest values are package defaults.
- `AgentConfig` stores local overrides and enablement.
- Config tab writes `config_schema` values into `user_config`.
- Overrides tab edits display/runtime overrides except Intent Routing fields, which have a dedicated Agent detail Intent Routing tab.
- Display override fields include name, description, and avatar.
- Prompt override replaces the manifest prompt at runtime.
- LLM runtime override can set `llm_profile_id` and `allow_session_override`.
- Knowledge runtime override can set `knowledge_context_mode` to `use_default`, `enabled`, or `disabled`. Prompt Agents default to effective `enabled`; Script Agents that declare `llm` default to effective `disabled`; Script Agents without `llm` do not show the override. This override is stored only in `AgentConfig.runtime` and is not written into `agent.yaml`.
- Intent Routing runtime fields are edited under Agent detail -> Intent Routing. They are still stored in `AgentConfig.runtime` and are not written into `agent.yaml` by manifest write.
- Prompt Agent Intent Routing override can set `intent_routing_mode` to `use_default`, `enabled`, or `disabled`. It controls whether this Prompt Agent can act as an Intent Routing entry when it is the session default Agent. General settings still own the master switch, Prompt Agent default, and global `shadow`/`auto` mode.
- Agent Intent Routing target hints are runtime-only AgentConfig fields: `intent_routing_aliases_text` is an English-comma-separated alias list, and `intent_routing_examples_text` is newline-separated natural-language examples. They are semantic route index candidates for `agent_route` metadata and Utility LLM candidate context. They do not enable Script Agents as router entries, do not permit generic Agent auto execution, and are not written into `agent.yaml`.
- Reset overrides clears local AgentConfig values back to manifest behavior.
- Write overrides to manifest only when intentionally changing the package default.

## Prompt Agents

- Prompt Agents let the core runtime build context and call the LLM.
- Model output is treated as assistant content, not tool calls or structured commands.
- Prompt Agents that call an LLM should declare `capabilities: [llm]`.
- Prompt Agents may opt into Intent Routing through local AgentConfig runtime overrides edited under Agent detail -> Intent Routing. `intent_routing_mode` controls whether a Prompt Agent can be an Intent Routing entry. In `shadow` mode, predictions are metadata only and do not alter routing, context, prompt text, or provider payloads. In General `auto` mode, only semantic `chat`, high-confidence `knowledge_query`, and narrow `pet_command` decisions can execute. `chat` keeps the current Prompt Agent path; `knowledge_query` may provide a temporary Knowledge KB/query override for the current Prompt Agent run; `pet_command` may execute only one existing `/pet` Capability command from `/pet status`, `/pet wake`, `/pet tuck`, `/pet reload`, or `/pet select <pet_id>`. Natural-language wake requests for a named pet use `/pet select <pet_id>` because select activates and wakes that pet. Auto routing does not change the session default Agent or session Knowledge bindings. Image generation, command-like, generic Agent, action, and compound semantic matches are diagnostic-only in this version.
- Depending on General Core Memory settings, Worldbook Defaults, and active Session Worldbook bindings, the core may append Core Memory and Worldbook system-context blocks before Retrieved Knowledge and conversation context.
- Visible streaming is controlled by the resolved Model Profile `supports_streaming`.
- Prompt Agent run steps, streaming, and LLM resolution follow `docs/RUNTIME_PROTOCOLS.md`.

## Script Agents

- Script Agents are trusted local Python imported into the backend process.
- `entry` must export `async def run(ctx)`.
- Older scripts that return a final value or reply once remain valid.
- Do not run untrusted Script Agent code; there is no sandbox.
- Script Agents are not Intent Routing router entries in the first alpha. They can still store target hints under Agent detail -> Intent Routing for route prediction metadata and future confirmation flows, and can be called explicitly through `@agent`, `@agent:action`, `:action`, forms, or trusted action invocation.

```python
async def run(ctx):
    async with ctx.step("Prepare input"):
        text = ctx.input.text.strip()
    await ctx.reply_markdown(f"Echo: {text}")
```

## Script Context API

### `ctx.input`

- `text`: routed argument text for this invocation.
- `action_id`: current Agent action id.
- `form_id`: submitted `action_form` id when the invocation came from a form submission.
- `is_silent_submission`: true when the invocation came from an `action_form` with `submit.visibility="silent"`.
- `attachments`: current message attachment metadata.
- `source_message_id`: source message for message-button/action invocations when available.
- `prefill`: structured action prefill data when available. Form submissions place validated field values here.

### `ctx.step` / `ctx.run`

- `ctx.step(name)` creates a visible run step.
- In Script Agents, custom steps default under the top-level `Running script` step.
- Steps are visible in chat and should describe user-meaningful progress.
- Do not use `ctx.step` for every tiny internal function.
- `ctx.run` exposes trusted lifecycle helpers such as `start_step`, `complete_step`, `fail_step`, and progress updates.

```python
async with ctx.step("Parse JSON"):
    ...
```

### `ctx.session`

- `session_id`: current Session id.
- `default_agent_id`: current default Agent id.
- `context_mode`: current Session context projection mode. See `docs/RUNTIME_PROTOCOLS.md#conversation-context-modes` and `docs/RUNTIME_PROTOCOLS.md#group-transcript-context`.

### `ctx.state`

- `ctx.state.get(key, default=None)` reads per-session, per-agent JSON runtime state.
- `ctx.state.set(key, value)` writes per-session, per-agent JSON runtime state.
- State is intended for runtime copies such as a form-backed recipe. It should not replace user-owned source files such as Capability asset files or Agent manifests.
- State is scoped by `session_id + agent_id + key`, so different sessions and Agents do not share values.

### `ctx.llm`

- `ctx.llm.text(...)` returns final text as a string.
- `ctx.llm.json(...)` parses and validates a JSON object from final text.
- `ctx.llm.stream(...)` is internal streaming. It does not write to chat.
- `ctx.llm.stream_to_output(...)` is public output streaming.
- `ctx.output.write_delta(...)` explicitly appends visible public content.
- `ctx.output.finish(...)` completes the public streaming message.
- `ctx.llm.unload_model(...)` is trusted script-only model unload through provider/model profiles and returns a structured `CapabilityCallResult` with unload outcome data.
- The first real `ctx.llm.*` provider call in a pending default-titled session may trigger the core automatic session-title pre-hook. Agent authors should not call title generation manually; the pre-hook is internal, non-streaming, and creates no visible messages.
- Depending on General Core Memory settings, Worldbook Defaults, and active Session Worldbook bindings, the core may append Core Memory and Worldbook system-context blocks before `ctx.llm.*` provider calls. Prompt-backed `ctx.llm.generate` receives these blocks prepended to the prompt. This is automatic, best-effort, and does not change script method signatures. Script Agent Core Memory and Worldbook injection are disabled by default.
- Depending on the Agent Knowledge override and active Session KB bindings, the core may append a `Retrieved Knowledge` system-context block before `ctx.llm.*` provider calls. This is automatic, best-effort, and does not change script method signatures. Retrieval warnings are recorded in run metadata without storing full snippet content.
- `ctx.llm.unload()` is legacy capability-runtime unload if the LLM runtime supports it and also returns structured outcome data when available.
- Script manual unload records run metadata, refreshes affected provider status when possible, and should surface success through the current run step rather than creating another assistant message.

Internal JSON streaming, hidden from chat:

```python
import json

chunks = []
async for chunk in ctx.llm.stream(system="Return JSON.", user=ctx.input.text):
    chunks.append(chunk.text)
data = json.loads("".join(chunks))
await ctx.reply_markdown(render_report(data))
```

Public streaming:

```python
await ctx.llm.stream_to_output(system="Reply in markdown.", user=ctx.input.text)
```

Or:

```python
async for chunk in ctx.llm.stream(system="Reply.", user=ctx.input.text):
    await ctx.output.write_delta(chunk.text)
await ctx.output.finish()
```

### Reply helpers

- `reply_text`: send plain text.
- `reply_markdown`: send markdown-rendered content.
- `reply_json`: send a JSON object or array.
- `reply_image`: send one image payload with `url`.
- `reply_images`: send an ordered image gallery.
- `reply_blocks`: send ordered rich content blocks.
- `reply_form` / `reply_action_form`: validate and send one `action_form` block as `rich_content`.
- `reply_file_content`: send raw file text, not markdown-rendered content.
- Reply helpers accept optional message metadata for durable structured details such as generated image recipe metadata.

## Attachments in Script Agents

- `ctx.input.attachments` contains current input attachment metadata.
- `ctx.read_attachment_text(attachment_or_id)` reads trusted local text attachment content.
- `ctx.read_attachment_bytes(attachment_or_id)` reads trusted local bytes.
- `ctx.attachment_as_data_url(attachment_or_id)` returns a data URL for image/file handoff.
- `await ctx.save_attachment_bytes(data, filename, mime_type, kind="file", metadata=None)` stores generated bytes as a local attachment and links it to the current output message/run.
- `await ctx.save_attachment_base64(data_base64, filename, mime_type, kind="file", metadata=None)` decodes base64 or a data URL, stores it as a local attachment, and links it to the current output message/run.
- Image attachments can be read by scripts regardless of Prompt Agent vision support.
- Text/code/config files can be read by scripts through helpers; Prompt Agent file context is controlled separately by General settings.
- Generated files and images should be saved as attachments and returned through `reply_image` / `reply_images` using the local attachment `url`; do not put large base64 data URLs in message content.

Generated attachment helpers return local attachment metadata:

```json
{
  "id": "uuid",
  "type": "image",
  "mime_type": "image/png",
  "name": "result.png",
  "size": 12345,
  "uri": "local://attachments/<id>.png",
  "url": "/api/attachments/<id>.png",
  "created_at": "2026-05-08T12:00:00Z",
  "metadata": {"source": "optional"}
}
```

## Capabilities

Capability manifests declare internal methods and optional global slash commands.

| field | meaning | notes |
| --- | --- | --- |
| `id` | Global Capability id. | Must be unique and match directory in strict checks. |
| `name` | Display name. | Human-readable. |
| `methods` | Internal callable methods. | Method id must match runtime callable. |
| `input_schema` | Method input contract. | Lightweight manifest metadata. |
| `output.type` | Declared output renderer. | Used by commands and validation. |
| `commands` | User-facing slash commands. | Global namespace; names start with `/`. |
| `safe` | Command safety hint. | Documentation/UI hint, not a sandbox. |
| `config_schema` | Local CapabilityConfig fields. | Settings stores values by capability id. |

Minimal `capability.yaml`:

```yaml
id: demo_tool
name: Demo Tool
methods:
  - id: echo
    input_schema:
      text:
        type: string
        required: true
    output:
      type: text
commands:
  - name: /demo
    method: echo
    description: Echo text.
    safe: true
```

Minimal runtime:

```python
class CapabilityRuntime:
    def echo(self, text: str, context: dict | None = None) -> str:
        return text


def get_runtime():
    return CapabilityRuntime()
```

Runtime call rules:
- Runtime can export `get_runtime()` or `CapabilityRuntime`.
- Strict checks import runtime code and require every manifest method id to exist as a callable.
- Command methods receive `(args, context)` when the runtime callable accepts two parameters.
- Command methods receive only `(args)` when the runtime callable accepts one parameter.
- Script Agents call capabilities through `await ctx.capability("id").method(...)`. When the runtime method accepts a `context` keyword, Script Agent calls receive resolved CapabilityConfig, session id, capability id, and current attachments.
- Capability methods should return plain Python values matching declared output.

Built-in `knowledge` Capability:
- `search(query, knowledge_base_ids=None, session_id=None, top_k=None, max_context_chars=None, debug=True)` returns the core Knowledge search JSON shape, using explicit KB ids when provided or the current Script/command context `session_id` otherwise.
- `list_bases(enabled_only=False)` returns compact KB records with id, name, enabled state, index status, source count, and chunk count.
- `stats(knowledge_base_id=None)` returns compact source/chunk/embedding counts globally or for one KB. It does not read full source originals or return vectors.
- `/kb-search <query>` passes the remaining text as `query`, searches current session active KBs, returns JSON, and does not call an LLM or create an Agent run. Empty input fails clearly; no active KBs returns an empty result with a `No active knowledge bases for this session.` warning.

Capability command manifest metadata may be used by the Intent Routing semantic router as weak diagnostic candidates. The router can record a possible `target_command`, command match source, and top-candidate preview in metadata or Route Test output, but general command-like predictions do not execute commands automatically and do not require any Capability schema change. Core RouteSpec/ActionSpec entries are internal runtime specs and are not added to Agent or Capability manifests. The only command auto-route exception is the narrow built-in `pet_command` allowlist, which may execute exactly one `/pet status`, `/pet wake`, `/pet tuck`, `/pet reload`, or `/pet select <pet_id>` through the normal CommandRunner and Pet Capability runtime after semantic `pet_command`, Utility LLM slots, and Pet validator checks all pass.

Built-in `runtime` Capability:
- `/free-memory <target>` calls the core runtime memory control service. Targets are `llm`, `comfyui`, `embedding`, `reranker`, and `all`.
- The command returns a compact readable markdown result list. Empty input returns `/free-memory [llm|comfyui|embedding|reranker|all]`.
- Memory release is best-effort per target and never deletes model files, knowledge bases, indexes, sessions, or settings.
- Busy targets return `busy` and are not force-released. In this alpha, manual LLM release is limited to LM Studio provider profiles.

Runtime memory API:
- `GET /api/runtime/memory?session_id=<id>` returns target availability summaries with `target`, `available`, `enabled`, `reason`, and `status`.
- `POST /api/runtime/free-memory` accepts `{"targets":["llm"|"comfyui"|"embedding"|"reranker"|"all"],"session_id":"..."}` and returns `{"results":[{"target":"...","status":"freed|skipped|busy|unavailable|failed","message":"..."}]}`.

Runtime resources API:
- `GET /api/runtime/resources` returns a cached local resource snapshot for the Chat header status panel.
- The response includes `cpu`, `memory`, `gpus`, `process.backend_memory_bytes`, and `updated_at`.
- CPU/RAM and backend process memory use base dependency `psutil`. GPU/VRAM uses NVML-compatible Python bindings when available. Missing or failed backends return unavailable fields instead of failing the API.
- Unavailable resource objects may include `reason`, for example `{"available": false, "reason": "psutil unavailable"}` for CPU/RAM or a NVML error for GPU/VRAM.
- Sampling is cached for a few seconds so Chat polling does not resample hardware on every request.

Reusable integration Capabilities should expose narrow protocol methods plus small helpers when that makes Agent code simpler. For example, the `comfyui` Capability exposes REST-only workflow submission, non-blocking prompt status, queue/history reads, blocking convenience polling, output extraction, image fetching, interrupt, upload, object-info, and `free_memory` methods. `free_memory` posts to ComfyUI `/free` with `unload_models` and `free_memory` booleans and returns a structured JSON outcome; it is not a slash command or user-facing Agent action. The Capability returns JSON contracts with image references or optional base64 image content; Script Agents remain responsible for attachments, user-visible progress, memory-release workflow choices, and final rendering.

The `comfyui` Capability also manages local workflow and preset library directories through CapabilityConfig. It can scan top-level API-format workflow JSON files, compute canonical workflow hashes, detect duplicate workflow content, load and validate preset YAML files, report per-workflow draft preset skip reasons, and create unmapped draft presets when configured. Preset files remain the durable user asset; session recipes are runtime state.

The built-in `comfyui_agent` Script Agent exposes user-callable `fresh` and `refine` actions as one-shot LLM prompt operations. Its AgentConfig `llm_operation_default` controls whether normal `default`/`llm` LLM-mode input uses `refine` or `fresh`; the stored recipe `input_mode` remains only `llm` or `raw`. Template config keys are `llm_refine_system_prompt`, `llm_refine_user_template`, `llm_fresh_system_prompt`, and `llm_fresh_user_template`.

General settings include `auto_generate_session_titles`, `session_title_backend`, `session_title_model_profile_id`, `session_title_unload_after_generation`, `session_title_prompt`, and `session_title_max_input_chars`. These control the core automatic title pre-hook for the first user message that resolves to an LLM-capable Agent/action and are read through `GET /api/settings/general` / `PATCH /api/settings/general`.

Title settings:
- `session_title_backend`: `"utility_llm"`, `"follow_agent_model_profile"`, or `"specified_model_profile"`. Default is `"utility_llm"`.
- `session_title_model_profile_id`: optional Model Profile id used only when `session_title_backend="specified_model_profile"`. `null` is valid to save; runtime skips title generation with a warning until a usable profile is selected.
- `session_title_unload_after_generation`: boolean, default `false`. When enabled, title model release is best-effort and must not unload the model currently generating the main response.

Title generation metadata is stored compactly under `metadata.title_generation` on the run and in `Session.title_generation_metadata`. It may include `state`, `requested_backend`, `backend`, `fallback_used`, `fallback_reason`, `model_profile_resolution`, `model_profile_id`, `trigger`, `trigger_agent_id`, `invoked_agent_id`, `invoked_action_id`, `input_override_model_profile_id`, `unload_after_generation`, `unload_state`, truncation counts, public model/provider ids, and compact warnings. It must not include full prompts, raw model output, full user input, Knowledge snippets, Core Memory, Worldbook content, or secrets. `backend="model_profile"` indicates the Provider/Profile path; Utility LLM backends remain internal Utility LLM identifiers. Allowed unload states are `not_requested`, `released`, `deferred_until_run_end`, `no_supported_release`, `failed`, and `skipped_no_model`.

Utility LLM is a core internal service for short tasks. It is not a Capability, Command, Provider Profile, Model Profile, AgentConfig field, or manifest field. Its backend, optional Model Profile reference, model path, device, and llama.cpp options live in General settings and are displayed under Settings -> General -> Utility LLM. Model paths are relative to `data/models`, use POSIX-style separators, and reject absolute paths, `..`, empty segments, and backslashes. The backend never downloads models or installs optional dependencies. When the backend is `model_profile`, Utility LLM makes an internal non-streaming low-temperature call through the selected Model Profile and does not create an Agent run, visible message, Intent Routing call, title trigger, session selected profile mutation, or main response LLM resolution change.

Related General settings:
- `intent_routing_utility_llm_backend`: `"transformers"`, `"llama_cpp"`, or `"model_profile"`, default `"transformers"`.
- `intent_routing_utility_llm_model_profile_id`: optional LLM Model Profile id used only when `intent_routing_utility_llm_backend="model_profile"`. `null` is valid to save; missing or disabled profiles are reported as unavailable at runtime.
- `intent_routing_utility_llm_model_path`: empty or a backend-specific path.
- `intent_routing_device`: `"auto"`, `"cpu"`, or `"cuda"` for the transformers backend.
- `intent_routing_utility_llm_context_size`: llama.cpp context size, default `4096`, range `512..32768`.
- `intent_routing_utility_llm_gpu_layers`: llama.cpp GPU layer count, default `0`, range `-1..200`.
- `intent_routing_utility_llm_threads`: optional llama.cpp thread count, default `null`, range `1..128`.
- `intent_routing_embedding_model_profile_id`: optional Knowledge Embedding Model Profile id used by Intent Routing semantic embedding routing. Defaults to `null`. This is the only semantic router profile selection field returned by current General settings clients. Old persisted `intent_routing_embedding_model_path` values are ignored if present.
- `intent_routing_semantic_intent_min_score`: semantic auto-route intent score threshold, default `0.50`.
- `intent_routing_semantic_intent_min_margin`: semantic auto-route grouped intent margin threshold, default `0.03`.
- `intent_routing_semantic_kb_min_score`: semantic Knowledge Base candidate threshold, default `0.45`.
- `intent_routing_semantic_agent_min_score`: semantic Agent diagnostic candidate threshold, default `0.45`.
- `intent_routing_semantic_command_min_score`: semantic command diagnostic candidate threshold, default `0.45`.

Utility LLM path contract:
- `transformers`: `utility_llms/<folder>`, for example `utility_llms/Qwen3-0.6B`.
- `llama_cpp`: `utility_llms/<model-folder>/<file>.gguf`, for example `utility_llms/qwen3-0.6b/Qwen3-0.6B-Q4_K_M.gguf`.
- `model_profile`: no local model path is required; the backend uses `intent_routing_utility_llm_model_profile_id`.
- GGUF files directly under `utility_llms`, such as `utility_llms/model.gguf`, are invalid and ignored by scan. GGUF files must be placed under `data/models/utility_llms/<model-folder>/<file>.gguf`.

Utility LLM APIs:
- `GET /api/intent/utility-llm/status` returns availability, configuration, loaded state, selected `backend`, model path, requested/resolved device, backend options, dependency flags under `backend_status`, and a compact reason such as `model_path_not_configured`, `model_not_found`, `backend_model_path_mismatch`, `model_path_invalid`, `UTILITY_LLM_BACKEND_UNAVAILABLE`, or `llama_cpp_unavailable`. For `model_profile`, it returns public fields such as `model_profile_id`, `model_profile_name`, `provider_profile_id`, `provider_label`, and `requested_model_id`, plus reasons such as `model_profile_not_configured`, `model_profile_not_found`, `model_profile_disabled`, or `provider_profile_unavailable`. It does not load a local model and does not generation-test providers.
- `GET /api/intent/utility-llm/models/scan` creates `data/models/utility_llms` if needed and returns `transformers_models`, one-level nested `gguf_models`, backend dependency flags, and warnings such as `root_gguf_ignored`. It does not load weights, download files, install dependencies, or create database records.
- `POST /api/intent/utility-llm/test-title` accepts `{"text":"..."}` and returns `{"ok":true,"title":"...","backend":"utility_llm:transformers","warnings":[]}`, `utility_llm:llama_cpp`, or `utility_llm:model_profile` when generation succeeds. Model Profile responses include only public profile/provider/model identifiers. Failures return `ok=false` with a structured reason such as `model_profile_not_configured`, `model_profile_not_found`, `model_profile_disabled`, `provider_profile_unavailable`, or `model_profile_generation_failed`.
- `POST /api/intent/utility-llm/test-json` accepts `{"text":"..."}` and returns strict extracted intent JSON plus compact slots. It may load the configured local model or call the configured Model Profile. Invalid JSON returns `ok=false` with `reason="utility_llm_invalid_json"`; raw model output is not returned.
- `POST /api/intent/utility-llm/unload` releases only the local Utility LLM cache. It does not unload the main LLM, embeddings, reranker, or ComfyUI. For `model_profile`, it returns `no_local_utility_cache` and does not call global LLM unload.
- `POST /api/intent/test-route` accepts `{"text":"...","session_id":null,"default_agent_id":null,"include_utility":true}` and returns `{"ok":true,"decision":{...}}`. It is a diagnostic route decision only: it creates no message, creates no run, executes no command, sends no ComfyUI request, performs no Knowledge retrieval, and does not change session defaults or Context Sources bindings. Without `session_id`, the decision is marked as a no-session simulation. The response mirrors auto-mode execution semantics with compact fields such as `auto_executable`, `would_execute`, `route_action`, `not_executed_reason`, `thresholds_used`/`semantic_thresholds_used`, `temporary_knowledge_base_ids`, `knowledge_query_override`, semantic score/margin, `intent_group_scores`, target ids, candidate previews, slots, and warnings.

Intent Routing embedding profile selection:
- The profile id references `GET /api/knowledge/embedding-models` records owned by Knowledge settings.
- Saving settings does not require loading or testing the embedding model.
- The selected profile is used by the semantic router for route candidates and current-message query embeddings. Candidate vectors are kept in a lazy in-memory cache and are not persisted.
- If a selected profile is missing or disabled, Settings should show an unavailable state without crashing. Runtime falls back to the current Prompt Agent path and records compact semantic-unavailable warnings. No fallback classifier runs, and Route Test/metadata must not include fallback classifier fields.

## Knowledge Settings, Local Model APIs, Indexing, And Search

Knowledge RAG v1 adds Workbench-owned settings, local model APIs, and source indexing APIs. These are internal Workbench JSON APIs, not provider function calling, tool calling, or OpenAI-compatible embedding endpoints.

Core Memory and Worldbook are also Workbench-owned settings/storage APIs. They are not Agent or Capability manifest fields, and they are not provider tool/function schemas.

Core Memory:

- Stored in General settings through `GET /api/settings/general` and `PATCH /api/settings/general`.
- Fields are `core_memory_content`, `core_memory_enabled_for_prompt_agents`, and `core_memory_enabled_for_script_agents`.
- Defaults are empty content, Prompt Agents enabled, and Script Agents disabled.
- Runtime injects non-empty trimmed Core Memory as a system-context block for Prompt Agent main LLM calls when Prompt Agents are enabled, and for Script Agent `ctx.llm.*` calls when Script Agents are enabled. Run metadata records only enablement, injection status, character count, skipped reason, and warnings.

Worldbook settings:

- `GET /api/worldbook/settings`
- `PATCH /api/worldbook/settings`

Fields are `worldbook_enabled_for_prompt_agents`, `worldbook_enabled_for_script_agents`, `worldbook_max_entries_per_call`, `worldbook_max_context_chars`, `worldbook_recursion_depth`, `worldbook_case_sensitive`, `worldbook_whole_words`, and compatibility field `worldbook_regex_case_insensitive`. Unknown fields are rejected. Max entries is bounded to 1-200, max context chars to 1000-200000, and recursion depth to 0-5. The user-facing case setting is `worldbook_case_sensitive`; when the legacy case-insensitive field is patched, the backend maps it to the inverse case-sensitive value.

Worldbook APIs:

- `GET /api/worldbooks`
- `POST /api/worldbooks`
- `GET /api/worldbooks/{worldbook_id}`
- `PATCH /api/worldbooks/{worldbook_id}`
- `DELETE /api/worldbooks/{worldbook_id}`
- `GET /api/worldbooks/{worldbook_id}/entries`
- `POST /api/worldbooks/{worldbook_id}/entries`
- `GET /api/worldbook-entries/{entry_id}`
- `PATCH /api/worldbook-entries/{entry_id}`
- `DELETE /api/worldbook-entries/{entry_id}`
- `PATCH /api/worldbooks/{worldbook_id}/entries/reorder`
- `GET /api/sessions/{session_id}/worldbooks`
- `PATCH /api/sessions/{session_id}/worldbooks`
- `POST /api/worldbooks/match-test`

Worldbook fields are `id`, `name`, `description`, `enabled`, timestamps, and optional counts. Entry fields are `id`, `worldbook_id`, `name`, `keywords_text`, `content`, `activation_mode`, `enabled`, `sort_order`, and timestamps. `activation_mode` is `always` or `keyword`; `keywords_text` is split on English commas, each trimmed non-empty piece is a regex pattern. Invalid regex is rejected on save and reported as a structured warning by match-test if legacy bad data is encountered.

`GET /api/worldbook-entries/{entry_id}` returns the current entry detail, including `id`, `worldbook_id`, `name`, `activation_mode`, `keywords_text`, `content`, `enabled`, `sort_order`, and timestamps. Chat context inspection uses this endpoint to show current Worldbook entry content from compact run metadata refs; runtime metadata must still store only refs/counts/warnings, not full entry content.

Session Worldbook binding PATCH replaces the session's enabled bindings with ordered `worldbook_ids`. Disabled worldbooks are skipped with warnings. `GET /api/sessions/{session_id}/worldbooks` returns enabled bindings in persisted binding order plus all available worldbooks. Match-test uses explicit `worldbook_ids` first, otherwise active session bindings when `session_id` is provided. Match-test and runtime injection share the same parser and matcher: matching starts with the current input text, adds always-active entries in the initial round, then recursively scans newly activated entry content up to `worldbook_recursion_depth`. Entries are deduped and final order remains session Worldbook binding order followed by entry `sort_order`. Matching does not scan history, assistant messages, command results, Knowledge snippets, or call an LLM. Whole-word matching wraps each pattern with ASCII boundaries `(?<![A-Za-z0-9_])` and `(?![A-Za-z0-9_])`; this prevents English partial-word matches while preserving CJK substring matching. Match-test returns content previews rather than full entry content and includes compact fields such as `recursion_depth`, `recursion_rounds_used`, `case_sensitive`, `whole_words`, per-result `matched_by_recursion`, and warnings.

Settings:

- `GET /api/knowledge/settings`
- `PATCH /api/knowledge/settings`

Knowledge Defaults store local model device, embedding batch/timeout defaults, optional local embedding unload-after-use behavior, the single global reranker configuration, optional reranker unload-after-use behavior, retrieval quality knobs, chunking/index limits, optional query expansion settings, and Knowledge context prompt templates. `models_root` is read-only in v1 and defaults to `data/models`.

The local model unload fields are:

- `unload_embedding_model_after_use`: boolean, default `false`. When true, local embedding model cache entries used by tests, indexing, and search query embedding are released after use.
- `unload_reranker_model_after_use`: boolean, default `false`. When true, the local reranker cache is released after reranking.

Unload is best-effort. It removes local backend cache references, runs Python garbage collection, and empties the torch CUDA cache when CUDA is available. It does not change retrieval, RRF, indexing, or reranker ranking semantics.

Local model directories:

- `data/models/embeddings/<model-folder>`
- `data/models/rerankers/<model-folder>`
- `data/knowledge/sources`

Model paths must be relative to `data/models`, use POSIX-style storage, and match either `embeddings/<folder>` for embedding profiles or `rerankers/<folder>` for the global reranker. Absolute paths and `..` segments are rejected.

Local model scan:

- `GET /api/knowledge/models/scan`

The scan creates the expected local model directories, lists direct child folders without loading model weights, and returns:

```json
{
  "models_root": "data/models",
  "embedding_models": [{"model_path": "embeddings/example", "name": "example", "exists": true}],
  "reranker_models": [{"model_path": "rerankers/example", "name": "example", "exists": true}],
  "backend": {
    "sentence_transformers_available": true,
    "torch_available": true,
    "transformers_available": true,
    "cuda_available": false,
    "available": true
  }
}
```

There is intentionally no `/api/knowledge/models/download` endpoint in this alpha. The frontend may show copyable install and download commands, and `scripts/download_knowledge_model.py` can be run manually from the project root, but the backend does not install dependencies, download models, create profiles, or start model scan jobs. The Download tab must only generate commands; it must not execute shell commands or create background download tasks.

Current Download tab presets:

- Recommended embeddings: `sentence-transformers/all-MiniLM-L6-v2` -> `all-MiniLM-L6-v2`, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` -> `paraphrase-multilingual-MiniLM-L12-v2`, `google/embeddinggemma-300m` -> `embeddinggemma-300m`, `BAAI/bge-m3` -> `bge-m3`.
- Advanced embeddings: `Qwen/Qwen3-Embedding-0.6B` -> `Qwen3-Embedding-0.6B`, `jinaai/jina-embeddings-v3` -> `jina-embeddings-v3`, `nomic-ai/nomic-embed-text-v1.5` -> `nomic-embed-text-v1.5`, `mixedbread-ai/mxbai-embed-large-v1` -> `mxbai-embed-large-v1`.
- Recommended rerankers: `BAAI/bge-reranker-v2-m3` -> `bge-reranker-v2-m3`.
- Advanced rerankers: `Qwen/Qwen3-Reranker-0.6B` -> `Qwen3-Reranker-0.6B`.

Embedding model profile APIs:

- `GET /api/knowledge/embedding-models`
- `POST /api/knowledge/embedding-models`
- `GET /api/knowledge/embedding-models/{id}`
- `PATCH /api/knowledge/embedding-models/{id}`
- `DELETE /api/knowledge/embedding-models/{id}`
- `POST /api/knowledge/embedding-models/{id}/test`

Embedding generation:

- `POST /api/knowledge/embeddings`

Request shape is `{model_profile_id, purpose, inputs}` where `purpose` is `query` or `document`. The API applies the profile instruction for that purpose, validates batch size against Knowledge Defaults, and returns `{model_profile_id, model_path, purpose, dimension, vectors}`. If `unload_embedding_model_after_use` is enabled, the local embedding model used by the request is released after the response is prepared.

Intent Routing semantic router uses the General setting `intent_routing_embedding_model_profile_id` to reference one existing enabled Embedding Model Profile. Route candidate texts are embedded as `purpose=document`; the current user message is embedded as `purpose=query`. The router uses the existing profile path validation, instructions, normalization, Knowledge Defaults device, and local model backend. It does not add a raw embedding path, create profiles, download models, or persist route-candidate vectors.

`POST /api/intent/test-route` returns the Intent Routing v2 pipeline contract. Semantic fields include `source`, `predicted_intent`, `confidence`, `intent_score`, `intent_margin`, `semantic_score`, `semantic_margin`, `semantic_thresholds_used`, `embedding_model_profile_id`, `semantic_index_version`, `intent_group_scores`, `second_intent`, `top_candidates`, `kb_candidate`, `agent_candidate`, `action_candidate`, `command_candidate`, and `warnings`. Spec fields include compact `route_spec_id`, optional `action_spec_id`, `slot_schema_id`, `validator_id`, and `executor_id`. Utility fields include `utility_required`, `utility_available`, `utility_used`, `utility_ok`, `utility_error_code`, and compact `slots`; the Utility backend may be local or `model_profile`, but metadata includes only public identifiers and no raw output or secrets. Validation/execution fields include `validation_ok`, `route_action`, `auto_executable`, `would_execute`, `executed=false`, `executed_in_real_run="route_test_only"`, `not_executed_reason`, `executor_plan`, `temporary_knowledge_base_ids`, and `knowledge_query_override`. For `pet_command`, it may also return compact fields `pet_action`, `target_pet_id`, `target_pet_hint`, `source_pet_id`, `source_pet_hint`, `target_ignored_for_action`, and one `generated_command` after Utility slots and validator checks. `would_execute` uses the same gating result as a real run would use; Route Test itself still never executes. Top candidates contain only compact previews, not embeddings or full route examples. Agent actions and general Capability commands are weak diagnostic candidates only; no Agent action, slash command, ComfyUI run, or Knowledge retrieval is executed by Route Test, including `/pet`.

Runtime `metadata.intent_routing` records the same execution contract compactly: `pipeline_version`, `evaluated`, `semantic_evaluated`, `skip_reason`, `source`, `route_spec_id`, `action_spec_id`, `slot_schema_id`, `validator_id`, `executor_id`, `predicted_intent`, `intent_score`, `intent_margin`, `semantic_thresholds_used`, `utility_required`, `utility_available`, `utility_used`, `utility_ok`, `utility_error_code`, `validation_ok`, `auto_executable`, `executed`, `route_action`, `not_executed_reason`, `executor_plan`, `temporary_knowledge_base_ids`, `knowledge_query_override`, `kb_candidate`, compact grouped intent scores, and warnings. For `pet_command`, it also records compact Pet fields such as `pet_action`, `target_pet_id`, `target_pet_hint`, `source_pet_id`, `source_pet_hint`, `target_ignored_for_action`, and `generated_command`. Natural-language `pet_command` auto execution preserves the original user text as the visible user message; `generated_command` is metadata/internal command input only and must not replace that message or create a synthetic `/pet ...` user message. It must not store embeddings, full candidates, full specs, raw Utility LLM output, prompts, KB content, Worldbook content, Core Memory content, full Pet manifests, spritesheet bytes, image content, or a duplicate full `original_user_text` field when the message body already stores it.

Utility LLM extractor contract for Intent Routing: input is limited to the current user text, semantic top intent/action candidate, compact top RouteSpec/ActionSpec context, compact slot schemas, compact KB list/name/aliases, compact Pet candidates when `predicted_intent=pet_command`, and safety boundaries. It must not receive full chat history, Agent prompts, KB content, Worldbook content, Core Memory content, raw embeddings, full specs/examples, or full candidate lists. Output is strict JSON and is only slot input to validators. The parser accepts a JSON object, fenced `json` object, or a response with a leading/trailing explanation and one balanced JSON object; malformed JSON records `utility_invalid_json`, while missing required slots or invalid enum values record `utility_slots_failed`. Extra fields are ignored. `knowledge_query` slots include `intent`, `query`, `kb_hint`, and optional `use_original_query`; `pet_command` slots include `intent`, `domain`, `action`, `target_pet_hint`, `source_pet_hint`, and optional `target_pet_explicit` / `source_pet_explicit`. Utility/semantic conflicts, missing KBs or Pets, non-Workbench pet domains such as `not_workbench_pet_context`, and invalid actions are validator failures, not execution instructions.

Reranking:

- `POST /api/knowledge/rerank`

The reranker uses Knowledge Defaults `reranker_enabled` and `reranker_model_path`. It returns sorted `{id, score}` results or structured errors such as `KNOWLEDGE_RERANKER_DISABLED`, `KNOWLEDGE_RERANKER_MODEL_NOT_CONFIGURED`, `KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE`, or `KNOWLEDGE_MODEL_NOT_FOUND`. If `unload_reranker_model_after_use` is enabled, the local reranker is released after the rerank attempt, including fallback paths where retrieval keeps RRF order.

Knowledge base APIs:

- `GET /api/knowledge/bases`
- `POST /api/knowledge/bases`
- `GET /api/knowledge/bases/{id}`
- `PATCH /api/knowledge/bases/{id}`
- `DELETE /api/knowledge/bases/{id}`

Knowledge Base create, read, and patch payloads include `aliases_text`, a comma-separated string used only by Intent Routing KB hint matching. Aliases are trimmed, empty pieces are ignored, duplicate aliases are removed case-insensitively, each alias is capped, and the stored list is capped. Patching only `aliases_text` does not change embedding profiles, index status, sources, chunks, retrieval ranking, RRF, or reranker behavior.

Knowledge source indexing APIs:

- `GET /api/knowledge/bases/{id}/sources`
- `POST /api/knowledge/bases/{id}/sources`
- `GET /api/knowledge/sources/{source_id}`
- `DELETE /api/knowledge/sources/{source_id}`
- `POST /api/knowledge/sources/{source_id}/reindex`
- `POST /api/knowledge/bases/{id}/reindex`

`POST /api/knowledge/bases/{id}/sources` supports pasted text:

```json
{"source_type": "pasted_text", "title": "Notes", "text": "..."}
```

and text attachments:

```json
{"source_type": "attachment_text", "attachment_id": "local://attachments/<id>.txt"}
```

The indexer validates source size and chunk limits, chunks text, embeds chunks with the KB embedding model profile using `purpose=document`, stores vectors as float32 SQLite BLOBs, and writes FTS5 rows. Pasted source originals are saved under `data/knowledge/sources/<source_id>.txt`; full pasted source text is not stored in `kb_sources`. Attachment indexing reads existing local text attachments and does not delete or modify the original attachment.

Markdown sources use chunk profiles: `plain_text`, `markdown_document`, `markdown_collection`, and `markdown_auto`. Markdown defaults to `markdown_auto`; non-Markdown text stays `plain_text`. Frontmatter may override the detector with `chunk_profile: markdown_document`, `chunk_profile: markdown_collection`, or `chunk_profile: plain_text`. The parser supports simple frontmatter, ATX headings `#` through `######`, heading paths, source line/character offsets, and ignores headings inside fenced code blocks. Per-chunk metadata is compact and stored in `kb_chunks.metadata_json`: `chunk_title`, `document_title`, `entity_type`, `heading_path`, `line_start`, `line_end`, `char_start`, `char_end`, `chunk_profile_requested`, `chunk_profile_effective`, `chunk_profile_confidence`, `title_source`, and `type_source`.

`chunk_title` is the RAG chunk retrieval title and embedding `Title:` value. It is not Semantic Router metadata and is not session title metadata. `markdown_auto` uses deterministic scoring and falls back to `markdown_document` on low confidence. This contract does not add directory import, automatic sync, file watching, or automatic reindexing.

Index responses include `source_id`, `status`, `chunks`, `embedding_model_profile_id`, `embedding_dimension`, `indexed_at`, and `error`.

Chunk inspection endpoints such as `GET /api/knowledge/chunks/{chunk_id}` and `GET /api/knowledge/sources/{source_id}/chunks` return chunk content plus compact `metadata`; they do not return vectors or full source originals.

Knowledge search:

- `POST /api/knowledge/search`

Request shape:

```json
{"query": "...", "knowledge_base_ids": ["kb_id"], "session_id": null, "top_k": 6, "max_context_chars": 10000, "min_score_threshold": null, "max_chunks_per_source": null, "max_chunks_per_knowledge_base": null, "expand_query": null, "debug": true}
```

`query` is required and non-empty. Provide either explicit `knowledge_base_ids` or `session_id`; explicit KB ids win. Search uses only enabled KBs. Vector search is grouped by embedding model profile and never compares scores across different embedding models directly. Keyword search uses FTS5/BM25 across selected KBs. Candidates are deduped by `chunk_id`, merged with RRF, optionally reranked once globally, filtered by min score and per-source/per-KB chunk limits when configured, then trimmed by `top_k` and `max_context_chars`.

When query expansion is enabled, search asks the resolved LLM runtime for short query variants before retrieval, searches the original query plus variants, dedupes candidates during RRF merge, and falls back to the original query with a debug warning if expansion fails. The search API can override expansion with `expand_query`; automatic Agent Knowledge injection uses the current run LLM runtime and does not recursively trigger Knowledge retrieval.

Response shape:

```json
{"query": "...", "results": [{"rank": 1, "chunk_id": "...", "content": "...", "rrf_score": 0.031, "rerank_score": null}], "context_preview": "# Retrieved Knowledge\n...", "debug": {"warnings": [], "before_filter_count": 3, "final_result_count": 1}}
```

Phase 4 adds automatic Prompt Agent and Script Agent Knowledge context injection plus a chat session KB picker. Phase 5 adds a thin `knowledge` Capability and `/kb-search` command that wrap the same core retrieval path for explicit debugging/manual search. Current non-goals: `local_file` sources, directory import, automatic sync, automatic reindexing, automatic model download, and changes to retrieval ranking/model backends.

Session bindings:

- `GET /api/sessions/{session_id}/knowledge-bases`
- `PATCH /api/sessions/{session_id}/knowledge-bases`

PATCH replaces the session's enabled bindings with ordered `knowledge_base_ids`. Responses are ordered `SessionKnowledgeBinding` records with `knowledge_base_id`, `enabled`, `sort_order`, timestamps, and optional compact `knowledge_base` data. Binding order is a persisted UI/session contract and future extension point; it does not change retrieval ranking semantics.

The Chat header Context Sources modal is a frontend workflow over the existing Knowledge Base and Worldbook session binding APIs. It is not a new Capability, slash command, provider tool schema, or runtime injection protocol.

## Capability Config

- `config_schema` declares Settings fields.
- Stored CapabilityConfig is local state, not part of the package manifest.
- Runtime command context receives `capability_config` after schema validation.
- Unknown config keys are rejected by API validation.

## Output Payloads

| output type | use when | minimal shape | common pitfall |
| --- | --- | --- | --- |
| `text` | Plain text. | `"hello"` | Markdown is not rendered as markdown. |
| `markdown` | Rendered markdown. | `"**hello**"` | Do not use for raw file dumps. |
| `json` | Structured data display. | `{"ok": true}` | Lists are valid command output but `reply_json` expects object or array. |
| `image` | One renderable image. | `{"url": "data:image/png;base64,..."}` | Missing `url` fails validation. |
| `image_gallery` | Multiple images. | `{"images": [{"url": "..."}]}` | Each image must satisfy image payload shape. |
| `file_content` | Raw text file display. | `{"content": "...", "filename": "a.txt"}` | It is raw text and does not go through markdown rendering. |
| `rich_content` | Ordered mixed blocks. | `{"blocks": [{"type": "markdown", "text": "..."}]}` | Keep block order explicit. |
| `action_form` block | Declarative form inside `rich_content`. | `{"type": "action_form", "form_id": "demo", "title": "Demo", "fields": [{"name": "prompt", "type": "text"}], "submit": {"action_id": "run", "visibility": "silent"}}` | Forms submit only to internal Agent actions. |
| `command_buttons` block | Send-message shortcut buttons inside `rich_content`. | `{"type": "command_buttons", "buttons": [{"label": "Run recipe", "message": "@comfyui_agent:run"}]}` | Buttons send ordinary user messages only. |

If a command returns a dict with no declared output, the runner may infer `json`, `image`, `image_gallery`, or `rich_content`.

### `action_form` rich content block

`action_form` is a declarative JSON block. It supports `text`, `textarea`, `integer`, `float`, `boolean`, `enum`, and `json` fields. It does not support HTML, frontend custom JavaScript, arbitrary URLs, file uploads, password/secret fields, remote options, or automatic execution.

Top-level fields:
- `type`: must be `action_form`.
- `form_id`: required string, unique within the message.
- `title`: required display title.
- `description`: optional help text.
- `ui`: optional form-level UI metadata. Supported keys are `default_collapsed`, `collapsed`, `collapse_on_success`, and `collapsed_message`.
- `fields`: required array of field declarations.
- `sections`: optional array of static layout section declarations shaped as `{key, title?}`.
- `submit`: required object.

Form-level `ui` fields:
- `default_collapsed`: optional boolean, used only for first render when `collapsed` is absent. Missing means expanded.
- `collapsed`: optional boolean persisted form state. When present, it takes precedence over `default_collapsed`.
- `collapse_on_success`: optional boolean. Trusted backend code may use this after a successful silent save to return an `updated_form` or emit `message_updated` with the source form collapsed.
- `collapsed_message`: optional short text shown in collapsed state, such as `Recipe saved. Click to expand.`

Collapsed state is frontend UI state on the same `action_form` block. It does not change the form submission protocol, submit target resolution, field values, provider-bound context, or the rule that the frontend submits only `source_message_id`, `form_id`, and `values`. Field `name` values remain submission keys; they are not DOM ids, and renderers should derive globally unique DOM ids per rendered form instance.

Field declarations use `name`, `type`, optional `label`, `description`/`help`, `required`, `value`, `default`, `placeholder`, numeric bounds/`step`, text length bounds, enum `options: [{"value": "...", "label": "..."}]`, and optional static UI metadata:

- `ui.section`: optional section key. Fields with the same section render in one section container.
- `ui.span`: optional integer from 1 to 12 for the frontend 12-column form grid.

Section order comes from the first occurrence of each `field.ui.section` in the `fields` array. Field order within a section is exactly the `fields` array order. If a field has no `ui.section`, it belongs to the default section. If `field.ui.section` has no matching top-level `sections` entry, the frontend may derive a title from the key. `ui.order` is not supported; reorder the `fields` array instead. The first version supports only static section grouping and grid span metadata. It does not support nested layout, collapsible sections, row layout DSL, or dynamic onchange refresh.

Grid rendering is frontend behavior. Typical spans are `12` for long fields such as `textarea`, `json`, and prompt text, `6` for medium text/select fields, and `4` or `3` for compact numeric, boolean, and enum fields. Small screens may collapse to one column.

Submit declarations use optional `label`, optional `agent_id`, required `action_id`, optional `message`, optional `visibility`, optional `success_message`, and optional `failure_message`. If `agent_id` is omitted, the source message Agent is used. `visibility` defaults to `"message"` and may be `"message"` or `"silent"`.

On submit, the frontend sends only `source_message_id`, `form_id`, and `values`. The backend reads the original message, finds the matching `action_form`, resolves the submit target and visibility from that original block, and validates values against the original fields. Request body `agent_id`, `action_id`, or `visibility` cannot override the original form target or visibility.

With `visibility="message"`, the backend creates a `form_submission` user message with a short summary body and invokes the target Agent action. This is the default and preserves older form behavior.

With `visibility="silent"`, the backend invokes the target Agent action without creating a visible user message and suppresses normal assistant output from reply helpers or public output streaming. The target Script Agent still receives validated values in `ctx.input.prefill`, `ctx.input.form_id`, `ctx.input.source_message_id`, and `ctx.input.is_silent_submission=true`, so it can save state, save a recipe, or update settings. Successful silent submissions return a structured response with `silent=true` and a user-facing message from `submit.success_message` or `"Saved"`. A Script Agent may return `{"updated_form": {"source_message_id": "...", "form_id": "...", "block": {...}}}` after it has rebuilt and persisted a replacement source `action_form`; the frontend can use that payload, or the corresponding `message_updated` event, to refresh the existing form without adding chat messages. The replacement block may set `ui.collapsed=true` to collapse the same source form after a successful silent save while retaining all fields and values for later expansion. Failed silent submissions return a structured error; `submit.failure_message` may be used as an error prefix.

Forms may edit runtime state such as a session recipe. Preset selectors and other field groups are static while the user edits a rendered form; there is no dynamic onchange refresh. If a silent submit changes the saved state enough to require different fields, the target action can save the state and replace the source message form block from trusted backend code. The frontend still submits only `source_message_id`, `form_id`, and values; it must not submit a replacement form block. The ComfyUI Agent uses `action_form` as a recipe editor only; form submission does not submit generation, choose input mode, or collect the LLM user request.

### `command_buttons` rich content block

`command_buttons` renders trusted send-message shortcut buttons. It is not a message action, hidden Agent action, URL, JavaScript hook, or form submit.

Top-level fields:
- `type`: must be `command_buttons`.
- `buttons`: required array of button declarations.

Button declarations use:
- `label`: required display text.
- `message`: required user message text to send through the normal composer route.

On click, the frontend sends `message` through the same ordinary user-message path as manual composer input. It creates a normal user message, uses normal routing, and does not send `prefill`, attachments, hidden action payloads, arbitrary URLs, or executable frontend code.

## Validation and CLI

```powershell
uv run python scripts/check_agents.py --strict
uv run python scripts/run_agent.py demo "hello"
uv run python scripts/run_command.py "/demo hello"
```

## Source and Tests

Source:
- `ai_workbench/core/script.py`
- `ai_workbench/core/runner.py`
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/capability_registry.py`
- `ai_workbench/core/capability_runtime.py`
- `frontend/src/components/MessageBubble.tsx`
- `frontend/src/store/useWorkbenchStore.ts`

Tests:
- `tests/test_script_agent.py`
- `tests/test_prompt_agent_execution.py`
- `tests/test_frontend_chat_contracts.py`
- `tests/test_api.py`
