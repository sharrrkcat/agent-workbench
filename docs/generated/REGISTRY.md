# Runtime catalog

Phase 1 has no generated extension registry. The application starts from
explicit code and does not scan manifests or plugin directories.

## Prompt targets

| id | visibility | purpose |
| --- | --- | --- |
| `chat` | public default | Normal conversation with session context and service injections. |
| `translate` | internal | Small translation target reserved for tests and future persona seeds. |

`ChatTargetCatalog` is the complete catalog. It is intentionally not extensible
through YAML or a runtime registration API.

## Explicit core services

- `ChatRunner`: context construction, model call, persistence, streaming events,
  title hook, and waiting-run resume.
- `UtilityLlmService`: short text/JSON/title calls through one configured model
  profile, with structured unavailable/invalid-output errors.
- `KnowledgeService`: source/index lifecycle, hybrid retrieval, RRF and optional
  fail-open post-retrieval reranking.
- `PetService`: nested application settings and pet package lifecycle.
- `NetworkPolicy`: pure URL/DNS/redirect/response-size validation for future
  tools; it performs no requests in Phase 1.

## Generation

This document is maintained as a static catalog during Phase 1. A future tool
harness may add an explicit, schema-checked registry, but it will not restore
manifest loading or extension discovery.
