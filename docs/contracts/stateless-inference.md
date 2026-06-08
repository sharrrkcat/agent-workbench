# Stateless Inference Contract

This contract owns the future core-owned Stateless Local Inference Service.
A1.1 defines the disabled API skeleton and privacy boundary only; it does not
implement model inference.

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

A1.1 registers these routes. If enabled before implementation, they return
`INFERENCE_NOT_IMPLEMENTED`.

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

Auth is represented by an API-key guard shape in A1.1. When
`inference_service_require_api_key=true`, future enabled routes must require an
Authorization bearer token or equivalent documented key transport. Raw secrets
must never be returned or logged.

A1.1 does not add an API key secret field or migration. Future auth storage must
use the project's secret masking conventions and keep unknown-field rejection.

## Request Size

`inference_service_max_request_mb` is the General setting owner for external
inference request size. Future middleware or route guards must reject oversized
requests with `INFERENCE_REQUEST_TOO_LARGE` before decoding large payloads.

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
servable profiles only.

`POST /v1/chat/completions` accepts OpenAI-compatible chat completion requests
and returns OpenAI-compatible non-streaming responses first. Streaming is
deferred.

`POST /v1/embeddings` accepts OpenAI-compatible text embedding requests and
returns vectors without Knowledge writes.

`GET /api/inference/status` returns compact service, auth, runtime, and cache
status without secrets or payloads.

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
