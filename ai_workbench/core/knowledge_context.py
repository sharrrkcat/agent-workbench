"""Context previews for explicit Knowledge search tests."""

from __future__ import annotations

from typing import Any


def render_knowledge_context_preview(*, settings: Any, results: list[dict[str, Any]], knowledge_base_names: dict[str,str] | None = None, snippet_spans: list | None = None) -> str:
    if not results: return ""
    names=knowledge_base_names or {}; snippets=[_snippet(item,index,names) for index,item in enumerate(results,1)]; blocks=[]
    for item in snippets:
        try: blocks.append(settings.knowledge_context_snippet_template.format(**item).strip())
        except Exception: blocks.append(f"[{item['index']}]\nSource: {item['source_title']}\nContent:\n{item['content']}")
    header = "\n\n".join(["# Retrieved Knowledge",str(settings.knowledge_context_instruction).strip()])
    offset = len(header)
    if snippet_spans is not None:
        for block in blocks:
            offset += 2
            snippet_spans.append((offset, offset + len(block)))
            offset += len(block)
    return "\n\n".join([header, *blocks])


def _snippet(item: dict[str,Any], index: int, names: dict[str,str]) -> dict[str,Any]:
    kb_id=str(item.get("knowledge_base_id") or "")
    return {**item,"index":f"K{index}","number":index,"knowledge_base_name":names.get(kb_id,kb_id),"source_title":item.get("title") or item.get("source_id") or "","section":item.get("heading_path") or "","heading_path":item.get("heading_path") or "","content":item.get("content") or ""}
