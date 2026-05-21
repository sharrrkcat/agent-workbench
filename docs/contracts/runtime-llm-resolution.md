# Runtime LLM Resolution Contract

This contract owns main LLM resolution, Model Profile runtime behavior, provider
capability flags, model metadata, and lifecycle unload behavior.

## Resolution Order

Main LLM calls resolve in this order:

1. Session override when the resolved Agent/action allows it.
2. AgentConfig runtime `llm_profile_id`.
3. Manifest `llm.profile`.
4. Default model profile.
5. Legacy global fallback.
6. Environment fallback.

Current implementation note: `resolve_llm_config` applies defaults first and
then overlays later sources, so later sources win. Keep user-facing behavior
aligned with the order above when changing it.

Session override is ignored when the resolved Agent runtime disallows it.
Missing model selection raises stable error code `LLM_MODEL_NOT_SELECTED`.

Legacy global fallback comes from persisted `llm` CapabilityConfig. Environment
fallback uses:

- `AGENT_WORKBENCH_LLM_BASE_URL`
- `AGENT_WORKBENCH_LLM_API_KEY`
- `AGENT_WORKBENCH_LLM_MODEL`
- `AGENT_WORKBENCH_LLM_TIMEOUT`

The Default model profile fallback is configured in Settings -> General -> LLM &
Prompts. Provider Profiles and LLM Model Profiles are managed under Settings ->
Models.

## Profile Semantics

Provider Profile means connection details: provider, base URL, API key, timeout,
enabled state, and provider-specific metadata.

Provider Profiles may also represent internal local LLM backends
(`internal_transformers` and `internal_llama_cpp`). LLM Model Profiles may
reference those providers with a `provider_model_id` / `model_id` value that
starts with `llm/`, resolved under `data/models/llms`. Internal provider
inventory can also list `embedding/` and `reranker/` refs for future profile
types, but LLM Model Profiles must not select those refs.

Model Profile means user-facing model selection and behavior defaults: provider
model id, stable profile key, capabilities, generation defaults, notes, and
enabled state.

Internal LLM Model Profile runtime support is metadata-only until generation:
startup and Settings loading must not import torch, transformers, or
llama-cpp-python. Generation through `internal_llama_cpp` requires a `.gguf`
`llm/...` ref and optional `llama-cpp-python`; generation through
`internal_transformers` requires a model directory `llm/...` ref plus optional
`transformers` and `torch`. Internal adapters do not support vision, tools, or
provider function calling in this round, and should not claim streaming support
unless an adapter explicitly implements and tests it.

Composer `Default` means the Agent default resolved model. It is not an
additional Model Profile.

Actual model metadata comes from provider responses and should be preserved in
run/message metadata and debug details. Assistant message header model badges
prefer Model Profile display name/name, then requested model id, then actual
model id. The bottom status bar may remain debug-oriented and show provider
profile plus target/actual model details; it does not need to match short chat
badges.

API keys and secrets must not be returned in status or metadata.

## Capability Flags

Model Profile capability flags declare expected behavior and UI/runtime gates:

- `supports_streaming`: enables visible Prompt Agent streaming.
- `supports_vision`: allows image attachments to be encoded into Prompt Agent
  LLM messages.
- `supports_tools`: reserved; routing does not depend on provider tool calls.
- `supports_reasoning`: declares expected reasoning output metadata and does not
  force provider behavior.
- `supports_json_mode`: declares provider/model support, but scripts must still
  validate JSON.

## Prompt Agent Calls

Prompt Agents let the core build context and call the resolved main LLM.

- Non-streaming calls store one final assistant message.
- Streaming calls emit public deltas and then store final content on completion.
- Deltas persist only when Settings -> Data enables debug persistence.
- Context warnings may attach to message metadata.
- Image vision metadata records supported, attached, sent, and ignored counts.
- File context metadata records included text attachment details and warnings.

Prompt Agents treat model output as assistant content, not provider tool calls or
structured commands.

## Script Agent Calls

`ctx.llm.text`, `ctx.llm.json`, and `ctx.llm.generate` mark the LLM as used for
lifecycle cleanup. `ctx.llm.stream` marks the LLM as used but remains internal.
`ctx.llm.stream_to_output` both uses the LLM and writes public deltas.

Scripts must parse and validate model output themselves. They should not assume
provider function calling is available.

Core Memory, Worldbook, and Knowledge may be injected into eligible Script Agent
`ctx.llm.*` calls according to their contracts. Direct prompt-backed
`ctx.llm.generate` receives rendered blocks prepended to the prompt.

## Utility LLM And Titles

Utility LLM does not participate in main LLM resolution. It is configured by
General settings and uses a selected enabled LLM Model Profile for internal
short calls. Legacy local Utility LLM backend fields may still be read for
compatibility warnings, but they are not the primary runtime selector. Utility
LLM does not change the user's selected main model.
Full behavior: [utility-llm.md](utility-llm.md).

Page Excerpt Gate has two internal Model Profile resolution modes outside the
visible Prompt Agent flow:

- `follow_agent_model_profile` reuses the already resolved current Prompt Agent
  response model config for a deterministic non-streaming JSON judgment.
- `specific_model_profile` resolves only the General setting
  `web_context_page_excerpt_gate_model_profile_id`; missing, disabled, invalid,
  or provider-unavailable profiles fail that gate attempt without failing the
  main Prompt Agent run.

These internal gate calls do not change the session selected Model Profile, do
not create assistant messages, do not create Agent or command runs, do not enter
Prompt Agent context building, and do not trigger title generation, Intent
Routing, Knowledge, Core Memory, Worldbook, attachments, history, or Web Context
recursively.
Prompt composition for follow-agent and specific-profile Page Excerpt Gate calls
includes automatic current local/UTC time context, the configured General Web
Search gate prompt body, and app-owned fixed JSON schema/safety instructions.
The page excerpt in that prompt is the capped cleaned excerpt produced by Prompt
Agent Web Context page fetching, or the capped basic excerpt when cleaning
falls back. This composition does not mutate the main response model resolution
and does not store raw prompts or raw model output in runtime metadata.

Session title generation has its own resolver:

- `utility_llm` tries Utility LLM first, then falls back to the title
  follow-Agent resolver.
- `follow_agent_model_profile` resolves composer/session input override, session
  default Agent profile, then invoked Agent profile.
- `specified_model_profile` uses only the configured title Model Profile id.

Title decisions never mutate the session selected Model Profile or main response
LLM resolution.

## Unload Behavior

Unload is trusted script-only for manual script calls and best-effort for
lifecycle policies. Providers may report unsupported unload.

Successful, skipped, unsupported, and failed unload attempts remain cleanup
outcomes in run metadata. Unsupported unload and status-refresh failure do not
overwrite an otherwise successful run unless `unload_failure` policy explicitly
fails the run.

Manual script unload uses trusted helpers such as `ctx.llm.unload()` or
`ctx.llm.unload_model(...)` and should surface success through the current run
step rather than adding another assistant message.
