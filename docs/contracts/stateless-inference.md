# Stateless Inference Contract

This contract owns the future core-owned Stateless Local Inference Service.
A1.2 defines auth, request-size checks, no-load status, and no-load model
listing. It does not implement model inference.

## Scope

The service may later expose local stateless inference for:

- OpenAI-compatible chat/completions.
- OpenAI-compatible text embeddings.
- Workbench-native multimodal/image embeddings.
- Workbench-native Florence2 family vision tasks.
- status, model listing, runtime resource visibility, and best-effort unload.

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

## API Candidates

OpenAI-compatible candidates:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`

Workbench-native candidates:

- `GET /api/inference/status`
- `GET /api/inference/models`
- `POST /api/inference/unload`
- `POST /api/inference/embeddings/multimodal`
- `POST /api/inference/vision`

A1.2 registers these routes. If enabled before inference implementation, model
listing returns empty no-load lists, status returns compact planned capability
state, and inference/unload endpoints return `INFERENCE_NOT_IMPLEMENTED`.

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

Code paths that need wrappers/guards: existing LLM calls, existing text
embeddings, image decode/validation, and status/unload.

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
6. parse/validate body only in future implemented handlers.

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
inference request size. A1.2 route guards use `Content-Length` when present and
reject oversized requests with `INFERENCE_REQUEST_TOO_LARGE` before body
parsing. If `Content-Length` is missing, A1.2 does not read the body solely to
enforce size; streaming/body middleware enforcement is future work.

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

## Runtime Cache And Unload

Future runtime cache release remains best-effort and must never delete model
files, sessions, settings, attachments, Knowledge data, indexes, or local user
assets. Existing memory targets may be extended or mapped for `image_embedding`
and `vision_task`.

Status refresh and model listing must not load model weights. Local inventory
scans must return compact metadata only.

## Future Profile Taxonomy

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

## Future Endpoint Contracts

`GET /v1/models` returns OpenAI-compatible model list data for externally
servable profiles only. In A1.2 it returns `{"object":"list","data":[]}` after
auth because no external per-profile allowlist exists yet.

`POST /v1/chat/completions` accepts OpenAI-compatible chat completion requests
and returns OpenAI-compatible non-streaming responses first. Streaming is
deferred.

`POST /v1/embeddings` accepts OpenAI-compatible text embedding requests and
returns vectors without Knowledge writes.

`GET /api/inference/status` returns compact service, auth, runtime, and planned
capability status without secrets or payloads. A1.2 preserves disabled behavior:
when the service is disabled, status returns `INFERENCE_SERVICE_DISABLED`.

`GET /api/inference/models` returns Workbench-native model/profile metadata for
servable profiles without loading weights. In A1.2 it returns an empty
externally-callable list with the reason
`external_model_allowlist_not_implemented`; it must not expose model ids until a
profile allowlist exists.

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
