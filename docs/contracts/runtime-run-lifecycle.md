# Run lifecycle contract

This contract defines generic chat run status, steps, metadata, cancellation,
and events.

## Status

Runs use `PENDING`, `RUNNING`, `CANCELLING`, `WAITING_FOR_USER`, `DONE`,
`FAILED`, `CANCELLED`, or `INTERRUPTED`. Step status is `pending`, `running`,
`completed`, `failed`, or `skipped`. Terminal runs never return to running.

`Run.kind` is `chat` or `tool`; each run stores its selected `persona_id`.
A session `waiting_run_id` blocks ordinary messages and new direct calls.
Only explicit tool approval resumes the same run; there is no implicit
chat-resume path or separate resume run kind.

## Steps

`RunStep.kind` is one of `context`, `model`, `save`, `approval`, or `tool`.
Harness emits tool and approval steps alongside ordinary chat steps. Steps have stable
ordering, optional parent ids, status, timing, compact message text, and
structured error fields. UI labels come from the kind and i18n, not from
implementation-specific strings.

## Persistence and cancellation

ChatRunner persists the user message, run, steps, assistant message, and run
events. Cancellation is best effort; a requested run reaches `CANCELLED` or
`INTERRUPTED` with an explanatory error/status. Waiting runs expose
`WAITING_FOR_USER` and an `approval` step for the UI.

Run/message metadata may contain public model/profile ids, counts, timings,
warnings, and context source references. It must not contain full prompts,
history, Memory/Worldbook/Knowledge bodies, vectors, attachments, or secrets.

Chat runs also have a private resolved Persona configuration snapshot. Its
prompt and generation defaults keep an in-flight run stable, but are not
exposed through metadata or events. See [persona-chat](persona-chat.md).

Harness runs additionally store private tool transcript and pending approval
state. `WAITING_FOR_USER` is resumed only by the explicit tool approval API;
ordinary chat input cannot implicitly approve a call.

Valid pending approvals survive restart with their original configuration,
remaining call queue and active-time budget. Other unfinished runs become
`INTERRUPTED`. Direct calls and approval resumes share active cancellation;
cancellation settles outstanding tool results/steps and clears waiting/private
state. Direct rejection or handler failure is `FAILED`; model-loop tool errors
may be handled by a later model answer. See [harness-tools](harness-tools.md).
