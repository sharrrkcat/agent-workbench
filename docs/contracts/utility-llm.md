# Utility LLM Contract

Utility LLM is a core internal service for short deterministic tasks. Current
uses are automatic session title generation and Intent Routing strict JSON slot
extraction.

## Identity

Utility LLM is:

- a core runtime service.
- an internal short-call helper.
- optionally backed by local model files or an existing Model Profile.

Utility LLM is not:

- an Agent.
- a Capability.
- a slash command.
- a Provider Profile.
- a Model Profile.
- an AgentConfig field.
- a CapabilityConfig field.
- an Agent or Capability manifest field.

It may reference a Model Profile as a backend, but that reference does not make
Utility LLM an owner of provider/model configuration and does not mutate main
LLM resolution.

## Backends

Supported backends:

- `transformers`: local Hugging Face / safetensors folder.
- `llama_cpp`: local GGUF file through optional `llama-cpp-python`.
- `model_profile`: existing LLM Model Profile for an internal short call.

Model path contract:

- `transformers`: `utility_llms/<folder>`
- `llama_cpp`: `utility_llms/<model-folder>/<file>.gguf`
- root-level GGUF files directly under `utility_llms` are ignored/invalid.
- `model_profile` does not require a local Utility LLM path.

Local paths are under `data/models/utility_llms`. The app never downloads Utility
LLM files, installs optional dependencies, or registers GGUF files as Provider
Profiles or Model Profiles.

## Settings Ownership

Settings -> General -> Utility LLM owns backend, local model path or Model
Profile reference, device, runtime options, llama.cpp options, scan/status/test
controls, and unload controls.

Settings -> General -> Intent Routing may show a compact Utility LLM status
summary, but it does not own backend/model/device/options.

Settings -> General -> LLM & Prompts owns session title settings: title backend
selection, optional specific title Model Profile, prompt/input limits, and
best-effort title model release.

## APIs

Utility LLM APIs:

| endpoint | responsibility |
| --- | --- |
| `GET /api/intent/utility-llm/status` | reports compact configuration, availability, loaded state, backend status, and public Model Profile identifiers when relevant |
| `GET /api/intent/utility-llm/models/scan` | scans local `data/models/utility_llms` folders without loading weights, downloading files, installing dependencies, or creating records |
| `POST /api/intent/utility-llm/test-title` | tests configured title generation behavior and returns compact title/error data |
| `POST /api/intent/utility-llm/test-json` | tests strict JSON extraction and returns compact parsed slots/error data |
| `POST /api/intent/utility-llm/unload` | releases only local Utility LLM caches |

`POST /api/intent/test-route` may use Utility LLM when `include_utility` is
requested and route gates require it, but Route Test remains an Intent Routing
diagnostic API. It must not execute commands, create messages/runs, run
Knowledge retrieval, or mutate session state.

The Utility LLM unload endpoint releases only local Utility LLM caches. It does
not unload the main LLM, embeddings, reranker, or ComfyUI. For `model_profile`,
it returns a no-local-cache style result and does not call global LLM unload.

Common status/test reason codes include:

- `model_path_not_configured`
- `model_not_found`
- `backend_model_path_mismatch`
- `model_path_invalid`
- `UTILITY_LLM_BACKEND_UNAVAILABLE`
- `llama_cpp_unavailable`
- `model_profile_not_configured`
- `model_profile_not_found`
- `model_profile_disabled`
- `provider_profile_unavailable`
- `model_profile_generation_failed`
- `utility_llm_invalid_json`
- `no_local_utility_cache`

## Model Profile Backend

The `model_profile` backend performs an internal non-streaming deterministic
short call through an existing Model Profile. It must not:

- create a visible message.
- create an Agent run.
- recursively trigger Intent Routing.
- recursively trigger session title generation.
- inject Knowledge, Core Memory, Worldbook, attachments, or history.
- mutate the session selected Model Profile.
- change main response LLM resolution.
- store secrets in metadata.

Metadata may record only compact public profile/provider/model identifiers and
warnings.

## Session Title Interaction

Automatic session title generation is a one-shot best-effort pre-hook for
pending default-titled sessions after the first user message that resolves to an
LLM-capable Agent/action. Non-LLM slash commands do not trigger title
generation. Explicit Agent/action calls and safe Intent Routing auto routes may
trigger titles when the final invoked Agent/action uses an LLM.

The title prompt uses only the triggering user message. It does not use
assistant replies, slash command results, prior history, Knowledge snippets,
Worldbook entries, Core Memory, attachments, or command output. Long user input
is truncated from the middle according to the General title input limit.

Title backend behavior:

- `utility_llm`: uses the configured Utility LLM first. If it is unconfigured,
  unavailable, missing dependencies/model files/profile/provider, fails
  generation, or returns an invalid title, it falls back to
  `follow_agent_model_profile`.
- `follow_agent_model_profile`: resolves the composer/session Model Profile
  override first, then the session default Agent Model Profile, then the actual
  invoked Agent Model Profile. It does not fall back to Utility LLM.
- `specified_model_profile`: uses only `session_title_model_profile_id`. Missing,
  disabled, invalid, or unavailable profiles skip title generation with a compact
  warning and do not fail the main run.

Title generation is internal and non-streaming. It creates no visible user or
assistant messages, emits no `message_delta`, does not trigger Intent Routing,
does not change selected Agent/Model Profile, and does not change main response
model resolution. Failure keeps the original title and lets the main
conversation continue.

Unload behavior is best-effort:

- `not_requested` when release is disabled.
- `released` when a supported release succeeds.
- `deferred_until_run_end` when the title target is also needed by the current
  response.
- `no_supported_release` for providers/backends without unload support.
- `failed` for release failure.
- `skipped_no_model` when no model was loaded.

Utility local backends use the Utility unload helper when release is requested.
Model Profile title calls use the existing provider unload helper when release
is requested and must not unload the current response model mid-run.

Title metadata is compact. It may include state, backend, fallback use, source
message id, truncation counts, generated timestamp or error, public model/profile
identifiers, unload state, and warnings. It must not store full long user input,
full prompts, raw model output, or secrets.

## Intent Routing Interaction

Intent Routing uses Utility LLM for strict JSON slots after semantic prediction.
Utility LLM must not replace the semantic router and must not execute directly.

The Intent Routing prompt/context is compact:

- current text.
- semantic intent/action candidate.
- compact top RouteSpec/ActionSpec data.
- compact slot schemas.
- compact Knowledge Base names/aliases.
- compact Pet candidates when needed.
- safety boundaries.

It must not include full prompts, full history, KB content, Worldbook content,
Core Memory content, Agent prompts, raw embeddings, full candidate lists, full
examples/specs, or secrets.

Output is strict JSON. The parser may accept a JSON object, fenced `json`
object, or a response with one balanced JSON object surrounded by explanation.
Malformed JSON records `utility_invalid_json`; missing required slots or invalid
enum values record `utility_slots_failed`. Extra fields are ignored. Semantic or
slot conflicts are validator failures, not execution instructions.

For Intent Routing `web_query`, the Utility LLM may return only compact slots:
`intent`, `query`, `use_original_query`, `freshness`, `domain_hints`, and
`language_hint`. These slots are diagnostic-only in this round; they must not
cause Web Search Capability calls, provider-bound web prompts, web context
injection, or search result storage.

## Metadata And Raw Output

Utility LLM metadata may store compact public backend/profile/provider/model
identifiers, availability, success/failure state, error codes, warnings, and
validated slots when the caller contract allows slots.

Production metadata and normal runtime APIs must not store or return:

- raw provider/model output.
- prompts.
- secrets.
- full chat history.
- Knowledge, Worldbook, Core Memory, attachment, or Agent prompt content.

Dedicated test endpoints may return only the validated artifact and compact
diagnostics defined by their API contract, such as a generated title or parsed
JSON slots. They must not expose raw provider output unless a future contract
explicitly creates a debug-only field with clear safety limits.
