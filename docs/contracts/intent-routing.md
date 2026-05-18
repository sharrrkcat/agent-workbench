# Intent Routing Contract

Intent Routing is an optional pre-routing layer for ordinary natural-language
messages. It predicts whether the current message should stay with the current
Prompt Agent, receive a temporary Knowledge query override, or use one of the
small explicitly allowed runtime paths. It never replaces explicit syntax.

## Explicit Bypass

These inputs bypass Intent Routing before semantic classification:

- `/command`
- `@agent`
- `@agent:action`
- `:action`

Waiting-run resumes, form submissions, silent submissions, explicit command or
Agent calls, explicit action shortcuts, and non-text inputs also bypass Intent
Routing.

## Modes And Eligibility

Settings -> General -> Intent Routing owns the master switch, global mode,
safe-auto switch, semantic thresholds, custom built-in-intent examples, and the
semantic router Embedding Model Profile reference.

Agent detail -> Intent Routing owns Prompt Agent effective entry overrides and
Agent target hints. Agent target hints help classify diagnostic `agent_route`
candidates; they do not grant generic Agent auto execution.

Intent Routing is eligible only when all of these are true:

- General `intent_routing_enabled` is true.
- General `intent_routing_mode` is `shadow` or `auto`.
- The input is ordinary text to the current session default Agent's `default`
  action.
- The current session default Agent is a Prompt Agent.
- The Prompt Agent effective Intent Routing override is enabled.
- The session `context_mode` is `single_assistant`.

Script Agents, non-Prompt Agents, and `group_transcript` mode do not enter the
classifier.

`shadow` mode records compact prediction metadata only and never changes the
selected route. `auto` mode may execute only the safe allowlist below when all
semantic, Utility LLM, validator, and executor gates pass.

## Pipeline

Intent Routing v2 uses one fixed pipeline:

```text
Semantic router -> Utility LLM slots/extraction -> Validator -> Executor
```

The embedding semantic router is the only natural-language classifier for Route
Test, shadow metadata, and auto-mode route decisions. It aggregates scores by
intent group before execution gating. The intent score is the best score for the
intent group, and the intent margin compares the top intent group with the
second intent group.

RouteSpec and ActionSpec are core runtime internals used for semantic
candidates, Utility LLM candidate context, slot schemas, validator ids, and
executor ids. They are not Agent or Capability manifest schema. SlotSchema
defines strict JSON slots. Validators produce ValidatorResult. Executors produce
ExecutorPlan. Route Test and real runs share validation/planning; only real
auto-mode runs execute.

Regex and deterministic helpers may support explicit syntax parsing, slot hints,
exact id/name/alias matching, false-positive guards, and validators. They must
not replace semantic routing as the classifier, replace Utility LLM as the
natural-language slot parser, or override semantic score/margin.

## Semantic Router Configuration

The semantic router uses only the existing Knowledge Embedding Model Profile
selected by General `intent_routing_embedding_model_profile_id`.

- There is no raw embedding model path UI or runtime path.
- Old persisted raw embedding path values are ignored.
- Saving settings does not load or test the model.
- Runtime never creates an Embedding Model Profile automatically.
- Runtime never downloads models or installs dependencies automatically.
- Candidate documents are embedded with `purpose=document`.
- Current user input is embedded with `purpose=query`.
- The selected profile's model path, instructions, normalization, and Knowledge
  Defaults device setting apply.
- Route candidate embeddings live in a lazy in-memory cache only; they are not
  persisted to SQLite, vector storage, or Knowledge indexes.

The route index key includes the embedding profile fingerprint, internal
RouteSpec/ActionSpec examples, General custom examples, enabled Knowledge Base
names/aliases/descriptions, Agent ids/names/descriptions/routing
aliases/examples/actions, Capability command metadata, and a short cache TTL.

If semantic routing is unavailable, runtime falls back to the current Prompt
Agent path and records compact warnings such as
`semantic_router_unavailable`, `semantic_router_profile_missing`, or
`semantic_router_embedding_unavailable`. No fallback classifier runs.

## Semantic Thresholds

Default semantic thresholds live in General settings:

| field | default | purpose |
| --- | ---: | --- |
| `intent_routing_semantic_intent_min_score` | `0.50` | minimum grouped intent score for safe auto-route decisions |
| `intent_routing_semantic_intent_min_margin` | `0.03` | minimum grouped margin between top and second intent |
| `intent_routing_semantic_kb_min_score` | `0.45` | minimum Knowledge Base candidate score |
| `intent_routing_semantic_agent_min_score` | `0.45` | diagnostic Agent candidate threshold |
| `intent_routing_semantic_command_min_score` | `0.45` | diagnostic command candidate threshold |

Old persisted high/low confidence threshold keys are ignored by current
settings and must not affect route decisions.

## Current Intent Boundaries

- `chat`: semantic-only special case. It keeps the current Prompt Agent path,
  does not call Utility LLM, does not add temporary Knowledge overrides, and
  does not change Context Sources.
- `knowledge_query`: may keep the current Prompt Agent path and pass a per-run
  temporary Knowledge Base/query override only after semantic gates, Utility LLM
  slots, and Knowledge validation pass.
- `pet_command`: may execute only the narrow existing `/pet` Capability command
  path described below.
- `web_query`: diagnostic-only. It identifies requests for current, recent,
  latest, official, or web-searched information and may extract compact query
  slots, but it does not call Web Search Capability, does not execute SearXNG,
  does not inject Prompt Agent web context, and does not create command or Agent
  runs.
- `image_generation`: diagnostic-only until action routing is designed. It does
  not auto-route to ComfyUI.
- `command_like`: diagnostic-only. It must not execute slash commands such as
  memory release or settings changes.
- `agent_route`: diagnostic-only. It must not switch the selected Agent or
  invoke a generic Agent.
- `action_route`: diagnostic-only. It must not invoke Agent actions.
- `compound`: diagnostic-only. It must not execute multiple tasks or command
  sequences.

The safe auto-route allowlist is deliberately narrow:

- `chat`
- high-confidence `knowledge_query`
- narrow `pet_command` for `/pet status`, `/pet wake`, `/pet tuck`,
  `/pet reload`, and `/pet select <pet_id>`

Web queries, general command-like requests, generic Agent routes, Agent actions,
image generation, and compound/multi-intent matches are metadata only in this
version.

## Web Query Rules

`web_query` is recognized by the semantic router and may use Utility LLM strict
JSON slots:

- `intent`: must be `web_query`.
- `query`: compact search query string; may be empty only when
  `use_original_query=true`.
- `use_original_query`: optional boolean.
- `freshness`: optional `any`, `recent`, or `today`.
- `domain_hints`: optional compact string array for diagnostics only.
- `language_hint`: optional compact language hint.

The validator requires semantic predicted intent `web_query`, Utility
`slots.intent=web_query`, and a non-empty effective query. If `query` is empty
and `use_original_query` is not true, validation records
`web_query_missing_query`.

The executor plan is always diagnostic-only:

- `would_execute=false`
- `executed=false`
- `not_executed_reason=web_query_diagnostic_only`
- `route_action=metadata_only`

This round must not call `/web-search`, Web Search Capability diagnostics, a
SearXNG provider, Knowledge retrieval, Prompt Agent Web Context, vectorization,
rerank, or search-result summarization for `web_query`.

## Knowledge Query Rules

`knowledge_query` auto execution requires:

- General mode `auto`.
- `intent_routing_auto_route_safe_intents=true`.
- all normal eligibility gates.
- semantic predicted intent `knowledge_query`.
- semantic score and margin meet intent thresholds.
- Utility LLM is available.
- Utility LLM slots extraction succeeds.
- `slots.intent=knowledge_query`.
- `slots.query` is non-empty or `slots.use_original_query=true`.
- the Knowledge validator selects an allowed KB set.

The Knowledge validator may select a KB from an exact Utility `kb_hint` match, a
semantic KB candidate above the KB threshold, or active session KB bindings when
no explicit KB candidate exists. KB aliases are trimmed comma-separated values on
Knowledge Base records and are used only for natural-language KB hint matching.
Ambiguous strong matches are warnings and must not randomly select a KB.

Execution sets only per-run temporary Knowledge values:

- `temporary_knowledge_base_ids`
- `knowledge_query_override`

It must not persist Context Sources bindings, change session KB bindings, change
the session default Agent, change the visible Agent selector, mutate retrieval
ranking/indexing, or rewrite the provider-bound current user message. The
original visible user message remains the persisted user message.

## Pet Command Rules

`pet_command` auto execution requires the normal safe-auto gates, semantic
predicted intent `pet_command`, semantic score at or above the intent minimum,
Utility LLM availability, Utility slot success, `slots.intent=pet_command`,
`slots.domain=workbench_pet`, an allowlisted action, and Pet validator approval.
Low semantic margin records a warning for `pet_command` but does not block
execution when the remaining gates pass.

Allowed actions:

- `status` generates `/pet status`.
- `wake` without a target generates `/pet wake`.
- `wake` with a unique target generates `/pet select <pet_id>` because selecting
  activates and wakes that pet.
- `tuck` generates `/pet tuck`.
- `reload` generates `/pet reload`.
- `select` requires a unique target and generates `/pet select <pet_id>`.

`/pet wake`, `/pet tuck`, and `/pet reload` do not accept parameters. Target
hints for status/tuck/reload are ignored and may record
`pet_target_ignored_for_action`. `source_pet_hint` is diagnostic only and never
blocks execution. `/pet random` is not implemented. No other slash command,
arbitrary Agent call, or multi-command sequence may execute through
`pet_command`.

Reality-pet questions and fictional character questions without Workbench Pet
context must not execute and should record `not_workbench_pet_context` when
Utility identifies a non-Workbench domain.

Natural-language `pet_command` auto routing preserves the original user text as
the visible message. The generated `/pet ...` command is metadata/internal input
only and must not create a synthetic user message.

## Utility LLM In Intent Routing

Utility LLM provides strict JSON slot extraction after semantic prediction. It
is not the classifier and cannot execute directly. Validator approval and an
ExecutorPlan are required before execution.

The extractor input is limited to:

- current user text.
- semantic top intent/action candidate.
- compact RouteSpec/ActionSpec ids, labels, descriptions, safety notes, and
  capped previews.
- compact SlotSchema definitions.
- compact Knowledge Base names/aliases.
- compact Pet candidates for `pet_command`.
- safety boundaries.

It must not receive Agent prompts, KB content, Worldbook content, Core Memory
content, full chat history, raw embeddings, full specs/examples, full candidate
lists, or provider-bound prompt text. Output is strict JSON used only as
validator input. Invalid JSON records `utility_invalid_json`; extraction or slot
validation failure records `utility_slots_failed`.

The Model Profile Utility backend is an internal non-streaming deterministic
short call. It does not create an Agent run or visible message, recursively
trigger Intent Routing or title generation, inject Knowledge/Core
Memory/Worldbook/attachments/history, mutate selected Model Profiles, or change
main response LLM resolution. Metadata may include public profile/provider/model
identifiers only.

See [Utility LLM](utility-llm.md) for the full Utility LLM contract.

## Route Test Contract

`POST /api/intent/test-route` is diagnostic-only. It may accept `text`,
optional `session_id`, optional `default_agent_id`, and `include_utility`.
Without a session it is a partial `eligibility_scope="no_session"` simulation.

Route Test must not:

- create a chat message.
- create a run or command run.
- execute `/pet` or any other command.
- execute an Agent or Agent action.
- run Knowledge retrieval.
- call Web Search Capability or its diagnostics endpoint.
- call ComfyUI.
- mutate session settings, Context Sources, session KB bindings, or Pet settings.

It reports semantic, spec, Utility LLM, validation, and execution-plan fields,
including `would_execute`. `would_execute` must match the same gating result a
real auto-mode run would use, while `executed=false` and
`executed_in_real_run="route_test_only"` remain diagnostic markers.

## Metadata Compactness

Intent Routing metadata may store compact public ids, scores, refs, counts,
slot values, warnings, and execution-plan summaries. It must not store:

- raw Utility LLM output.
- Utility prompts or provider-bound prompt text.
- embeddings.
- full examples, full specs, or full candidate lists.
- Agent prompts.
- KB, Worldbook, or Core Memory content.
- full chat history.
- Web Search provider raw payloads or search results.
- Pet manifests, spritesheet content, or image bytes.
- duplicate full `original_user_text` when the message body already stores it.

## Common Codes

Common `not_executed_reason` and warning codes are stable lowercase strings. UI
clients should map them to localized labels instead of displaying raw codes by
default.

Common codes include:

- `semantic_router_unavailable`
- `semantic_router_profile_missing`
- `semantic_router_embedding_unavailable`
- `semantic_confidence_too_low`
- `semantic_margin_too_low`
- `utility_llm_required`
- `utility_llm_unavailable`
- `utility_slots_failed`
- `utility_invalid_json`
- `utility_semantic_intent_conflict`
- `utility_semantic_action_conflict`
- `validation_failed`
- `knowledge_query_missing_query`
- `web_query_diagnostic_only`
- `web_query_missing_query`
- `kb_hint_semantic_conflict`
- `ambiguous_kb_candidate`
- `no_kb_candidate_or_active_kbs`
- `pet_candidate_not_found`
- `ambiguous_pet_candidate`
- `select_target_missing`
- `pet_target_ignored_for_action`
- `not_workbench_pet_context`
- `diagnostic_only`
- `image_generation_action_routing_not_ready`
- `command_like_auto_route_disabled`
- `agent_route_auto_route_disabled`
- `action_route_auto_route_disabled`
- `compound_intent_not_auto_routed`
- `explicit_command`
- `explicit_agent`
- `explicit_action`
- `group_transcript_not_supported`

## Settings And UI Ownership

- General -> Intent Routing owns route behavior, examples, Route Test, semantic
  router profile selection/status, candidate counts, and safe-auto controls.
- The Chat composer Intent Routing toggle controls the global General
  `intent_routing_enabled` setting. It does not create session-specific routing
  state.
- The Chat composer Web Search toggle controls the global General
  `web_context_enabled` setting. It forces Web Context only for eligible
  ordinary Prompt Agent messages and is not driven by Intent Routing
  `web_query`; `web_query` remains diagnostic-only.
- General -> Utility LLM owns Utility backend/model/device/options. The Intent
  Routing page shows only a compact Utility LLM status summary.
- Agent detail -> Intent Routing owns Prompt Agent overrides and Agent target
  hints.
- Knowledge Base aliases are Knowledge Base data used for `kb_hint` matching.
- Agent target hints are AgentConfig runtime fields, not manifest fields and not
  auto-execution grants.
