from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text


@dataclass
class VectorSearchResult:
    chunk_id: str
    knowledge_base_id: str
    source_id: str
    title: str
    heading_path: str
    content: str
    vector_score: float
    vector_rank: int


def search_vectors(
    *,
    engine: Any,
    query_vector: list[float],
    embedding_model_profile_id: str,
    knowledge_base_ids: list[str],
    top_k: int,
) -> tuple[list[VectorSearchResult], list[str]]:
    if not knowledge_base_ids or top_k <= 0:
        return [], []
    warnings: list[str] = []
    placeholders = ", ".join(f":kb_{index}" for index, _ in enumerate(knowledge_base_ids))
    params: dict[str, Any] = {
        "embedding_model_profile_id": embedding_model_profile_id,
        **{f"kb_{index}": knowledge_base_id for index, knowledge_base_id in enumerate(knowledge_base_ids)},
    }
    statement = text(
        f"""
        SELECT
          e.chunk_id,
          e.knowledge_base_id,
          e.source_id,
          src.title,
          c.heading_path,
          c.content,
          e.embedding_dimension,
          e.vector_blob
        FROM kb_embeddings e
        JOIN kb_chunks c ON c.id = e.chunk_id
        JOIN kb_sources src ON src.id = e.source_id
        WHERE e.embedding_model_profile_id = :embedding_model_profile_id
          AND e.knowledge_base_id IN ({placeholders})
          AND src.status = 'indexed'
        """
    )
    scored: list[VectorSearchResult] = []
    query_dimension = len(query_vector)
    with engine.connect() as connection:
        rows = connection.execute(statement, params).mappings().all()
    for row in rows:
        if int(row["embedding_dimension"]) != query_dimension:
            warnings.append(
                f"Skipped chunk {row['chunk_id']} because vector dimension {row['embedding_dimension']} did not match query dimension {query_dimension}."
            )
            continue
        vector = _vector_from_blob(row["vector_blob"])
        if len(vector) != query_dimension:
            warnings.append(
                f"Skipped chunk {row['chunk_id']} because vector BLOB dimension {len(vector)} did not match query dimension {query_dimension}."
            )
            continue
        scored.append(
            VectorSearchResult(
                chunk_id=str(row["chunk_id"]),
                knowledge_base_id=str(row["knowledge_base_id"]),
                source_id=str(row["source_id"]),
                title=str(row["title"] or ""),
                heading_path=str(row["heading_path"] or ""),
                content=str(row["content"] or ""),
                vector_score=sum(float(left) * float(right) for left, right in zip(query_vector, vector, strict=True)),
                vector_rank=0,
            )
        )
    scored.sort(key=lambda item: item.vector_score, reverse=True)
    results = scored[:top_k]
    for index, item in enumerate(results, start=1):
        item.vector_rank = index
    return results, warnings


def _vector_from_blob(blob: bytes) -> list[float]:
    try:
        import numpy as np  # type: ignore

        return [float(value) for value in np.frombuffer(blob, dtype=np.float32).tolist()]
    except Exception:
        vector = array("f")
        vector.frombytes(blob)
        return [float(value) for value in vector.tolist()]
