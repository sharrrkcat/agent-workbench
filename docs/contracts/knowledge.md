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

Attachment indexing reads complete UTF-8 text under Knowledge's byte/character
limits, independently of chat's attachment-preview limit. Empty, invalid or
oversized input is rejected. Source creation and reindex return
KnowledgeSourceIndexResult (source_id, status, chunks and index metadata), not
a source record. Listing returns records; previews use content/truncated.
Preview and reindex resolve the actual attachment. A source reference protects
its attachment from deletion and orphan cleanup; deleting a source removes its
chunks/vectors/FTS rows but leaves files for explicit cleanup.

The settings UI has Resources and Global settings views. A base opens an inline
detail with Configuration, Sources and Search test tabs, initially Sources.
Creation saves Configuration and then opens Sources. Sources combines pasted
text and uploaded UTF-8 files with the list, individual/all reindex and deletion.
Uploads are processed sequentially, retain per-file failures for retry and never
resubmit successful items. Temporary unreferenced uploads are cleaned on closing
the form. Workspace-file creation remains an API operation without a UI path picker.
The source modal shows read-only original text and chunks; it has no origin,
directory, chunk-profile classification or text-edit workflow.

Search test uses the selected base and displays result order and text, with
collapsed scores, diagnostics and context preview. Rerank fallback remains
visible. Configuration references the unified embedding catalog and displays
missing/disabled selections without replacement. Optional aliases and retrieval
overrides are in its collapsed advanced section.

## Retrieval

Vector and keyword candidates are merged with reciprocal rank fusion (RRF).
The current speaker's Persona bindings plus independent session additions define
the default Knowledge Bases, deduplicated in that order. An empty session list
clears only additions. Callers may provide an explicit list. Search can return compact debug metadata and a
rendered context preview. RRF ordering is deterministic for equal candidates.

`KnowledgeSettings` retains `reranker_enabled`,
`reranker_model_profile_id`, and `reranker_candidate_limit`. There is no
independent reranker profile store or public rerank endpoint. If a
reranker is not configured, unavailable, or fails, retrieval returns the RRF
order and records `metadata.rerank_fallback` without failing the chat.

Query expansion, managed origins, multiple chunk profiles, and download or
background-indexing workflows are not part of this contract.

## API surface

- `/api/knowledge/settings` — read/update retrieval and chunk settings.
- `/api/knowledge/bases` — Knowledge Base CRUD.
- `/api/knowledge/bases/{id}/sources` — direct source creation/listing.
- `/api/knowledge/sources/{id}/reindex` — rebuild one source index.
- `/api/knowledge/bases/{id}/reindex` — rebuild all sources, reporting partial failures.
- `/api/knowledge/sources/{id}/preview`, `/chunks` — original text and indexed chunks.
- `/api/knowledge/sources/{id}` — get/delete a source.
- `/api/knowledge/search` — explicit hybrid search.
- `/api/sessions/{id}/knowledge-bases` — ordered additions, Persona and effective ids.
- `/api/personas/{id}/knowledge-bases` — ordered Persona bindings.
- Model selection uses `/api/models/profiles?kind=embedding` or `reranker`.

Indexing, query embedding and reranking are async calls to the app-scoped
ModelManager. Model instructions, dimensions, normalization and batch sizes
belong to the unified profile. Indexing and `/v1/embeddings` use the same
document preprocessing; retrieval uses query preprocessing. No local runtime
is imported by Knowledge. Rerank executes in the CPU Python worker when its
runtime and local model are available; failures retain the documented RRF order.

Changing an embedding profile's provider, runtime binding/options, model reference or parameters, or
its provider URL, marks associated bases and sources `needs_reindex` in both
memory and SQLite stores. Retrieval excludes invalidated bases until reindex.
One successful source does not clear a base's needs_reindex state while other
sources still require rebuilding. Deleting the final source sets the base empty.
Search forwards threshold, per-source and per-base chunk limits to retrieval.

Request models use `extra="forbid"`; removed fields are rejected with 422.
OpenAPI and runtime response models cover bases, sources, indexing results,
partial reindex failures, previews, chunks and search. Retrieval scores, ranks,
rerank diagnostics and optional debug output have concrete schemas; no vectors
are exposed. Source/chunk metadata remains documented finite JSON. PATCH schemas
distinguish omission from nullable overrides; the existing merge validators and
domain error codes still apply. Memory chunk responses omit embedding_dimension,
while SQLite responses include the value or null, preserving the existing wire format.
