# Documentation maintenance

`README.md` owns installation and user-facing behavior. The refactor roadmap
owns frozen decisions and phase status. `docs/contracts/` contains one concise
owner for each boundary: models, chat/context, harness/tools, Knowledge,
runs/streaming and settings. `docs/ai/TASK_*.md` cards
are short read-first pointers for contributors.

When behavior changes, update the owning contract and both frontend locales
when text is user-visible. Do not document removed extension concepts as
supported behavior or add compatibility/legacy promises.

Check size limits with:

```powershell
uv run python scripts/check_docs_size.py
```

Each of the six contracts has a 300-line limit. README has 350, AI_CONTEXT 150,
and task cards 120. Do not split a topic to evade the limit; remove duplication
and link to its actual owner. Historical phase records belong only in the roadmap.

`npm run check:docs` in frontend parses Markdown to check local file links and
heading anchors. It also runs through `npm test`.
Before committing, run `git diff --check`,
and include changed docs, tests, and any intentionally deferred work in the
commit summary.
