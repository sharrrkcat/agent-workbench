# Persona and chat contract

Personas are editable database records. They are prompt data, never executable
agents, scripts, manifests, commands, or extension registrations.

## Persona

`Persona` contains `id`, `name`, optional `avatar_attachment_id`,
`system_prompt`, optional `model_profile_id`, `context_policy`, generation
parameters, `harness_enabled`, and `tools_allowed`. Inputs use strict schemas
with `extra="forbid"`. Avatar references use an existing local image filename;
binary data remains in the attachment store.

The migration seeds editable `Chat` and `Translate` records. New sessions bind
`Chat` as their only member and current speaker. The seeded Chat record may be
edited but is not deletable. Persona deletion is rejected while a session or
unfinished run references it. Historical messages retain speaker id, name and
avatar reference snapshots.

## Session members

`session_personas` stores an ordered, enabled member list. `current_persona_id`
must identify an enabled member. A group session may have several members, but
each user message starts one response from the selected current speaker. There
is no automatic member round-robin.

Session overrides are nullable and explicit. Resolution is session override,
then current Persona, then the global model default for model selection. Context
policy, generation, harness and tool settings resolve session override before
Persona defaults. Harness execution is enabled only when the resolved flag is true; the
resolved allowlist is validated against the built-in tool registry.

## Context bindings

Personas own ordered Knowledge and Worldbook defaults. A session binding mode is
`inherit` or `override`. Inherit uses the current speaker's Persona bindings;
override uses the session's ordered binding rows, and an empty override list
means no resources. Retrieval and worldbook matching receive the resolved ids
explicitly and do not silently fall back to another binding set.

## Run snapshot

At run creation the resolved Persona configuration is copied into a private
`config_snapshot_json` column. Public Run metadata/events expose only ids,
names, model selection, context mode, limits and binding ids. The snapshot may
contain the Persona prompt so an in-flight run is unaffected by edits, but the
prompt is never copied into public metadata, events, or error payloads.

The assistant message uses `speaker_id` equal to the selected Persona id and a
name/avatar snapshot from run start. Editing a Persona or switching a session's
current speaker affects later runs only. Retry uses the original assistant
speaker configuration.

## HTTP surface

- `/api/personas` supports strict CRUD.
- `/api/personas/{id}/knowledge-bases` and `/worldbooks` manage Persona defaults.
- `/api/sessions/{id}/personas` manages ordered members/current speaker.
- `/api/sessions/{id}/knowledge-bases` and `/worldbooks` return binding mode,
  configured ids and resolved effective ids.

All referenced Personas and resources are validated before persistence. Unknown
or removed fields return 422; missing references return structured 404/409
errors. Registered `/tool_name` prefixes invoke built-in tools under the same
allowlist; other prefixes remain plain text. Waiting tool approvals block new
messages and preserve this run's Persona snapshot. See [harness-tools](harness-tools.md).
