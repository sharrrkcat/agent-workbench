# Knowledge / RAG Contract

Knowledge v1 is the local RAG foundation for Agent Workbench. It owns local
Knowledge defaults, embedding model profiles, knowledge bases, source indexing,
SQLite chunk/vector/FTS storage, explicit retrieval search, session KB bindings,
automatic context injection, and a thin Knowledge Capability wrapper.

## Scope

Knowledge v1 includes:

- local Knowledge settings.
- embedding model profiles managed in Settings -> Models -> Embedding Model
  Profiles.
- knowledge bases.
- pasted text, text attachment, and managed-origin source indexing.
- SQLite storage for sources, chunks, float32 vectors, and FTS rows.
- explicit retrieval search.
- session Knowledge Base bindings.
- automatic Knowledge context injection for eligible Prompt and Script Agents.
- a thin `knowledge` Capability wrapper with `/kb-search`.

Knowledge v1 does not include automatic model download, dependency install,
arbitrary local path import, file watching, scheduled scan, background reindex,
chat-time scan/reindex, or Capability-owned retrieval/indexing backends.

## Local Models

Local model directories are:

- `data/models/llms/<model-folder-or-file>` for internal provider LLM
  inventory.
- `data/models/embeddings/<model-folder>`
- `data/models/rerankers/<model-folder>`

Provider Profiles can list local embedding and reranker inventory using
`embedding/...` and `reranker/...` refs, but this round does not change
Knowledge indexing, retrieval, embedding generation, reranking, or Embedding
Model Profile schema.

Optional dependencies include `sentence-transformers`, `torch`, and
`transformers`. Missing optional dependencies must not break normal chat
startup. Local model scan and test APIs may report unavailable backends with
structured errors.

There is no automatic download/install path:

- no `/api/knowledge/models/download` endpoint.
- no backend shell execution.
- no background download task.
- the Download tab only generates copyable commands.

Model scanning creates expected directories, lists direct child folders, and
reports backend availability without loading model weights. Test endpoints may
load local models and optionally unload caches when the corresponding
best-effort unload setting is enabled.

## Knowledge API Index

Main API groups and responsibilities:

| API group | responsibility |
| --- | --- |
| `GET/PATCH /api/knowledge/settings` | Knowledge Defaults, local model device, retrieval knobs, chunk/index limits, prompt templates, query expansion, and local model unload settings |
| `GET /api/knowledge/models/scan` | local embedding/reranker folder scan and optional backend availability without loading weights |
| `GET/POST/PATCH/DELETE /api/knowledge/embedding-models` | Embedding Model Profile CRUD |
| `POST /api/knowledge/embedding-models/{id}/test` | profile-specific embedding test |
| `POST /api/knowledge/embeddings` | Workbench-native embedding generation for query/document inputs |
| `POST /api/knowledge/rerank` | Workbench-native global reranker test/API using Knowledge Defaults |
| `GET/POST/PATCH/DELETE /api/knowledge/bases` | Knowledge Base CRUD, aliases, display metadata, and per-KB defaults |
| `GET/POST /api/knowledge/bases/{id}/sources` | source listing and pasted/text attachment source creation |
| `GET/POST /api/knowledge/bases/{id}/origins` plus `GET/PATCH/DELETE /api/knowledge/origins/{id}` | managed origin records under safe `data/knowledge/origins` folders |
| `POST /api/knowledge/origins/{id}/scan` | lightweight managed-origin metadata/status scan only |
| `POST /api/knowledge/origins/{id}/import` | explicit indexing/reindexing for new or changed origin files |
| `GET/DELETE /api/knowledge/sources/{id}` plus `POST /api/knowledge/sources/{id}/reindex` | source inspection, delete, and explicit reindex actions |
| `GET /api/knowledge/chunks/{id}` | chunk inspection for context/snippet UI without vectors or full source originals |
| `POST /api/knowledge/search` | explicit retrieval search over selected or session-bound KBs |
| `GET/PATCH /api/sessions/{id}/knowledge-bases` | ordered session KB bindings for Context Sources UI and runtime injection |
| `knowledge` Capability / `/kb-search` | thin wrapper over core list/stats/search for manual debugging |

These APIs are Workbench JSON APIs. They are not provider tool/function schemas
and do not imply automatic download, background indexing, or Capability-owned
retrieval backends.

## Embedding Model Profiles

Embedding Model Profiles bind a user-named profile to a local embedding model
path and instructions.

The Settings UI exposes them under Settings -> Models -> Embedding Model
Profiles. Settings -> Knowledge keeps Knowledge Defaults and Knowledge Bases;
Knowledge Base configuration still selects an Embedding Model Profile.

- `model_path` must be relative to `data/models`.
- Embedding profiles use `embeddings/<folder>`.
- Reranker settings use `rerankers/<folder>`.
- Absolute paths and `..` segments are rejected.
- `purpose` is `query` or `document`.
- Query and document instructions are profile fields applied by the API.
- Dimensions are detected from generated vectors and stored/displayed as compact
  metadata.
- Normalization follows the profile/default behavior and is reused by retrieval
  and Intent Routing.

Intent Routing may reference an existing enabled Embedding Model Profile, but it
does not own profiles, create profiles, download models, or persist route
candidate embeddings.

## Data Ownership

- `kb_origins` owns managed origin configuration, optional chunk profile
  override data stored in the legacy `default_chunk_profile` field, and
  scan/import timestamps.
- `kb_sources` owns source metadata and local source references, including
  origin relative paths, virtual folder grouping, file status, and compact
  effective profile fields. It does not store full pasted source text.
- `kb_chunks` owns indexed chunk content, offsets, and compact metadata.
- `kb_embeddings` owns embedding snapshots and float32 vector BLOBs.
- `kb_chunk_fts` owns FTS5/BM25 keyword-search rows.

Pasted source originals are stored as text files under `data/knowledge/sources`.
Full source originals are not stored in SQLite. Deleting a source deletes its
derived chunks, embeddings, and FTS rows without deleting the original
attachment.

## Managed Origins

Managed origin directories are safe relative folders under:

```text
data/knowledge/origins/<origin_folder>/
```

The origin folder may be nested, but it must not be absolute, contain traversal,
empty segments, or backslashes. Resolved roots must stay inside
`data/knowledge/origins`.

Scan and import are separate operations:

- Scan validates paths, walks supported text files, compares mtime/size/hash,
  and records statuses such as `new`, `changed`, `missing`, `failed`, or
  `ready`.
- Scan does not parse, chunk, embed, write chunks, write embeddings, write FTS
  rows, delete old derived indexes, or change retrieval-visible indexes.
- Import/Reindex is the explicit heavy action that indexes new or changed files
  through the normal source indexer.
- Origin chunk profile override is optional. When set, it overrides the
  Knowledge Base default for files under that origin unless frontmatter or a
  source/import override is present. When unset, files use the Knowledge Base
  default.
- Pasted text and text attachment imports may set a one-time source/import
  chunk profile override. No override means the source uses the origin override
  when applicable, otherwise the Knowledge Base default.
- There is no file watcher, scheduled scan, automatic sync, background reindex,
  or chat-time scan/reindex.
- Missing files keep old derived indexes until the user deletes the source or
  deletes the origin.
- Deleting an origin removes origin source rows and derived chunks, embeddings,
  and FTS rows from that KB, but never deletes disk files.

Folder suggestion APIs list directory names only; they do not read file
contents, scan, index, or create sources.

## Markdown Chunk Profiles

Markdown source indexing supports:

- `plain_text`
- `markdown_document`
- `markdown_collection`
- `markdown_auto`

Each Knowledge Base owns a concrete `default_chunk_profile`. New Knowledge
Bases default to `markdown_auto`. Legacy Knowledge Bases with an empty or
missing default use `markdown_auto` effectively and may write that value back
when saved through the normal settings flow. The old Knowledge Defaults
`default_chunk_profile` field may still be read for compatibility, but it does
not participate in profile resolution.

Profile resolution precedence is:

1. frontmatter `chunk_profile`.
2. source/import chunk profile override for pasted text or text attachments.
3. origin chunk profile override stored as origin `default_chunk_profile`.
4. Knowledge Base `default_chunk_profile`.
5. `markdown_auto`.
6. `markdown_document` fallback.

Changing an origin override or KB default profile marks affected indexed
sources as needing reindex and does not change existing chunks or embeddings.
Changing the legacy Knowledge Defaults profile field does not affect profile
resolution and must not mark sources for reindex.

The deterministic Markdown parser reads simple frontmatter, ATX headings `#`
through `######`, and ignores headings inside fenced code blocks. Per-chunk
metadata is compact and may include `chunk_title`, `document_title`,
`entity_type`, `heading_path`, line/character offsets,
`chunk_profile_requested`, `chunk_profile_effective`,
`chunk_profile_confidence`, `profile_source`, `entity_level`, `title_source`,
and `type_source`.

`chunk_title` is the retrieval-facing title used in the embedding `Title:` line.
It is not Semantic Router metadata and not session title metadata.
`markdown_document` uses the document title for all chunks.
`markdown_collection` uses entity headings as chunk titles and maps parent
category headings to compact entity types. `markdown_auto` is deterministic and
falls back to `markdown_document` on low confidence or ambiguity.

Markdown chunking skips sections whose content is only one or more heading
lines. Parent headings with no direct body are not emitted as standalone chunks,
but they remain in `heading_path` metadata for child chunks. Overflow splitting
prefers paragraph, line, sentence, and whitespace boundaries before hard
character cuts. Existing indexed sources keep their current chunks until the
user explicitly reindexes or imports them again.

## Retrieval

`POST /api/knowledge/search` accepts a non-empty query and either explicit
`knowledge_base_ids` or a `session_id`; explicit KB ids win. Search uses only
enabled KBs.

Retrieval pipeline:

- group vector search by `embedding_model_profile_id`.
- embed one query per profile group with `purpose=query`.
- search only matching model-profile vectors.
- run FTS5/BM25 across selected KBs.
- dedupe candidates by chunk id.
- merge vector and keyword candidates with RRF.
- optionally run the configured global reranker once over the merged set.
- apply quality filtering.
- apply per-source and per-KB chunk limits.
- trim by top-k and context budget.

Keyword search sanitizes user queries before FTS5 `MATCH`; unsupported FTS
syntax is treated as search text or skipped with a compact warning.

Vector scores from different embedding profiles are not compared directly. If
reranking is disabled or fails, results keep RRF order and debug warnings record
the reason. `min_score_threshold` applies to rerank score when reranking was
used, otherwise to RRF score.

Query expansion is disabled by default. When enabled, retrieval generates short
variants from the original query through the current LLM runtime, searches the
original query plus variants through vector and keyword branches, dedupes during
RRF merge, and falls back to the original query with a warning if expansion
fails. Normal run-step metadata must not expose full expanded query text.

## Session Bindings

Session Knowledge Base binding APIs preserve user-defined order for the UI and
future extension points. Binding order does not control retrieval ranking.
Retrieval ranking is controlled by the retrieval pipeline.

The Context Sources modal uses existing session binding APIs. It is not a new
Capability, slash command, provider tool schema, or runtime injection protocol.

## Runtime Injection

Prompt Agents default to Knowledge enabled. During the `Building context` step,
after normal `context_policy` rendering and after prompt/action instructions are
resolved, runtime appends system-context blocks in this order:

```text
Core Memory -> Worldbook -> Retrieved Knowledge -> conversation context -> current user message
```

Knowledge normally searches active session KB bindings with the current user
message text. Intent Routing may supply a per-run temporary KB list and query
override for high-confidence `knowledge_query`; that override affects only the
current run and does not persist bindings or ranking changes.

Knowledge results render as a `# Retrieved Knowledge` system-context block using
Knowledge Defaults instruction/template settings. If the Agent has no system
message, runtime creates one.
Knowledge citation UI uses the compact `snippet_refs` metadata and may coexist
with Web citation UI from Prompt Agent Web Context. `[K#]` citations continue to
resolve through Knowledge chunk APIs, while `[W#]` citations resolve only from
compact `web_context.source_refs` metadata. Web citations do not change
Knowledge retrieval, indexing, or snippet contracts.
Knowledge citation badges may display a readable title from existing compact
snippet metadata, preferring source or snippet title/path/heading-style fields
when present and falling back to the `K#` label. This is a render-time display
choice only and does not change retrieval, injection, chunk fetch behavior, or
the raw `[K#]` markdown token.

Script Agents with `llm` default to session Knowledge disabled. If settings or
Agent overrides enable it, `ctx.llm.text`, `ctx.llm.json`, `ctx.llm.stream`,
`ctx.llm.stream_to_output`, and chat-backed `ctx.llm.generate` append enabled
Core Memory, Worldbook, and Retrieved Knowledge blocks to the call's system
context. Direct prompt-backed `ctx.llm.generate` prepends rendered blocks.

Automatic injection does not run for session title generation, command result
context, Knowledge query expansion, embedding generation, reranking,
`/kb-search`, form JSON/recipe JSON, or non-LLM Script Agents. Failures are
best-effort warnings and do not fail the main LLM call.

Agent override `runtime.knowledge_context_mode` is tri-state:

- `use_default`
- `enabled`
- `disabled`

Effective defaults:

- Prompt Agent: `use_default` means enabled.
- Script Agent with `llm`: `use_default` means disabled.
- Other Agents: disabled and no Knowledge override UI.

## Metadata Compactness

Run and message metadata may store compact refs, counts, truncated query text,
injection/skipped state, public ids, scores, and warnings. They must not store:

- full snippets outside explicit chunk refs.
- full source originals.
- vectors or vector blobs.
- rendered context blocks.
- full Core Memory text.
- full Worldbook entry content.
- full expanded query text.

Chat context inspection fetches current content on demand using compact refs,
such as chunk ids or Worldbook entry ids. Edited or deleted user-owned content
should be reflected at inspection time rather than read from old snapshots.

## Knowledge Capability

The `knowledge` Capability is a thin wrapper around core Knowledge services.

It may expose:

- `list_bases`
- `stats`
- `search`
- `/kb-search`

`/kb-search <query>` routes through the normal slash command path, creates a
command run, searches active KBs for the current session, and returns JSON with
query/results/debug data. It does not call Prompt Agents, call an LLM, create an
Agent run, or participate in automatic context injection.

The Capability must not reimplement retrieval algorithms, indexing, embedding,
reranking, model downloads, local model backends, automatic injection, or
Knowledge storage ownership.

## Intent Routing Interaction

Knowledge Base aliases are comma-separated data on Knowledge Base records. They
are used for Intent Routing `kb_hint` matching and semantic candidates alongside
enabled KB names and descriptions.

The semantic router may use KB names, aliases, and descriptions as candidates.
Intent Routing temporary overrides affect only the current run's automatic
Knowledge retrieval. They must not mutate session KB bindings, Context Sources,
retrieval ranking, indexing, or Knowledge Base configuration.
