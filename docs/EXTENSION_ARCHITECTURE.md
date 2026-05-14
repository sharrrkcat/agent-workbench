# Extension Architecture

## Purpose

Extension Architecture is the design guide for complex Agent Workbench extensions.

It complements:

- `docs/EXTENSION_API.md`: concrete Agent, Capability, ctx, and output APIs.
- `docs/RUNTIME_PROTOCOLS.md`: streaming, run lifecycle, attachments, and LLM resolution.
- `docs/generated/REGISTRY.md`: current installed Agents and Capabilities.

Use this document before writing code for an external integration, local workspace tool,
knowledge bridge, long task Agent, or LLM-assisted tool workflow.

This is not a tutorial.

This is not a product-specific recipe.

This document answers architecture questions about Agent/Capability split,
configuration ownership, output payloads, run steps, streaming, safety, and tests.

## Extension Categories

### Pure Agent

Use when:

- The extension only interprets user input.
- The extension calls an LLM and returns text, JSON, images, or rich content.
- The behavior is primarily prompt and workflow logic.
- The result does not need reusable low-level tools.

Typical components:

- `agents/<agent_id>/agent.yaml`.
- Optional `agents/<agent_id>/agent.py` for Script Agents.
- LLM prompt, action definitions, context policy, and output rendering.

Common pitfalls:

- Creating a Capability only for prompt formatting.
- Hiding reusable protocol or file code inside one Agent.
- Treating LLM output as trusted structured data without validation.

### Tool Capability

Use when:

- The extension provides a clear reusable tool.
- Multiple Agents or slash commands can use the same behavior.
- Inputs and outputs can be expressed as stable method contracts.
- The behavior can be unit tested without chat UI.

Typical components:

- `capabilities/<capability_id>/capability.yaml`.
- `capabilities/<capability_id>/__init__.py`.
- Optional slash commands declared in the Capability manifest.

Common pitfalls:

- Letting a Capability decide conversational style.
- Returning user-facing prose from low-level methods when structured data is better.
- Adding a slash command to an Agent instead of a Capability.

### External Service Integration

Use when:

- The extension talks to an external HTTP/API service.
- The service has its own protocol, authentication, request shape, errors, or limits.
- More than one Agent may need the same service client.

Typical components:

- A Capability for service protocol, auth, retries, timeouts, and normalized errors.
- A Script Agent for user-facing workflow, LLM planning, progress, and final output.
- Tests with a fake runtime or mock HTTP server.

Common pitfalls:

- Calling the external service directly from Agent workflow code.
- Storing API keys in `agent.yaml`.
- Returning temporary remote URLs as the only durable output.
- Requiring a real service in automated tests.

### Local Workspace Integration

Use when:

- The extension reads or writes local directories, files, notes, or project data.
- The extension needs allowlists, size limits, path validation, or write controls.
- The same local workspace operations may be reused by several Agents.

Typical components:

- A Capability for path validation, read/write operations, and conflict handling.
- A Script Agent for user intent, preview/write decisions, LLM transforms, and summaries.
- Tests using temporary directories.

Common pitfalls:

- Allowing paths outside configured roots.
- Letting raw LLM output overwrite files directly.
- Making write behavior unconditional.
- Mixing workspace safety checks into prompt text.

### Long-running Workflow

Use when:

- The extension submits a job and waits for completion.
- The operation has phases such as validate, submit, poll, fetch, save, and render.
- Cancellation or timeout needs explicit behavior.
- Users need progress visibility.

Typical components:

- Capability methods for submit, poll/status, fetch, and cancel when supported.
- Script Agent steps for user-visible phases and progress.
- Configurable timeouts and polling intervals.

Common pitfalls:

- Blocking the event loop with synchronous polling loops.
- Creating a run step for every helper function.
- Polling forever without max wait or cancellation checks.
- Losing completed outputs because final rendering failed.

### Knowledge Bridge

Use when:

- The extension turns files, pages, wiki data, or notes into LLM-usable context.
- It may index, summarize, link, search, preview, or write back knowledge.
- It separates raw source access from user-facing synthesis.

Typical components:

- Capability methods for source read/search/write and metadata extraction.
- Script Agent logic for summarization, concept extraction, linking, and review.
- Mock LLM outputs and temp source data in tests.

Agent Workbench Knowledge v1 local model foundation:

- Phase 1 owns local Knowledge settings and model APIs in the core application rather than a Capability manifest.
- Phase 2 owns source indexing, chunk storage, vector BLOB storage, and FTS5 rows in the core application rather than a Capability manifest.
- Phase 3 owns explicit retrieval search in the core application rather than a Capability manifest: SQLite vector BLOB brute-force search, FTS5/BM25 keyword search, RRF merge, one optional global rerank pass, and context-budget trimming.
- Phase 4 owns session Knowledge context injection in the core runtime rather than a Capability manifest: Chat sessions bind enabled KBs, Prompt Agents inject by default during `Building context`, and LLM Script Agents inject only when AgentConfig overrides enable it.
- Phase 5 adds a thin `knowledge` Capability around core retrieval and Knowledge store status. `knowledge.search` and `/kb-search` call the existing core search service; `list_bases` and `stats` inspect compact store metadata. The Capability does not own retrieval algorithms, indexing, embedding, reranking, model downloads, or automatic context injection.
- Local model directories are `data/models/embeddings/<model-folder>` and `data/models/rerankers/<model-folder>`.
- Local source staging starts at `data/knowledge/sources`; pasted source originals are written there as `<source_id>.txt`.
- Embedding model profiles bind a user-named profile to an `embeddings/<folder>` model path.
- Knowledge Defaults hold the single global reranker setting with a `rerankers/<folder>` model path.
- The local embedding and reranker APIs use Workbench JSON shapes and optional local dependencies; missing optional dependencies must not prevent normal chat startup.
- `kb_sources` owns source metadata and local source references, not full pasted source text.
- `kb_chunks` owns indexed chunk content and source offsets.
- `kb_embeddings` owns embedding snapshots and float32 vector BLOBs.
- `kb_chunk_fts` owns keyword-search rows for future BM25 retrieval.
- Local-file sources, automatic model download, and retrieval/indexing/backend changes remain later phases.

Common pitfalls:

- Treating generated summaries as source truth.
- Skipping source path validation.
- Returning only prose when raw note/file previews are needed.
- Letting indexing tests depend on a real personal knowledge base.

### LLM-assisted Tool Orchestration

Use when:

- The LLM extracts structure, drafts a plan, or generates tool parameters.
- Script code validates and normalizes that plan.
- Capabilities execute the validated operations.

Typical components:

- Internal LLM calls through `ctx.llm.text`, `ctx.llm.json`, or `ctx.llm.stream`.
- Pydantic or equivalent validation in script code.
- Capability calls for external effects.
- Public output only after validation and execution decisions.

Common pitfalls:

- Trusting raw LLM JSON for file writes, network calls, or destructive actions.
- Publicly streaming hidden planning data.
- Depending on provider function calling.
- Combining planning, validation, execution, and presentation inside one opaque prompt.

## Agent vs Capability Decision Table

Use an Agent when the code is responsible for:

- User interaction.
- Intent interpretation.
- Selecting an action or workflow.
- Calling an LLM.
- Orchestrating multiple steps.
- Deciding final output format.
- Presenting progress through `ctx.step`.
- Returning the final chat result.

Use a Capability when the code is responsible for:

- Reusable tool behavior.
- External service protocol.
- Local file or workspace operations.
- Stable method inputs and outputs.
- Slash commands.
- Functionality reusable by multiple Agents.
- Easy unit testing without chat UI.

Recommended split:

```text
External API / protocol / file operation -> Capability
User-facing workflow / LLM planning / progress / final response -> Agent
```

Examples:

ComfyUI:

- `capabilities/comfyui`: submit workflow, poll status, fetch images, cancel, and request `POST /free`.
- `agents/comfyui_agent`: fill workflow, show progress, save output images, optionally request memory release after generation, and return image gallery.

ComfyUI workflow library foundation:

- Workflow files and preset YAML files are local user assets managed by the ComfyUI Capability configuration.
- Presets are durable mapping assets that reference workflow file basenames and optional canonical hashes.
- Preset file format is specified in `docs/COMFYUI_PRESET_SCHEMA.md`.
- A session recipe is a per-session, per-agent runtime copy of a preset plus user-edited values.
- Editing a session recipe must not rewrite the preset file.
- Generation requests are built as `workflow file -> preset -> session recipe -> filled workflow request`.
- Long-running generation submits the filled workflow, polls status, fetches formal output images, filters temporary/preview images, saves local attachments, optionally requests ComfyUI memory release as best-effort cleanup, and renders an attachment-backed image gallery.
- Forms edit only the current session recipe. They do not edit preset files, choose input mode, collect the LLM user request, or submit generation.
- Form submit saves only the session recipe; generation actions are `default`, `raw`, `llm`, `fresh`, `refine`, and `run`.
- LLM mode may either auto-run after saving the generated positive prompt or stop for user inspection depending on the ComfyUI AgentConfig.
- LLM mode has a second operation layer, separate from `input_mode`: `refine` uses the current session recipe `positive_prompt` plus the user input, while `fresh` uses only the user input.
- The LLM operation affects only positive prompt generation. It does not reset or change preset, steps, cfg, seed, sampler, scheduler, dimensions, or other recipe parameters.
- The `fresh` and `refine` actions are one-shot LLM operations. They do not change the stored recipe `input_mode` or AgentConfig default LLM operation.
- Refine and fresh prompt generation use the AgentConfig template fields `llm_refine_system_prompt`, `llm_refine_user_template`, `llm_fresh_system_prompt`, and `llm_fresh_user_template`.

Obsidian or LLM Wiki:

- `capabilities/obsidian_vault`: search/read/write notes, list links, create/update markdown.
- `agents/wiki_assistant`: analyze input, draft note, create backlinks, ask LLM, preview/write result.

GitHub triage:

- `capabilities/github`: search issues, read issue, comment, label.
- `agents/issue_triage`: summarize issue, propose labels, draft reply, optionally apply changes.

Rules:

- Do not put a reusable external protocol only inside one `agent.py` unless it is truly one-off.
- Do not create a Capability for pure prompt formatting.
- Do not let a Capability decide user-facing conversation style.
- Do not let an Agent duplicate stable low-level API code that should be testable.
- Keep Agent actions user-callable and workflow-oriented.
- Keep Capability methods narrow, named, and reusable.
- Put slash commands only in Capability manifests.

## Configuration Ownership

`CapabilityConfig` stores connection and tool behavior:

- `base_url`.
- `api_key`.
- `vault_path`.
- `allowed_directories`.
- `write_enabled`.
- `timeout_seconds`.
- `poll_interval_seconds`.
- `max_wait_seconds`.
- `max_file_size`.
- Redirect and network limits.
- Provider or service-specific transport settings.

`AgentConfig` stores workflow and user experience:

- Default workflow or template.
- Default output format.
- Default target folder.
- Note style.
- Prompt style.
- Whether to preview before write.
- Default tags.
- Default width, height, steps, or seed policy.
- User-facing behavior toggles.

Rules:

- Connection and protocol config belongs to `CapabilityConfig`.
- User-facing behavior and workflow defaults belong to `AgentConfig`.
- Secrets belong to `CapabilityConfig` or Provider Profile, not `agent.yaml`.
- Package defaults can live in manifests.
- Local user values live in `AgentConfig` or `CapabilityConfig`.
- If multiple Agents can use the same connection, do not store it only in one `AgentConfig`.

Examples:

ComfyUI CapabilityConfig:

- `base_url`.
- `timeout_seconds`.
- `poll_interval_seconds`.
- `max_wait_seconds`.
- `workflows_dir`.
- `presets_dir`.
- workflow/preset write toggles.

ComfyUI AgentConfig:

- `default_preset_id`.
- `default_input_mode`.
- `llm_operation_default`.
- refine/fresh prompt enhancer templates.
- Whether LLM prompt enhancement auto-runs generation.
- Seed policy.
- Whether to request ComfyUI model unload and execution memory release after generation.

Knowledge configuration ownership:

- Knowledge Defaults store app-level RAG defaults such as local model device, reranker path, retrieval limits, chunking limits, and future context prompt templates.
- Embedding Model Profiles store local embedding model paths and instructions.
- Knowledge Bases store per-KB configuration, overrides, and Intent Routing aliases used only for natural-language KB hint matching.
- Knowledge Sources, Chunks, Embeddings, and FTS rows are Workbench-owned data derived from source inputs. Deleting a source deletes its chunks, embeddings, and FTS rows without deleting the original attachment.
- Session Knowledge Bindings store which KBs are active for a session and Phase 4 uses them for Prompt Agent and opted-in Script Agent context injection.
- AgentConfig may store only the tri-state `knowledge_context_mode` runtime override. Do not store Knowledge model paths in AgentConfig or CapabilityConfig.

Core Memory and Worldbook configuration ownership:

- Core Memory content and enablement flags are Workbench-owned General settings, not Agent manifest fields.
- Worldbook Defaults, Worldbooks, entries, and Session Worldbook Bindings are Workbench-owned data.
- Worldbook matching is regex/text storage in SQLite only; it does not own Knowledge indexes, vectors, rerankers, or FTS rows.
- Runtime injection for Core Memory and Worldbook is owned by the core runtime, not Agent or Capability manifests. Prompt Agents use the Prompt Agent enablement defaults; Script Agent `ctx.llm.*` calls use the Script Agent enablement defaults, which are off unless the user enables them. Do not store per-Agent Worldbook overrides in AgentConfig until that runtime behavior is explicitly designed.

Intent Routing configuration ownership:

- General settings own Intent Routing's master switch, Prompt Agent default, global `shadow`/`auto` mode, safe auto-route toggle, semantic thresholds, and the optional semantic router Embedding Model Profile reference.
- General settings own built-in intent custom route examples. These examples are user data merged with built-in route examples at prediction time.
- Prompt Agent local override state belongs in `AgentConfig.runtime.intent_routing_mode` and is edited under Agent detail -> Intent Routing.
- Agent target hint aliases/examples belong in `AgentConfig.runtime.intent_routing_aliases_text` and `AgentConfig.runtime.intent_routing_examples_text`, edited under Agent detail -> Intent Routing. They are local runtime hints, not manifest fields and not router-entry grants.
- Knowledge Base aliases belong to Knowledge Base data/configuration and are used only to match Intent Routing `knowledge_query` KB hints.
- Intent Routing semantic router configuration references an existing Knowledge Embedding Model Profile through General settings. The Embedding Model Profile itself remains owned by Knowledge/local model configuration.
- Intent Routing must not own or restore a raw embedding model path UI. Old persisted raw embedding path values are ignored; semantic router selection uses only the Knowledge Embedding Model Profile id.
- The semantic router is core runtime behavior. Its route index is a lazy in-memory cache derived from the internal RouteSpec registry plus existing owners: General route examples, Knowledge Base names/aliases/descriptions, AgentConfig target hints, Agent action manifest metadata, and Capability command manifest metadata.
- Explicit syntax parsing for `/command`, `@agent`, `@agent:action`, and `:action` remains owned by the core router and bypasses Intent Routing before the semantic classifier runs. There is no separate fallback route classifier after semantic routing.
- Agent action and Capability command candidates are read-only diagnostic candidates. They do not change Agent or Capability manifest schemas and do not grant automatic execution.
- Route candidate embeddings are not persisted to SQLite or a vector database. The Knowledge Embedding Model Profile remains the only model configuration owner, and route candidates do not modify Knowledge retrieval indexes or ranking.
- Utility LLM settings belong to General settings and are displayed under General -> Utility LLM: `intent_routing_utility_llm_backend`, `intent_routing_utility_llm_model_profile_id`, `intent_routing_utility_llm_model_path`, `intent_routing_device`, and optional llama.cpp options. Transformers/HF paths are `utility_llms/<folder>`; GGUF paths are `utility_llms/<model-folder>/<file>.gguf` and remain under `data/models/utility_llms`. The Model Profile backend references an existing LLM Model Profile for short internal calls.
- The Utility LLM service belongs to the core runtime. It is used for internal short tasks such as session title generation and Intent Routing strict JSON slot extraction.
- Intent Routing's long-term runtime pipeline is owned by core runtime: Semantic router -> Utility LLM slots/extraction -> Validator -> Executor. The RouteSpec registry is a core runtime internal registry that provides built-in route/action examples, slot schemas, validator ids, and executor ids. The semantic router remains the only classifier; Utility LLM is required for non-chat executable slots; validators and executors are the final safety boundary.
- New executable Intent Routing intents or actions should be added by extending the internal RouteSpec/ActionSpec registry, defining a SlotSchema, adding Utility LLM extraction context, implementing a validator, producing an ExecutorPlan, and then wiring an executor path. Do not add Agent or Capability manifest schema fields for this registry, and do not add broad regex parsers as the primary natural-language routing path.
- Route candidates are derived from internal RouteSpec/ActionSpec entries plus existing owners: General route examples, Knowledge Base names/aliases/descriptions, AgentConfig target hints, existing Agent action metadata, existing Capability command metadata, and compact Pet runtime list data. Specs do not become new extension manifest schema in this round, and no Agent or Capability manifest route registry fields are added.
- Utility LLM is not AgentConfig, CapabilityConfig, Provider Profile, Model Profile, Agent manifest, or Capability manifest configuration. It may reference a Model Profile as a backend, but that reference does not make Utility LLM an owner of provider/model configuration and does not mutate main LLM resolution.
- A GGUF Utility LLM is still not a Model Profile or Provider Profile and must not be registered as one. The app does not automatically download Utility LLM files or install `llama-cpp-python`. A Model Profile Utility backend is still not a new Agent, Capability, Provider Profile, or Model Profile.
- Session title generation settings belong to General -> LLM & Prompts, not the Utility LLM page. These settings include title backend selection, an optional specific Model Profile reference, prompt/input limits, and best-effort title model release.
- Title generation may reference Model Profiles for a title-only call, but that reference does not change AgentConfig, CapabilityConfig, session default Agent configuration, or the user's selected/composer Model Profile.
- Intent route definitions, deterministic shadow classification, and utility model backends are core runtime concerns.
- Safe auto-route decisions are per-run runtime decisions owned by the core pipeline. `chat` keeps the current Prompt Agent path and is semantic-only. `knowledge_query` and the narrow single-command `pet_command` `/pet status|wake|tuck|reload|select <pet_id>` allowlist require Utility LLM slots and validator approval before execution. `knowledge_query` may pass temporary Knowledge KB/query overrides for the current Prompt Agent run, but it must not write session config, change the session default Agent, persist Context Sources bindings, or change Knowledge retrieval ranking. Image generation, action routing, generic Agent target hints, command-like predictions, and compound matches remain metadata/diagnostic decisions until separate action/confirmation designs exist.
- Intent Routing is not owned by Agent manifests, Capability manifests, or slash command declarations. Do not add Intent Routing route registry fields to `agent.yaml` or `capability.yaml`.

Obsidian CapabilityConfig:

- `vault_path`.
- `allowed_subdirs`.
- `write_enabled`.
- `backup_before_write`.

Obsidian AgentConfig:

- Note template.
- Default folder.
- Backlink policy.
- Tag policy.
- Preview/write mode.

## Data Ownership and Output Rules

Choose output payloads by the data being returned:

- Short text: `text` or `markdown`.
- Rendered prose: `markdown`.
- Structured data for downstream inspection: `json`.
- Raw source, config, log, or note text: `file_content`.
- One image: `image`.
- Multiple images: `image_gallery`.
- Mixed ordered result: `rich_content`.
- Long-term file or image result: save as local attachment or stable local reference where possible.

Temporary external URLs:

- Do not use a temporary external URL as the only final output if it may expire.
- Do not use a temporary external URL as the only final output if it requires a service to stay online.

Rules:

- Do not return raw workflow logs as markdown when `file_content` is more appropriate.
- Do not use data URLs for large durable outputs if attachment storage is available.
- Do not return remote temporary service URLs as the only final result.
- Keep raw debug data in metadata or `file_content`, not primary user prose.
- For generated images, prefer local attachment-backed image outputs.
- For generated notes or files, return a markdown summary plus `file_content` or a stable file reference when useful.
- Use `json` for plans, validation reports, and structured results that another Agent or UI may inspect.
- Use `rich_content` only when ordered mixed blocks matter.

Examples:

- ComfyUI: generated images use `image` or `image_gallery`; workflow JSON uses `file_content`; summaries use `markdown`.
- Obsidian: note previews use `markdown`; raw note bodies use `file_content`; write results use markdown summaries with paths or links.

## Long-running Workflow Pattern

Recommended run step structure:

```text
Running script
  Prepare input
  Validate configuration
  Build request/workflow
  Submit or start task
  Wait for completion
  Fetch or build outputs
  Save artifacts
  Render result
Cleanup
```

For polling services:

- Submit task.
- Poll non-blocking status methods at configured interval from Script Agent code.
- Update `ctx.run` progress or `ctx.step` messages.
- Stop polling on cancellation.
- Fetch outputs only after completion.

For local batch work:

- Scan inputs.
- Process items.
- Update progress current/total.
- Save outputs.
- Render summary.

Rules:

- Use `ctx.step` for user-meaningful progress.
- Do not create a step for every small helper function.
- Long-running external operations should report progress or current phase.
- Cancellation should be best effort.
- Cancellation should not corrupt already saved outputs.
- Do not block the event loop with long synchronous loops.
- Use async sleep and async HTTP where appropriate.
- Blocking convenience helpers are acceptable for CLI or small tests, but long-running workflow Agents should prefer async polling through status methods.

Examples:

- ComfyUI mapping: prepare recipe, validate preset, fill workflow, optionally enhance prompt with an internal LLM call, submit workflow, poll status, fetch output images, save attachments, optionally request ComfyUI memory release, render result.
- Obsidian wiki mapping: scan candidate notes, extract concepts, build links, preview changes, write notes, render summary.

## LLM Usage Patterns

### Final LLM Output

Use when:

- LLM output is the final user reply.
- The task is chat, rewrite, translation, summary, or direct prose generation.

Use:

- Prompt Agent.
- `ctx.llm.stream_to_output`.

### Internal LLM Transform

Use when:

- LLM output is intermediate data.
- The script must validate, normalize, or combine it before showing results.

Use:

- `ctx.llm.text`.
- `ctx.llm.json`.
- `ctx.llm.stream`.

Rules:

- Do not output raw intermediate data to chat.
- Validate and normalize before use.
- Keep prompt/debug details out of the primary reply.

### LLM-assisted Tool Orchestration

Use when:

- The LLM produces a plan or parameters.
- Script code validates the plan.
- A Capability executes the operation.

Rules:

- Never trust raw LLM output for file writes.
- Never trust raw LLM output for network calls.
- Never trust raw LLM output for destructive actions.
- Do not rely on provider function calling unless the project explicitly supports it.

### Public Streaming

Use when:

- Streamed text is intended to be shown to the user.

Use:

- `ctx.llm.stream_to_output`.
- `ctx.output.write_delta`.

Rules:

- `ctx.llm.stream` is internal streaming.
- `ctx.llm.stream_to_output` is public streaming.
- Do not use public streaming for hidden JSON or intermediate planning.
- For JSON, scripts must parse and validate.
- Keep raw LLM debug output out of primary user-facing messages unless needed.

## External Writes and Safety

General rules:

- Prefer preview before write for destructive or persistent changes.
- Make write behavior configurable.
- Do not let raw LLM output directly overwrite files.
- Validate paths and stay inside allowed directories.
- Consider backup or conflict handling before overwriting.
- Return a clear summary of what changed.
- Store raw details in metadata or `file_content` when useful.
- Tests must cover denied paths and disabled write mode.
- Keep secrets out of logs, markdown replies, and generated files.

Examples:

- Obsidian: default to preview when appropriate; require write config; keep generated paths inside the vault; make overwrites explicit or backed up.
- GitHub: draft comments or labels when writes are disabled; store API key in `CapabilityConfig`; normalize rate limit and API errors.
- ComfyUI: save generated files to attachments; do not rely on service-side temp files as durable output.

## Cancellation and Timeout Rules

Rules:

- Long tasks should accept cancellation if possible.
- If an external service supports cancel or interrupt, the Capability should expose it.
- If cancellation is not supported, the Agent should stop polling and mark the local run cancelled.
- Cancellation is best effort.
- Timeout should fail the relevant step with a clear message.
- Partial outputs should be handled intentionally.
- Keep partial outputs if useful and safe.
- Discard partial outputs if incomplete or corrupt.
- Summarize what happened when partial output handling matters.
- Do not move terminal run statuses back to running.

Common status mapping:

- Service unreachable: provider/service unreachable error.
- Rejected request: validation/workflow failed.
- Timeout: task timeout.
- No output: output not found.
- Cancelled: run cancelled.

## Testing Strategy

General rules:

- Do not require real external services in automated tests.
- External service integrations use fake runtime or mock HTTP server.
- Local workspace integrations use temp directories.
- LLM behavior uses mock text, JSON, or stream chunks.
- Images use small fake bytes.
- Tests should cover success, unreachable, invalid response, timeout, cancel, and output validation.
- Run `check_agents.py --strict` for manifest validation.
- Update generated registry when manifests change.
- Keep tests focused on contracts and failure behavior, not personal environment state.

External Service Integration test matrix:

- Reachable success.
- Unreachable.
- Rejected request.
- Timeout.
- Completed with outputs.
- No outputs.
- Cancel requested.

Local Workspace Integration test matrix:

- Read allowed file.
- Deny outside path.
- Preview write.
- Actual write when enabled.
- Conflict or overwrite behavior.

LLM-assisted workflow test matrix:

- Mock valid JSON.
- Mock invalid JSON.
- Validation failure.
- No public leak of internal JSON.
- Public streaming only when explicitly requested.

## Example Mappings

### ComfyUI

- Category: External Service Integration plus Long-running Workflow.
- Capability: service protocol.
- Agent: workflow fill, progress, output rendering.
- Output: `image_gallery` plus markdown summary.
- Tests: fake ComfyUI server or runtime.

### Obsidian / LLM Wiki

- Category: Local Workspace Integration plus Knowledge Bridge.
- Capability: vault read/search/write.
- Agent: note generation, backlinks, preview/write.
- Output: markdown summary plus `file_content` note preview.
- Tests: temp vault plus mock LLM JSON.

### GitHub Issue Triage

- Category: External Service Integration plus LLM-assisted Tool Orchestration.
- Capability: GitHub API.
- Agent: summarize, label suggestions, draft comments.
- Output: markdown plus JSON plan.
- Tests: mock API responses.

## Non-goals

This document does not define:

- Product-specific workflow details.
- UI workflow editors.
- Plugin marketplace behavior.
- Permission system design.
- External service installation instructions.
- Provider-specific authentication docs.
- Full Diagnostics implementation.
- Frontend CSS or component styling rules.
- Historical compatibility notes.
