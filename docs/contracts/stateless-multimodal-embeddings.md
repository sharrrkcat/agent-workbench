# Stateless multimodal embeddings

The optional inference service exposes local image/text embedding profiles.
Common auth, limits, errors, and persistence boundaries are defined in
[`stateless-inference.md`](stateless-inference.md).

`POST /v1/embeddings/multimodal` accepts image input and, for profiles that
declare it, text input. Supported local architectures are CLIP, OpenCLIP,
SigLIP2, and DINOv2 (image-only). Profiles use safe
`image_embedding/<name>` refs under `data/models/image_embeddings` and default
to `external_inference_enabled=false`.

Profile CRUD remains under `/api/inference/multimodal-embedding-models`; model
inventory and unload are no-load/best-effort operations. No endpoint downloads
models or writes project sessions, messages, runs, or Knowledge indexes.
