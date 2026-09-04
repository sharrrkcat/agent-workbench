"""Explicit best-effort model memory controls."""

from __future__ import annotations

from typing import Any

TARGETS = ("llm", "embedding", "reranker")
VALID_TARGETS = (*TARGETS, "all")


class RuntimeMemoryService:
    def __init__(self, *, llm: Any = None, knowledge_model_backend: Any = None, llm_profiles: Any = None, provider_profiles: Any = None, llm_defaults: Any = None, sessions: Any = None) -> None:
        self.llm=llm; self.knowledge_model_backend=knowledge_model_backend; self.llm_profiles=llm_profiles; self.provider_profiles=provider_profiles; self.llm_defaults=llm_defaults; self.sessions=sessions
    def memory_summary(self, session_id: str | None = None) -> dict[str,Any]: return {"targets":[self._summary(item) for item in TARGETS]}
    def free_memory(self, targets: list[str], context: dict[str,Any] | None = None) -> dict[str,Any]: return {"results":[self._free(item) for item in expand_targets(targets)]}
    def _summary(self,target: str) -> dict[str,Any]:
        if target=="llm": return {"target":"llm","available":self.llm is not None,"enabled":True,"status":"available" if self.llm is not None else "unavailable","reason":"" if self.llm is not None else "LLM service unavailable"}
        backend=self.knowledge_model_backend; busy=getattr(backend,f"{target}_busy",lambda:False)() if backend is not None else False; count=len(getattr(backend,"_embedding_cache" if target=="embedding" else "_reranker_cache",{}) or {}) if backend is not None else 0
        return {"target":target,"available":backend is not None,"enabled":True,"status":"busy" if busy else ("loaded" if count else "not_loaded"),"reason":""}
    def _free(self,target: str) -> dict[str,str]:
        if target=="llm":
            result=self.llm.unload({}) if self.llm is not None else {"success":False}
            return {"target":target,"status":"freed" if result.get("success") else "unsupported","message":str(result.get("message") or "")}
        method=getattr(self.knowledge_model_backend,f"unload_all_{target}_models",None) if self.knowledge_model_backend is not None else None
        if not callable(method): return {"target":target,"status":"unavailable","message":"Model backend unavailable."}
        removed=method(); return {"target":target,"status":"freed" if removed else "skipped","message":""}


def expand_targets(targets: list[str]) -> list[str]:
    values=[str(item).strip().lower() for item in targets]
    if not values: raise ValueError("Memory target is required.")
    invalid=[item for item in values if item not in VALID_TARGETS]
    if invalid: raise ValueError(f"Invalid memory target: {invalid[0]}")
    if "all" in values: return list(TARGETS)
    return list(dict.fromkeys(values))


def format_memory_result(payload: dict[str,Any]) -> str:
    return "\n".join(f"{item.get('target')}: {item.get('status')}" for item in payload.get("results",[]) if isinstance(item,dict))
