# Runtime Run Lifecycle Contract

This contract owns run status, run steps, run metadata compactness, cancellation,
failure behavior, and run-related WebSocket events.

## Status Values

Run status values:

- `PENDING`
- `RUNNING`
- `CANCELLING`
- `WAITING_FOR_USER`
- `DONE`
- `FAILED`
- `CANCELLED`
- `INTERRUPTED`

RunStep status values:

- `pending`
- `running`
- `completed`
- `failed`
- `skipped`

Terminal statuses must not move back to running.

## Default Step Shape

`RunStep.parent_step_id` creates nesting.

Prompt Agent top-level steps normally include:

- `Resolving agent`
- optional `Intent semantic routing`
- `Building context`
- `Resolving model`
- `Calling LLM`
- `Saving response`
- `Cleanup`

Script Agent top-level steps normally include:

- `Resolving agent`
- optional `Resolving model`
- `Starting script`
- `Running script`
- `Saving response`
- `Cleanup`

Script custom steps created with `ctx.step` default under `Running script`.
Long-running scripts may update step messages while polling external jobs.
Steps should represent user-meaningful phases, not every helper function.

Intent Routing semantic decisions happen before `Building context`. The step
records compact outcomes only. Full routing behavior is owned by
[intent-routing.md](intent-routing.md).

Automatic session title generation is considered only after routing resolves
the actual Agent/action. Prompt Agents try it after model resolution and before
the main provider call. Script Agents try it lazily before the first real
`ctx.llm.*` call. Full title behavior is owned by
[utility-llm.md](utility-llm.md#session-title-interaction).

Cleanup records model lifecycle unload attempts, ComfyUI memory release attempts
when configured, and cleanup warnings. Cleanup failure must not overwrite an
already successful main run unless a lifecycle policy explicitly says unload
failure should fail the run.

## Metadata Compactness

Run and message metadata may store compact refs, counts, public ids, decisions,
warnings, status, and metrics. Common compact keys include:

- `llm_resolution`
- `llm_metrics`
- `vision_input`
- `file_context`
- `intent_routing`
- `core_memory_context`
- `worldbook_context`
- `knowledge_context`
- generated image recipe metadata, such as `comfyui_generation`
- cleanup warnings, such as `llm_unload` or `comfyui_memory_release`

Metadata must not store:

- full Core Memory text.
- full Worldbook entry content.
- rendered context blocks.
- full Knowledge snippets or source originals.
- vectors or vector blobs.
- full workflow JSON.
- large binary data or image bytes.
- secrets.

Generated image metadata should record compact recipe/run facts such as
attachment ids, prompt/request ids, image filtering counts, and output counts.
ComfyUI LLM prompt metadata may record operation labels and the current request
prompt fields needed by existing UI/debug flows, but raw/run-only generation
must not be mislabeled as `refine` or `fresh`.

Chat context inspection fetches current content by refs where possible. Runtime
metadata stores refs/counts/warnings, not snapshots of full user-owned content.

## Failure And Cancellation

Failures set both terminal run status and user-visible error metadata when
applicable. A failed step should point to the phase that failed.

Cancellation is best effort:

- The Cancel API sets `cancel_requested` before terminal cancellation when
  possible.
- Non-streaming provider calls may finish before cancellation is observed.
- If an external service supports cancel/interrupt, the Capability should expose
  it and the Agent may call it.
- If an external service cannot cancel, the Agent should stop local polling and
  mark the local run cancelled.
- Partial outputs should be kept only when useful and safe; incomplete or corrupt
  outputs should be discarded or clearly summarized.

## WebSocket Events And Session Load

Run events are emitted over WebSocket so the frontend can update message
timelines without polling. Session load returns runs and steps attached to
messages.

Run event names include:

- `run_started`
- `run_updated`
- `run_step_created`
- `run_step_updated`
- `run_completed`
- `run_failed`
- `run_cancel_requested`
- `run_cancelled`
- `run_warning`

These events are for frontend timeline/run-step updates. Message streaming
events are owned by [runtime-streaming.md](runtime-streaming.md) and should not
be mixed into this run event list. `llm_provider_status_updated` is a related
provider-status event emitted after some status refreshes, not a run timeline
event.

The frontend may expand run-step timelines from message metadata and run event
state. It may render `Building context` as a compact `Context injected` summary
for Core Memory, Worldbook, Knowledge, and warnings, but must not show or store
full injected content in metadata.

## Related Contracts

- Streaming messages: [runtime-streaming.md](runtime-streaming.md)
- LLM resolution and unload policies: [runtime-llm-resolution.md](runtime-llm-resolution.md)
- Provider/runtime memory release: [provider-status.md](provider-status.md)
- Attachments and vision metadata: [attachments-vision.md](attachments-vision.md)
- Core Memory and Worldbook metadata: [memory-worldbook.md](memory-worldbook.md)
- Knowledge metadata: [knowledge.md](knowledge.md)
