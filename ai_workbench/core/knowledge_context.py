from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ai_workbench.core.retrieval import search_knowledge


MAX_METADATA_QUERY_CHARS = 240


@dataclass
class KnowledgeContextResult:
    rendered_text: str = ""
    snippets: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_session_knowledge_context(
    *,
    knowledge_store: Any,
    model_backend: Any,
    query: str,
    session_id: str,
    source: str,
    effective_mode: str = "enabled",
    search_fn: Callable[..., dict[str, Any]] | None = None,
) -> KnowledgeContextResult:
    query_text = str(query or "").strip()
    if effective_mode != "enabled":
        return _skipped("agent_disabled", effective_mode=effective_mode, source=source, query=query_text)
    if not query_text:
        return _skipped("empty_query", effective_mode=effective_mode, source=source, query=query_text)
    if not session_id or knowledge_store is None:
        return _skipped("no_active_kbs", effective_mode=effective_mode, source=source, query=query_text)

    active_kbs = _active_session_kbs(knowledge_store, session_id)
    active_kb_ids = [kb.get("id", "") for kb in active_kbs if kb.get("id")]
    if not active_kb_ids:
        return _skipped("no_active_kbs", effective_mode=effective_mode, source=source, query=query_text)

    metadata_base = {
        "enabled": True,
        "effective_mode": effective_mode,
        "source": source,
        "knowledge_base_ids": active_kb_ids,
        "knowledge_base_names": [kb["name"] for kb in active_kbs if kb.get("name")],
        "query": _short_query(query_text),
    }
    try:
        engine = getattr(knowledge_store, "engine", None)
        search = search_fn or search_knowledge
        response = search(
            engine=engine,
            knowledge_store=knowledge_store,
            model_backend=model_backend,
            query=query_text,
            knowledge_base_ids=None,
            session_id=session_id,
            top_k=None,
            max_context_chars=None,
            include_debug=True,
        )
    except Exception as exc:
        warning = f"Knowledge retrieval failed: {exc}"
        return KnowledgeContextResult(
            metadata={**metadata_base, "result_count": 0, "injected": False, "reason": "retrieval_failed", "warnings": [warning]},
            warnings=[warning],
        )

    results = list(response.get("results") or []) if isinstance(response, dict) else []
    warnings = _debug_warnings(response)
    debug_metadata = _debug_metadata(response)
    if not results:
        return KnowledgeContextResult(
            metadata={**metadata_base, **debug_metadata, "result_count": 0, "injected": False, "reason": "no_results", "warnings": warnings},
            warnings=warnings,
        )

    settings = knowledge_store.get_settings()
    kb_names = {kb["id"]: kb["name"] for kb in active_kbs if kb.get("id")}
    snippets = [_snippet_payload(item, index, kb_names) for index, item in enumerate(results, start=1)]
    rendered_text = _render_block(
        instruction=getattr(settings, "knowledge_context_instruction", ""),
        snippet_template=getattr(settings, "knowledge_context_snippet_template", "{content}"),
        snippets=snippets,
    )
    return KnowledgeContextResult(
        rendered_text=rendered_text,
        snippets=snippets,
        metadata={
            **metadata_base,
            **debug_metadata,
            "result_count": len(snippets),
            "injected": bool(rendered_text),
            "snippet_refs": [_snippet_ref(snippet) for snippet in snippets] if rendered_text else [],
            "warnings": warnings,
        },
        warnings=warnings,
    )


def append_knowledge_to_system(messages: list[dict[str, Any]], rendered_text: str) -> list[dict[str, Any]]:
    if not rendered_text:
        return messages
    next_messages = [dict(message) for message in messages]
    for index, message in enumerate(next_messages):
        if message.get("role") == "system":
            content = str(message.get("content") or "")
            next_messages[index] = {**message, "content": f"{content.rstrip()}\n\n{rendered_text}" if content.strip() else rendered_text}
            return next_messages
    return [{"role": "system", "content": rendered_text}, *next_messages]


def _active_session_kbs(knowledge_store: Any, session_id: str) -> list[dict[str, str]]:
    active: list[dict[str, str]] = []
    for binding in knowledge_store.list_session_bindings(session_id):
        if not getattr(binding, "enabled", False):
            continue
        kb = getattr(binding, "knowledge_base", None)
        if kb is None:
            try:
                kb = knowledge_store.get_knowledge_base(binding.knowledge_base_id)
            except KeyError:
                continue
        if not getattr(kb, "enabled", False):
            continue
        active.append({"id": kb.id, "name": kb.name})
    return active


def _snippet_payload(item: dict[str, Any], index: int, kb_names: dict[str, str]) -> dict[str, Any]:
    kb_id = str(item.get("knowledge_base_id") or "")
    return {
        **item,
        "index": f"K{index}",
        "number": index,
        "knowledge_base_name": kb_names.get(kb_id, kb_id),
        "source_title": item.get("title") or item.get("source_id") or "",
        "section": item.get("heading_path") or "",
        "heading_path": item.get("heading_path") or "",
        "content": item.get("content") or "",
    }


def _snippet_ref(snippet: dict[str, Any]) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "index": snippet.get("index"),
        "chunk_id": snippet.get("chunk_id"),
        "knowledge_base_id": snippet.get("knowledge_base_id"),
        "knowledge_base_name": snippet.get("knowledge_base_name"),
        "source_id": snippet.get("source_id"),
        "source_title": snippet.get("source_title"),
        "rank": snippet.get("rank"),
        "heading_path": snippet.get("heading_path") or "",
    }
    for key in ("vector_score", "keyword_score", "rrf_score", "rerank_score"):
        value = snippet.get(key)
        if isinstance(value, (int, float)):
            ref[key] = value
    return {key: value for key, value in ref.items() if value not in (None, "") or key == "heading_path"}


def _render_block(*, instruction: str, snippet_template: str, snippets: list[dict[str, Any]]) -> str:
    rendered_snippets = []
    for snippet in snippets:
        try:
            rendered_snippets.append(snippet_template.format(**snippet).strip())
        except Exception:
            rendered_snippets.append(
                f"[{snippet['index']}]\n"
                f"Knowledge base: {snippet['knowledge_base_name']}\n"
                f"Source: {snippet['source_title']}\n"
                f"Section: {snippet['heading_path']}\n"
                f"Content:\n{snippet['content']}".strip()
            )
    parts = ["# Retrieved Knowledge", str(instruction or "").strip(), *rendered_snippets]
    return "\n\n".join(part for part in parts if part)


def _debug_warnings(response: dict[str, Any]) -> list[str]:
    if not isinstance(response, dict):
        return []
    debug = response.get("debug")
    if not isinstance(debug, dict):
        return []
    warnings = debug.get("warnings")
    return [str(item) for item in warnings] if isinstance(warnings, list) else []


def _debug_metadata(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    debug = response.get("debug")
    if not isinstance(debug, dict):
        return {}
    metadata: dict[str, Any] = {}
    embedding_groups = debug.get("embedding_groups")
    if isinstance(embedding_groups, list):
        vector_count = 0
        for group in embedding_groups:
            if isinstance(group, dict) and isinstance(group.get("candidate_count"), int):
                vector_count += group["candidate_count"]
        metadata["vector_candidate_count"] = vector_count
    for key in ("keyword_candidate_count", "merged_candidate_count"):
        value = debug.get(key)
        if isinstance(value, int):
            metadata[key] = value
    for key in ("reranker_used", "reranker_failed"):
        value = debug.get(key)
        if isinstance(value, bool):
            metadata[key] = value
    return metadata


def _skipped(reason: str, *, effective_mode: str, source: str, query: str) -> KnowledgeContextResult:
    return KnowledgeContextResult(
        metadata={
            "enabled": False,
            "effective_mode": effective_mode,
            "source": source,
            "knowledge_base_ids": [],
            "query": _short_query(query),
            "result_count": 0,
            "injected": False,
            "reason": reason,
            "warnings": [],
        }
    )


def _short_query(query: str) -> str:
    text = str(query or "").strip()
    if len(text) <= MAX_METADATA_QUERY_CHARS:
        return text
    keep = (MAX_METADATA_QUERY_CHARS - 3) // 2
    return f"{text[:keep]}...{text[-keep:]}"
