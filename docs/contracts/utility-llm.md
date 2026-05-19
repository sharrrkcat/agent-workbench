# Utility LLM Contract

Utility LLM is a lightweight core internal service for short deterministic tasks. Current
uses are automatic session title generation, Intent Routing strict JSON slot
extraction, Web Context Plan Resolver strict JSON planning, and optional Web
Candidate Relevance Judge conservative JSON noise filtering.

## Identity

Utility LLM is:

- a core runtime service.
- an internal short-call helper.
- optionally backed by local model files or an existing Model Profile.
- suitable for simple JSON slots, query extraction, and low-risk auxiliary
  judgments.

Utility LLM is not:

- an Agent.
- a Capability.
- a slash command.
- a Provider Profile.
- a Model Profile.
- an AgentConfig field.
- a CapabilityConfig field.
- an Agent or Capability manifest field.
- the sole judge for complex evidence selection or factual correctness.

Callers must assume small local Utility LLMs may miss useful context. Utility
LLM output can assist deterministic core logic, but it must not be treated as a
stable final authority for complex evidence evaluation, source selection, or
fact judgment.

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

## Web Context Plan Resolver Interaction

When General Web Search is enabled and Intent Routing auto mode does not already
select Knowledge, Pet, or validated `web_query` slots, Web Context may use one
short Utility LLM call to decide whether the current user message asks for an
external fact search. The call returns strict JSON with only
`should_search`, `query`, `reason`, and `confidence`.

Resolver guidance must distinguish explicit information requests from incidental
mentions. "Do you know / have you heard / did you see" plus
yesterday/today/recently and a real-world event is treated as a likely
`time_sensitive_fact_question`. Explicit search/check/latest/current-status
requests should produce a compact query. Personal preference, emotion,
roleplay, conversation continuation, and long messages that only incidentally
mention prices, news, entities, or real-world keywords should not search.
Keywords alone are not sufficient.

This planning call is internal. It does not create a message or run, does not
trigger Intent Routing or title generation, does not inject Knowledge, Core
Memory, Worldbook, attachments, assistant replies, or full history, and does
not change main model resolution. It must receive only the current user text,
compact task rules, a strict schema, and small examples. Runtime metadata may
store only validated compact slots and warnings, never raw Utility output or the
prompt.

## Web Candidate Relevance Judge Interaction

When General Web Search Candidate Judge is enabled, Prompt Agent Web Context may
use one short Utility LLM call to judge filtered/de-duplicated search candidates
before page fetching. The call returns strict JSON with an `items` array. Each
item may include `candidate_id`, `use_source`, `relevance`, `confidence`,
`source_role`, and a short `reason`.

The Candidate Judge runs in `conservative_reject_only` mode. Search candidates
are retained by default. The Utility LLM may only remove clear noise: an item
must be valid JSON, reference a known candidate id, set `use_source=false`,
`relevance=low`, `confidence=high`, and use a reject role such as `noise`,
`off_topic`, or `weak_match`. `use_source=true`, medium/high relevance,
low/medium confidence, missing candidate ids, invalid items, unknown enum
values, and candidates omitted from Utility output are retained. Omitted
candidate ids are counted as unjudged. Unknown candidate ids are ignored with a
compact warning.

The judge input is limited to:

- current user text, truncated for the judge.
- Web Context query and query source.
- compact candidate fields: candidate id, rank, title, domain, short URL path,
  snippet preview, and source label.
- task rules and strict schema.

It must not receive Agent prompts, full chat history, assistant output,
Knowledge snippets, Core Memory, Worldbook entries, attachments, raw SearXNG
payloads, page bodies, page excerpts, raw HTML, Web Context prompt text, or
secrets. It must not create messages or runs, execute commands/Agents/actions,
modify session state, mutate Context Sources, change Agent selection, or affect
main model resolution. Invalid JSON, unavailable Utility LLM, or whole-response
schema failure falls back to the pre-judge search results with compact warning
codes and must not fail the main Prompt Agent run. Runtime metadata may store
only compact mode/counts, warning codes, aggregate rejected reason counts, and
compact per-final source state/relevance/role/confidence/reason fields.

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
