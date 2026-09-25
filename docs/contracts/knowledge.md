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
oversized input is rejected. File imports support UTF-8 text attachment types;
PDF and Office document parsing are unsupported. Source creation and reindex return
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
The singleton Cogita Persona, selected Agent Persona, Workspace Project and session additions
define default Knowledge Bases, deduplicated in that order; ordinary sessions have no Project bindings.
Project bindings remain inherited while additions are independently editable. An empty session list
clears only additions. Callers may provide an explicit list. Search can return compact debug metadata and a
rendered context preview. RRF ordering is deterministic for equal candidates.

`KnowledgeSettings` retains `reranker_enabled`,
`reranker_model_profile_id`, and `reranker_candidate_limit`. There is no
independent reranker profile store. `/v1/rerank` shares ModelManager with Knowledge. If a
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
- `/api/sessions/{id}/knowledge-bases` — additions, separate Cogita/Agent/Project bindings and effective ids.
- `/api/personas/{id}/knowledge-bases` — ordered Cogita/Agent Persona bindings.
- `/api/projects/{id}/knowledge-bases` — ordered Workspace bindings, inherited by its sessions; Timeline rejects Knowledge.
- Model selection uses `/api/models/profiles?kind=embedding` or `reranker`.

Deleting a base referenced by a Persona or Project requires removing those bindings first.
Project deletion removes only its bindings/conversations, preserving shared bases and sources.

Indexing, query embedding and reranking are async calls to the app-scoped
ModelManager. Local text profiles derive dimensions, pooling, normalization and
query/document prompts from Sentence Transformers metadata; provider profiles
retain their explicit instructions/dimensions/normalization. [Models](models.md#local-text-embeddings)
owns processing and acceptance limits. Indexing passes purpose=document and retrieval
passes purpose=query, sharing `/v1/embeddings` preprocessing without importing runtimes.
Both SQLite and memory score native cosine by vector norms or native dot directly;
vectors retain native output normalization. Unsupported similarities block local loading.
Local CrossEncoder reranking returns native scores in candidate order; Knowledge sorts them descending, preserving RRF ties.
Unavailable or failed reranking retains RRF order; public rerank requests instead return explicit errors.
Reranker profile changes do not invalidate embedding indexes. [Models](models.md#local-reranking) owns native scoring and limits.

Changing an embedding profile's source binding, model reference or parameters, or
its provider URL, marks associated bases and sources `needs_reindex` in both
memory and SQLite stores. Retrieval excludes invalidated bases until reindex.
Replacing model files at the same path also requires explicit unload/reload and reindex;
model files are immutable while loaded and no content hashing detects replacements.
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
