# Stateless Inference Contract

This contract owns the core-owned Stateless Local Inference Service. A2
implements the first real stateless OpenAI-compatible chat and text embedding
endpoints.

## Scope

The service exposes local stateless inference for:

- OpenAI-compatible chat/completions.
- OpenAI-compatible text embeddings.
- status and no-load model listing.

The service may later expose:

- Workbench-native multimodal/image embeddings.
- Workbench-native Florence2 family vision tasks.
- runtime resource visibility and best-effort unload.

The service must remain stateless for external API requests. Request payloads
and inference outputs are never project data.

Deferred features: Jina CLIP v2, BLIP, JoyCaption, text-to-image, vector
database / image search hosting, multi-tenant billing, and a generic
Triton-style tensor protocol.

## Ownership

Stateless inference is core-owned. Core owns route registration,
OpenAI-compatible protocol shapes, Workbench-native API shapes, Provider
Profiles, Model Profiles, runtime caches, settings, status, unload, auth,
request limits, and persistence guards.

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
and must not call LLM runtimes, embedding services, attachment persistence,
Knowledge indexing, Agent runners, Command runners, or event logging paths.

Default exposure is localhost-oriented. Any future non-localhost serving,
reverse proxy use, or CORS expansion must be explicit and documented here.

## A2 API

OpenAI-compatible:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`

Workbench-native:

- `GET /api/inference/status`
- `GET /api/inference/models`

Still registered but not implemented:

- `POST /api/inference/unload`
- `POST /api/inference/embeddings/multimodal`
- `POST /api/inference/vision`

Streaming chat completions, `/v1/responses`, `/v1/completions`, multimodal
embeddings, CLIP/OpenCLIP, SigLIP 2, DINOv2, Florence2, BLIP/JoyCaption,
text-to-image, operational log persistence, Capability wrappers, new
multimodal/vision profile tables, and runtime memory target changes are
deferred.

## Stateless Data Boundary

External inference requests must not create or update Sessions, Messages, Runs,
RunSteps, RunEvents, command runs, Agent state, session state, attachments,
Knowledge sources, Knowledge chunks, Knowledge embeddings, or session Knowledge
bindings.

The service must not store raw image bytes, base64 payloads, data URLs, raw
request text, raw response text, text embedding vectors, image embedding
vectors, DINOv2 vectors, Florence2 raw output, Florence2 post-processed
captions/OCR/boxes, complete request bodies, complete response bodies,
API-uploaded images as chat attachments, or API results as messages, runs,
Knowledge rows, session state, or Agent state.

Allowed compact operational metadata, if implemented later: request id,
endpoint, status, duration, model profile id, architecture, input counts, input
byte sizes, vector dimensions, error code, warning code, timestamp, API key id
hash or caller label, runtime status/cache state, and best-effort unload
outcomes.

Forbidden logs and metadata include raw text, raw output, vectors, raw image
bytes, base64, data URLs, full request bodies, full response bodies, API keys,
and provider secrets.

## Safe And Unsafe Paths

Safe to reuse:

- General settings reads.
- Provider/Profile list and status reads that do not load model weights.
- LLM resolution helpers when used without Session, Message, Run, Agent, or
  context persistence.
- text embedding provider adapters only behind a wrapper that returns vectors
  directly and never calls Knowledge indexing.
- in-memory validation/decode helpers that do not save attachments.
- runtime memory/status helpers that release caches without deleting files.

Unsafe for external inference routes:

- `WorkbenchRuntime.handle_input`.
- `AgentRunner`.
- `CommandRunner`.
- message creation routes/stores.
- attachment save helpers.
- Knowledge source creation and indexing helpers.
- run, run step, and run event persistence.
- session Agent state and session Knowledge binding mutation.

A2 reuses the existing LLM runtime `chat(messages, model_config, stream=False)`
and `ai_workbench.core.embedding.embed_texts(...)` directly. It does not use
session/Agent LLM resolution, Prompt Agent calls, title generation, Knowledge
retrieval, attachment helpers, or Knowledge indexing.

## Auth And Exposure

A1.2 supports API-key auth for enabled routes through:

- `Authorization: Bearer <key>`.
- `x-api-key: <key>`.

API keys in query parameters are not supported. If both supported headers are
present and differ, the request is rejected with `INFERENCE_AUTH_INVALID`.
Comparisons should use constant-time comparison where practical. Raw secrets
must never be returned or logged.

Enabled guard order is:

1. resolve request id/error shape.
2. read General settings.
3. reject disabled service before body parsing.
4. enforce `Content-Length` request size before body parsing.
5. authenticate before body parsing.
6. parse JSON body for implemented POST handlers with a streaming byte limit.
7. endpoint validation.
8. runtime call.

When `inference_service_require_api_key=true` and no key is configured, enabled
routes fail closed with `INFERENCE_SERVICE_MISCONFIGURED`. Missing credentials
return `INFERENCE_AUTH_REQUIRED`; invalid or conflicting credentials return
`INFERENCE_AUTH_INVALID`; valid credentials reach the A1.2 skeleton behavior.

`inference_service_api_key` is a backend General setting. Settings GET responses
return only `null` or the standard `********` marker plus
`inference_service_api_key_set`; PATCH can set or clear the local key. The raw
key may exist in local settings storage in this alpha, but it must not appear in
route responses, logs, metadata, docs examples, or tests.

## Request Size

`inference_service_max_request_mb` is the General setting owner for external
inference request size. Route guards use `Content-Length` when present and
reject oversized requests with `INFERENCE_REQUEST_TOO_LARGE` before body
parsing. Implemented POST handlers also read the body through a bounded stream
helper and stop once `max_request_mb` is exceeded, so missing `Content-Length`
does not allow unlimited reads.

The existing chat attachment limits do not authorize storing API payloads as
attachments.

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

OpenAI-compatible lowercase codes include:

- `inference_service_disabled`
- `inference_service_misconfigured`
- `inference_auth_required`
- `inference_auth_invalid`
- `inference_request_too_large`
- `inference_invalid_request`
- `inference_not_implemented`
- `model_not_found`
- `model_not_allowed`
- `model_input_type_unsupported`
- `provider_unavailable`
- `provider_error`

Provider errors are normalized to compact errors. Responses must not include API
keys, raw request bodies, raw provider payloads, raw vectors in metadata, or
provider secrets.

## Runtime Cache And Unload

Future runtime cache release remains best-effort and must never delete model
files, sessions, settings, attachments, Knowledge data, indexes, or local user
assets. Existing memory targets may be extended or mapped for `image_embedding`
and `vision_task`.

Status refresh and model listing must not load model weights. Local inventory
scans must return compact metadata only.

## External Inference Allowlist

External inference is opt-in per model profile:

- LLM Model Profile: `external_inference_enabled`, default `false`.
- Embedding Model Profile: `external_inference_enabled`, default `false`.

The fields are persisted and accepted/returned by profile CRUD APIs. Existing
profiles default to not externally callable. Disabled profiles and profiles
whose Provider Profile is disabled are not listed or callable even when
`external_inference_enabled=true`.

`GET /v1/models` and `GET /api/inference/models` list only:

- enabled LLM Model Profiles with `external_inference_enabled=true`.
- enabled text Embedding Model Profiles with `external_inference_enabled=true`.

Model listing must not load weights, call provider status/network checks, expose
API keys, expose absolute paths, expose local directory trees, return raw
provider payloads, or list disabled/non-allowlisted profiles.

## Model Id Policy

A2 returns and accepts only profile-derived ids with explicit type prefixes:

- LLM chat models: `llm:<llm_profile_id>`.
- text embedding models: `embedding:<embedding_model_profile_id>`.

The exact ids returned by `/v1/models` must be used with `/v1/chat/completions`
and `/v1/embeddings`. Prefixes make LLM and embedding namespaces separate and
avoid visible id collisions. A chat request for an embedding id, or an embedding
request for an LLM id, returns `model_not_allowed`. Unknown ids return
`model_not_found`.

## Profile Taxonomy

- Existing LLM Model Profiles serve chat/completions.
- Existing Embedding Model Profiles serve text embeddings.
- Future `MultimodalEmbeddingModelProfile` serves CLIP/OpenCLIP, SigLIP 2, and
  DINOv2 with architecture flags and supported input types.
- Future `VisionTaskModelProfile` serves Florence2 family tasks.

Multimodal embedding profile metadata should include architecture, embedding
space, dimensions, normalize default, preprocessing signature, pooling strategy,
and supported input types.

DINOv2 is image-only and must reject text input with
`MODEL_INPUT_TYPE_UNSUPPORTED`.

Florence2 public task names are `caption`, `detailed_caption`, `ocr`, and
`object_detection`. Internal prompt mapping and post-processing belong to the
future Florence2 runtime wrapper, not to route handlers.

## Endpoint Contracts

`GET /v1/models` returns OpenAI-compatible model list data for externally
servable profiles only. If no profiles are allowlisted, it returns:

```json
{"object":"list","data":[]}
```

`POST /v1/chat/completions` accepts a minimal OpenAI-compatible request:

```json
{
  "model": "llm:<profile_id>",
  "messages": [{"role": "user", "content": "hello"}],
  "temperature": 0.7,
  "top_p": 1,
  "max_tokens": 256,
  "stream": false
}
```

Supported roles are `system`, `user`, and `assistant`, with string `content`.
`stream=true` returns `inference_not_implemented` and must not call the provider
runtime. Tools/function calling, image input, response format/json mode, chat
history, Knowledge, Core Memory, Worldbook, Web Context, attachments, and title
generation are not used.

Responses are normalized to:

```json
{
  "id": "chatcmpl_...",
  "object": "chat.completion",
  "created": 123,
  "model": "llm:<profile_id>",
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

`POST /v1/embeddings` accepts OpenAI-compatible text embedding requests and
returns vectors without Knowledge writes:

```json
{
  "model": "embedding:<profile_id>",
  "input": "hello",
  "encoding_format": "float"
}
```

`input` may be a string or array of strings. Objects, images, nested arrays, and
binary inputs are rejected. Only `encoding_format="float"` is supported. A
non-standard optional `purpose` of `query` or `document` may be accepted; default
is `document`.

Responses are normalized to:

```json
{
  "object": "list",
  "data": [
    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}
  ],
  "model": "embedding:<profile_id>",
  "usage": {"prompt_tokens": 0, "total_tokens": 0}
}
```

`GET /api/inference/status` returns compact service, auth, route, capability,
and allowlisted model counts without loading models, calling providers, or
exposing secrets. When the service is disabled, status returns
`INFERENCE_SERVICE_DISABLED`.

`GET /api/inference/models` returns Workbench-native model/profile metadata for
servable profiles without loading weights.

`POST /api/inference/unload` requests best-effort cache release for a target or
profile and returns compact outcomes.

`POST /api/inference/embeddings/multimodal` future request shape:

```json
{
  "model": "profile_or_model_id",
  "inputs": [
    {"type": "image_base64", "data": "..."},
    {"type": "text", "text": "red robot"}
  ],
  "normalize": true
}
```

`POST /api/inference/vision` future request shape:

```json
{
  "model": "profile_or_model_id",
  "task": "caption",
  "image_base64": "...",
  "options": {}
}
```

Vision response shapes should be task-specific: captions return text plus
compact metadata, OCR returns text and optional regions, and object detection
returns boxes with labels, scores, and coordinates. Raw Florence2 outputs must
not be persisted.
