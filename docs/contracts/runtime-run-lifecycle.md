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

When Prompt Agent Web Context is enabled and the web plan is evaluated, runtime
may add a compact `Web context plan` child step under `Building context`. The
child step records only the plan source, resolver reason/confidence when used,
skip reason, warnings, and compact query metadata. It must not include raw
Utility output, prompts, full user text duplicates, rendered web context, raw
search payloads, or retrieved content.
The child step uses plan-only metadata and should not be rendered as a second
full `Context injected` summary. The parent `Building context` step remains the
single place for the combined Memory, Worldbook, Knowledge, and Web injection
summary.

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
- `web_context`
- generated image recipe metadata, such as `comfyui_generation`
- cleanup warnings, such as `llm_unload` or `comfyui_memory_release`

Metadata must not store:

- full Core Memory text.
- full Worldbook entry content.
- rendered context blocks.
- full Knowledge snippets or source originals.
- full Web Search results, raw provider payloads, rendered `# Retrieved Web`
  blocks, or fetched page bodies.
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

`web_context` metadata stores the Web Context plan and outcome compactly. Allowed
fields include enablement, attempted/injected booleans, truncated query,
`query_source`, provider, result count, compact source refs, `skipped_reason`,
warnings, compact search filtering diagnostics, compact page fetch diagnostics,
compact Web Candidate Relevance Judge diagnostics, and a compact resolver object
with `used`, `reason`, and `confidence`.
Each `source_refs` item may include only compact citation UI fields:
`ref_id` such as `W1`, `rank`, `title`, validated HTTP/HTTPS `url`, `domain`,
`published_at`, `source`, a capped `snippet_preview` or short `snippet`, and
compact page fetch fields such as `page_fetch_status`, `page_title`,
`page_excerpt_preview`, `page_excerpt_chars`, and `page_fetch_warning`.
When Page Excerpt Gate is enabled, `source_refs` may also include compact
per-source gate fields: `page_excerpt_gate_status` (`accepted`, `rejected`,
`failed`, `skipped`, or `disabled`), `page_excerpt_quality`,
`page_excerpt_confidence`, `page_excerpt_coverage`,
`page_excerpt_gate_reason`, and `page_excerpt_injected`. Rejected or failed
gate sources must not expose the full excerpt; only capped previews and compact
status/reason fields are allowed.
When the Candidate Judge annotates a final source, the source ref may also
include compact `candidate_judge_state` (`retained` or `unjudged`),
`candidate_judge_relevance`, `candidate_judge_role`,
`candidate_judge_confidence`, and a short `candidate_judge_reason`.
`page_excerpt_preview` must be capped for UI inspection and must not contain the
full fetched page excerpt.
`search_diagnostics` may include only compact filtering facts such as
`filtered_count`, `deduped_count`, `filters_applied`, and warning codes. It must
not include raw provider payloads, full filtered result lists, or fetched page
bodies.
Page fetch summary fields may include `page_fetch_enabled`, `pages_attempted`,
`pages_fetched`, `pages_failed`, and `page_fetch_warnings`.
Page Excerpt Gate summary may include `page_excerpt_gate.enabled`, backend,
attempted/accepted/rejected/failed counts, `stopped_reason`, and compact warning
codes. It must not store the raw gate prompt, raw gate model output, rendered
Web context, full page excerpts, raw HTML, raw HTTP responses, raw provider
payloads, secrets, or a full accepted evidence chain.
Candidate Judge summary fields may include `candidate_judge.enabled`,
`candidate_judge.used`, `candidate_judge.mode =
conservative_reject_only`, `candidate_judge.schema = rejected_items_v1`,
candidate/retained/rejected/unjudged counts, invalid item count,
`fallback_used`, compact warning codes, and aggregate rejected reason counts.
Missing Utility items, invalid items, unknown enum values, non-reject source
roles, medium/high relevance, and low/medium confidence judgments retain the
candidate. It must not include the raw Utility prompt, raw Utility output, raw
SearXNG payload, page bodies, rendered Web context, or a full rejected source
list.
The plan may record whether Intent Routing influenced the decision, but it must
not store raw Utility output, Utility prompts, full user text duplicates,
rendered `# Retrieved Web`, raw provider payloads, fetched page bodies, Web
Context prompt text, KB snippets, Core Memory, Worldbook content, or secrets.

For real Prompt Agent runs only, `intent_routing.web_context_usage` may be
`used_for_web_context` when diagnostic `web_query` slots/original query were
used by Prompt Agent Web Context. This is a display hint and does not mean the
Intent Routing executor ran a route.

Known Web Context skip reasons include `knowledge_query_selected`,
`knowledge_query_candidate_blocked`, `pet_command_selected`, resolver reasons
such as `time_sensitive_fact_question` or `incidental_mentions_only`, and
provider/runtime reasons such as `search_failed`, `no_results`, or
`web_results_filtered_empty`, and judge reasons such as
`web_candidate_judge_rejected_all`.

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
