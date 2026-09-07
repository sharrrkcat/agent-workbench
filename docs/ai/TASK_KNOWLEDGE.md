# Task: Knowledge / RAG

Read [Knowledge](../contracts/knowledge.md),
[chat/context](../contracts/chat-context.md) and [models](../contracts/models.md).

Likely sources are `ai_workbench/core/knowledge_*`, `retrieval.py`,
`keyword_search.py`, `vector_store.py`, `api/routes/knowledge.py`, and the
Knowledge settings components.

Preserve direct source creation, one chunk profile, hybrid vector/keyword
retrieval, deterministic RRF, session bindings, context injection, and
fail-open rerank metadata. Do not add query expansion, managed origins, or a
separate reranker profile stack. Embeddings and rerank use core/models and
unified UUID references. Preserve shared document/query preprocessing and
invalidate indexes when the vector configuration changes.

Run `uv run pytest tests/test_phase2a_knowledge.py -q` and `uv run pytest -q`;
for UI changes also run the frontend build and contract scripts.
