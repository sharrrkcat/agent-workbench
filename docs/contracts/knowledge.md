# Knowledge / RAG contract

Knowledge is an explicit core service used by ChatRunner and the Knowledge
HTTP routes. It owns bases, sources, chunks, indexes, session bindings,
hybrid retrieval, context formatting, and optional post-retrieval reranking.

## Sources and indexing

Sources are created directly as pasted text, attachment text, or a workspace
file (`uri`/`path`). There is no separate origin/scan/import workflow. A source
is chunked with the single `default_chunk_size`/`default_chunk_overlap` pair
from `KnowledgeSettings`; its chunks, vectors, and FTS rows are rebuilt by the
source reindex operation.

## Retrieval

Vector and keyword candidates are merged with reciprocal rank fusion (RRF).
Session bindings define the Knowledge Bases searched by default; callers may
provide an explicit list. Search can return compact debug metadata and a
rendered context preview. RRF ordering is deterministic for equal candidates.

`KnowledgeSettings` retains `reranker_enabled`,
`reranker_model_profile_id`, and `reranker_candidate_limit`. There is no
independent reranker profile store or public rerank endpoint in Phase 1. If a
reranker is not configured, unavailable, or fails, retrieval returns the RRF
order and records `metadata.rerank_fallback` without failing the chat.

Query expansion, managed origins, multiple chunk profiles, and download or
background-indexing workflows are not part of this contract.

## API surface

- `/api/knowledge/settings` — read/update retrieval and chunk settings.
- `/api/knowledge/bases` — Knowledge Base CRUD.
- `/api/knowledge/bases/{id}/sources` — direct source creation/listing.
- `/api/knowledge/sources/{id}/reindex` — rebuild one source index.
- `/api/knowledge/search` — explicit hybrid search.
- `/api/sessions/{id}/knowledge-bases` — ordered session bindings.
- Embedding profile routes and `/api/knowledge/embeddings` provide the
  existing embedding skeleton used by indexing.

Request models use `extra="forbid"`; removed fields are rejected with 422.
