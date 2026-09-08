# Documentation maintenance

All repository documentation, including headings and active plans, must be
written in English. Application localization remains English/Chinese; user
content, identifiers and API payloads are outside this documentation policy.

## Ownership

- `AGENTS.md` owns permanent engineering constraints and contributor rules.
- `docs/AI_CONTEXT.md` is the current-product and contract navigation entry.
- `docs/contracts/` has six owners for implemented behavior: models,
  chat/context, harness/tools, Knowledge, runs/streaming and settings.
- `docs/ai/TASK_*.md` cards locate relevant source and tests; they link to
  behavioral rules rather than maintaining another specification.
- `README.md` owns source installation, model setup, API examples and verification.
  `README_RUN.md` owns launcher and portable-package instructions.
- `docs/DATA_LAYOUT.md` owns storage boundaries, revision effects and maintenance.
- `docs/FUTURE_MODEL_SERVICES.md` records unimplemented design boundaries,
  without authorizing implementation or promising frozen interfaces.

When behavior changes, update the owning contract and both frontend locales
when text is user-visible. Do not document removed extension concepts as
supported behavior or add compatibility/legacy promises.

Keep current defaults, ownership, error behavior, support limits and essential
decision rationale with their owner. Link to shared rules instead of copying
them. Describe current layouts and workflows directly, without requiring a
historical commit or implementation round to interpret them. Keep migration
effects in data layout and executable revisions in Alembic.

## Plan lifecycle

Plans may remain in the repository while accepted work is in progress. They
describe intended changes, outstanding work and acceptance criteria. Contracts
must reflect each implemented step; unimplemented proposals remain in the plan.

Before declaring planned work complete:

1. Synchronize the owning contracts and affected user/contributor instructions.
2. Verify the result and record current limitations with their domain owner.
3. Delete the completed plan and every reference to it in the same completion change.

Unfinished accepted work keeps its plan active. Explicitly deferred work belongs
in the relevant future-boundary note, without retaining a completed plan as its
container. Do not create an archive or replacement implementation log. Git
preserves historical documents; task results or commit/PR descriptions record
changed files, commands/results, API/settings/workflow changes and limitations.
Temporary server details, test totals/timings and session-specific verification
waivers do not become permanent contributor rules or support guarantees.

## Verification

Check line limits with:

```powershell
uv run python scripts/check_docs_size.py
```

Each of the six contracts has a 300-line limit. README has 350, AI_CONTEXT 150,
and task cards 120. Do not split a topic to evade the limit; remove duplication
and link to its actual owner.

`npm run check:docs` in frontend parses Markdown to check local file links and
heading anchors. It also runs through `npm test`.
Review English usage and search for stale filenames, phase-based prerequisites
and unsupported capability claims. Check substantive statements against current
code and tests. Report implementation discrepancies separately rather than
documenting them as intended behavior. Run the [repository verification commands](../../README.md#verification)
and `git diff --check` before committing.
