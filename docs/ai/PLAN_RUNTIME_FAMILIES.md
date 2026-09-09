# Runtime families plan

Status: **Accepted and frozen; implementation in progress**.
Freeze date: 2026-09-09.

This plan owns the accepted target for runtime families, dependency maintenance,
device selection and Whisper duration limits. The [Models contract](../contracts/models.md)
describes implemented behavior. Windows Transformers and catalog cleanup are the
current implementation round; Infinity, Audio and WD14 migration remain pending.

Keep this plan active until runtime implementation and acceptance are complete.
Update owning contracts as each behavior is implemented, then delete this plan
and every reference in the completion change, following
[documentation maintenance](DOCS_MAINTENANCE.md#plan-lifecycle).

## Frozen runtime families

| Distribution family | Builds | Responsibility |
| --- | --- | --- |
| llama-server | CPU, CUDA | GGUF LLM inference |
| PyTorch Transformers | CUDA | Transformers LLM inference through Transformers v5 serve |
| PyTorch Infinity | CUDA | Text Embedding, Reranker and Image Embedding |
| ONNX | CPU | Kokoro TTS and WD14 Vision |
| PyTorch Audio | CUDA | Qwen3-TTS, Chatterbox and Transformers Whisper ASR |

These names identify distribution families, not new wire values for runtime_id
or runtime_variant. Existing identifiers, settings and schemas remain described
by their implemented contracts until the code refactor changes them.

GPU means NVIDIA CUDA. The target platforms are Windows and Linux x64; each
family/platform combination must pass acceptance before being advertised as
supported. The target matrix does not extend today's supported platform matrix.

PyTorch Transformers, PyTorch Infinity, ONNX and PyTorch Audio each own a separate
Python dependency environment. The three Audio engines share the Audio environment.
Kokoro and WD14 share the ONNX CPU environment. Infinity model support must be
verified by architecture; its presence does not promise arbitrary embedding or
reranker compatibility. Follow [Knowledge](../contracts/knowledge.md) for index
invalidation/rebuilding after backend or preprocessing changes and preservation
of RRF order when reranking is unavailable.

Florence, DINOv2 and future CosyVoice3 support are excluded from the target.
Vulkan, ONNX GPU and separate PyTorch CPU distributions are also excluded.
Remove corresponding existing implementation and configuration during the
runtime refactor, without compatibility bindings or data conversions. Preserve
model files, attachments, installed runtimes and other protected data under the
[data layout rules](../DATA_LAYOUT.md#database-revisions).

## Devices and managed execution

- All three PyTorch families ship CUDA builds only. Profiles may explicitly
  select CPU execution from those builds; each engine needs a validated CPU
  dtype and operator path. ONNX executes on CPU. llama-server retains separate
  CPU and CUDA builds.
- An explicit CUDA selection fails when the requested device is unavailable;
  there is no automatic CPU substitution. Package installation and GPU execution
  availability are separate checks.
- All inference continues through core/models and managed execution remains
  outside the API process. Reuse ModelManager, runtime supervision and the
  code-owned catalog; do not introduce an extension registry.
- Qwen3-TTS, Chatterbox and Whisper each use a separate managed worker, queue and
  cancellation scope while sharing the Audio environment. One engine's
  cancellation or process failure must not terminate the other Audio workers.
  Runtime maintenance accounts for all workers using that environment.
- Dependency sharing concerns installation storage, not shared model memory or
  VRAM. Existing manual model release remains the default; engine-owned idle
  unloading must not override ModelManager's selected lifecycle policy.
- Model weights and auxiliary resources remain locally supplied. Preserve
  offline execution and the prohibition on automatic model downloads and remote
  model code. This freeze introduces no image-generation functionality.

## Dependency ownership and Audio compatibility

Every family/platform release owns a complete dependency or artifact lock with
exact versions and hashes, including its Python interpreter and CUDA build where
applicable. Select Torch and Torchaudio as a matching pair. Different families
may use different Torch/CUDA versions; do not force a single CUDA wheel channel
across the catalog. Shared interpreters and identical cached artifacts may be
reused through the existing managed storage and cache services.

Audio is one compatibility and release unit. Pin Qwen3-TTS, Chatterbox, Whisper's
Transformers implementation and all transitive dependencies together. Required
ONNX Runtime and audio-processing dependencies belong in that environment even
though its family is named PyTorch Audio.

Controlled upstream patches, adjusted dependency metadata and built artifacts
must be versioned and auditable. A no-deps installation step is not evidence of
compatibility: the complete lock and dependency declarations must describe the
combination actually validated. Do not track unpinned upstream branches or treat
unresolved dependency constraints as a successful compatibility check.

Python 3.12, Transformers 4.57.3 and NumPy 1.26.4 are starting points for Audio
compatibility validation, not approved release pins. Torch/Torchaudio, Chatterbox
and remaining versions must be selected and tested before locking a release.
The Audio Transformers version is independent of PyTorch Transformers' v5 serve
environment. No current upstream-version combination is guaranteed by this plan.

### Voicebox design evidence

The reference is [Voicebox commit 51f49de][voicebox]. Its
[dependency file][voicebox-deps] defines a shared environment and manually lists
Chatterbox dependencies. Its [release workflow][voicebox-release] installs
Chatterbox with no-deps and does not pin that package's version. Its
[Chatterbox backend][voicebox-chatterbox] adapts CPU loading and attention, with
[float32 fixes][voicebox-dtype]; its [Whisper backend][voicebox-whisper] uses
Transformers directly.

This is evidence for application-owned dependency maintenance and engine
adaptation, not proof that arbitrary current upstream versions coexist or that
Voicebox's entire process/packaging design belongs in this project. In
particular, [Chatterbox 0.1.7][chatterbox-deps] declares Transformers 5.2.0 while
[Qwen-TTS 0.1.1][qwen-deps] declares 4.57.3. Resolving this for the shared Audio
environment remains implementation and validation work.

## Whisper duration boundary

Whisper uses Transformers in the shared Audio environment. Accept otherwise
valid audio with decoded duration at most 30 seconds, including exactly 30
seconds. Determine duration from decoded audio rather than trusting container
metadata alone. Reject audio longer than 30 seconds explicitly before inference,
and return no partial transcript.

Do not silently truncate to the first 30 seconds or automatically segment longer
recordings. Long-form transcription is outside this frozen scope. The explicit
duration guard must run before feature extraction can apply its own truncation.

Voice-cloning uploads, temporary voice interfaces, playback and live capture are
outside this runtime freeze. Their existing boundaries remain in
[future model services](../FUTURE_MODEL_SERVICES.md#voice-cloning-and-text-analysis)
and the implemented Models contract; this plan adds no interfaces for them.

## Outstanding implementation and acceptance

- Completed in this round: the code-owned catalog now exposes validated
  llama-server, ONNX CPU, Windows Transformers CUDA and explicit unsupported
  Infinity/Audio placeholders. Torch CPU, Vulkan, ONNX GPU, DINOv2 and Florence
  bindings were removed. Windows Transformers has a complete lock, managed
  offline child server and CPU/CUDA validation with Qwen3.5-0.8B.
- Remaining: move WD14 into the ONNX environment without a Torch import
  requirement, and implement Infinity and Audio with complete locks and managed
  process adaptations. Candidate versions alone do not satisfy acceptance.
- Run real inference for all three Audio engines on explicit CPU and CUDA paths.
  Cover loading, repeated inference, manual unloading, cancellation, unavailable
  CUDA errors and preservation of unrelated workers. Re-run the three-engine
  matrix together for dependency upgrades.
- Verify Whisper below 30 seconds and exactly 30 seconds succeeds for valid
  inputs. An input longer than 30 seconds by one decoded sample must fail before
  inference, with no transcript, truncation or automatic segmentation. Check
  that misleading duration metadata cannot bypass the decoded-duration guard.
- Verify Infinity architecture support, embedding index invalidation/rebuilding
  and unavailable-reranker RRF behavior. Validate platform support before exposing
  it in the catalog; retain unverified limits in the owning contract.
- Run the [repository verification commands](../../README.md#verification),
  including backend tests, frontend tests/build, documentation links/line limits,
  OpenAPI and workspace checks. Record real-runtime results separately from
  deterministic tests; neither this document nor passing documentation checks
  constitutes runtime compatibility validation.

[voicebox]: https://github.com/jamiepine/voicebox/tree/51f49dea198384b4eb6087b72c17057c6eb1c1cd
[voicebox-deps]: https://github.com/jamiepine/voicebox/blob/51f49dea198384b4eb6087b72c17057c6eb1c1cd/backend/requirements.txt
[voicebox-release]: https://github.com/jamiepine/voicebox/blob/51f49dea198384b4eb6087b72c17057c6eb1c1cd/.github/workflows/release.yml
[voicebox-chatterbox]: https://github.com/jamiepine/voicebox/blob/51f49dea198384b4eb6087b72c17057c6eb1c1cd/backend/backends/chatterbox_backend.py
[voicebox-dtype]: https://github.com/jamiepine/voicebox/blob/51f49dea198384b4eb6087b72c17057c6eb1c1cd/backend/backends/base.py
[voicebox-whisper]: https://github.com/jamiepine/voicebox/blob/51f49dea198384b4eb6087b72c17057c6eb1c1cd/backend/backends/pytorch_backend.py
[chatterbox-deps]: https://pypi.org/pypi/chatterbox-tts/0.1.7/json
[qwen-deps]: https://pypi.org/pypi/qwen-tts/0.1.1/json
