from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text


@dataclass
class KeywordSearchResult:
    chunk_id: str
    knowledge_base_id: str
    source_id: str
    title: str
    heading_path: str
    content: str
    keyword_score: float
    keyword_rank: int


def search_keywords(
    *,
    engine: Any,
    query: str,
    knowledge_base_ids: list[str],
    top_k: int,
) -> tuple[list[KeywordSearchResult], list[str]]:
    if not knowledge_base_ids or top_k <= 0:
        return [], []
    warnings: list[str] = []
    raw_query = query.strip()
    sanitized_query = sanitize_fts_query(raw_query)
    for match_query, label in ((raw_query, "raw"), (sanitized_query, "sanitized")):
        if not match_query:
            continue
        try:
            return _execute_keyword_search(engine=engine, query=match_query, knowledge_base_ids=knowledge_base_ids, top_k=top_k), warnings
        except Exception as exc:
            warnings.append(f"Keyword search {label} query failed: {exc}")
            continue
    warnings.append("Keyword search returned no candidates because the query could not be parsed by FTS5.")
    return [], warnings


def sanitize_fts_query(query: str) -> str:
    tokens = re.findall(r"[\w\u3400-\u9fff\u3040-\u30ff]+", query, flags=re.UNICODE)
    return " ".join(f'"{token}"' for token in tokens)


def _execute_keyword_search(
    *,
    engine: Any,
    query: str,
    knowledge_base_ids: list[str],
    top_k: int,
) -> list[KeywordSearchResult]:
    placeholders = ", ".join(f":kb_{index}" for index, _ in enumerate(knowledge_base_ids))
    params: dict[str, Any] = {
        "query": query,
        "limit": top_k,
        **{f"kb_{index}": knowledge_base_id for index, knowledge_base_id in enumerate(knowledge_base_ids)},
    }
    statement = text(
        f"""
        SELECT
          kb_chunk_fts.chunk_id,
          kb_chunk_fts.knowledge_base_id,
          kb_chunk_fts.source_id,
          kb_chunk_fts.title,
          kb_chunk_fts.heading_path,
          kb_chunk_fts.content,
          bm25(kb_chunk_fts) AS keyword_score
        FROM kb_chunk_fts
        JOIN kb_sources src ON src.id = kb_chunk_fts.source_id
        WHERE kb_chunk_fts MATCH :query
          AND kb_chunk_fts.knowledge_base_id IN ({placeholders})
          AND src.status = 'indexed'
        ORDER BY keyword_score ASC
        LIMIT :limit
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(statement, params).mappings().all()
    results = [
        KeywordSearchResult(
            chunk_id=str(row["chunk_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"] or ""),
            heading_path=str(row["heading_path"] or ""),
            content=str(row["content"] or ""),
            keyword_score=float(row["keyword_score"]),
            keyword_rank=index,
        )
        for index, row in enumerate(rows, start=1)
    ]
    return results
