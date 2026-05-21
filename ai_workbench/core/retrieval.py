from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.keyword_search import KeywordSearchResult, search_keywords
from ai_workbench.core.knowledge_models import KnowledgeModelError, safe_unload_embedding_model, safe_unload_reranker_model
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
    min_score_threshold: float | None = None,
    max_chunks_per_source: int | None = None,
    max_chunks_per_knowledge_base: int | None = None,
    expand_query: bool | None = None,
    query_expander: Callable[[str, int, str], list[str]] | None = None,
    provider_profile_store: Any | None = None,
    repo_root: Any | None = None,
) -> dict[str, Any]:
    settings = knowledge_store.get_settings()
    debug: dict[str, Any] = {
        "embedding_groups": [],
        "keyword_candidate_count": 0,
        "merged_candidate_count": 0,
        "reranker_used": False,
        "reranker_failed": False,
        "query_expansion_enabled": bool(settings.query_expansion_enabled if expand_query is None else expand_query),
        "query_expansion_used": False,
        "expanded_query_count": 1,
        "expansion_failed": False,
        "before_filter_count": 0,
        "min_score_filtered_count": 0,
        "per_source_filtered_count": 0,
        "per_kb_filtered_count": 0,
        "final_result_count": 0,
        "warnings": [],
    }
    selected_kbs = _resolve_selected_kbs(knowledge_store, knowledge_base_ids, session_id, debug["warnings"])
    selected_kbs = [kb for kb in selected_kbs if kb.enabled]
    if not selected_kbs:
        debug["warnings"].append("No enabled knowledge bases were selected for search.")
        return _response(query, [], debug, include_debug)

    queries = _expanded_queries(query, settings=settings, enabled=debug["query_expansion_enabled"], query_expander=query_expander, debug=debug)

    profiles = _load_profiles(knowledge_store, selected_kbs, debug["warnings"])
    vector_candidates: list[RetrievalCandidate] = []
    for profile_id, group_kbs in _group_kbs_by_profile(selected_kbs).items():
        profile = profiles.get(profile_id)
        if profile is None or not profile.enabled:
            debug["warnings"].append(f"Skipped embedding group {profile_id} because the embedding profile is missing or disabled.")
            continue
        candidate_k = _candidate_k(settings.default_vector_candidate_k, [kb.vector_candidate_k_override for kb in group_kbs])
        group_count = 0
        try:
            embedding_result = embed_texts(
                backend=model_backend,
                profile=profile,
                texts=queries,
                purpose="query",
                device=settings.local_model_device,
                provider_profile_store=provider_profile_store,
                repo_root=repo_root,
            )
            for query_vector in embedding_result["vectors"]:
                results, warnings = search_vectors(
                    engine=engine,
                    query_vector=query_vector,
                    embedding_model_profile_id=profile.id,
                    knowledge_base_ids=[kb.id for kb in group_kbs],
                    top_k=candidate_k,
                )
                debug["warnings"].extend(warnings)
                group_count += len(results)
                vector_candidates.extend(_from_vector(result) for result in results)
        finally:
            if settings.unload_embedding_model_after_use:
                if profile.model_path:
                    safe_unload_embedding_model(model_backend, profile.model_path, settings.local_model_device, debug["warnings"])
        debug["embedding_groups"].append(
            {
                "embedding_model_profile_id": profile.id,
                "embedding_model_profile_name": profile.name,
                "embedding_model_profile_alias": profile.alias,
                "embedding_dimension": embedding_result.get("dimension") or profile.dimension,
                "knowledge_base_ids": [kb.id for kb in group_kbs],
                "candidate_count": group_count,
            }
        )

    keyword_candidates: list[RetrievalCandidate] = []
    if settings.hybrid_search_enabled:
        keyword_k = _candidate_k(settings.default_keyword_candidate_k, [kb.keyword_candidate_k_override for kb in selected_kbs])
        for query_text in queries:
            keyword_results, keyword_warnings = search_keywords(
                engine=engine,
                query=query_text,
                knowledge_base_ids=[kb.id for kb in selected_kbs],
                top_k=keyword_k,
            )
            debug["warnings"].extend(keyword_warnings)
            debug["keyword_candidate_count"] += len(keyword_results)
            keyword_candidates.extend(_from_keyword(result) for result in keyword_results)

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
    debug["before_filter_count"] = len(ranked)
    score_threshold = min_score_threshold if min_score_threshold is not None else (settings.min_score_threshold if settings.min_score_threshold is not None else settings.default_min_score)
    source_limit = max_chunks_per_source if max_chunks_per_source is not None else settings.retrieval_max_chunks_per_source
    kb_limit = max_chunks_per_knowledge_base if max_chunks_per_knowledge_base is not None else settings.retrieval_max_chunks_per_knowledge_base
    ranked = _apply_quality_filters(
        ranked,
        min_score_threshold=score_threshold,
        max_chunks_per_source=source_limit,
        max_chunks_per_knowledge_base=kb_limit,
        use_rerank_score=debug["reranker_used"],
        debug=debug,
    )
    final_top_k = top_k or _candidate_k(settings.default_final_top_k, [kb.final_top_k_override for kb in selected_kbs])
    final_max_chars = max_context_chars or _candidate_k(settings.default_max_context_chars, [kb.max_context_chars_override for kb in selected_kbs])
    results = _trim_results(ranked[:final_top_k], final_top_k, final_max_chars)
    debug["final_result_count"] = len(results)
    return _response(query, results, debug, include_debug)


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


def expand_query_variants(*, llm_runtime: Any, query: str, max_variants: int, prompt_template: str, model_config: dict[str, Any] | None = None) -> list[str]:
    prompt = prompt_template.format(query=query, max_variants=max_variants)
    generate = getattr(llm_runtime, "generate", None)
    chat = getattr(llm_runtime, "chat", None)
    if callable(generate):
        raw = generate(prompt, model_config=model_config or {}, stream=False)
    elif callable(chat):
        raw = chat(messages=[{"role": "user", "content": prompt}], model_config=model_config or {}, stream=False)
    else:
        raise RuntimeError("LLM runtime does not support query expansion.")
    if isinstance(raw, dict):
        raw = raw.get("text") or raw.get("content") or raw.get("message") or ""
    payload = json.loads(str(raw).strip())
    if not isinstance(payload, list):
        raise ValueError("Query expansion response must be a JSON array.")
    variants: list[str] = []
    for item in payload:
        text = str(item or "").strip()
        if text:
            variants.append(text)
    return variants


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


def _expanded_queries(
    query: str,
    *,
    settings: KnowledgeSettings,
    enabled: bool,
    query_expander: Callable[[str, int, str], list[str]] | None,
    debug: dict[str, Any],
) -> list[str]:
    if not enabled:
        return [query]
    if query_expander is None:
        debug["warnings"].append("Query expansion enabled but no LLM expander is available; using original query.")
        return [query]
    try:
        variants = query_expander(query, settings.query_expansion_max_variants, settings.query_expansion_prompt)
    except Exception as exc:
        debug["expansion_failed"] = True
        debug["warnings"].append(f"Query expansion failed; using original query: {exc}")
        return [query]
    seen = {query.strip().lower()}
    queries = [query]
    expanded: list[str] = []
    for variant in variants:
        text = str(variant or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        queries.append(text)
        expanded.append(text)
        if len(expanded) >= settings.query_expansion_max_variants:
            break
    debug["query_expansion_used"] = bool(expanded)
    debug["expanded_query_count"] = len(queries)
    debug["expanded_queries"] = expanded
    return queries


def _apply_quality_filters(
    candidates: list[RetrievalCandidate],
    *,
    min_score_threshold: float | None,
    max_chunks_per_source: int | None,
    max_chunks_per_knowledge_base: int | None,
    use_rerank_score: bool,
    debug: dict[str, Any],
) -> list[RetrievalCandidate]:
    filtered: list[RetrievalCandidate] = []
    for candidate in candidates:
        score = candidate.rerank_score if use_rerank_score else candidate.rrf_score
        if min_score_threshold is not None and (score is None or score < min_score_threshold):
            debug["min_score_filtered_count"] += 1
            continue
        filtered.append(candidate)
    if min_score_threshold is not None and debug["min_score_filtered_count"]:
        debug["warnings"].append(f"Filtered {debug['min_score_filtered_count']} candidates below min score threshold.")

    source_counts: dict[str, int] = {}
    source_limited: list[RetrievalCandidate] = []
    for candidate in filtered:
        source_counts[candidate.source_id] = source_counts.get(candidate.source_id, 0) + 1
        if max_chunks_per_source is not None and source_counts[candidate.source_id] > max_chunks_per_source:
            debug["per_source_filtered_count"] += 1
            continue
        source_limited.append(candidate)

    kb_counts: dict[str, int] = {}
    kb_limited: list[RetrievalCandidate] = []
    for candidate in source_limited:
        kb_counts[candidate.knowledge_base_id] = kb_counts.get(candidate.knowledge_base_id, 0) + 1
        if max_chunks_per_knowledge_base is not None and kb_counts[candidate.knowledge_base_id] > max_chunks_per_knowledge_base:
            debug["per_kb_filtered_count"] += 1
            continue
        kb_limited.append(candidate)
    return kb_limited


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
    if not documents:
        return candidates
    debug["reranker_input_count"] = len(documents)
    try:
        response = rerank_documents(
            backend=backend,
            model_path=settings.reranker_model_path,
            query=query,
            documents=documents,
            device=settings.local_model_device,
        )
        scores = {str(item["id"]): float(item["score"]) for item in response.get("results", [])}
        debug["reranker_output_count"] = len(scores)
        for candidate in limited:
            candidate.rerank_score = scores.get(candidate.chunk_id)
        debug["reranker_used"] = True
        return sorted(limited, key=lambda item: (item.rerank_score is not None, item.rerank_score or float("-inf"), item.rrf_score), reverse=True)
    except (KnowledgeModelError, Exception) as exc:
        debug["reranker_failed"] = True
        debug["warnings"].append(f"Reranker failed; using RRF order: {exc}")
        return candidates
    finally:
        if settings.unload_reranker_model_after_use:
            safe_unload_reranker_model(backend, settings.reranker_model_path, settings.local_model_device, debug["warnings"])


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
