# Future model services

The services below are not implemented. These notes identify future design
boundaries, not active tasks or frozen wire schemas. Each requires a separate
scope decision before implementation; this document grants no implementation
authority and makes no delivery commitment.

## Installation verification

The [verification policy](../AGENTS.md#runtime-verification-and-acceptance) requires
removing full installed-environment hash inventories while retaining artifact and
installation-boundary checks. The current installer still creates and compares
these inventories, as documented by [Models](contracts/models.md#managed-catalog-and-installation).
Their removal is not implemented; it requires a separate installer change and
matching tests. This note records the boundary without claiming the optimization exists.

## Local engine and platform expansion

The shared local release supports Windows x64 GGUF, Transformers LLM, Kokoro,
Chatterbox and Qwen3-TTS Base. Linux requires its own complete dependency lock,
native components and real-runtime acceptance before it can be advertised.
Local embedding, reranker, image embedding and WD14 are deferred. Their model
kinds and existing parameter schemas remain; local binding currently fails.
Future support must use the same installation and dependency environment,
validate architecture/preprocessing/index behavior and preserve independent
queues and worker cancellation. Infinity is an implementation choice to reassess
within that shared environment, not a separate package to restore.
ONNX GPU, Vulkan, DINOv2, Florence and CosyVoice3 remain outside scope.

## Public rerank

The reranker profile kind and ModelManager operation remain in Knowledge;
local execution is pending. A future `/v1/rerank` should call that same manager
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

Kokoro presets, English Chatterbox and Qwen3-TTS Base references are implemented
under [Models](contracts/models.md#audio-tts-and-temporary-references), which owns
uploads, optional Qwen transcripts, quotas, credential/profile binding and expiry.
Qwen CustomVoice/VoiceDesign, public Whisper, multilingual Chatterbox, live capture
and application playback remain deferred. Whisper is included in the shared Windows
environment only for acceptance, without a public kind or endpoint.

The separate en_core_web_sm resource currently serves Misaki's English frontend.
A future task-based text-analysis kind could support reusable tokenization,
tagging or entity analysis with its own manager operation. That model would be
one supported implementation, not a model-kind name. No separate NLP API or
lifecycle is implemented. ONNX GPU remains outside the accepted unification scope.
