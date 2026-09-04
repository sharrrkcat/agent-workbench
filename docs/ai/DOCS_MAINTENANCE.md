# Documentation maintenance

`README.md` owns installation and user-facing behavior. The refactor roadmap
owns frozen decisions and phase status. `docs/contracts/` contains one concise
owner for each API, schema, runtime, or UI boundary. `docs/ai/TASK_*.md` cards
are short read-first pointers for contributors.

When behavior changes, update the owning contract and both frontend locales
when text is user-visible. Do not document removed extension concepts as
supported behavior or add compatibility/legacy promises.

Check soft size limits with:

```powershell
uv run python scripts/check_docs_size.py
```

Before committing, verify links to deleted documents, run `git diff --check`,
and include changed docs, tests, and any intentionally deferred work in the
commit summary.
