# Settings contract

GET/PATCH /api/settings/general validates AppSettings with extra=forbid.
Unknown/removed fields return HTTP 422.

General owns attachment/context limits, title behavior, Core Memory, group
transcript instruction, appearance, resource monitoring, streaming-delta
persistence and nested PetSettings. GET/PATCH /api/pets/settings deep-merges
position and bubble_texts into that nested object.

## Models

GET/PATCH /api/models/settings owns default_model_profile_id,
utility_model_profile_id, external_enabled, external_api_key and
max_request_mb. Session model_profile_id overrides the global default.
Settings are persisted as one models object in appmetadatarecord.

The Models panel has Profiles, Connections and External service tabs.
One kind filter exposes llm, embedding, reranker, image_embedding and vision
profiles. Connections use only the OpenAI-compatible protocol. Editors own
capability flags, generation/per-kind parameters and lifecycle (manual by
default). Local inventory and provider model listing do not load weights.
Load, health, unload and occupation use the shared model store.

Keys are omitted from reads; presence flags replace them. PATCH omission
retains a key, an explicit empty string clears it. External enablement requires
a key. Reference deletion, invalid kind/capability/parameter combinations and
busy connection edits report errors; they are not silently accepted.

## Other ownership

Knowledge settings own chunk/retrieval/context controls and the unified
reranker selection. KB records select unified embedding profiles. Model paths,
connection timeouts, instructions, dimensions, batching and normalization
belong to Models. Worldbook settings remain at /api/worldbook/settings.

The Settings navigation remains General, Models, Knowledge, Worldbook, Pet.
There are no extension configs, old default-model routes, independent
per-kind profile pages or old General inference-service settings.
