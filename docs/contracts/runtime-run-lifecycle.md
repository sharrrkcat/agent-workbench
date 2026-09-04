# Run lifecycle contract

This contract defines generic chat run status, steps, metadata, cancellation,
and events.

## Status

Runs use `PENDING`, `RUNNING`, `CANCELLING`, `WAITING_FOR_USER`, `DONE`,
`FAILED`, `CANCELLED`, or `INTERRUPTED`. Step status is `pending`, `running`,
`completed`, `failed`, or `skipped`. Terminal runs never return to running.

`Run.kind` is `chat` or `resume`; `Run.target` is a plain target string and is
`chat` for the default path. A session `waiting_run_id` always takes priority:
the next message resumes that run and clears the waiting reference.

## Steps

`RunStep.kind` is one of `context`, `model`, `save`, `approval`, or `tool`.
Phase 1 emits the first four kinds; `tool` is reserved. Steps have stable
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
