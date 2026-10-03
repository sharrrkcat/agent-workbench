from __future__ import annotations

from array import array
from dataclasses import dataclass
from collections import Counter
from heapq import nlargest
import math
from typing import Any

from sqlalchemy import text, bindparam
from ai_workbench.core.models.schema import EmbeddingSimilarity


def embedding_score(left: list[float], right: list[float], similarity: EmbeddingSimilarity) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    if similarity == "dot":
        return dot
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0


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


@dataclass
class VectorRank:
    score: float
    chunk_id: str

    def __lt__(self, other):
        return self.score < other.score if self.score != other.score else self.chunk_id > other.chunk_id


def search_vectors(
    *,
    engine: Any,
    query_vector: list[float],
    embedding_model_profile_id: str,
    knowledge_base_ids: list[str],
    top_k: int,
    similarity: EmbeddingSimilarity = "dot",
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
    skipped = Counter()
    examples: list[str] = []
    query_dimension = len(query_vector)
    with engine.connect() as connection:
        def ranks():
            with connection.execute(statement, params) as cursor:
                for batch in cursor.mappings().partitions(256):
                    for row in batch:
                        reason = ("dimension" if int(row["embedding_dimension"]) != query_dimension else
                                  "BLOB dimension" if len(row["vector_blob"]) != query_dimension * 4 else None)
                        if reason:
                            skipped[reason] += 1
                            if len(examples) < 10:
                                examples.append(f"{row['chunk_id']} ({reason})")
                            continue
                        yield VectorRank(embedding_score(query_vector, _vector_from_blob(row["vector_blob"]), similarity), str(row["chunk_id"]))
        best = nlargest(top_k, ranks())
        winners = text("""SELECT c.id, c.knowledge_base_id, c.source_id, src.title, c.heading_path, c.content
                          FROM kb_chunks c JOIN kb_sources src ON src.id = c.source_id WHERE c.id IN :ids""").bindparams(bindparam("ids", expanding=True))
        details = {row["id"]: row for row in connection.execute(winners, {"ids": [item.chunk_id for item in best]}).mappings()}
        results = [VectorSearchResult(item.chunk_id, details[item.chunk_id]["knowledge_base_id"],
            details[item.chunk_id]["source_id"], details[item.chunk_id]["title"] or "", details[item.chunk_id]["heading_path"] or "",
            details[item.chunk_id]["content"] or "", item.score, index) for index, item in enumerate(best, start=1)]
    if skipped:
        warnings.append("Skipped vectors: " + ", ".join(f"{reason}={count}" for reason, count in skipped.items())
                        + "; examples: " + ", ".join(examples))
    return results, warnings


def _vector_from_blob(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector
