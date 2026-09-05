# Models and chat resolution contract

All inference calls use the app-scoped `core/models/ModelManager` and
`ProviderAdapter`. ChatRunner, Utility LLM, Knowledge and `/v1` call the
manager directly; internal callers do not loop back through HTTP.

## Profiles and connections

`model_profiles` has one schema/store and five kinds: `llm`, `embedding`,
`reranker`, `image_embedding`, `vision`. Internal references use the UUID
`id`; external requests use the globally unique `alias`. An alias is a
lowercase identifier, with no kind prefix or alternate lookup rules.

`provider_profiles` holds `protocol=openai_compatible`, `base_url`,
`api_key`, timeouts, concurrency, queue limits and enablement. There are no
brand-specific provider variants. A model holds `provider_profile_id`,
`model_ref`, capabilities, per-kind parameters, lifecycle, `enabled` and
`external_enabled`. Kind is immutable after creation. A model with no
connection can be saved but cannot execute until a backend is configured.

CRUD lives at `/api/models/providers` and `/api/models/profiles`; the latter
accepts `?kind=...`. Unknown parameters are rejected before persistence.
Deleting referenced profiles/connections returns 409. Changes to embedding
parameters, model reference or provider URL invalidate associated KB indexes.

Provider/settings GET responses omit keys and return `has_api_key` or
`has_external_api_key`. An omitted PATCH key preserves the secret; an empty
string clears it. Keys are stored locally and are not encrypted at rest.

## Resolution and parameters

1. `session.model_profile_id`, when set;
2. `/api/models/settings.default_model_profile_id`.

A missing selection returns `MODEL_NOT_CONFIGURED`; a disabled, missing or
wrong-kind selection fails explicitly. There is no substitution from
environment variables, text prefixes, manifests or old profile settings.

LLM profiles validate temperature, top_p, max_tokens, presence/frequency
penalties, seed and stop. Explicit request fields override profile defaults.
Capabilities are streaming, tools, vision, json_object and json_schema.
Unsupported requested capabilities return `UNSUPPORTED_CAPABILITY`.

## Lifecycle and implementation boundary

The manager owns health/load/unload, provider queues and cleanup. Defaults
are concurrency 1, 32 waiting slots and 30 seconds queue timeout. All requests,
including connection model discovery, share the provider queue. Queue
overflow/timeout returns `MODEL_BUSY`. Cancelling or closing a stream releases
its upstream response, slot and task registration.

Residency and active/queued counts are shared by `(provider_profile_id,
model_ref)`. Release defaults to `manual`. `after_request` and `idle`
(default 300 seconds) are opt-in. Any enabled manual alias keeps a shared model
resident; otherwise the longest configured idle timeout wins. Automatic
release errors are diagnostic and do not replace successful inference.

OpenAI-compatible connections execute chat and text embeddings. Load is a
health/model-list check; residency stays unknown and unload is unsupported.
Standalone rerank/image embedding/vision execution and local model loading
await Phase 2b managed runtimes. Their profile kinds and adapter operations
already exist. The old in-process runtime implementations are deleted.

See [provider-status](provider-status.md), [stateless-inference](stateless-inference.md)
and [utility-llm](utility-llm.md).
