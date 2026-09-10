# Future model services

The services below are not implemented. These notes identify future design
boundaries, not active tasks or frozen wire schemas. Each requires a separate
scope decision before implementation; this document grants no implementation
authority and makes no delivery commitment.

## Public rerank

The reranker profile kind, ModelManager operation and managed worker already
support Knowledge retrieval. A future `/v1/rerank` should call that same manager
operation and reuse external enablement, single-key loopback authentication,
public aliases, capability/kind checks, byte limits and access observations.
No second profile table, provider protocol or lifecycle owner is needed.

The endpoint's request/response format and public visibility rules will be
decided when implementing it. Direct API failures should be explicit; Knowledge's
intentional RRF ordering on unavailable rerank remains a separate retrieval rule.
Acceptance must cover aliases, invalid input, cancellation, queue release and
absence of chat/Knowledge writes from stateless requests.

## Image service

Current vision and image_embedding kinds consume images; they do not generate
them. A future image service requires a separate decision about generation
operations, profile capabilities and supported managed backend, followed by
strict schemas and a ModelManager adapter. Heavy execution stays outside the
API process. Reuse runtime supervision and external service guards where they
fit, without restoring the removed internal diffusers implementation.

An eventual `/v1/images/generations` must define bounded inputs/outputs, artifact
ownership/retention, cancellation, lifecycle, observability and error behavior
before implementation. Model weights remain manually managed under the current
product boundary. This note adds no route, runtime variant or model kind.

## Voice cloning and text analysis

Kokoro presets and English Chatterbox references are implemented under
[Models](contracts/models.md#chatterbox-and-temporary-references), which owns uploads,
quotas, credential/profile binding and expiry. Public Qwen3-TTS/Whisper interfaces,
multilingual Chatterbox, live capture and application playback remain deferred.
The Windows Audio package includes Qwen3-TTS/Whisper only for shared-environment
acceptance; their presence does not add public model kinds or API routes.

The separate en_core_web_sm resource currently serves Misaki's English frontend.
A future task-based text-analysis kind could support reusable tokenization,
tagging or entity analysis with its own manager operation. That model would be
one supported implementation, not a model-kind name. No separate NLP API or
lifecycle is implemented. ONNX GPU remains excluded from the runtime families.
