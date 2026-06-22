# Stateless Vision Models Contract

This contract owns Stateless Inference Vision Model Profiles, Florence2-family
vision tasks, Florence2 PromptGen variants, preflight, transformers
compatibility, local runtime behavior, and response shapes. Common service
auth, request limits, model id policy, error schema, logging, and data
boundaries are owned by [stateless-inference.md](stateless-inference.md).

## Scope

Vision Model Profiles serve local Florence2-family vision tasks through:

- `architecture=florence2`
- `architecture=florence2_promptgen`

The runtime uses local model folders only, decodes image payloads before loading
model weights, and never auto-downloads models. Florence2 custom model code
requires explicit opt-in through `metadata.trust_remote_code=true`.

Deferred features include BLIP, JoyCaption, OpenAI-compatible image input to
chat completions, frontend preflight UI, and generic video understanding.

## API

Primary external route:

- `POST /v1/vision`

Workbench-native compatibility alias:

- `POST /api/inference/vision`

Profile and preflight APIs:

- `GET/POST/PATCH/DELETE /api/inference/vision-models`
- `POST /api/inference/vision-models/{profile_id_or_alias}/preflight`
- `GET /api/inference/model-inventory?kind=vision`
- `POST /api/inference/unload`

`GET /v1/models` and `GET /api/inference/models` list enabled, allowlisted
Vision Model Profiles as `vision:<profile_key_or_id>` without loading model
weights.

## Profile Taxonomy

`VisionModelProfile` serves Florence2-family tasks. Fields mirror other Model
Profiles:

- `id`, `name`, `description`, `notes`, `enabled`.
- `external_inference_enabled=false` by default.
- optional `provider_profile_id`.
- `provider_model_id` safe ref shaped as `vision/<folder>`.
- `architecture`: `florence2` or `florence2_promptgen`.
- `backend`: `transformers`.
- `supported_tasks`.
- `max_batch_size`.
- compact `metadata`.
- timestamps.

Florence2 and Florence2 PromptGen use safe local refs under
`data/models/vision`. `provider_model_id` must not be empty, absolute, contain
backslashes, traversal, or empty path segments. APIs return safe refs and never
absolute local paths.

Existing profiles are not auto-migrated when new tasks are added. Explicitly
saved `supported_tasks` remain authoritative.

## Tasks

Standard Florence2 public task names:

- `caption`
- `detailed_caption`
- `more_detailed_caption`
- `ocr`
- `object_detection`

Prompt mapping:

- `caption` -> `<CAPTION>`
- `detailed_caption` -> `<DETAILED_CAPTION>`
- `more_detailed_caption` -> `<MORE_DETAILED_CAPTION>`

Florence2 PromptGen fine-tunes use the separate
`architecture=florence2_promptgen` profile variant. PromptGen defaults to
caption/tag/prompt tasks only:

- `caption`
- `detailed_caption`
- `more_detailed_caption`
- `generate_tags`
- `analyze`
- `mixed_caption`
- `mixed_caption_plus`

PromptGen-only task mapping:

- `generate_tags` -> `<GENERATE_TAGS>`
- `analyze` -> `<ANALYZE>`
- `mixed_caption` -> `<MIXED_CAPTION>`
- `mixed_caption_plus` -> `<MIXED_CAPTION_PLUS>`

PromptGen profiles do not default to OCR or object detection; use a standard
`florence2` profile for those tasks.

## Trust Remote Code

Florence2 remote model code is local custom Python code. The runtime never
auto-enables it. `metadata.trust_remote_code=true` is required on the Vision
Model Profile. If it is not exactly `true`, Florence2 and PromptGen fail before
model loading with `INFERENCE_INVALID_REQUEST`.

The runtime passes `trust_remote_code=True` only during local Florence2
load/preflight operations. It must not affect CLIP, DINOv2, SigLIP2, Utility
LLM, or unrelated transformers runtime paths.

## Transformers Compatibility

Florence2 runs through a runtime-local transformers compatibility layer for
transformers 5-era changes to legacy Florence2 remote code. The compat layer is
active only while Florence2 load/preflight constructs config, model, processor,
or tokenizer objects.

The runtime preserves these compatibility behaviors:

- eager attention implementation.
- legacy config/model attribute shims.
- tokenizer `additional_special_tokens` legacy property shim.
- `use_cache=False` for generation so legacy remote code does not receive
  transformers 5 cache objects.
- square padding and Florence2-safe processor image size.
- legacy tied language shared embeddings and `lm_head` repair only when needed
  for standard Florence2.

PromptGen additionally uses runtime-local compatibility for old list-style
`_tied_weights_keys`, legacy language model generation mixin materialization,
and missing `generation_config`. PromptGen does not use the standard Florence2
missing tied language weight repair to overwrite existing PromptGen weights.

All compatibility shims must be lock-protected, temporary, and limited to
Florence2 or PromptGen load/preflight.

## Precision And Devices

Runtime device selection comes from the selected Provider Profile metadata.
`auto` prefers CUDA, then MPS, then CPU. Explicit unavailable devices fail with
a compact provider/runtime error.

PromptGen profiles additionally support `metadata.use_half_precision`. The
settings UI defaults it to `true`, which loads model weights as float16 on
accelerator devices. CPU loads remain float32. `use_half_precision=false` uses
the float32/default path for quality or compatibility debugging. Standard
`florence2` default precision behavior is unchanged.

Real Florence2 local loading requires the local ML extra, currently including
`torch`, `torchvision`, `transformers`, `einops`, `timm`, and `Pillow`.
Florence2 custom model code requires `einops`, `timm`, `Pillow`, `torch`, and
`torchvision`.

CPU/default installs use:

```bash
uv sync --extra knowledge
```

CUDA 12.8 installs use:

```bash
uv sync --extra knowledge-cuda128
```

The CUDA extra routes both `torch` and `torchvision` through the PyTorch cu128
wheel index. A plain `uv sync --extra knowledge` resolves torch from the
configured/default indexes and may replace a manually installed CUDA wheel such
as `torch==...+cu128` with the CPU wheel. Do not combine CPU and CUDA extras in
the same environment; they are declared as mutually exclusive installation
modes.

ONNX Runtime vision providers use `internal_onnxruntime` Provider Profiles and
scan `data/models/vision/<folder>` directories containing `.onnx` files. The
runtime dependency extra is:

```bash
uv sync --extra onnx
```

The `onnx` extra includes `onnxruntime-gpu>=1.17,<1.24`, `numpy`, and `Pillow`.
The upper bound keeps the extra installable on the project's Python 3.10+
runtime while newer ONNX Runtime GPU wheels target newer Python versions. ONNX
model execution is wired in later Vision architecture support; this provider
layer only owns local inventory, dependency checks, and execution-provider
selection.

## Request

`POST /v1/vision` request shape:

```json
{
  "model": "vision:florence2",
  "task": "caption",
  "input": {"type": "image", "image_base64": "..."},
  "options": {}
}
```

Validation order after common service guards:

- JSON object shape.
- model id prefix and allowlisted enabled profile.
- Provider Profile enabled state when configured.
- task name and profile `supported_tasks`.
- input object with `type="image"` and `image_base64`.
- allowed generation options.
- image decode and tiny-image validation before model loading.

Unknown generation options are rejected with `INFERENCE_INVALID_REQUEST` before
image decode or model loading.

`options` may include bounded generation controls:

- `max_new_tokens`: 1 through 1024.
- `num_beams`: 1 through 8.

Defaults:

- standard `caption`: 64.
- standard `detailed_caption`: 256.
- standard `more_detailed_caption`: 512.
- standard OCR/object detection: 1024.
- PromptGen `generate_tags`, `analyze`, and `mixed_caption`: 512.
- PromptGen `mixed_caption_plus`: 768.

For indexing, prefer concise `caption` plus PromptGen tags over long
`more_detailed_caption` as primary index text. Reduce `num_beams` or token
count first when accelerator memory is tight.

## Runtime Behavior

Vision serving calls only the vision runtime interface after guards, JSON
parsing, validation, profile resolution, task allowlist checks, and image input
shape/size checks.

The Florence2 runtime:

- decodes and validates the image in memory before loading model weights.
- rejects images with either side smaller than 16 px as
  `INFERENCE_INVALID_REQUEST`.
- square-pads non-square images in memory for Florence2 remote-code feature-map
  constraints.
- resizes processor input to the Florence2-safe `768x768` size.
- builds task prompts in memory.
- generates under a no-grad/inference context.
- normalizes output to the public response shape.
- persists none of the prompt, generated text, OCR text, captions, detections,
  or image payload.

CUDA/MPS out-of-memory, illegal memory access, and device-side assert failures
are treated as fatal accelerator failures for the cached Florence2 runtime. The
runtime unloads model references before returning the provider error, though
the process may still require a backend restart if CUDA remains poisoned.

## Output Normalization

Text tasks return:

```json
{"type":"text","text":"..."}
```

Object detection returns:

```json
{
  "type": "objects",
  "objects": [
    {
      "label": "person",
      "score": 0.91,
      "box": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.6, "y_max": 0.9}
    }
  ]
}
```

Coordinates are normalized to `[0, 1]`. Florence2 prompt tokens, raw generated
text, pixel boxes, and post-processor internals are not public API and must not
be persisted.

The runtime keeps raw decode with `skip_special_tokens=False` because object
detection post-processing needs location tokens. Text-class task cleanup removes
leaked Florence2 task tokens, leaked `<loc_N>` tokens, repeated whitespace, and
conservative repeated leading fragments such as `InIn this image`.

PromptGen `analyze` output is model-generated text, not a guaranteed schema.
Clients that need fixed fields should parse into a controlled schema with a raw
fallback.

## Preflight

`POST /api/inference/vision-models/{profile_id_or_alias}/preflight` diagnoses a
configured Vision Model Profile before real inference. The request body is
optional:

```json
{"load_model": false}
```

`load_model=false` is the default. It checks:

- Florence2/PromptGen dependencies.
- safe local model directory.
- explicit `metadata.trust_remote_code=true`.
- config plus processor/tokenizer construction without loading weights.
- local runtime device availability.

`load_model=true` additionally constructs a temporary Florence2 or PromptGen
runtime, loads weights once, then immediately unloads it without adding
anything to the global vision runtime cache.

Preflight returns HTTP 200 with `ok=false` for diagnosable profile/runtime
failures and HTTP 404 only when the profile is missing. Responses must not
include absolute paths, raw images, base64 input, tracebacks, provider secrets,
raw generated text, or raw model output.

```json
{
  "ok": true,
  "profile_id": "...",
  "architecture": "florence2",
  "load_model": false,
  "checks": [
    {"id": "trust_remote_code", "status": "pass", "message": "..."}
  ],
  "runtime": {
    "transformers_version": "...",
    "torch_available": true,
    "torch_version": "...",
    "cuda_available": true,
    "torch_cuda_version": "..."
  }
}
```

## Runtime Cache

Vision runtime cache status returns counts only: runtime count, profile count,
and architecture counts. It must not expose model paths, safe refs, raw configs,
request payloads, image bytes, base64, generated text, raw model output, API
keys, or secrets.

`POST /api/inference/unload` supports targets `vision`, `vision_task`, and
`all` for vision cache release. Cache release is best-effort and must never
delete model files, sessions, settings, attachments, Knowledge data, indexes,
or local user assets.

## Settings UI

Settings -> Models owns Vision Model Profiles. The UI should show safe
`vision/...` inventory refs from internal transformers inventory, profile key,
architecture, backend, supported tasks, `metadata.trust_remote_code`,
PromptGen-only `metadata.use_half_precision`, external inference allowlist, and
API examples.

The Settings UI should use `/v1/vision` in user examples. The Workbench-native
`/api/inference/vision` route remains a compatibility alias.

## Smoke Checklist

For a real vision smoke test:

1. Place a local model folder under `data/models/vision/<folder>`.
2. Create or enable the matching internal Provider Profile.
3. Create or enable the Vision Model Profile with
   `external_inference_enabled=true` and `metadata.trust_remote_code=true`.
4. Run `POST /api/inference/vision-models/{profile_id_or_alias}/preflight`
   with `{"load_model": false}` first, then `{"load_model": true}` when ready
   to validate local weights.
5. Use `vision:<profile_key>` in `POST /v1/vision`.
6. Verify `GET /api/inference/status`, `GET /api/inference/models`, and
   `POST /api/inference/unload`.
7. Install optional local ML packages and model files only for smoke tests;
   automated tests remain fake-backed and do not require them.
