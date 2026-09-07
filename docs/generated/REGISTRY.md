# Runtime catalog

There is no generated extension registry. The application starts from
explicit code and does not scan manifests or plugin directories.

## Personas

| id | visibility | purpose |
| --- | --- | --- |
| `Chat` | public default | Editable normal conversation persona with session context and service injections. |
| `Translate` | public | Editable translation persona using current-message context. |

Personas are database records managed through `/api/personas`; there is no YAML
or runtime registration API.

## Explicit core services

- `ChatRunner`: context construction, model call, persistence, streaming events,
  title hook, and opt-in harness dispatch.
- `ToolRegistry`/`HarnessAgentLoop`: six built-in tools, bounded model loops,
  private approval continuations, direct calls and shared cancellation.
- `ModelManager`: the shared adapter, provider queue, model status and
  lifecycle owner for all internal/external inference.
- `ModelProfileStore`: five model kinds with internal UUIDs and public aliases.
- `UtilityLLMService`: short text/JSON/title calls through one configured model
  profile, with structured unavailable/invalid-output errors.
- `KnowledgeService`: source/index lifecycle, hybrid retrieval, RRF and optional
  fail-open post-retrieval reranking.
- `PetService`: nested application settings and pet package lifecycle.
- `NetworkPolicy`: URL/DNS/redirect/response-size policy; network helpers connect
  only to its validated public addresses.

## Generation

This document is maintained as a static catalog. The tool registry is explicit
and schema-checked; it does not restore manifest loading or extension discovery.
