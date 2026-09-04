# Task: Core Memory and Worldbook

Read first: `../contracts/memory-worldbook.md` and
`../contracts/message-parts.md`.

Likely sources: `core/memory_context.py`, `core/worldbook.py`,
`core/worldbook_context.py`, `core/context.py`, and the matching API routes.

Keep injection deterministic and data-only. Core Memory is controlled by
General settings; Worldbook settings and CRUD remain under their own routes.
Session bindings, group transcript speaker labels, entry limits, matching
rules, and compact metadata are part of the contract.

Run `uv run pytest tests/test_core_memory_context.py tests/test_worldbook_context.py -q`
and the full suite after changes.
