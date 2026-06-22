# Stateless Inference Contract

This contract owns the core-owned Stateless Local Inference Service: service
enablement, auth, request limits, model id policy, common response/error shapes,
privacy boundaries, operational logs, and no-load model listing. Topic-specific
runtime details live in:

- [stateless-multimodal-embeddings.md](stateless-multimodal-embeddings.md)
- [stateless-vision-models.md](stateless-vision-models.md)

## Scope

The service exposes disabled-by-default local stateless inference for:

- OpenAI-compatible chat completions.
- OpenAI-compatible text embeddings.
- Multimodal/image embeddings through local model profiles and runtime caches.
- Vision tasks through local Vision Model Profiles and runtime caches.
- Status, no-load model listing, local model inventory, preflight, and
  best-effort unload.

External inference requests are stateless. They never create project Sessions,
Messages, Runs, RunSteps, RunEvents, attachments, Knowledge rows, indexes, or
Agent state.

Deferred features include streaming chat completions, `/v1/responses`,
`/v1/completions`, similarity scoring, external stateless text-to-image,
frontend log viewing, generic tensor serving, and Capability-owned external
inference routes. Project-native image generation profiles, the internal
generation Capability, and drawing Agents are owned by
[image-generation.md](image-generation.md), not by this external stateless
service.

## Ownership

Stateless inference is core-owned. Core owns route registration,
OpenAI-compatible protocol shapes, Workbench-native API shapes, Provider
Profiles, Model Profiles, runtime caches, settings, status, unload, auth,
request limits, privacy boundaries, and persistence guards.

A future thin Capability wrapper may expose trusted Script Agent helpers, but it
must not own external routes, profile storage, runtime caches, status, unload,
or the privacy boundary.

## Disabled Default

The service is disabled by default through General settings:

- `inference_service_enabled=false`.
- `inference_service_require_api_key=true`.
- `inference_service_max_request_mb=10`.
- `inference_service_api_key=null`.

When disabled, every external inference route returns a stable disabled error
and must not call LLM runtimes, embedding services, multimodal runtimes, vision
runtimes, attachment persistence, Knowledge indexing, Agent runners, Command
runners, or EventBus persistence.

Default exposure is localhost-oriented. Any future non-localhost serving,
reverse proxy use, or CORS expansion must be explicit and documented here.

## API Index

OpenAI-compatible:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `POST /v1/embeddings/multimodal`
- `POST /v1/vision`

Workbench-native:

- `GET /api/inference/status`
- `GET /api/inference/models`
- `GET /api/inference/model-inventory?kind=image_embedding|vision`
- `GET/POST/PATCH/DELETE /api/inference/multimodal-embedding-models`
- `GET/POST/PATCH/DELETE /api/inference/vision-models`
- `POST /api/inference/vision-models/{profile_id_or_alias}/preflight`
- `POST /api/inference/unload`

Compatibility aliases:

- `POST /api/inference/embeddings/multimodal`
- `POST /api/inference/vision`

The `/v1` routes are the external stateless inference entry points. The
Workbench-native aliases remain for existing local clients and tests; new user
examples should prefer `/v1/embeddings/multimodal` and `/v1/vision`.

## Auth And Guard Order

Enabled guard order is:

1. Resolve request id and error shape.
2. Read General settings.
3. Reject disabled service before body parsing.
4. Enforce `Content-Length` request size before body parsing.
5. Authenticate before body parsing.
6. Parse JSON body for implemented POST handlers with a streaming byte limit.
7. Endpoint validation.
8. Runtime call.

Supported auth headers:

- `Authorization: Bearer <key>`.
- `x-api-key: <key>`.

API keys in query parameters are not supported. If both supported headers are
present and differ, the request is rejected with `INFERENCE_AUTH_INVALID`.
Comparisons should use constant-time comparison where practical. Raw secrets
must never be returned or logged.

When `inference_service_require_api_key=true` and no key is configured, enabled
routes fail closed with `INFERENCE_SERVICE_MISCONFIGURED`. Missing credentials
return `INFERENCE_AUTH_REQUIRED`; invalid or conflicting credentials return
`INFERENCE_AUTH_INVALID`.

## Request Size

`inference_service_max_request_mb` is the General setting owner for external
inference request size. Route guards use `Content-Length` when present and
reject oversized requests with `INFERENCE_REQUEST_TOO_LARGE` before body
parsing. Implemented POST handlers also read the body through a bounded stream
helper, so missing `Content-Length` does not allow unlimited reads.

Image payloads are additionally bounded by the runtime request validators. The
existing chat attachment limits do not authorize storing API payloads as
attachments.

## External Inference Allowlist

External inference is opt-in per model profile:

- LLM Model Profile: `external_inference_enabled`, default `false`.
- Embedding Model Profile: `external_inference_enabled`, default `false`.
- Multimodal Embedding Model Profile: `external_inference_enabled`, default
  `false`.
- Vision Model Profile: `external_inference_enabled`, default `false`.

Disabled profiles and profiles whose Provider Profile is disabled are not
listed or callable even when `external_inference_enabled=true`.

`GET /v1/models` and `GET /api/inference/models` list only enabled,
allowlisted, externally servable profiles. Listing routes must not load weights,
call provider status/network checks, expose API keys, expose absolute paths,
return raw provider payloads, or list disabled/non-allowlisted profiles.

## Model Id Policy

Profile-derived ids use explicit type prefixes:

- LLM chat models: `llm:<llm_profile_key_or_id>`.
- Text embedding models: `embedding:<embedding_model_profile_key_or_id>`.
- Multimodal embedding models:
  `multimodal:<multimodal_profile_key_or_id>`.
- Vision task models: `vision:<vision_model_profile_key_or_id>`.

Model ids are alias-first in listing responses while UUID refs remain accepted
for backward compatibility. Raw local safe refs such as
`image_embedding/<folder>` or `vision/<folder>` are profile configuration
values, not stateless API model ids. A request for the wrong model type returns
`model_not_allowed`; unknown ids return `model_not_found`.

## Model Listing

`GET /v1/models` returns OpenAI-compatible model list items plus compact
Workbench metadata for external clients:

- `id`
- `object`
- `created`
- `owned_by`
- `type`
- `capabilities`
- `profile_id`
- `profile_alias`
- `legacy_model_id`
- runtime-specific compact fields such as architecture, dimensions, supported
  input types, embedding space, or supported tasks.

If no profiles are allowlisted, it returns:

```json
{"object":"list","data":[]}
```

`GET /api/inference/models` returns the same profile entries plus a summary of
available model counts.

## Chat Completions

`POST /v1/chat/completions` accepts a minimal OpenAI-compatible request:

```json
{
  "model": "llm:chat",
  "messages": [{"role": "user", "content": "hello"}],
  "temperature": 0.7,
  "top_p": 1,
  "max_tokens": 256,
  "stream": false
}
```

Supported roles are `system`, `user`, and `assistant`, with string `content`.
`stream=true` returns `inference_not_implemented` and must not call provider
runtime. Tools/function calling, image input, response format/json mode, chat
history, Knowledge, Core Memory, Worldbook, Web Context, attachments, and title
generation are not used.

Responses are normalized to:

```json
{
  "id": "chatcmpl_...",
  "object": "chat.completion",
  "created": 123,
  "model": "llm:chat",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

## Text Embeddings

`POST /v1/embeddings` accepts OpenAI-compatible text embedding requests and
returns vectors without Knowledge writes:

```json
{
  "model": "embedding:bge-m3",
  "input": "hello",
  "encoding_format": "float"
}
```

`input` may be a string or array of strings. Objects, images, nested arrays, and
binary inputs are rejected. Only `encoding_format="float"` is supported. A
non-standard optional `purpose` of `query` or `document` may be accepted;
default is `document`.

Responses are normalized to:

```json
{
  "object": "list",
  "data": [
    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}
  ],
  "model": "embedding:bge-m3",
  "usage": {"prompt_tokens": 0, "total_tokens": 0}
}
```

## Multimodal And Vision Topics

Multimodal embeddings are specified in
[stateless-multimodal-embeddings.md](stateless-multimodal-embeddings.md). That
contract owns Multimodal Embedding Model Profile fields, CLIP/OpenCLIP/SigLIP2/
DINOv2 behavior, local `image_embedding/...` refs, request/response shape,
runtime cache keys, and smoke tests.

Vision tasks are specified in
[stateless-vision-models.md](stateless-vision-models.md). That contract owns
Vision Model Profile fields, Florence2 and Florence2 PromptGen behavior, local
`vision/...` refs, transformers compatibility, preflight, request/response
shape, generation options, and smoke tests.

## Stateless Data Boundary

External inference requests must not create or update Sessions, Messages, Runs,
RunSteps, RunEvents, command runs, Agent state, session state, attachments,
Knowledge sources, Knowledge chunks, Knowledge embeddings, or session Knowledge
bindings.

The service must not store raw image bytes, base64 payloads, data URLs, raw
request text, raw response text, text embedding vectors, image embedding
vectors, DINOv2 vectors, Florence2 raw output, Florence2 post-processed
captions/OCR/boxes, complete request bodies, complete response bodies, API
keys, provider secrets, or full absolute local paths.

Allowed compact operational file log metadata includes request id, endpoint,
status, duration, model profile id, architecture, task name, input counts, input
byte sizes, vector dimensions, error code, warning code, timestamp, API key id
hash or caller label, runtime status/cache state, safe exception class names,
sanitized cause chains, compact relative stack frames, and best-effort unload
outcomes.

## Error Schema

Workbench-native errors:

```json
{"error":{"code":"INFERENCE_SERVICE_DISABLED","message":"Stateless inference service is disabled.","request_id":"..."}}
```

OpenAI-compatible errors:

```json
{"error":{"message":"Stateless inference service is disabled.","type":"invalid_request_error","code":"inference_service_disabled"}}
```

Stable codes:

- `INFERENCE_SERVICE_DISABLED`
- `INFERENCE_SERVICE_MISCONFIGURED`
- `INFERENCE_AUTH_REQUIRED`
- `INFERENCE_AUTH_INVALID`
- `INFERENCE_NOT_IMPLEMENTED`
- `INFERENCE_REQUEST_TOO_LARGE`
- `INFERENCE_INVALID_REQUEST`
- `MODEL_INPUT_TYPE_UNSUPPORTED`
- `MODEL_NOT_FOUND`
- `MODEL_NOT_ALLOWED`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_ERROR`

OpenAI-compatible routes return lowercase code values, for example
`inference_invalid_request`, `model_not_found`, and `provider_error`.

Provider and local runtime errors are normalized to compact errors. Responses
must not include API keys, raw request bodies, raw provider payloads, raw image
payloads, base64 data, raw text inputs, raw vectors in metadata, absolute paths,
tracebacks, raw model outputs, or provider secrets.

## Request IDs And Local Logs

External inference routes emit an `X-Request-ID` response header. A short safe
incoming `X-Request-ID` header is preserved; unsafe or missing values are
replaced with a generated UUID. Workbench-native error bodies use the same
request id as the response header. OpenAI-compatible error bodies keep their
OpenAI-style shape and should be correlated through the response header.

Operational logs are JSONL files under `data/logs/inference/inference.jsonl`
with local rotation. Logs are for local troubleshooting and must not be written
to Sessions, Messages, Runs, RunSteps, RunEvents, Knowledge, attachments, or
EventBus streams.

Logs must not contain raw request bodies, raw response bodies, prompts, raw text
inputs, generated text, OCR/caption text, object labels from model output,
vectors, image bytes, base64 payloads, data URLs, API keys, provider secrets, or
full absolute local paths.

## Runtime Cache And Unload

`POST /api/inference/unload` owns local stateless multimodal and vision cache
release. Supported targets are:

- `image_embedding`
- `multimodal_embedding`
- `vision`
- `vision_task`
- `all`

It never deletes model files, Knowledge data, attachments, settings, sessions,
indexes, or local user assets. Empty or missing JSON bodies use the default
unload request. Non-object JSON bodies are rejected with
`INFERENCE_INVALID_REQUEST` and do not clear cache state.

Global `/api/runtime/free-memory` targets are unchanged; provider/runtime memory
ownership is summarized in [provider-status.md](provider-status.md).

## Safe And Unsafe Paths

Safe to reuse:

- General settings reads.
- Provider/Profile list and status reads that do not load model weights.
- LLM resolution helpers when used without Session, Message, Run, Agent, or
  context persistence.
- Text embedding provider adapters only behind a wrapper that returns vectors
  directly and never calls Knowledge indexing.
- In-memory validation/decode helpers that do not save attachments.
- Runtime memory/status helpers that release caches without deleting files.

Unsafe for external inference routes:

- `WorkbenchRuntime.handle_input`.
- `AgentRunner`.
- `CommandRunner`.
- Message creation routes/stores.
- Attachment save helpers.
- Knowledge source creation and indexing helpers.
- Run, run step, and run event persistence.
- Session Agent state and session Knowledge binding mutation.
