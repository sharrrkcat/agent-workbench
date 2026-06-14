# Stateless Multimodal Embeddings Contract

This contract owns Stateless Inference multimodal/image embedding profiles,
routes, local runtime behavior, and response shapes. Common service auth,
request limits, model id policy, error schema, logging, and data boundaries are
owned by [stateless-inference.md](stateless-inference.md).

## Scope

The service exposes Workbench-native multimodal/image embeddings through a
pluggable runtime interface. Production builds register lazy local runtimes for:

- `architecture=clip`
- `architecture=open_clip`
- `architecture=siglip2`
- `architecture=dinov2`

DINOv2 is image-only. CLIP/OpenCLIP/SigLIP2 may accept both image and text
inputs when the profile declares support for text.

Deferred features include Jina CLIP v2, BLIP, JoyCaption, vector database/image
search hosting, similarity scoring, and a generic tensor protocol.

## API

Primary external route:

- `POST /v1/embeddings/multimodal`

Workbench-native compatibility alias:

- `POST /api/inference/embeddings/multimodal`

Profile and inventory APIs:

- `GET/POST/PATCH/DELETE /api/inference/multimodal-embedding-models`
- `GET /api/inference/model-inventory?kind=image_embedding`
- `POST /api/inference/unload`

`GET /v1/models` and `GET /api/inference/models` list enabled, allowlisted
Multimodal Embedding Model Profiles as `multimodal:<profile_key_or_id>` without
loading model weights.

## Profile Taxonomy

`MultimodalEmbeddingModelProfile` serves CLIP/OpenCLIP, SigLIP2, and DINOv2
image embedding runtimes with architecture flags and supported input types.

Fields:

- `id`, `name`, `description`, `notes`, `enabled`.
- `external_inference_enabled=false` by default.
- optional `provider_profile_id`.
- `provider_model_id` safe ref shaped as `image_embedding/<folder-or-file>`.
- `architecture`: `clip`, `open_clip`, `siglip2`, or `dinov2`.
- `backend`: `transformers`, `open_clip`, or `auto`.
- optional `embedding_space`, positive `dimensions`,
  `preprocessing_signature`, positive bounded `max_batch_size`, and compact
  `metadata`.
- `normalize_default=true`.
- `supported_input_types`: includes `image`; CLIP/OpenCLIP/SigLIP2 may include
  `text`; DINOv2 must not include `text`.
- `pooling_strategy`: `cls`, `mean`, `pooler`, or `model_default`.

Existing profiles are not auto-migrated when defaults change. Explicitly saved
profile fields remain authoritative.

## Local Refs

`provider_model_id` must not be empty, absolute, contain backslashes,
traversal, or empty path segments. Local refs resolve only under
`data/models/image_embeddings`; APIs return safe refs and never absolute local
paths.

CLIP treats the resolved folder as a local Hugging Face CLIP directory.
OpenCLIP requires `metadata.open_clip_model_name` and a local checkpoint inside
the resolved folder, using `metadata.open_clip_checkpoint` or documented
defaults such as `open_clip_pytorch_model.bin` or `model.pt`.

Status/listing/inventory paths are no-load operations. They must not initialize
torch, transformers, OpenCLIP, or model weights.

## Request

`POST /v1/embeddings/multimodal` request shape:

```json
{
  "model": "multimodal:siglip-image",
  "inputs": [
    {"type": "image_base64", "data": "..."},
    {"type": "text", "text": "red robot"}
  ],
  "normalize": true
}
```

Validation order after common service guards:

- JSON object shape.
- model id prefix and allowlisted enabled profile.
- Provider Profile enabled state when configured.
- typed input items.
- image base64 string presence and size.
- malformed image decode/validation before loading weights.
- DINOv2 image-only support.
- optional `normalize` boolean.
- profile `max_batch_size`.

Supported input item types are `image_base64` and `text`. Object inputs, image
URLs, local paths, nested inputs, empty text, and unsupported types are rejected.

DINOv2 profiles reject text with `MODEL_INPUT_TYPE_UNSUPPORTED`.

## Runtime Behavior

Multimodal serving calls only the multimodal embedding runtime interface after
guards, JSON parsing, validation, profile resolution, and allowlist checks. It
does not call text embedding runtimes, LLM runtimes, attachment helpers,
Knowledge helpers, provider status APIs, optional ML imports, or model-loading
paths before runtime execution.

CLIP/OpenCLIP/SigLIP2/DINOv2 runtimes decode images in memory only, preprocess
in memory only, and load local model weights only during valid embedding calls.
They never auto-download model files.

Invalid runtime outputs, including non-numeric vectors, non-finite values,
wrong vector counts, and ragged vectors, normalize to compact runtime/provider
errors without leaking raw values.

## Response

Successful responses use:

```json
{
  "object": "list",
  "model": "multimodal:siglip-image",
  "profile_id": "<profile_id>",
  "profile_alias": "siglip-image",
  "architecture": "siglip2",
  "embedding_space": "siglip2/<profile_id>/default",
  "dimensions": 1152,
  "normalized": true,
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "input_type": "image",
      "embedding": [0.1, 0.2]
    },
    {
      "object": "embedding",
      "index": 1,
      "input_type": "text",
      "embedding": [0.3, 0.4]
    }
  ],
  "usage": {"input_count": 2}
}
```

Vectors are returned only in the HTTP response. Dimensions match runtime vector
length; when `profile.dimensions` is null, dimensions are derived from runtime
output for the response only and the profile is not mutated. `embedding_space`
uses `profile.embedding_space` when set, otherwise
`<architecture>/<profile_id>/default`. `normalized` reflects the request
`normalize` value or the profile `normalize_default`.

## Runtime Cache

The multimodal cache key includes profile id plus a compact fingerprint of
runtime-relevant profile fields: provider profile id, provider model ref,
architecture, backend, embedding space, dimensions, normalization default,
supported input types, preprocessing signature, pooling strategy, max batch
size, and metadata hash input. Profile changes do not reuse stale runtime
instances.

Cache operations:

- clear all runtimes.
- clear all cached runtime instances for one profile id.
- status returns counts only: runtime count, profile count, and architecture
  counts.

Cache status must not expose model paths, safe refs, raw configs, request
payloads, image bytes, base64, raw text, vectors, API keys, or secrets. Cache
release is best-effort and must never delete model files, sessions, settings,
attachments, Knowledge data, indexes, or local user assets.

`POST /api/inference/unload` supports targets `image_embedding`,
`multimodal_embedding`, and `all` for multimodal cache release.

## Settings UI

Settings -> Models owns Multimodal Embedding Model Profiles. The UI should show
safe `image_embedding/...` inventory refs from internal transformers inventory,
profile key, architecture/backend, supported input types, embedding defaults,
OpenCLIP metadata fields, external inference allowlist, and API examples.

The Settings UI should use `/v1/embeddings/multimodal` in user examples. The
Workbench-native `/api/inference/embeddings/multimodal` route remains a
compatibility alias.

## Smoke Checklist

For a real local smoke test:

1. Place a local model folder under `data/models/image_embeddings/<folder>`.
2. Create or enable the matching internal Provider Profile.
3. Create or enable the Multimodal Embedding Model Profile with
   `external_inference_enabled=true`.
4. Use `multimodal:<profile_key>` in `POST /v1/embeddings/multimodal`.
5. Verify `GET /api/inference/status` and `GET /api/inference/models`.
6. Verify `POST /api/inference/unload` clears cached multimodal runtimes.
7. Install optional local ML packages and model files only for smoke tests;
   automated tests remain fake-backed and do not require them.
