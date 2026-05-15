from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError


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
    match_query = build_safe_fts_query(query)
    if match_query is None:
        warnings.append("KEYWORD_QUERY_UNSAFE: Keyword search skipped: query could not be converted to a safe FTS query.")
        return [], warnings
    try:
        return _execute_keyword_search(engine=engine, query=match_query, knowledge_base_ids=knowledge_base_ids, top_k=top_k), warnings
    except (OperationalError, SQLAlchemyError):
        warnings.append("KEYWORD_SEARCH_FAILED: Keyword search skipped: FTS query failed after sanitization.")
        return [], warnings


def build_safe_fts_query(raw_query: str) -> str | None:
    tokens = _safe_fts_tokens(raw_query)
    if not tokens:
        return None
    return " ".join(_quote_fts_term(token) for token in tokens)


def sanitize_fts_query(query: str) -> str | None:
    return build_safe_fts_query(query)


def _safe_fts_tokens(raw_query: str) -> list[str]:
    tokens = re.findall(r"[\w\u3400-\u9fff\u3040-\u30ff]+", raw_query, flags=re.UNICODE)
    return [token for token in tokens if _has_searchable_character(token)]


def _has_searchable_character(token: str) -> bool:
    return any(character.isalnum() or "\u3400" <= character <= "\u9fff" or "\u3040" <= character <= "\u30ff" for character in token)


def _quote_fts_term(term: str) -> str:
    return f'"{term.replace(chr(34), chr(34) + chr(34))}"'


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
