from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.keyword_search import KeywordSearchResult, search_keywords
from ai_workbench.core.knowledge_models import KnowledgeModelError
from ai_workbench.core.knowledge_settings import KnowledgeSettings
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase
from ai_workbench.core.rerank import rerank_documents
from ai_workbench.core.vector_store import VectorSearchResult, search_vectors


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


def search_knowledge(
    *,
    engine: Any,
    knowledge_store: Any,
    model_backend: Any,
    query: str,
    knowledge_base_ids: list[str] | None,
    session_id: str | None,
    top_k: int | None,
    max_context_chars: int | None,
    include_debug: bool,
) -> dict[str, Any]:
    settings = knowledge_store.get_settings()
    debug: dict[str, Any] = {
        "embedding_groups": [],
        "keyword_candidate_count": 0,
        "merged_candidate_count": 0,
        "reranker_used": False,
        "reranker_failed": False,
        "warnings": [],
    }
    selected_kbs = _resolve_selected_kbs(knowledge_store, knowledge_base_ids, session_id, debug["warnings"])
    selected_kbs = [kb for kb in selected_kbs if kb.enabled]
    if not selected_kbs:
        debug["warnings"].append("No enabled knowledge bases were selected for search.")
        return _response(query, [], debug, include_debug)

    profiles = _load_profiles(knowledge_store, selected_kbs, debug["warnings"])
    vector_candidates: list[RetrievalCandidate] = []
    for profile_id, group_kbs in _group_kbs_by_profile(selected_kbs).items():
        profile = profiles.get(profile_id)
        if profile is None or not profile.enabled:
            debug["warnings"].append(f"Skipped embedding group {profile_id} because the embedding profile is missing or disabled.")
            continue
        candidate_k = _candidate_k(settings.default_vector_candidate_k, [kb.vector_candidate_k_override for kb in group_kbs])
        embedding_result = embed_texts(
            backend=model_backend,
            profile=profile,
            texts=[query],
            purpose="query",
            device=settings.local_model_device,
        )
        results, warnings = search_vectors(
            engine=engine,
            query_vector=embedding_result["vectors"][0],
            embedding_model_profile_id=profile.id,
            knowledge_base_ids=[kb.id for kb in group_kbs],
            top_k=candidate_k,
        )
        debug["warnings"].extend(warnings)
        debug["embedding_groups"].append(
            {
                "embedding_model_profile_id": profile.id,
                "knowledge_base_ids": [kb.id for kb in group_kbs],
                "candidate_count": len(results),
            }
        )
        vector_candidates.extend(_from_vector(result) for result in results)

    keyword_candidates: list[RetrievalCandidate] = []
    if settings.hybrid_search_enabled:
        keyword_k = _candidate_k(settings.default_keyword_candidate_k, [kb.keyword_candidate_k_override for kb in selected_kbs])
        keyword_results, keyword_warnings = search_keywords(
            engine=engine,
            query=query,
            knowledge_base_ids=[kb.id for kb in selected_kbs],
            top_k=keyword_k,
        )
        debug["warnings"].extend(keyword_warnings)
        debug["keyword_candidate_count"] = len(keyword_results)
        keyword_candidates = [_from_keyword(result) for result in keyword_results]

    merged = rrf_merge(vector_candidates, keyword_candidates, rrf_k=settings.rrf_k)
    debug["merged_candidate_count"] = len(merged)
    merged_limit = max(settings.reranker_candidate_limit, top_k or settings.default_final_top_k)
    merged = merged[:merged_limit]
    ranked = _rerank_candidates(
        backend=model_backend,
        settings=settings,
        query=query,
        candidates=merged,
        debug=debug,
    )
    final_top_k = top_k or _candidate_k(settings.default_final_top_k, [kb.final_top_k_override for kb in selected_kbs])
    final_max_chars = max_context_chars or _candidate_k(settings.default_max_context_chars, [kb.max_context_chars_override for kb in selected_kbs])
    return _response(query, _trim_results(ranked, final_top_k, final_max_chars), debug, include_debug)


def rrf_merge(
    vector_candidates: list[RetrievalCandidate],
    keyword_candidates: list[RetrievalCandidate],
    *,
    rrf_k: int = 60,
) -> list[RetrievalCandidate]:
    merged: dict[str, RetrievalCandidate] = {}
    for candidate in vector_candidates:
        target = merged.setdefault(candidate.chunk_id, candidate)
        target.vector_score = candidate.vector_score
        target.vector_rank = candidate.vector_rank
        if candidate.vector_rank is not None:
            target.rrf_score += 1.0 / (rrf_k + candidate.vector_rank)
    for candidate in keyword_candidates:
        target = merged.get(candidate.chunk_id)
        if target is None:
            target = candidate
            merged[candidate.chunk_id] = target
        target.keyword_score = candidate.keyword_score
        target.keyword_rank = candidate.keyword_rank
        if candidate.keyword_rank is not None:
            target.rrf_score += 1.0 / (rrf_k + candidate.keyword_rank)
    return sorted(merged.values(), key=lambda item: item.rrf_score, reverse=True)


def _resolve_selected_kbs(
    knowledge_store: Any,
    knowledge_base_ids: list[str] | None,
    session_id: str | None,
    warnings: list[str],
) -> list[KnowledgeBase]:
    if knowledge_base_ids:
        seen: set[str] = set()
        result: list[KnowledgeBase] = []
        for knowledge_base_id in knowledge_base_ids:
            if knowledge_base_id in seen:
                continue
            seen.add(knowledge_base_id)
            result.append(knowledge_store.get_knowledge_base(knowledge_base_id))
        return result
    if session_id:
        bindings = knowledge_store.list_session_bindings(session_id)
        return [binding.knowledge_base or knowledge_store.get_knowledge_base(binding.knowledge_base_id) for binding in bindings if binding.enabled]
    warnings.append("No knowledge_base_ids or session_id provided.")
    return []


def _load_profiles(knowledge_store: Any, kbs: list[KnowledgeBase], warnings: list[str]) -> dict[str, EmbeddingModelProfile]:
    profiles: dict[str, EmbeddingModelProfile] = {}
    for profile_id in {kb.embedding_model_profile_id for kb in kbs}:
        try:
            profiles[profile_id] = knowledge_store.get_embedding_profile(profile_id)
        except KeyError:
            warnings.append(f"Embedding profile not found for selected KB group: {profile_id}.")
    return profiles


def _group_kbs_by_profile(kbs: list[KnowledgeBase]) -> dict[str, list[KnowledgeBase]]:
    groups: dict[str, list[KnowledgeBase]] = {}
    for kb in kbs:
        groups.setdefault(kb.embedding_model_profile_id, []).append(kb)
    return groups


def _candidate_k(default: int, overrides: list[int | None]) -> int:
    values = [value for value in overrides if value is not None]
    return max(values) if values else default


def _from_vector(result: VectorSearchResult) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=result.chunk_id,
        knowledge_base_id=result.knowledge_base_id,
        source_id=result.source_id,
        title=result.title,
        heading_path=result.heading_path,
        content=result.content,
        vector_score=result.vector_score,
        vector_rank=result.vector_rank,
    )


def _from_keyword(result: KeywordSearchResult) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=result.chunk_id,
        knowledge_base_id=result.knowledge_base_id,
        source_id=result.source_id,
        title=result.title,
        heading_path=result.heading_path,
        content=result.content,
        keyword_score=result.keyword_score,
        keyword_rank=result.keyword_rank,
    )


def _rerank_candidates(
    *,
    backend: Any,
    settings: KnowledgeSettings,
    query: str,
    candidates: list[RetrievalCandidate],
    debug: dict[str, Any],
) -> list[RetrievalCandidate]:
    if not settings.reranker_enabled:
        return candidates
    if not settings.reranker_model_path:
        debug["warnings"].append("Reranker is enabled but reranker_model_path is not configured.")
        return candidates
    limited = candidates[: settings.reranker_candidate_limit]
    documents = [{"id": candidate.chunk_id, "text": candidate.content} for candidate in limited]
    try:
        response = rerank_documents(
            backend=backend,
            model_path=settings.reranker_model_path,
            query=query,
            documents=documents,
            device=settings.local_model_device,
        )
        scores = {str(item["id"]): float(item["score"]) for item in response.get("results", [])}
        for candidate in limited:
            candidate.rerank_score = scores.get(candidate.chunk_id)
        debug["reranker_used"] = True
        return sorted(limited, key=lambda item: (item.rerank_score is not None, item.rerank_score or float("-inf"), item.rrf_score), reverse=True)
    except (KnowledgeModelError, Exception) as exc:
        debug["reranker_failed"] = True
        debug["warnings"].append(f"Reranker failed; using RRF order: {exc}")
        return candidates


def _trim_results(candidates: list[RetrievalCandidate], top_k: int, max_context_chars: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    used_chars = 0
    for candidate in candidates:
        if len(results) >= top_k:
            break
        remaining = max_context_chars - used_chars
        if remaining <= 0:
            break
        content = candidate.content
        truncated = False
        if len(content) > remaining:
            content = content[:remaining]
            truncated = True
        used_chars += len(content)
        results.append(
            {
                "rank": len(results) + 1,
                "chunk_id": candidate.chunk_id,
                "knowledge_base_id": candidate.knowledge_base_id,
                "source_id": candidate.source_id,
                "title": candidate.title,
                "heading_path": candidate.heading_path,
                "content": content,
                "truncated": truncated,
                "vector_rank": candidate.vector_rank,
                "vector_score": candidate.vector_score,
                "keyword_rank": candidate.keyword_rank,
                "keyword_score": candidate.keyword_score,
                "rrf_score": candidate.rrf_score,
                "rerank_score": candidate.rerank_score,
            }
        )
    return results


def _response(query: str, results: list[dict[str, Any]], debug: dict[str, Any], include_debug: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "results": results}
    if include_debug:
        payload["debug"] = debug
    return payload
