# Runtime Protocols

## Message Streaming

- Streaming content has one source of truth.
- During streaming, visible content is updated by `message_delta`.
- `message_updated` must not replace streaming content.
- `message_completed` is the final authoritative content.
- `message_delta` is a realtime transport event. By default it is sent over WebSocket but is not persisted to the SQLite event log.
- `message_completed` persists the final assistant message content.
- Settings -> Data -> `Persist streaming message deltas` makes `message_delta` persist for debugging.
- Run steps, errors, warnings, and other diagnostic events are not affected by the streaming delta persistence setting.
- `message_delta` carries `message_id`, `run_id`, `seq`, `delta`, and optional `reasoning_delta`.
- `message_completed` carries `message_id`, `run_id`, `seq`, and final `message`.
- `seq` is monotonic per message.
- The frontend ignores older `seq`.
- The frontend ignores delta after completed if `seq` is old.
- `message_updated` can merge metadata, `run_id`, attachments, and status, but not old content while streaming.
- Non-streaming source messages may use `message_updated` to persist backend-generated rich content changes such as replacing an `action_form` block after a silent save, including setting form-level `ui.collapsed=true`.
- Internal `ctx.llm.stream` does not emit public `message_delta`.
- `ctx.output.write_delta` and `ctx.llm.stream_to_output` emit public deltas.
- `command_buttons` rich content blocks are rendered after message completion like other non-streaming rich content. Clicking a command button starts a new ordinary user message; it does not mutate the source assistant message.

Producer rules:
- Emit `message_started` before public deltas for a new assistant draft.
- Increment `seq` once for each public delta.
- Emit `message_completed` once with the final message and a greater `seq`.
- Keep final message content equal to the accumulated visible deltas unless an explicit final replacement is intended.
- Include `draft_message_id` on completion when the frontend may need to replace a draft id.
- Do not emit empty visible deltas unless carrying `reasoning_delta`.

Frontend merge rules:
- Use `message_id` plus `draft_message_id` to resolve the active streaming row.
- Track the last accepted `seq` per message.
- Mark messages completed after `message_completed`.
- Merge `message_updated` conservatively while streaming.
- Attach run metrics and steps without resetting streamed content.

Tiny event examples:

```json
{
  "type": "message_delta",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {"seq": 1, "delta": "hel", "reasoning_delta": null}
}
```

```json
{
  "type": "message_completed",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {"seq": 2, "message": {"message_id": "msg_1", "content": "hello"}}
}
```

## Run Lifecycle

Run status values:
- `PENDING`
- `RUNNING`
- `CANCELLING`
- `WAITING_FOR_USER`
- `DONE`
- `FAILED`
- `CANCELLED`
- `INTERRUPTED`

Core Memory and Worldbook runtime injection is implemented only in Prompt Agent main LLM calls and Script Agent `ctx.llm.*` provider calls. It is not part of routing, commands, title generation, Knowledge query expansion, embeddings, reranking, resource status, runtime memory release, or non-LLM Capability methods.

RunStep status values:
- `pending`
- `running`
- `completed`
- `failed`
- `skipped`

Run steps:
- `RunStep.parent_step_id` creates nesting.
- Prompt Agent default top-level steps include `Resolving agent`, optional `Intent semantic routing`, `Building context`, `Resolving model`, `Calling LLM`, `Saving response`, and `Cleanup`.
- Intent Routing semantic decision happens before `Building context`. The `Intent semantic routing` step shows a compact outcome such as `knowledge_query · score 0.57 · executed`, `knowledge_query · score 0.57 · not executed: score below threshold`, or `skipped: explicit command`. If auto mode authorizes a `knowledge_query` override, the temporary KB/query values are passed into that run's Knowledge context builder.
- Script Agent default top-level steps include `Resolving agent`, optional `Resolving model`, `Starting script`, `Running script`, `Saving response`, and `Cleanup`.
- Automatic session title generation is considered only after routing has resolved the actual Agent/action. Prompt Agents try it after model resolution and before the main provider call. Script Agents try it lazily before the first real `ctx.llm.*` call.
- Script custom steps created with `ctx.step` default under `Running script`.
- Script Agents may update long-running step messages while polling external jobs, for example queued, running, completed, failed, not_found, or timeout.
- Model lifecycle unload outcomes are shown on the `Cleanup` step when cleanup attempts unload.
- Session load returns runs and steps attached to messages.
- The frontend may render the `Building context` step with a compact `Context injected` summary for Core Memory, Worldbook, Knowledge, and warnings. This summary is diagnostic only and must not include full Core Memory text, full Worldbook entry content, Knowledge query text, or full Knowledge snippet content.

Run metadata:
- Prompt Agent runs record `llm_resolution` when model resolution succeeds.
- Intent Routing predictions and safe auto-route decisions may be recorded under `intent_routing`. The metadata is not injected into provider-bound context, title generation, Core Memory, or Worldbook matching. In auto mode only, a high-confidence `knowledge_query` decision may provide a per-run Knowledge KB/query override to the Knowledge context builder, and a safe `pet_command` decision may execute only the existing `/pet` command path.
- Prompt Agent runs can record `llm_metrics`, `vision_input`, `file_context`, and reasoning metadata.
- Prompt Agent and Script Agent LLM runs may record compact `core_memory_context` and `worldbook_context` metadata. These records include enablement, injection status, counts, ids, entry refs, truncation, and warnings, but must not store full Core Memory text, full Worldbook entry content, or rendered context blocks.
- Model lifecycle unload attempts are recorded under `llm_unload`, including success, skipped, unsupported, failure, and provider status refresh outcome.
- Generated image workflows may record compact recipe metadata under a domain key such as `comfyui_generation`; this metadata should include attachment ids, prompt/request ids, image filtering counts, and output counts, not full workflow JSON or large binary data.
- ComfyUI generation cleanup may record `comfyui_memory_release` with whether release was enabled, attempted, successful, requested flags, status code, and any structured error. ComfyUI memory release is separate from LLM provider unload; release failure is a cleanup/workflow warning and must not turn an already successful image generation into a failed run.
- ComfyUI LLM prompt generation metadata may record `input_mode`, `llm_operation`, `llm_operation_requested`, `llm_operation_used`, `user_prompt`, and `positive_prompt` for the current request. Raw and run-only ComfyUI generation should not be labeled as `refine` or `fresh`.
- Failures should set both run status and user-visible error metadata where applicable.
- Cancellation sets `cancel_requested` before terminal cancellation when possible.

## Intent Routing

Intent Routing is an optional pre-routing layer for ordinary natural-language messages. Explicit syntax keeps priority and bypasses intent routing:

- `/command`
- `@agent`
- `@agent:action`
- `:action`

UI locations:

- Global settings: Settings -> General -> Intent Routing.
- Per-Agent Prompt Agent entry override and target hints: Agent detail -> Intent Routing.

Eligibility in the first alpha:

- General `intent_routing_enabled` must be true.
- The route must be ordinary text to the current session default Agent's `default` action.
- The current session default Agent must be a Prompt Agent.
- The Prompt Agent effective Intent Routing override must be enabled.
- The session `context_mode` must be `single_assistant`.
- General `intent_routing_mode` must be `shadow` or `auto`.

Script Agents, non-prompt Agents, `group_transcript` mode, form submissions, silent submissions, waiting-run resumes, slash commands, explicit Agent calls, and explicit action shortcuts do not enter the classifier.

Shadow mode never changes the selected route. A prediction such as `image_generation` or `knowledge_query` is recorded only as metadata; the original current/default Prompt Agent still receives the message.

The embedding semantic router is the only classifier for Route Test, shadow metadata, and auto-mode route decisions. It aggregates semantic scores by intent group before making an execution decision: the intent score is the best score for that intent group, and the intent margin compares the top intent group with the second intent group. Multiple top candidates from the same intent do not reduce the margin by themselves. Metadata caps `intent_group_scores` to the top few intent groups and does not store embeddings.

Semantic auto execution uses semantic-specific thresholds:

- `intent_routing_semantic_intent_min_score`, default `0.50`.
- `intent_routing_semantic_intent_min_margin`, default `0.03`.
- `intent_routing_semantic_kb_min_score`, default `0.45`.
- `intent_routing_semantic_agent_min_score`, default `0.45`, diagnostic candidates only.
- `intent_routing_semantic_command_min_score`, default `0.45`, diagnostic candidates only.

Old persisted `intent_routing_high_confidence_threshold` and `intent_routing_low_confidence_threshold` keys are ignored on load and patch. They are not returned by the General settings API and never affect route decisions.

Auto execution is intentionally narrow:

- `chat`: keep the current Prompt Agent path. Intent Routing does not force-enable or disable Knowledge; existing session KB injection rules still apply.
- `knowledge_query`: for high-confidence semantic decisions, keep the current Prompt Agent path and pass a per-run temporary Knowledge KB/query override into `Building context` only after Utility LLM slots and the Knowledge validator pass.
- `pet_command`: a narrow `/pet`-only allowlist for Workbench Pet status, wake, tuck, select, and reload. It reuses the normal Capability command runner and Pet runtime, records `target_command="/pet"` and `generated_command`, and does not execute any other slash command. Utility LLM slots must set `domain=workbench_pet` and an allowlisted action, then the Pet validator must pass. `/pet random` is not part of this allowlist.
- `image_generation`: diagnostic-only in semantic v1. It does not auto-route to ComfyUI until action routing is designed.
- `command_like`, generic `agent_route`, `action_route`, and `compound`: diagnostic-only. They may record compact target metadata but do not execute commands, Agents, actions, or multiple tasks.

`knowledge_query` auto execution requires all of the following: General mode `auto`, `intent_routing_auto_route_safe_intents=true`, eligible ordinary text in `single_assistant` mode, current default Agent is an effective Intent Routing enabled Prompt Agent, semantic predicted intent is `knowledge_query`, grouped intent score and margin meet the semantic intent thresholds, Utility LLM is available, Utility LLM slots extraction succeeds, `slots.query` is non-empty, and either a selected KB candidate meets the semantic KB threshold or no explicit KB candidate is available but the session has active KB bindings. Utility LLM unavailable records `not_executed_reason=utility_llm_required` or `utility_llm_unavailable`; slots failure records `utility_llm_slots_failed`. No local query regex/heuristic extractor may replace Utility slots. The execution keeps the current Prompt Agent, sets only per-run `temporary_knowledge_base_ids` and `knowledge_query_override`, and never persists Context Sources bindings or changes the session default Agent.

`pet_command` auto execution requires the same General/session/Prompt-Agent eligibility gates as other safe auto routes, semantic predicted intent `pet_command`, passing semantic thresholds, Utility LLM availability, Utility LLM slots extraction success, `slots.domain=workbench_pet`, and `slots.action` in `status | wake | tuck | select | reload`. Regex or keyword helpers may only provide hints or validator input; they must not override semantic score/margin or independently determine action/target execution. The validator resolves candidates from the existing Pet Capability runtime/settings/list data. Missing targets use the current default pet, except `select` must resolve a unique target. Ambiguous targets record `ambiguous_pet_candidate`; missing targets record `pet_candidate_not_found`; `wake`, `tuck`, and `reload` with a target that is not the current pet record `target_pet_not_current` instead of selecting and acting; a source pet hint that does not match the current default pet records `source_pet_mismatch`. Reality-pet questions such as sick cats/dogs, training real pets, or fictional character questions without Workbench Pet context must not execute and should record `pet_domain_not_workbench_pet` when Utility identifies a non-Workbench domain.

If the semantic router is unavailable, the runtime falls back to the current Prompt Agent and records a semantic-unavailable source/reason such as `semantic_router_unavailable`, `semantic_router_profile_missing`, or `semantic_router_embedding_unavailable`. No fallback classifier runs, and unavailable semantic routing never triggers command, Agent, action, or image-generation execution.

`command_like` and generic `agent_route` are not executed automatically in this version. They fall back to the current Prompt Agent and record warnings such as `command_like_auto_route_disabled` or `agent_route_auto_route_disabled`. No slash command other than the narrow `pet_command` `/pet` allowlist, memory release, deletion, settings change, shell command, or arbitrary Agent call is performed.

Intent predictions are not appended to prompts, not passed to providers, not used by automatic title generation, and not used to alter Core Memory or Worldbook context injection.

When natural language auto-routes to `pet_command`, the original user text is still persisted as the visible user message. The generated `/pet ...` command is stored only as compact metadata and is used internally to run the existing command path; it does not replace the visible user message and does not create a synthetic user message such as `/pet wake`.

General settings may store custom route examples for `chat`, `image_generation`, `knowledge_query`, `agent_route`, and `command_like`. Each field is newline-separated user data. Empty lines are ignored, individual examples are capped, and the classifier merges custom examples with built-in examples instead of replacing them. Custom examples can raise or clarify a prediction, but they do not expand the safe auto-route allowlist.

Knowledge Bases may store comma-separated aliases. Intent Routing uses enabled KB names and aliases to match `knowledge_query` `kb_hint` values in this order: name exact, alias exact, name substring, alias substring, then description weak match. Exact alias matches take priority over description matches. Ambiguous strong matches record a warning and do not randomly choose a KB. Any selected KB ids are temporary for the run only.

AgentConfig runtime may store routing target hints under `intent_routing_aliases_text` and `intent_routing_examples_text`. These hints are edited under Agent detail -> Intent Routing, help classify `agent_route`, and produce compact target metadata. They do not make Script Agents router entries and do not allow generic Agent auto execution. Prompt Agent `runtime.intent_routing_mode` remains the only per-Agent router-entry override.

General settings may store `intent_routing_embedding_model_profile_id`, which references an existing Knowledge Embedding Model Profile. This profile id is the only Intent Routing semantic router configuration field. Old persisted `intent_routing_embedding_model_path` values are ignored if present. The semantic router uses the selected profile's model path, instructions, normalization setting, and Knowledge Defaults device setting. Candidate documents are embedded with `purpose=document`; the current user input is embedded with `purpose=query`. Missing, disabled, unavailable, or failing profiles fall back to the current Prompt Agent path and add warnings such as `semantic_router_profile_missing` or `semantic_router_embedding_unavailable`.

The semantic route index is a lazy in-memory cache. Its key includes the embedding profile fingerprint, built-in examples version, General custom examples, enabled Knowledge Base names/aliases/descriptions, Agent ids/names/descriptions/routing aliases/examples/actions, and Capability command metadata. It is not persisted to SQLite and does not use a vector database. Route Test and the first eligible shadow prediction can build it; settings or hint changes are picked up by key changes or the short cache TTL.

Candidate sources:

- Built-in and General custom intent examples for `chat`, `knowledge_query`, `image_generation`, `command_like`, and `agent_route`, plus diagnostic `action_route` and `compound`.
- Enabled Knowledge Base name, aliases, and description.
- Agent id, name, description, runtime routing aliases, and runtime route examples.
- Weak diagnostic Agent action id, label, and description.
- Weak diagnostic Capability command name, description, capability name, and safe flag.

Command, action, generic Agent, image-generation, and compound candidates are diagnostic-only in semantic v1. They may appear as `target_command`, `target_agent_id`, `target_action_id`, `sub_intents`, and top candidates in metadata, but they are not executed and do not change the selected route.

`pet_command` metadata may include compact Pet slots: `pet_action`, `target_pet_id`, `target_pet_hint`, `source_pet_id`, `source_pet_hint`, `generated_command`, `route_action="pet_command"`, `auto_executable`, `executed`, `not_executed_reason`, and `warnings`. It must not store full Pet manifests, spritesheet content, image bytes, or large Pet objects.

When General `intent_routing_utility_llm_model_path` is configured and available, the core may call the Utility LLM for strict JSON slot extraction after semantic prediction. The Utility LLM backend is selected by `intent_routing_utility_llm_backend`: `transformers` loads a Hugging Face / safetensors model folder at `utility_llms/<folder>`, while `llama_cpp` loads a GGUF file at `utility_llms/<model-folder>/<file>.gguf` through optional `llama-cpp-python`. Root-level GGUF files under `utility_llms` are invalid and ignored by model scan. The extractor is used for slots such as `kb_hint` and `query`, or optional low-confidence verification. It receives a compact candidate context: intent ids with capped built-in/custom examples, enabled Knowledge Base names and aliases, Agent ids/names and routing aliases/examples, and safety-boundary reminders. It must not receive full candidate lists, Agent prompts, KB content, Worldbook content, Core Memory content, raw run history, raw Utility LLM output, or provider-bound prompt text. It does not execute command-like requests and must not override semantic predictions into execution.

Utility LLM configuration is displayed under Settings -> General -> Utility LLM. Intent Routing only shows a compact Utility LLM status summary and uses the same status API without loading the model.

Intent Routing v2 pipeline contract:

- The execution pipeline is Semantic router -> Utility LLM slots/extraction -> Validator -> Executor.
- `chat` is a semantic-only special case. It keeps the current Prompt Agent path, does not call Utility LLM, does not add temporary Knowledge overrides, and does not change Context Sources.
- `knowledge_query` and `pet_command` require Utility LLM availability and strict JSON slot success before auto execution. Utility unavailable records `utility_llm_required` or `utility_llm_unavailable`; extraction failure records `utility_llm_slots_failed`.
- `knowledge_query` slots include at least `intent`, `query`, and `kb_hint`. The validator checks enabled KB candidates, semantic/slot conflicts, ambiguity, non-empty query, and active KB availability without mutating session bindings.
- `pet_command` slots include at least `intent`, `domain`, `action`, `target_pet_hint`, and `source_pet_hint`. The validator requires `domain=workbench_pet`, an allowlisted action, unique target resolution, `select` target presence, current-pet checks for wake/tuck/reload, and source-pet consistency.
- Regex and deterministic helpers may only support explicit syntax parsing, slot hints, exact id/name/alias matching, false-positive guards, and validators. They must not replace Utility LLM as the primary natural-language slots parser, and they must not override semantic score or margin.
- Route Test and real run gating use the same pipeline. Route Test reports Semantic, Utility LLM, Validation, and Execution plan fields without creating messages/runs, executing `/pet`, running Knowledge retrieval, changing sessions, changing Pet settings, or calling ComfyUI.

`POST /api/intent/test-route` predicts a semantic route decision for Settings diagnostics. It accepts `text`, optional `session_id`, optional `default_agent_id`, and `include_utility`. It creates no chat message, no run, no ComfyUI request, no Knowledge retrieval, and no session or Context Sources mutation. Without a session, the response is marked with `eligibility_scope="no_session"` and is a partial simulation using General examples and configured KB/Agent/action/command/Knowledge hints. It reports what auto mode would do through `auto_executable`, `would_execute`, `route_action`, `not_executed_reason`, temporary KB ids, query override preview, `semantic_thresholds_used`, grouped intent scores, and warnings.

For `pet_command`, Route Test also reports Pet action, target Pet, optional source Pet, generated command, would-execute status, not-executed reason, and warnings. Route Test never executes `/pet`, never creates a command run, and never updates Pet settings.

Prediction metadata shape:

```json
{
  "enabled": true,
  "pipeline_version": "semantic_utility_validator_v1",
  "mode": "auto",
  "evaluated": true,
  "semantic_evaluated": true,
  "eligible": true,
  "bypassed": false,
  "source": "embedding_semantic_router+utility_llm",
  "predicted_intent": "knowledge_query",
  "confidence": 0.84,
  "intent_score": 0.84,
  "intent_margin": 0.09,
  "semantic_score": 0.84,
  "semantic_margin": 0.09,
  "semantic_thresholds_used": {
    "intent_min_score": 0.5,
    "intent_min_margin": 0.03,
    "kb_min_score": 0.45,
    "agent_min_score": 0.45,
    "command_min_score": 0.45
  },
  "route_action": "knowledge_override",
  "auto_executable": true,
  "executed": true,
  "would_execute": true,
  "not_executed_reason": null,
  "utility_required": true,
  "utility_available": true,
  "utility_used": true,
  "utility_ok": true,
  "utility_error_code": null,
  "validation_ok": true,
  "executor_plan": {
    "route_action": "knowledge_override",
    "auto_executable": true
  },
  "target_agent_id": "chat",
  "target_action_id": "default",
  "session_default_agent_id": "chat",
  "session_default_changed": false,
  "embedding_model_profile_id": "embedding_profile_id",
  "semantic_index_version": "abc123def456",
  "intent_group_scores": [{"intent": "knowledge_query", "score": 0.84}, {"intent": "chat", "score": 0.31}],
  "second_intent": "chat",
  "kb_candidate": {"kind": "knowledge_base", "kb_id": "kb_id", "kb_name": "Star Wars", "field": "alias", "score": 0.71, "text_preview": "SW"},
  "session_bindings_changed": false,
  "temporary_knowledge_base_ids": ["kb_id"],
  "knowledge_query_override": "stormtrooper ranks",
  "kb_match_source": "alias",
  "agent_match_source": "none",
  "action_match_source": "none",
  "command_match_source": "none",
  "target_command": null,
  "matched_alias": "Star Wars",
  "ambiguous_matches": [],
  "slots": {
    "kb_hint": "Star Wars",
    "query": "stormtrooper ranks"
  },
  "warnings": []
}
```

Bypass metadata shape:

```json
{
  "enabled": true,
  "mode": "shadow",
  "evaluated": false,
  "eligible": false,
  "bypassed": true,
  "skip_reason": "explicit_command",
  "bypass_reason": "explicit_command"
}
```

Metadata must stay compact and must not store long prompts, full history, full route example lists, raw Utility LLM prompts or outputs, vector data, full candidate lists, Agent prompts, KB content, Worldbook content, Core Memory content, or extracted private content. Alias fields such as `matched_alias` are truncated, grouped intent scores are capped, Route Test top candidates are capped to compact previews, and `ambiguous_matches` is capped. Utility LLM unavailability or extraction failures keep the semantic prediction and record `utility_llm_required`, `utility_llm_unavailable`, or `utility_llm_slots_failed`; they do not trigger fallback classifiers or non-chat auto execution. Route metadata must not include a fallback classifier prediction.

WebSocket events:
- `run_updated`
- `run_step_created`
- `run_step_updated`
- `run_completed`
- `run_failed`

Related events:
- `run_started` marks creation/start but does not include the full lifecycle payload.
- `run_cancel_requested` marks a cancellation request.
- `run_cancelled` marks terminal cancellation.
- `run_warning` carries non-fatal lifecycle warnings.
- `message_done` is a compatibility completion signal; do not use it as streaming source of truth.
- `llm_provider_status_updated` carries a refreshed provider status payload after runtime-triggered model status changes.

Cancel API:

```text
POST /api/runs/{run_id}/cancel
```

Frontend run-step expansion:
- `running`, `cancelling`, `failed`, and `cancelled` render expanded by default.
- `completed` renders collapsed by default.
- Manual toggle state is scoped by `run_id`.

Prompt Agent step contract:
- `Resolving agent` applies AgentConfig runtime overrides.
- `Building context` uses the resolved context policy.
- `Resolving model` resolves provider/model profile and attachment capabilities.
- `Calling LLM` wraps the provider call or stream.
- `Saving response` persists final assistant content.
- `Cleanup` applies model lifecycle policy.

Script Agent step contract:
- `Resolving agent` loads the script entry.
- `Resolving model` appears only when the Agent uses `llm`.
- `Starting script` marks pre-run setup.
- `Running script` is the parent for normal `ctx.step` calls.
- `Saving response` finalizes returned or replied content.
- `Cleanup` applies model lifecycle policy.

Failure behavior:
- If a step fails, emit `run_step_updated` with `failed`.
- If the run fails, emit `run_failed` with a run payload and error details.
- If a Script Agent streamed partial content before failure, complete the partial message rather than dropping visible output.
- If no partial content exists, write an error payload for the assistant message.
- Terminal statuses should not be moved back to `RUNNING`.

## LLM Resolution

Resolution order:

1. Session override when allowed.
2. AgentConfig runtime `llm_profile_id`.
3. Manifest `llm.profile`.
4. Default model profile.
5. Legacy global fallback.
6. Environment fallback.

Semantics:
- Provider Profile means connection details: provider, base URL, API key, and timeout.
- Model Profile means model id, capabilities, and generation defaults.
- Actual model metadata comes from provider response.
- Composer `Default` means agent default resolved model.
- Assistant message header model badges prefer Model Profile display name/name, then requested model id, then actual model id.
- Actual model id is preserved in message/run metadata and debug details/tooltips even when the short badge shows the Model Profile name.
- The bottom status bar may keep its debug-oriented provider profile plus model target/actual display and does not need to match chat message badges.
- `supports_streaming` controls visible Prompt Agent streaming.
- Script Agent public streaming requires explicit `ctx.output.write_delta` or `ctx.llm.stream_to_output`.
- `supports_vision` controls image input to Prompt Agent LLM calls.
- `supports_reasoning` is an output declaration and does not force provider behavior.
- Unload is trusted script-only for manual script calls, and best-effort for lifecycle policies.
- Successful, skipped, unsupported, and failed unload attempts remain cleanup outcomes in run metadata; unsupported unload and status refresh failure do not overwrite an otherwise successful run unless the lifecycle policy explicitly fails on unload failure.
- Utility LLM does not participate in LLM resolution. It is configured by General settings and displayed under Settings -> General -> Utility LLM, can use either the `transformers` or `llama_cpp` backend, is not a Provider Profile or Model Profile, and does not change the user's selected main model.
- Session title generation has its own backend resolver. `utility_llm` uses the Utility LLM first and falls back to the title follow-Agent resolver. `follow_agent_model_profile` resolves Model Profiles in this order: composer/session input override, session default Agent profile, then the invoked Agent profile. `specified_model_profile` uses only the configured title Model Profile id. These title decisions never mutate the session selected Model Profile or the main response LLM resolution.

Current implementation note: `resolve_llm_config` applies defaults first and then overrides later sources, so later sources win. Keep user-facing behavior aligned with the order above when changing it.

Profile capability flags:
- `supports_streaming`: enables visible Prompt Agent stream path.
- `supports_vision`: allows image attachments to be encoded into LLM messages.
- `supports_tools`: reserved capability flag; routing does not depend on model tool calls.
- `supports_reasoning`: declares expected reasoning output metadata.
- `supports_json_mode`: declares provider/model support, but scripts must still validate JSON.

Fallback notes:
- Legacy global fallback comes from persisted `llm` CapabilityConfig.
- Environment fallback uses `AGENT_WORKBENCH_LLM_BASE_URL`, `AGENT_WORKBENCH_LLM_API_KEY`, `AGENT_WORKBENCH_LLM_MODEL`, and `AGENT_WORKBENCH_LLM_TIMEOUT`.
- Session override is ignored when the resolved Agent runtime disallows it.
- Missing model selection raises `LLM_MODEL_NOT_SELECTED`.

Prompt Agent LLM calls:
- Non-streaming calls store one final assistant message.
- Streaming calls emit deltas, then store final content on completion. Deltas are persisted only when Settings -> Data enables `Persist streaming message deltas`.
- Context warnings may be attached to message metadata.
- Image vision metadata records supported, attached, sent, and ignored counts.
- File context metadata records included text attachment details and warnings.

Script Agent LLM calls:
- `ctx.llm.text`, `ctx.llm.json`, and `ctx.llm.generate` mark the LLM as used for lifecycle cleanup.
- `ctx.llm.stream` marks the LLM as used but remains internal.
- `ctx.llm.stream_to_output` both uses the LLM and writes public deltas.
- Scripts must parse and validate model output themselves.
- Scripts should not assume provider function calling is available.

## Session Title Generation

Automatic session title generation is an internal best-effort LLM call controlled by Settings -> General -> LLM & Prompts -> Session Titles. It runs after the first user message that resolves to an LLM-capable Agent/action while the session still has a default title.

Trigger points:
- Prompt Agents try title generation after model resolution succeeds and before their main LLM call.
- Script Agents try title generation immediately before the first actual `ctx.llm.text`, `ctx.llm.json`, `ctx.llm.generate`, `ctx.llm.stream`, or `ctx.llm.stream_to_output` call.
- Explicit `@agent`, `@agent:action`, `:action`, and Intent Routing safe auto-route results can trigger title generation only when the final invoked Agent/action is LLM-capable.
- Slash commands, command result messages, pure command output, file uploads that do not invoke an LLM, form/status/scan actions that do not call `ctx.llm`, and non-LLM Script Agent actions do not trigger title generation.

Input and output rules:
- The title prompt uses only the user message that triggered the LLM call.
- Assistant output, Agent output, command result output, group transcript context, and historical messages are not title inputs.
- Long user input is truncated from the middle using head/tail preservation according to `session_title_max_input_chars`.
- The title call is non-streaming, creates no visible user or assistant messages, and emits no `message_delta`.
- Title generation does not trigger Intent Routing and does not use retrieved Knowledge snippets, Worldbook entries, Core Memory, assistant output, or command output. For an Intent Routing `knowledge_query` auto route, the title input remains the original user message, not the retrieval query override.

Settings:
- `auto_generate_session_titles`: enables the one-shot title pre-hook.
- `session_title_backend`: `utility_llm`, `follow_agent_model_profile`, or `specified_model_profile`. Default is `utility_llm`.
- `session_title_model_profile_id`: optional Model Profile id used only by `specified_model_profile`. Missing, disabled, invalid, or unavailable profiles skip title generation with a compact warning and do not fail the main run.
- `session_title_unload_after_generation`: best-effort title model release after title generation. Default is `false`.
- `session_title_prompt` and `session_title_max_input_chars`: prompt template and source input cap.

Backend resolution:
- `utility_llm`: uses the configured Utility LLM first. If it is unconfigured, unavailable, missing dependencies/model files, fails generation, or returns an invalid title, resolution falls back to `follow_agent_model_profile`.
- `follow_agent_model_profile`: resolves the composer/session Model Profile override first, then the session default Agent Model Profile, then the actual invoked Agent Model Profile. It does not fall back to Utility LLM.
- `specified_model_profile`: uses only `session_title_model_profile_id`. It does not fall back to Utility LLM or follow-Agent resolution.
- Model Profile title calls use the normal provider/profile resolution path, but with title-specific resolution inputs. They do not change selected Agent, selected Model Profile, main prompt construction, or main response model resolution.

Unload behavior:
- When `session_title_unload_after_generation=false`, metadata records `unload_state="not_requested"`.
- Utility LLM title generation calls the Utility LLM unload helper when release is requested and records `released`, `no_supported_release`, or `failed`.
- Model Profile title generation calls the existing provider unload helper when release is requested. If the title target matches the current response provider/model, release is deferred until run cleanup so the current response model is not unloaded mid-run.
- Providers that do not support unload record `unload_state="no_supported_release"` without failing the main run. Release failures record `failed` and a compact warning.

Session state:
- New default-titled sessions start with `title_generation_state="pending"`.
- A successful title sets `done`.
- If `auto_generate_session_titles=false` at the first LLM call, the session is marked `skipped` and is not backfilled later.
- A failed title attempt sets `failed`; this first implementation does not retry.
- Manual rename or an existing non-default title sets or behaves as `manual`.

Lifecycle and metadata:
- Title generation records compact `title_generation` metadata when tied to a run, including state, backend, fallback use, source message id, truncation counts, generated timestamp or error, and public model/profile identifiers when a Model Profile backend is used. It must not store full long user input, full prompts, raw model output, or secrets.
- Metadata includes `requested_backend`, `backend`, `fallback_used`, optional `fallback_reason`, `model_profile_resolution`, `model_profile_id`, `trigger`, `trigger_agent_id`, `invoked_agent_id`, `invoked_action_id`, `input_override_model_profile_id`, `unload_after_generation`, `unload_state`, and compact `warnings`.
- Utility LLM success records a Utility LLM backend id and `utility_model_path`. Model Profile title calls record `backend="model_profile"` plus public provider/model identifiers. Utility fallback records `fallback_used=true`, `fallback_reason`, and compact `utility_error` when applicable.
- Allowed unload states are `not_requested`, `released`, `deferred_until_run_end`, `no_supported_release`, `failed`, and `skipped_no_model`.
- Title generation failure records a warning when tied to a run, but it does not fail the main task.

## Conversation Context Modes

Session `context_mode` controls how the core projects stored messages into provider-bound LLM context. It affects only future context builds. Switching the mode does not rewrite historical messages, and a run uses the mode captured while its context is built.

Modes:
- `single_assistant`: default mode. The core preserves the existing user/assistant-style chat history projection as closely as possible.
- `group_transcript`: speaker-aware mode. The core renders historical messages into one transcript block and sends the current user input in a separate current-message block.

New sessions default to `single_assistant`. Users can switch a session between `single_assistant` and `group_transcript` at any time; there is no auto mode.

Changing `context_mode` persists a `context_mode_changed` separator message for timeline review. The separator is a system event, is not treated as user/assistant/agent speaker content, and is excluded from LLM context.

Retry and edit reruns build context from the current session `context_mode`.

Settings -> General -> Context Rendering exposes prompt-text overrides for group transcript and command result context instructions. These settings affect only future context builds. They do not rewrite historical messages and do not dynamically update a run whose context has already been built.

## Knowledge Context

Knowledge RAG v1 Phase 4 defines persisted Knowledge settings, local model directory conventions, embedding model profiles, knowledge base configuration records, session knowledge bindings, local embedding/reranker APIs, synchronous source indexing, explicit retrieval search, and automatic session Knowledge context injection.

Session Knowledge Base bindings and Session Worldbook bindings preserve user-defined binding order. Knowledge retrieval continues to rank retrieved chunks by the retrieval pipeline; binding order is not a retrieval ranking override. Worldbook injection uses Session Worldbook binding order first, then each Worldbook entry `sort_order`.

Source indexing supports `pasted_text` and text attachment sources. Pasted source originals are stored as text files under `data/knowledge/sources`; full source originals are not stored in SQLite. The indexer chunks source text, embeds chunks with the Knowledge Base embedding profile using `purpose=document`, stores float32 vectors in SQLite BLOB rows, and writes FTS5/BM25-ready rows.

`POST /api/knowledge/search` can search explicit `knowledge_base_ids` or active session bindings. It groups vector search by `embedding_model_profile_id`, embeds one query per group with `purpose=query`, searches only matching model-profile vectors, runs FTS5/BM25 across selected KBs, merges vector and keyword candidates with RRF, and optionally runs the configured global reranker once over the merged candidate set. If reranking is disabled or fails, results use RRF order and debug warnings record the reason.

Retrieval quality filtering runs after RRF merge and optional reranking, before top-k and context-budget trimming. `min_score_threshold` applies to `rerank_score` when reranking was used, otherwise to `rrf_score`. Retrieval-specific per-source and per-KB chunk limits cap final candidates before context budget trimming. Debug metadata records `before_filter_count`, `min_score_filtered_count`, `per_source_filtered_count`, `per_kb_filtered_count`, and `final_result_count`.

Query expansion is disabled by default. When enabled, retrieval generates short variants from the original query using the current LLM runtime, searches the original query plus variants through both vector and keyword branches, and dedupes candidates during RRF merge. Expansion failures are warnings and fall back to the original query. Search debug metadata records whether expansion was enabled or used, the expanded query count, and failure state; normal run-step metadata must not expose full expanded query text.

Prompt Agents default to Core Memory and Worldbook enabled. During the existing `Building context` step, after normal `context_policy` rendering and after the Agent prompt/prompt override/action instruction are resolved, the runtime appends system-context blocks in this order: Core Memory, Worldbook, Retrieved Knowledge, conversation context, current user message. Knowledge normally searches active session KB bindings with the current user message text. Intent Routing auto mode may provide a per-run temporary KB list and query override for a high-confidence `knowledge_query`; that override affects only automatic Knowledge retrieval for the current run. It does not persist session bindings, change Context Sources state, change retrieval ranking, or rewrite the provider-bound current user message. Knowledge results are rendered as a `# Retrieved Knowledge` system-context block using Knowledge Defaults `knowledge_context_instruction` and `knowledge_context_snippet_template`, then appended to the system message. If the Agent has no system message, the runtime creates one. Provider message roles are not otherwise changed.

Script Agents that declare the `llm` capability default to session Knowledge disabled, Core Memory disabled, and Worldbook disabled. If settings or Agent overrides enable them, every `ctx.llm.text`, `ctx.llm.json`, `ctx.llm.stream`, `ctx.llm.stream_to_output`, and chat-backed `ctx.llm.generate` call appends enabled Core Memory, Worldbook, and Retrieved Knowledge blocks to that call's system context. Direct prompt-backed `ctx.llm.generate` prepends the rendered blocks to the generated prompt because it has no role-bearing message list. The query/match text is `ctx.input.text` first, then the current visible user message content when available. Silent form submissions with no user-facing query skip Knowledge retrieval and keyword Worldbook matches, while Worldbook `always` entries may still inject if Script Worldbook injection is enabled.

Core Memory, Worldbook, and Knowledge context injection never runs for session title generation, command result context, Knowledge query expansion, embedding generation, reranking, `/kb-search`, form JSON/recipe JSON, or non-LLM Script Agents. Automatic injection failures are best-effort warnings: retrieval/rendering/matching failure does not fail the main LLM call, does not add streaming deltas, and records warning metadata.

Core Memory is stored in General settings. Prompt Agent injection follows `core_memory_enabled_for_prompt_agents`, which defaults to true. Script Agent `ctx.llm.*` injection follows `core_memory_enabled_for_script_agents`, which defaults to false. Empty trimmed memory is skipped. Runtime metadata stores only `enabled`, `injected`, `content_chars`, `skipped_reason`, and compact warnings.

Worldbook is stored in the Worldbook core module and Session Worldbook bindings. Prompt Agent injection follows `worldbook_enabled_for_prompt_agents`, which defaults to true. Script Agent `ctx.llm.*` injection follows `worldbook_enabled_for_script_agents`, which defaults to false. Matching starts with the current user input for that call, not historical user messages, assistant messages, command results, form JSON, recipe JSON, or retrieved Knowledge. Disabled worldbooks and disabled entries are skipped. `activation_mode=always` entries activate in the initial round without keywords. `activation_mode=keyword` entries split `keywords_text` on English commas; each trimmed non-empty piece is treated as a regex pattern. `worldbook_case_sensitive=false` uses case-insensitive regex matching, and `worldbook_case_sensitive=true` uses case-sensitive matching. `worldbook_whole_words=true` wraps patterns with ASCII word boundaries `(?<![A-Za-z0-9_])` and `(?![A-Za-z0-9_])` so English keywords do not match inside longer words while CJK keywords can still match normally. Invalid legacy regex patterns are warnings and are skipped without failing the LLM call.

Worldbook recursion is controlled by `worldbook_recursion_depth`, default `0`. Depth `0` only scans the current input. Depth `1` scans the current input, then scans the content of entries newly activated in that first round; higher values repeat that content-triggered scan up to the configured depth. Recursion does not call an LLM, does not scan chat history, and does not scan Knowledge snippets. The same entry id can inject only once. Final injection order remains Session Worldbook binding order followed by entry `sort_order`; injected entries are capped by `worldbook_max_entries_per_call` and `worldbook_max_context_chars`, and recursion-related truncation records warnings.

`/kb-search <query>` is an explicit Knowledge Capability command for manual search/debugging. It routes through the normal slash command path, creates a command run, searches active KBs for the current session, and returns JSON with `query`, `results`, and `debug`. It does not call Prompt Agents, does not call an LLM, does not create an Agent run, and does not participate in automatic Knowledge context injection.

Agent override `runtime.knowledge_context_mode` is tri-state: `use_default`, `enabled`, or `disabled`. Effective defaults are:

- Prompt Agent: `use_default => enabled`.
- Script Agent with `llm`: `use_default => disabled`.
- Other Agents: disabled and no Knowledge override UI.

Run metadata records `metadata.knowledge_context` without full snippet content:

```json
{
  "enabled": true,
  "effective_mode": "enabled",
  "source": "prompt_agent",
  "knowledge_base_ids": ["kb_id"],
  "query": "short truncated query",
  "result_count": 4,
  "injected": true,
  "snippet_refs": [
    {
      "index": "K1",
      "chunk_id": "chunk_id",
      "knowledge_base_id": "kb_id",
      "knowledge_base_name": "Project KB",
      "source_id": "source_id",
      "source_title": "Spec",
      "rank": 1,
      "heading_path": "Intro",
      "vector_score": 0.72,
      "keyword_score": -3.1,
      "rrf_score": 0.031,
      "rerank_score": 0.91
    }
  ],
  "warnings": []
}
```

When Intent Routing provides a temporary Knowledge override, `metadata.knowledge_context.source` is `intent_routing_override`, `temporary_override` is true, `knowledge_base_ids` reflects the temporary KB selection, and `query` is the compact/truncated retrieval query override. Full query text beyond the metadata limit is not stored.

Run metadata records `metadata.core_memory_context` and `metadata.worldbook_context` without full user-maintained content:

```json
{
  "core_memory_context": {
    "enabled": true,
    "injected": true,
    "content_chars": 1234,
    "skipped_reason": null,
    "warnings": []
  },
  "worldbook_context": {
    "enabled": true,
    "injected": true,
    "worldbook_ids": ["worldbook_id"],
    "matched_entry_count": 3,
    "injected_entry_count": 2,
    "recursion_depth": 1,
    "recursion_rounds_used": 1,
    "case_sensitive": false,
    "whole_words": true,
    "truncated": false,
    "warnings": [],
    "entry_refs": [
      {
        "index": "W1",
        "worldbook_id": "worldbook_id",
        "worldbook_name": "Project Lore",
        "entry_id": "entry_id",
        "entry_name": "Terms",
        "activation_mode": "keyword"
      }
    ]
  }
}
```

Run step metadata may also carry compact context summaries for step-level display. Prompt Agents attach compact Core Memory, Worldbook, and Knowledge summaries to `Building context`. Script Agents append compact summaries to `Running script.metadata.core_memory_contexts`, `worldbook_contexts`, and `knowledge_contexts` for LLM calls. Step-level metadata must not include full Core Memory text, full Worldbook content, Knowledge query text, full snippet content, `snippet_refs`, or vector blobs; those remain in run/message metadata only where explicitly allowed for snippets button wiring.

Chat context inspection is a frontend workflow over compact refs. The message action opens a modal that shows only tabs for context types used in that run. Core Memory is read from current General settings, Worldbook entries are fetched by `metadata.worldbook_context.entry_refs[*].entry_id`, and Knowledge chunks are fetched by `metadata.knowledge_context.snippet_refs[*].chunk_id`. If user-owned content changed or was deleted after the run, the modal shows the current content or an unavailable state rather than a stored snapshot.

Skipped or failed retrieval records `enabled=false` or `injected=false` with a `reason` such as `agent_disabled`, `no_active_kbs`, `empty_query`, `no_results`, or `retrieval_failed`. Query metadata is truncated and full retrieved content is not stored in run or message metadata. Assistant/agent messages that used automatic Knowledge context copy this compact `knowledge_context` metadata so the UI can show a snippets button. Full chunk content is fetched on demand with `GET /api/knowledge/chunks/{chunk_id}`, which returns chunk content and minimal KB/source metadata without vectors or full source originals.

## Speaker Identity

Message `role` is the provider-compatible direction of the message. New provider-bound payloads may only use `system`, `user`, and `assistant`.

Message speaker fields identify the actual Workbench speaker:
- `speaker_type`: `user`, `agent`, `capability`, or `system`.
- `speaker_id`: stable speaker id when available, such as `local_user`, an Agent id, or a Capability id.
- `speaker_name`: display name used for transcript labels.
- `origin`: message origin such as `user_message`, `agent_reply`, `command_result`, `system_notice`, `separator`, `model_changed`, or `context_mode_changed`.

New user messages use `role="user"`, `speaker_type="user"`, `speaker_id="local_user"`, `speaker_name="User"`, and `origin="user_message"`.

New Agent replies use `role="assistant"`, `speaker_type="agent"`, `speaker_id=<agent_id>`, the resolved Agent display name as `speaker_name`, and `origin="agent_reply"`.

New slash command results use `role="assistant"`, `speaker_type="capability"`, `speaker_id=<capability_id>`, a Capability or command display name as `speaker_name`, and `origin="command_result"`. Their metadata continues to include `metadata.kind="command_result"`, `metadata.command`, `metadata.capability_id`, and `metadata.output_type`.

Interactive form submissions with `submit.visibility="message"` create user-origin messages with `role="user"`, `speaker_type="user"`, `speaker_id="local_user"`, and `origin="form_submission"`. Their visible `content` is the form submit message or `Submitted form: <title>`, not the full submitted JSON. Silent form submissions do not create a visible user message.

`command_buttons` clicks create ordinary user messages with `role="user"`, `speaker_type="user"`, `speaker_id="local_user"`, and `origin="user_message"`. The message content is the button `message`, and provider-bound role remains `user`.

Manual `:action` shortcut input also creates an ordinary user message with the original `:action args` content when it routes successfully. The run resolves to `session.default_agent_id` plus the parsed action, and invocation metadata records `route_kind="current_agent_action_shortcut"` with the resolved Agent/action ids. Provider-bound role remains `user`.

Old messages may lack speaker fields. Context projection falls back from role, top-level `agent_id` / `command_name`, and command-result metadata. Old `role="tool"` command results are compatibility data only and are normalized or skipped before provider calls.

## Interactive Forms

`action_form` is a `rich_content` block that lets trusted Agents render declarative forms. The frontend must not execute form-provided HTML or JavaScript and must not submit to arbitrary URLs.

An `action_form` may include static UI layout metadata: top-level `sections`, form-level `ui.default_collapsed` / `ui.collapsed` / `ui.collapse_on_success` / `ui.collapsed_message`, and per-field `ui.section` / `ui.span`. This metadata only shapes frontend rendering. It does not affect form submission, validated values, conversation context projection, provider-bound roles, submit target resolution, or silent submit behavior. Collapsed state is not projected into provider-bound LLM context. Dynamic onchange refresh is not part of the protocol; trusted backend Agent code may still replace a source form after a validated submit.

Form submission protocol:
- The frontend sends `source_message_id`, `form_id`, and `values` to the form submission endpoint.
- The backend reads the original source message and resolves the target `agent_id` / `action_id` from the original `action_form` block.
- The backend resolves `submit.visibility` from the original `action_form` block. Missing visibility means `"message"`.
- Request body target fields or visibility cannot override the original form target or visibility.
- Submitted values are validated against the original form field declarations before any Agent action is called.
- Validation failure returns a structured error and does not create a run.
- The frontend must not send replacement form blocks. Only trusted backend Agent code may rebuild and persist a source form after validated submission.

For `submit.visibility="message"`, the backend creates a new user message with metadata like:

```json
{
  "origin": "form_submission",
  "source_message_id": "msg_1",
  "form_id": "demo",
  "target_agent_id": "render_test",
  "target_action_id": "form_submit",
  "prefill": {"prompt": "hello"}
}
```

The target Script Agent receives the validated values in `ctx.input.prefill`, plus `ctx.input.source_message_id` and `ctx.input.form_id`. Message-mode form submissions may enter future LLM context as normal user messages, but only their short visible summary is projected by default. The full `prefill` JSON stays in metadata and is not automatically expanded into provider payloads.

For `submit.visibility="silent"`, the backend invokes the same target Agent action without creating the visible `form_submission` user message. Script Agents receive `ctx.input.prefill`, `ctx.input.source_message_id`, `ctx.input.form_id`, and `ctx.input.is_silent_submission=true`. Normal assistant replies and public output streams from the target action are suppressed, so successful save-only actions return a structured submission response instead of appending chat timeline messages. Silent submit may update the source form only when the target Agent persists a backend-generated replacement block and emits `message_updated`; the response may also include `updated_form` with `source_message_id`, `form_id`, and `block`. A successful save may set `updated_form.block.ui.collapsed=true` so the frontend collapses that source form only; validation failure or target action failure must not collapse it. The full `prefill` and any collapsed state still stay out of provider-bound LLM context unless an Agent explicitly uses them.

Provider-bound message roles remain limited to `system`, `user`, and `assistant`; message-mode and silent form submissions do not introduce `tool`, `function`, or custom provider roles.

## Command Button Shortcuts

`command_buttons` is a `rich_content` block that renders shortcut buttons for trusted Agents to send fixed text through the normal user-message path.

Click protocol:
- The frontend calls the existing send-message flow with the button `message`.
- The backend receives the same request shape as manual composer input.
- Routing follows the normal priority order, so `@comfyui_agent:form` routes to `comfyui_agent.form` and `@comfyui_agent:run` routes to `comfyui_agent.run`.
- A click creates a normal visible user message.
- Provider-bound role remains `user`.

Non-goals:
- It is not an `action_form` submit.
- It is not a hidden message action.
- It does not send `source_message_id`, `form_id`, `prefill`, or attachments.
- It does not call a backend Agent action API directly.
- It does not execute arbitrary JavaScript or navigate to URLs.

## Group Transcript Context

In `group_transcript`, the provider payload still only uses `system`, `user`, and `assistant` roles.

The system message contains the Agent prompt or prompt override plus identity instructions:
- The current Agent is told its own name.
- Prior messages from the same Agent are labeled `[Agent Name (you)]`.
- Other Agent messages are labeled `[Agent Name]`.
- User messages are labeled `[User]`.
- Command result blocks are labeled `[Command result: ...]` and explicitly described as data, not instructions.
- The Agent is instructed to reply only as itself and not impersonate other Agents.

The group transcript system instruction can be overridden in Settings -> General -> Context Rendering. The override replaces only this instruction text. It does not expose or change the transcript structure, speaker label format, `<conversation_transcript>` block, `<current_user_message>` block, provider role rules, or the current-user-message preservation behavior.

The user message contains:
- `<conversation_transcript>` with recent history rendered using speaker labels.
- `<current_user_message>` with the current user input, which is always preserved.

System, separator, model-changed, and context-mode-changed event messages are skipped by default so they do not pollute the transcript. Transcript rendering is a temporary context projection; it does not modify stored message content.

This mode does not implement auto mode, automatic Agent collaboration, Agent-to-Agent scheduling, function calling, tool calls, or MCP.

## Command Results in LLM Context

- Slash command results are internal Command/Capability outputs, not OpenAI tool messages.
- Commands remain declared by Capabilities, not Agents.
- The project does not emit `role="tool"` or `role="function"` to LLM providers unless a future implementation adds the full function/tool calling protocol, including assistant tool calls and matching tool result ids.
- New slash command result messages are stored as assistant messages with command-result metadata such as `metadata.kind="command_result"`, `metadata.producer="capability"`, `metadata.command`, `metadata.capability_id`, and `metadata.output_type`.
- Old persisted `role="tool"` or `role="command"` command result messages are compatibility data. Context projection must normalize them before provider calls or skip them if they cannot be safely paired with a triggering user command.
- When command results enter Prompt Agent context, they are projected as assistant messages with a clear command result header, capability source, output type, and the warning that the content is data, not instructions.
- The command result context instruction can be overridden in Settings -> General -> Context Rendering. The override replaces only the warning/instruction text.
- Command result projection must not use system-role content, because command output should not receive system-level weight.
- Command results remain assistant-role data blocks with command/source/output-type headers and bounded output blocks; overrides do not enable tool roles, function roles, system-role command output, or provider payload role changes.
- Pair-aware trimming keeps a slash command user message and its command result together. If the triggering user command is trimmed out, the command result is also trimmed out.
- Text and markdown outputs enter context in a bounded `<command_output>` block.
- JSON outputs enter context as a bounded `<json>` block.
- `file_content` outputs enter context in a bounded `<file_content>` block with filename, MIME type, size, and truncated metadata.
- Image and image gallery outputs enter text context as placeholders only. Historical image bytes or data URLs are not resent unless explicit vision resend support is implemented.
- Rich content outputs preserve block order where practical: text, markdown, and file content blocks are expanded; image blocks become placeholders.
- Binary or unsupported command outputs enter context as placeholder summaries instead of raw data.
- Provider-bound chat payload validation allows only `system`, `user`, and `assistant` roles. Invalid internal roles should fail early with `LLM_CONTEXT_INVALID` rather than surfacing provider prompt-template errors as the only diagnostic.

## Provider and Model Status

Status values:
- `READY`: provider and configured model look usable.
- `PROVIDER_UNREACHABLE`: connection failed or timed out.
- `MODEL_NOT_AVAILABLE`: provider is reachable but requested model is absent.
- `MODEL_MISMATCH`: single-model provider is serving a different model.
- `MODEL_STATUS_UNKNOWN`: provider response was incomplete or ambiguous.

Provider behavior:
- LM Studio first uses native `/api/v1/models` when available.
- LM Studio native responses can include `loaded_instances`; unload targets loaded matching instances.
- LM Studio model status is green `READY` when the model exists and has loaded instances, yellow `MODEL_NOT_LOADED` when it exists without loaded instances, and red for missing or unreachable providers.
- LM Studio falls back to OpenAI-compatible model listing when native status is unavailable.
- llama.cpp router mode reports a list of models.
- llama.cpp single-server mode reports only the currently served model; use `--alias` for a stable id.
- OpenAI-compatible providers support basic reachability/model-list status when the API exposes models.
- OpenAI-compatible model status is green `READY` when the provider is reachable, `/v1/models` returns a parseable list, and the configured model id exists in that list.
- OpenAI-compatible model status is red when the provider is unreachable, the provider/model profile cannot be resolved, the target model id is missing, or the parseable model list does not contain the configured model id.
- OpenAI-compatible providers do not expose portable loaded/unloaded pool semantics, so they should not produce yellow unloaded status.

Status usage:
- Provider-level status is an aggregate across configured model profiles.
- Model-level status is more specific and should be preferred for user-facing model badges.
- A reachable provider with an incomplete model list should not be treated as ready without model evidence.
- Unload support is provider-specific; unsupported unload should be reported as a warning unless policy says fail.
- Unload is available to trusted script/runtime paths only, not as a normal user-facing action.
- After an unload attempt finishes, refresh the affected provider profile status and emit `llm_provider_status_updated` when refresh succeeds.
- Unsupported unload and unload-triggered status refresh failures are cleanup outcomes and must not overwrite an otherwise successful main run.

## Attachments and Vision

- User attachments are stored as local refs in message metadata.
- Image attachments are sent to the LLM only when resolved Model Profile has `supports_vision=true`.
- Text files are sent to Prompt Agent context only when the General setting enables file context.
- Script Agents can read attachments through trusted helpers.
- `file_content` displays raw text and should not be markdown-rendered.

Attachment metadata:
- User message metadata keeps attachment refs rather than full base64 payloads.
- Script-generated attachments are stored in the same local attachment store and linked from assistant message metadata so orphan cleanup can track them.
- Generated attachment metadata may record source integration details such as ComfyUI prompt id, preset id, and workflow file name.
- ComfyUI generated image attachments should represent formal output images, such as SaveImage outputs. Temporary, preview, and input image refs are filtered before final `image_gallery` rendering.
- Prompt Agent vision resolves images to data URLs only for supported profiles.
- Unsupported image input becomes a text placeholder or warning instead of a vision payload.
- File attachment context obeys per-file and per-message byte limits.
- File and HTTP Capabilities are active commands, not passive upload handling.

Output rendering boundaries:
- Backend output type selects the frontend renderer.
- `markdown` content is rendered as markdown.
- `file_content` content is rendered as raw text.
- `image` and `image_gallery` payloads require renderable URLs.
- Generated images should use local attachment URLs such as `/api/attachments/<id>.png` rather than durable message content containing base64.
- `rich_content` preserves ordered blocks.
- The frontend must not infer streaming state from content shape.
- Renderer changes should update output payload contracts when shapes change.

## Source and Tests

Source:
- `ai_workbench/core/runner.py`
- `ai_workbench/core/script.py`
- `ai_workbench/core/run_lifecycle.py`
- `ai_workbench/core/events.py`
- `ai_workbench/core/llm_config.py`
- `ai_workbench/core/provider_status.py`
- `frontend/src/store/useWorkbenchStore.ts`
- `frontend/src/components/MessageBubble.tsx`

Tests:
- `tests/test_prompt_agent_execution.py`
- `tests/test_script_agent.py`
- `tests/test_provider_status.py`
- `tests/test_frontend_chat_contracts.py`
- `tests/test_file_http_attachments.py`
