# Task: Knowledge / RAG

Read first: `../contracts/knowledge.md`,
`../contracts/memory-worldbook.md`, and `../contracts/runtime-llm-resolution.md`.

Likely sources are `ai_workbench/core/knowledge_*`, `retrieval.py`,
`keyword_search.py`, `vector_store.py`, `api/routes/knowledge.py`, and the
Knowledge settings components.

Preserve direct source creation, one chunk profile, hybrid vector/keyword
retrieval, deterministic RRF, session bindings, context injection, and
fail-open rerank metadata. Do not add query expansion, managed origins, or a
separate reranker profile stack.

Run `uv run pytest tests/test_phase1_contracts.py -q` and `uv run pytest -q`;
for UI changes also run the frontend build and contract scripts.
