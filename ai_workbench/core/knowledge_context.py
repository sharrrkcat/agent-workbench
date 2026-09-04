"""Automatic session knowledge projection for chat context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ai_workbench.core.retrieval import search_knowledge


@dataclass
class KnowledgeContextResult:
    rendered_text: str = ""
    snippets: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_session_knowledge_context(*, knowledge_store: Any, model_backend: Any, query: str, session_id: str, source: str = "chat", search_fn: Callable[..., dict[str, Any]] | None = None, provider_profile_store: Any = None, repo_root: Any = None, **_ignored: Any) -> KnowledgeContextResult:
    text=str(query or "").strip()
    if not text or knowledge_store is None or not session_id: return KnowledgeContextResult(metadata={"injected":False,"reason":"no_active_kbs"})
    bindings=[item for item in knowledge_store.list_session_bindings(session_id) if item.enabled]
    if not bindings: return KnowledgeContextResult(metadata={"injected":False,"reason":"no_active_kbs"})
    try:
        response=(search_fn or search_knowledge)(engine=getattr(knowledge_store,"engine",None),knowledge_store=knowledge_store,model_backend=model_backend,query=text,session_id=session_id,include_debug=True,top_k=None,max_context_chars=None,provider_profile_store=provider_profile_store,repo_root=repo_root)
    except Exception as exc:
        warning=f"Knowledge retrieval failed: {exc}"; return KnowledgeContextResult(metadata={"injected":False,"reason":"retrieval_failed","rerank_fallback":False},warnings=[warning])
    results=list(response.get("results") or []); debug=response.get("debug") if isinstance(response.get("debug"),dict) else {}; warnings=[str(item) for item in debug.get("warnings",[])]; settings=knowledge_store.get_settings(); names={item.knowledge_base_id:(item.knowledge_base.name if item.knowledge_base else item.knowledge_base_id) for item in bindings}
    snippets=[_snippet(item,index,names) for index,item in enumerate(results,1)]; rendered=render_knowledge_context_preview(settings=settings,results=results,knowledge_base_names=names)
    return KnowledgeContextResult(rendered_text=rendered,snippets=snippets,metadata={"injected":bool(rendered),"source":source,"result_count":len(snippets),"knowledge_base_ids":list(names),"reranker_used":False,"rerank_fallback":bool(debug.get("rerank_fallback",False)),"snippet_refs":[{"index":s["index"],"chunk_id":s.get("chunk_id"),"source_id":s.get("source_id")} for s in snippets]},warnings=warnings)


def append_knowledge_to_system(messages: list[dict[str, Any]], rendered_text: str) -> list[dict[str, Any]]:
    if not rendered_text: return messages
    result=[dict(item) for item in messages]
    for index,item in enumerate(result):
        if item.get("role")=="system": result[index]={**item,"content":f"{str(item.get('content') or '').rstrip()}\n\n{rendered_text}".strip()}; return result
    return [{"role":"system","content":rendered_text},*result]


def render_knowledge_context_preview(*, settings: Any, results: list[dict[str, Any]], knowledge_base_names: dict[str,str] | None = None) -> str:
    if not results: return ""
    names=knowledge_base_names or {}; snippets=[_snippet(item,index,names) for index,item in enumerate(results,1)]; blocks=[]
    for item in snippets:
        try: blocks.append(settings.knowledge_context_snippet_template.format(**item).strip())
        except Exception: blocks.append(f"[{item['index']}]\nSource: {item['source_title']}\nContent:\n{item['content']}")
    return "\n\n".join(["# Retrieved Knowledge",str(settings.knowledge_context_instruction).strip(),*blocks])


def _snippet(item: dict[str,Any], index: int, names: dict[str,str]) -> dict[str,Any]:
    kb_id=str(item.get("knowledge_base_id") or "")
    return {**item,"index":f"K{index}","number":index,"knowledge_base_name":names.get(kb_id,kb_id),"source_title":item.get("title") or item.get("source_id") or "","section":item.get("heading_path") or "","heading_path":item.get("heading_path") or "","content":item.get("content") or ""}
