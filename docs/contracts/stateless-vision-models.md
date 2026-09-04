# Stateless vision models

The optional inference service exposes local Florence2-family vision tasks.
Common auth, limits, errors, and persistence boundaries are defined in
[`stateless-inference.md`](stateless-inference.md).

`POST /v1/vision` accepts an image and a declared task such as `caption`,
`detailed_caption`, `ocr`, or `object_detection`. Profiles use safe
`vision/<folder>` refs under `data/models/vision`, require explicit enablement,
and never download model files. Florence2 custom model code requires explicit
`metadata.trust_remote_code=true`. Runtime loading is lazy and inventory/status
operations do not initialize heavy dependencies.

Profile CRUD and preflight remain under `/api/inference/vision-models`.
Responses contain task output and compact model metadata only; no project state
is created and no absolute paths or secrets are returned.

The `knowledge` and `knowledge-cuda128` extras provide the local vision stack
(`einops`, `timm`, `Pillow`, `torch`, and `torchvision`) plus `transformers`.
Use `uv sync --extra knowledge` for CPU/default wheels or
`uv sync --extra knowledge-cuda128` for the explicit CUDA 12.8 index. The
optional `onnx` extra includes `onnxruntime-gpu>=1.17,<1.24`, `numpy`, and
`Pillow`; it is used only by providers that explicitly request that backend.
Preflight is available at
`/api/inference/vision-models/{profile_id_or_alias}/preflight`.
