"""Hybrid knowledge retrieval with deterministic RRF fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.keyword_search import search_keywords
from ai_workbench.core.vector_store import search_vectors
from ai_workbench.core.rerank import RERANK_FALLBACK_KEY


@dataclass
class RetrievalCandidate:
    chunk_id: str
    knowledge_base_id: str
    source_id: str
    title: str
    heading_path: str
    content: str
    vector_score: float | None = None
    vector_rank: int | None = None
    keyword_score: float | None = None
    keyword_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


def rrf_merge(vector_candidates: list[RetrievalCandidate], keyword_candidates: list[RetrievalCandidate], *, rrf_k: int = 60) -> list[RetrievalCandidate]:
    merged: dict[str, RetrievalCandidate] = {}
    for item in vector_candidates:
        target=merged.setdefault(item.chunk_id,item); target.vector_score=item.vector_score; target.vector_rank=item.vector_rank
        if item.vector_rank is not None: target.rrf_score += 1/(rrf_k+item.vector_rank)
    for item in keyword_candidates:
        target=merged.setdefault(item.chunk_id,item); target.keyword_score=item.keyword_score; target.keyword_rank=item.keyword_rank
        if item.keyword_rank is not None: target.rrf_score += 1/(rrf_k+item.keyword_rank)
    return sorted(merged.values(), key=lambda item:item.rrf_score, reverse=True)


def search_knowledge(*, engine: Any, knowledge_store: Any, model_backend: Any, query: str, knowledge_base_ids: list[str] | None = None, session_id: str | None = None, top_k: int | None = None, max_context_chars: int | None = None, include_debug: bool = False, min_score_threshold: float | None = None, max_chunks_per_source: int | None = None, max_chunks_per_knowledge_base: int | None = None, provider_profile_store: Any | None = None, repo_root: Any | None = None, **_ignored: Any) -> dict[str, Any]:
    settings=knowledge_store.get_settings(); warnings=[]
    ids=list(dict.fromkeys(knowledge_base_ids or [b.knowledge_base_id for b in knowledge_store.list_session_bindings(session_id or "") if b.enabled]))
    if not ids:
        return _response(
            query,
            [],
            warnings,
            include_debug,
            rerank_fallback=False,
            reranker_enabled=bool(settings.reranker_enabled),
        )
    bases=[knowledge_store.get_knowledge_base(item) for item in ids]
    bases=[item for item in bases if item.enabled]
    vector=[]; keyword=[]
    profiles={}
    for base in bases:
        try: profiles[base.embedding_model_profile_id]=knowledge_store.get_embedding_profile(base.embedding_model_profile_id)
        except KeyError: warnings.append(f"Embedding profile not found: {base.embedding_model_profile_id}")
    for profile_id, profile in profiles.items():
        group=[base.id for base in bases if base.embedding_model_profile_id==profile_id]
        try:
            embedded=embed_texts(backend=model_backend,profile=profile,texts=[query],purpose="query",device=settings.local_model_device,provider_profile_store=provider_profile_store,repo_root=repo_root)
            candidate_k = max((int(base.vector_candidate_k_override or settings.default_vector_candidate_k) for base in bases if base.id in group), default=settings.default_vector_candidate_k)
            if engine is not None:
                found, extra=search_vectors(engine=engine,query_vector=embedded["vectors"][0],embedding_model_profile_id=profile.id,knowledge_base_ids=group,top_k=candidate_k); warnings.extend(extra); vector.extend(_vector(item) for item in found)
            else:
                vector.extend(_memory_vector_candidates(knowledge_store, embedded["vectors"][0], group, profile.id, candidate_k))
        except Exception as exc: warnings.append(f"Vector search unavailable: {exc}")
    if settings.hybrid_search_enabled:
        try:
            candidate_k = max((int(base.keyword_candidate_k_override or settings.default_keyword_candidate_k) for base in bases), default=settings.default_keyword_candidate_k)
            if engine is not None:
                found,extra=search_keywords(engine=engine,query=query,knowledge_base_ids=[base.id for base in bases],top_k=candidate_k); warnings.extend(extra); keyword.extend(_keyword(item) for item in found)
            else:
                keyword.extend(_memory_keyword_candidates(knowledge_store, query, [base.id for base in bases], candidate_k))
        except Exception as exc: warnings.append(f"Keyword search unavailable: {exc}")
    merged=rrf_merge(vector,keyword,rrf_k=settings.rrf_k)
    limit=top_k or max((int(base.final_top_k_override or settings.default_final_top_k) for base in bases), default=settings.default_final_top_k)
    max_chars=max_context_chars or max((int(base.max_context_chars_override or settings.default_max_context_chars) for base in bases), default=settings.default_max_context_chars)
    results=[]; source_counts={}; kb_counts={}; used=0
    threshold=min_score_threshold if min_score_threshold is not None else settings.min_score_threshold if settings.min_score_threshold is not None else settings.default_min_score
    for item in merged:
        if threshold is not None and item.rrf_score < threshold: continue
        source_counts[item.source_id]=source_counts.get(item.source_id,0)+1; kb_counts[item.knowledge_base_id]=kb_counts.get(item.knowledge_base_id,0)+1
        source_limit = max_chunks_per_source if max_chunks_per_source is not None else settings.retrieval_max_chunks_per_source
        kb_limit = max_chunks_per_knowledge_base if max_chunks_per_knowledge_base is not None else settings.retrieval_max_chunks_per_knowledge_base
        if source_limit and source_counts[item.source_id]>source_limit: continue
        if kb_limit and kb_counts[item.knowledge_base_id]>kb_limit: continue
        text=item.content; remaining=max_chars-used; truncated=len(text)>remaining
        if remaining<=0: break
        text=text[:remaining]; used+=len(text)
        results.append({"chunk_id":item.chunk_id,"knowledge_base_id":item.knowledge_base_id,"source_id":item.source_id,"title":item.title,"heading_path":item.heading_path,"content":text,"truncated":truncated,"vector_score":item.vector_score,"vector_rank":item.vector_rank,"keyword_score":item.keyword_score,"keyword_rank":item.keyword_rank,"rrf_score":item.rrf_score,"rerank_score":None})
        if len(results)>=limit: break
    # A fallback is meaningful only when there are candidates that would have
    # been reranked. Empty searches should not claim that reranking failed.
    rerank_fallback = bool(settings.reranker_enabled and results)
    if settings.reranker_enabled and results:
        if settings.reranker_model_profile_id:
            warnings.append("RERANK_FALLBACK: configured reranker is not available in Phase 1; using RRF order.")
        else:
            warnings.append("RERANK_FALLBACK: no reranker model is configured; using RRF order.")
    return _response(
        query,
        results,
        warnings,
        include_debug,
        rerank_fallback=rerank_fallback,
        reranker_enabled=bool(settings.reranker_enabled),
    )


def _vector(item: Any) -> RetrievalCandidate: return RetrievalCandidate(item.chunk_id,item.knowledge_base_id,item.source_id,item.title,item.heading_path,item.content,item.vector_score,item.vector_rank)
def _keyword(item: Any) -> RetrievalCandidate: return RetrievalCandidate(item.chunk_id,item.knowledge_base_id,item.source_id,item.title,item.heading_path,item.content,keyword_score=item.keyword_score,keyword_rank=item.keyword_rank)


def _memory_vector_candidates(store: Any, query_vector: list[float], knowledge_base_ids: list[str], profile_id: str, top_k: int) -> list[RetrievalCandidate]:
    rows: list[RetrievalCandidate] = []
    sources = getattr(store, "_sources", {})
    chunks_by_source = getattr(store, "_chunks", {})
    vectors_by_source = getattr(store, "_vectors", {})
    for source_id, source in sources.items():
        if source.knowledge_base_id not in knowledge_base_ids or source.status != "indexed":
            continue
        chunks = chunks_by_source.get(source_id, [])
        vectors = vectors_by_source.get(source_id, [])
        for index, vector in enumerate(vectors):
            if len(vector) != len(query_vector):
                continue
            chunk = chunks[index] if index < len(chunks) else None
            if chunk is None:
                continue
            chunk_id = str(getattr(chunk, "id", "") or f"{source_id}:{index}")
            rows.append(RetrievalCandidate(chunk_id, source.knowledge_base_id, source_id, source.title, chunk.heading_path, chunk.content, vector_score=sum(float(a) * float(b) for a, b in zip(query_vector, vector))))
    rows.sort(key=lambda item: item.vector_score or 0.0, reverse=True)
    for index, item in enumerate(rows[:top_k], start=1):
        item.vector_rank = index
    return rows[:top_k]


def _memory_keyword_candidates(store: Any, query: str, knowledge_base_ids: list[str], top_k: int) -> list[RetrievalCandidate]:
    terms = {token.casefold() for token in query.split() if token.strip()}
    rows: list[RetrievalCandidate] = []
    sources = getattr(store, "_sources", {})
    for source_id, source in sources.items():
        if source.knowledge_base_id not in knowledge_base_ids or source.status != "indexed":
            continue
        for index, chunk in enumerate(getattr(store, "_chunks", {}).get(source_id, [])):
            haystack = str(chunk.content).casefold()
            score = float(sum(haystack.count(term) for term in terms))
            if score <= 0:
                continue
            chunk_id = str(getattr(chunk, "id", "") or f"{source_id}:{index}")
            rows.append(RetrievalCandidate(chunk_id, source.knowledge_base_id, source_id, source.title, chunk.heading_path, chunk.content, keyword_score=-score))
    rows.sort(key=lambda item: item.keyword_score or 0.0)
    for index, item in enumerate(rows[:top_k], start=1):
        item.keyword_rank = index
    return rows[:top_k]
def _response(
    query: str,
    results: list[dict[str, Any]],
    warnings: list[str],
    include_debug: bool,
    *,
    rerank_fallback: bool = False,
    reranker_enabled: bool = False,
) -> dict[str, Any]:
    rerank_meta = {
        RERANK_FALLBACK_KEY: rerank_fallback,
        "reranker_used": False,
        "reranker_enabled": reranker_enabled,
    }
    payload = {"query": query, "results": results, "metadata": rerank_meta}
    if include_debug:
        payload["debug"] = {
            "warnings": warnings,
            "merged_candidate_count": len(results),
            "reranker_used": False,
            "reranker_failed": rerank_fallback,
            **rerank_meta,
        }
    return payload
