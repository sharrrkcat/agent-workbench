# Task: Knowledge / RAG

Read [Knowledge](../contracts/knowledge.md),
[chat/context](../contracts/chat-context.md) and [models](../contracts/models.md).

## Source map

Core modules under ai_workbench/core/ include knowledge_*, retrieval.py,
keyword_search.py and vector_store.py; models/ owns preprocessing and execution.
Persistence is in ai_workbench/db/stores.py and HTTP routes are in
ai_workbench/api/routes/knowledge.py. Frontend API/types use Knowledge domain
modules. Under frontend/src/components/settings/, KnowledgePanel.tsx composes
knowledge/ and shared resources/ components.

## Verification

Start with tests/test_phase2a_knowledge.py and tests/test_resource_management.py.
Cover indexing, partial invalidation/rebuild, attachment ownership, binding
resolution, deterministic RRF and rerank failure diagnostics in memory and SQLite.
frontend/scripts/test-resource-management.mjs and frontend/tests/resource-management.spec.ts
cover source uploads/retries, previews, drafts and search. Run the full backend
suite and frontend tests/build using the [README](../../README.md#verification).
