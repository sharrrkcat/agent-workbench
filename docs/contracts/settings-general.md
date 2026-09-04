# General settings contract

General settings are served by `GET/PATCH /api/settings/general`. Pydantic
schemas use `extra="forbid"`; unknown or removed fields return HTTP 422.

## AppSettings groups

- Attachment limits and whether text attachments enter model context.
- `auto_generate_session_titles`, `session_title_prompt`, and
  `session_title_max_input_chars`.
- One `utility_model_profile_id` for the internal Utility LLM.
- Core Memory content and enablement.
- Group transcript instruction and resource/inference service switches.
- Appearance font settings.
- Nested `pet: PetSettings` (see [Pet contract](pet.md)).

There are no Agent, Command, Intent, Web, image-generation, or extension
configuration fields. Pet updates are also exposed by
`GET/PATCH /api/pets/settings`; the façade deep-merges `position` and
`bubble_texts` before saving the nested object.

## Models

`/api/settings/llm-defaults` stores the global default chat profile. Session
`llm_profile_id` overrides it. Provider and LLM profile CRUD remains under
`/api/provider-profiles` and `/api/llm-profiles`; profile secrets are masked in
responses.

Knowledge settings are owned by `/api/knowledge/settings`, and Worldbook
settings by `/api/worldbook/settings`. The Settings UI exposes only General,
Models, Knowledge, Worldbook, and Pet.

## Validation and errors

Strict booleans, bounded numeric fields, nested Pet models, and constrained
literal values are validated before persistence. Secrets are never copied into
run metadata, logs, generated documentation, or model prompts.
