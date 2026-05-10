from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from ai_workbench.core.knowledge_models import KnowledgeModelError
from ai_workbench.core.retrieval import search_knowledge


class CapabilityRuntime:
    def __init__(
        self,
        *,
        knowledge_store: Any = None,
        model_backend: Any = None,
        search_service: Callable[..., dict[str, Any]] = search_knowledge,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.model_backend = model_backend
        self.search_service = search_service

    def configure(self, *, knowledge_store: Any, model_backend: Any) -> None:
        self.knowledge_store = knowledge_store
        self.model_backend = model_backend

    def search(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        knowledge_base_ids: list[str] | None = None,
        session_id: str | None = None,
        top_k: int | None = None,
        max_context_chars: int | None = None,
        debug: bool = True,
    ) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            raise ValueError("Query is required for /kb-search.")

        store = self._knowledge_store()
        resolved_session_id = session_id or _context_session_id(context)
        resolved_kb_ids = _normalize_kb_ids(knowledge_base_ids)
        if not resolved_kb_ids and resolved_session_id and not self._active_session_kbs(store, resolved_session_id):
            return {
                "query": query,
                "results": [],
                "debug": {"warnings": ["No active knowledge bases for this session."]},
            }
        if not resolved_kb_ids and not resolved_session_id:
            raise ValueError("knowledge_base_ids or session_id is required.")

        engine = getattr(store, "engine", None)
        if engine is None:
            raise ValueError("Knowledge search requires the SQLite knowledge store.")

        try:
            return self.search_service(
                engine=engine,
                knowledge_store=store,
                model_backend=self._model_backend(),
                query=query,
                knowledge_base_ids=resolved_kb_ids,
                session_id=resolved_session_id,
                top_k=top_k,
                max_context_chars=max_context_chars,
                include_debug=debug,
            )
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        except KnowledgeModelError as exc:
            raise ValueError(exc.message) from exc

    def list_bases(self, enabled_only: bool = False, context: dict[str, Any] | None = None) -> dict[str, Any]:
        store = self._knowledge_store()
        bases = []
        for kb in store.list_knowledge_bases():
            if enabled_only and not kb.enabled:
                continue
            counts = self._counts_for_kb(kb.id)
            bases.append(
                {
                    "id": kb.id,
                    "name": kb.name,
                    "enabled": kb.enabled,
                    "index_status": kb.index_status,
                    "source_count": counts["sources"],
                    "chunk_count": counts["chunks"],
                }
            )
        return {"knowledge_bases": bases}

    def stats(self, knowledge_base_id: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        store = self._knowledge_store()
        if knowledge_base_id:
            kb = store.get_knowledge_base(knowledge_base_id)
            counts = self._counts_for_kb(kb.id)
            return {"knowledge_base_id": kb.id, "name": kb.name, **counts}

        totals = Counter()
        status_counts = Counter()
        for kb in store.list_knowledge_bases():
            counts = self._counts_for_kb(kb.id)
            totals["knowledge_bases"] += 1
            totals["sources"] += counts["sources"]
            totals["chunks"] += counts["chunks"]
            totals["embeddings"] += counts["embeddings"]
            status_counts.update(counts["source_status_counts"])
        return {
            "knowledge_bases": totals["knowledge_bases"],
            "sources": totals["sources"],
            "chunks": totals["chunks"],
            "embeddings": totals["embeddings"],
            "source_status_counts": dict(sorted(status_counts.items())),
        }

    def _active_session_kbs(self, store: Any, session_id: str) -> list[str]:
        result = []
        for binding in store.list_session_bindings(session_id):
            if not binding.enabled:
                continue
            kb = binding.knowledge_base or store.get_knowledge_base(binding.knowledge_base_id)
            if kb.enabled:
                result.append(kb.id)
        return result

    def _counts_for_kb(self, knowledge_base_id: str) -> dict[str, Any]:
        sources = self._knowledge_store().list_sources(knowledge_base_id)
        status_counts = Counter(source.status for source in sources)
        chunks = sum(source.chunks for source in sources)
        embeddings = sum(source.chunks for source in sources if source.embedding_model_profile_id)
        return {
            "sources": len(sources),
            "chunks": chunks,
            "embeddings": embeddings,
            "source_status_counts": dict(sorted(status_counts.items())),
            "indexed_sources": status_counts.get("indexed", 0),
            "failed_sources": status_counts.get("failed", 0),
        }

    def _knowledge_store(self) -> Any:
        if self.knowledge_store is None:
            raise ValueError("Knowledge store is not configured.")
        return self.knowledge_store

    def _model_backend(self) -> Any:
        if self.model_backend is None:
            raise ValueError("Knowledge model backend is not configured.")
        return self.model_backend


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()


def _context_session_id(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    session_id = context.get("session_id")
    return str(session_id) if session_id else None


def _normalize_kb_ids(value: list[str] | tuple[str, ...] | str | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        ids = [item.strip() for item in value.split(",")]
    else:
        ids = [str(item).strip() for item in value]
    ids = [item for item in ids if item]
    return ids or None
