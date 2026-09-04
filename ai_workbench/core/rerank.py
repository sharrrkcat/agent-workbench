"""Optional post-retrieval reranking boundary.

Phase 1 deliberately has no model-profile store for reranking. Retrieval is
always useful with deterministic RRF ordering; callers may provide a small
callable in a later phase, and failures are represented as metadata instead
of escaping into the chat path.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence


RERANK_FALLBACK_KEY = "rerank_fallback"


def rerank_documents(
    documents: Sequence[dict[str, Any]],
    *,
    query: str = "",
    reranker: Callable[..., Sequence[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return reranked documents and stable diagnostic metadata.

    ``reranker`` is intentionally an injected callable rather than a profile
    or registry lookup. If it is absent or raises, the original order is
    returned and ``rerank_fallback`` is true.
    """

    original = [dict(item) for item in documents]
    if reranker is None:
        return original, {RERANK_FALLBACK_KEY: True, "reranker_used": False}
    try:
        value = reranker(query=query, documents=original)
        result = [dict(item) for item in (value or ())]
        if not result:
            return original, {RERANK_FALLBACK_KEY: True, "reranker_used": False}
        return result, {RERANK_FALLBACK_KEY: False, "reranker_used": True}
    except Exception as exc:  # pragma: no cover - defensive provider boundary
        return original, {
            RERANK_FALLBACK_KEY: True,
            "reranker_used": False,
            "rerank_error": str(exc) or "reranker failed",
        }


__all__ = ["RERANK_FALLBACK_KEY", "rerank_documents"]
