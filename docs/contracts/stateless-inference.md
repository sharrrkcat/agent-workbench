# Stateless inference contract

The optional local inference service is core-owned, disabled by default, and
stateless. It shares provider/profile adapters with internal chat but never
creates project sessions, messages, runs, events, attachments, or Knowledge
rows.

## Settings and guard

General settings control `inference_service_enabled`,
`inference_service_require_api_key`, `inference_service_max_request_mb`, and
the secret API key. Requests are localhost-oriented and authenticate with
`Authorization: Bearer <key>` or `x-api-key`. Disabled service, missing key,
invalid key, oversized body, and schema errors have structured error codes.

## Endpoints

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `POST /v1/embeddings/multimodal`
- `POST /v1/vision`
- `/api/inference/status`, `/models`, `/model-inventory`, profile CRUD,
  preflight, and unload helpers.

Phase 1 keeps the existing non-streaming protocol skeleton and embedding/
vision profile APIs. Streaming, tools, response formats, and broader protocol
features are Phase 2 work. Request parsing uses strict schemas and profile
allowlists; raw secrets and provider payloads are never returned or logged.
