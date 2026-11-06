# Native reasoning output implementation plan

Status: planned; implementation has not started. Updated: 2026-11-07.

## Objective and scope

Use the managed engines' native response parsers to separate reasoning, answer
text and tool calls. NVIDIA-Nemotron-3.5-Bolt-E4B-4GB is the motivating GGUF
case; the implementation must apply to supported templates without model-name
special cases. Normal chat and Harness must consume the same structured fields.

This task authorizes planning, not implementation or model execution. The user's
no-model-execution constraint remains active. Do not load models, start inference
servers, call inference endpoints, or run real-model smoke scripts under it.

Excluded: asynchronous tools, a conversational-mode button or template option,
reasoning budgets, DFlash, downloads, runtime upgrades, schema/data conversions,
and historical-message rewriting. Reasoning-mode capability detection is a
separate concern and is not expanded by this plan.

## Verified baseline

- [Managed startup](../../ai_workbench/core/models/runtimes/adapters.py) pins
  llama-server b10809 and passes `--reasoning-format none`. This retains native
  reasoning delimiters in `content`.
- b10809 enables Jinja by default and already has a Gemma 4 response parser.
  Its `deepseek` reasoning format returns `reasoning_content`; the name denotes
  the response format, not a restriction to DeepSeek models.
- The local Bolt GGUF contains the Gemma 4 delimiters
  `<|channel>thought` and `<channel|>`. Existing stored replies confirm that
  these can reach text parts. Reading metadata and stored records required no
  inference; no private message text belongs in fixtures or documentation.
- [Assistant output](../../ai_workbench/core/assistant_output.py) accepts
  `reasoning_content`, but also runs every `content` value through ThinkParser,
  which recognizes only `<think>` markers outside Markdown code and escapes.
- [TransformersEngine](../../ai_workbench/workers/transformers_engine.py) already
  uses the pinned Transformers 5.16.1 ChatCompletionHandler. Its serving layer
  selects tokenizer `response_template`, then upstream model-type defaults,
  then unparsed text. Gemma 4 and Qwen 3.5 defaults exist in that version.
  Streaming uses ResponseParser; complete responses use tokenizer.parse_response.
  Both receive the generation prefix and return independent reasoning/tool data.
- [Native mode evidence](../../ai_workbench/workers/reasoning.py) checks rendered
  generation prefixes. Bolt enables thinking through a system token while the
  ordinary assistant prefix remains unchanged, so the current classifier returns
  unknown. Output-parser availability does not establish mode-switch support.

Pinned upstream references:
[llama defaults](https://github.com/ggml-org/llama.cpp/blob/b10809/common/common.h),
[llama Gemma parsing](https://github.com/ggml-org/llama.cpp/blob/b10809/common/chat.cpp),
[Transformers serving](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/cli/serving/utils.py),
[Bolt template](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-BF16/blob/49843eed8db1f1c616c47af75cfd36e07aec0667/chat_template.jinja).

## Target behavior

1. Managed llama-server starts with explicit `--jinja` and
   `--reasoning-format deepseek`. Remove the `none` setting directly; do not add
   dual modes, a profile switch, legacy output, or retry-based parsing recovery.
2. Transformers retains its upstream parsing pipeline. Keep raw special tokens
   available to its parser and preserve its generation-prefix handling. Do not
   copy upstream templates or implement a second family registry in Cogita.
3. For both managed backends, `reasoning_content` becomes reasoning parts and
   `content` becomes text parts verbatim. Tool calls stay structured. Do not
   parse managed content again or reconstruct missing markers from output text.
4. Derive a private presentation policy from the resolved profile's source before
   constructing AssistantDraft. Pass it explicitly in normal chat and each
   Harness round, including resumed runs. Direct-tool drafts do not parse model
   markers. No public request field or persisted configuration is needed.
5. External-provider internal chat retains its existing structured-reasoning and
   raw `<think>` normalization behavior. Keep that behavior explicitly scoped
   to provider input; it is not a recovery path for managed engines. Provider
   `/v1` passthrough remains unchanged.
6. Preserve received reasoning independently of the requested reasoning mode.
   The request selects generation behavior; it does not hide response fields.
   Keep partial results, stable part IDs, timing, cancellation and failure
   settlement. Retain structured reasoning in the active tool transcript and
   exclude reasoning parts from ordinary historical context as currently owned.
7. Public `/v1` forwards the engine's fields without parsing or recombining them.
   GGUF callers will receive extracted thoughts in `reasoning_content` instead
   of raw thought markers in `content`. Existing schemas already accept this
   field; document the response-placement change without a compatibility flag.
8. Keep reasoning request translation and supported/unsupported/unknown checks.
   An unknown mode remains unknown and follows current admission behavior.
   Missing native parsing rules remain an engine limitation; do not claim
   universal template support or infer reasoning from ordinary answer text.

## Implementation sequence and ownership

### 1. Enable native GGUF extraction

Update the startup arguments in
[adapters.py](../../ai_workbench/core/models/runtimes/adapters.py).
Reuse the installed runtime and the existing OpenAI transport. Preserve CPU/CUDA
launch behavior, authentication, queues, counting and lifecycle ownership.
Add focused launch coverage in
[test_phase2b_runtime.py](../../tests/test_phase2b_runtime.py) or
[test_llama_cuda.py](../../tests/test_llama_cuda.py).

### 2. Make managed presentation consume fields directly

Update [assistant_output.py](../../ai_workbench/core/assistant_output.py),
[chat_runner.py](../../ai_workbench/core/chat_runner.py) and
[agent_loop.py](../../ai_workbench/core/harness/agent_loop.py) together.
Use resolved source ownership, not model names, marker presence or arrival of
the first reasoning chunk, to select the policy. Update constructor call sites
and fixtures. Remove abandoned local-marker paths directly; retain the provider
parser only for its explicit provider behavior.

Verify that active tool transcripts use original structured fields, so a
reasoning-only tool round can continue without fabricated answer text. No new
frontend controls, localization strings or message-part schema are expected.

### 3. Verify both engine boundaries

Use synthetic native responses through the existing transport and presentation
fixtures. These tests establish Cogita's handling, not model generation quality.
In [test_transformers_runtime.py](../../tests/test_transformers_runtime.py),
verify delegation to the existing upstream parser and propagation of its fields.
An isolated installed-runtime parser check may feed synthetic strings to the
pinned parser without loading weights; it is not a normal-suite dependency on
an installed runtime and must never instantiate TransformersEngine or a model.

Extend meaningful coverage in
[test_reasoning.py](../../tests/test_reasoning.py),
[test_chat_presentation.py](../../tests/test_chat_presentation.py), and
[test_phase2a_protocol.py](../../tests/test_phase2a_protocol.py):

| Case | Required result |
| --- | --- |
| Complete and streamed native reasoning | Same reasoning/answer parts without duplicate markers |
| Split markers and a prefilled opener in an isolated native parser check | Correct reasoning boundary using the actual generation prefix |
| Native content containing literal `<think>` text or code | Content remains literal at Cogita's presentation boundary |
| Reasoning-only, empty content, or output ending during reasoning | No invented answer; received reasoning is retained |
| Cancellation/error after reasoning begins | Partial parts settle once; timing and incomplete state remain valid |
| Reasoning plus tool call and resumed continuation | Separate tool data; active transcript retains structured reasoning |
| Reasoning disabled or omitted | Existing request translation remains; returned fields are not filtered |
| Public JSON and SSE | Native field placement survives; finish reasons and terminal framing remain valid |
| Provider raw-marker input | Existing Markdown/escape-aware provider behavior remains covered |
| Unfamiliar template or identical mode prefixes | No model-name assumptions, forced support claim or inference probe |

### 4. Update contracts and finish the change

Update [Models](../contracts/models.md) for native parsing ownership and `/v1`
field placement; [Chat/context](../contracts/chat-context.md) for local versus
provider normalization; [Runs/streaming](../contracts/runs-streaming.md) for
field-driven reasoning timing. Update [Harness/tools](../contracts/harness-tools.md)
if continuation behavior changes. Keep current acceptance limits with their owner.

## Verification and acceptance

For this documentation-only planning round, run frontend tests/build,
`uv run python scripts/check_docs_size.py` and `git diff --check`; skip backend
tests. No model process is started by these checks.

For implementation, use the [README verification commands](../../README.md#verification):

```powershell
uv run pytest -n 8 -q
uv run python scripts/openapi.py check
uv run python scripts/check_docs_size.py
git diff --check
```

From `frontend`, run `npm test` and `npm run build`. Review the API contract even
if the schema is unchanged, because GGUF response field placement changes.

Real-model acceptance remains pending until model execution is explicitly
authorized. The intended matrix is thinking on/off and streaming/non-streaming,
with normal replies and a tool continuation on CPU/CUDA as applicable. Use the
configured Bolt GGUF plus an explicitly selected representative Qwen GGUF for
regression. Transformers requires a representative local checkpoint selected
at that time; the installed 0.8B checkpoint is not acceptance evidence. Reuse
verified installations and README smoke entry points; do not download models.
Record exact engine/model/device and unresolved cases in the task result.

Before implementation completion, all deterministic checks must pass and the
owning contracts must state any outstanding live acceptance honestly. A verified
native parser is not proof of a model's reasoning switch or generation quality.
Delete this plan and its AI_CONTEXT reference in the same completion change,
following [the plan lifecycle](../ai/DOCS_MAINTENANCE.md#plan-lifecycle).
