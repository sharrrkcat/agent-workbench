"""Explicit facade for knowledge indexing and retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_workbench.core.knowledge_indexing import (
    KnowledgeIndexError,
    SourceText,
    build_search_text,
    chunk_source_text,
    embed_chunks,
    prepare_attachment_text_source,
    prepare_file_source,
    prepare_pasted_text_source,
    validate_source_limits,
)
from ai_workbench.core.knowledge_store import KnowledgeSource
from ai_workbench.core.retrieval import search_knowledge


class KnowledgeService:
    def __init__(self, *, store: Any, model_backend: Any, provider_profiles: Any = None, repo_root: Path | None = None) -> None:
        self.store=store; self.model_backend=model_backend; self.provider_profiles=provider_profiles; self.repo_root=Path(repo_root or Path.cwd())

    def search(self, *, query: str, knowledge_base_ids: list[str] | None = None, session_id: str | None = None, top_k: int | None = None, max_context_chars: int | None = None, include_debug: bool = False) -> dict[str,Any]:
        return search_knowledge(engine=getattr(self.store,"engine",None),knowledge_store=self.store,model_backend=self.model_backend,query=query,knowledge_base_ids=knowledge_base_ids,session_id=session_id,top_k=top_k,max_context_chars=max_context_chars,include_debug=include_debug,provider_profile_store=self.provider_profiles,repo_root=self.repo_root)

    def add_text(self, *, knowledge_base_id: str, title: str, text: str, uri: str | None = None) -> Any:
        prepared=prepare_pasted_text_source(root=self.repo_root,title=title,text=text); return self._index(knowledge_base_id,prepared,uri=uri)

    def add_file(self, *, knowledge_base_id: str, path: str) -> Any:
        prepared=prepare_file_source(path=Path(path),root=self.repo_root); return self._index(knowledge_base_id,prepared)

    def reindex(self, source_id: str) -> Any:
        source=self.store.get_source(source_id)
        if source.source_type == "attachment_text":
            attachment_id = str((source.metadata or {}).get("attachment_id") or source.uri)
            prepared = prepare_attachment_text_source(attachment_id=attachment_id)
            prepared = SourceText(**{**prepared.__dict__, "source_id": source.id, "title": source.title})
        elif source.source_type == "file":
            path=(self.repo_root / source.uri).resolve()
            prepared=prepare_file_source(path=path,root=self.repo_root,source_id=source.id)
        else:
            path=(self.repo_root / source.uri).resolve()
            root=(self.repo_root / "data" / "knowledge" / "sources").resolve()
            try: path.relative_to(root)
            except ValueError as exc: raise KnowledgeIndexError("KNOWLEDGE_SOURCE_NOT_READABLE", "Source path is invalid.") from exc
            if not path.is_file(): raise KnowledgeIndexError("KNOWLEDGE_SOURCE_NOT_READABLE", "Source file was not found.")
            prepared=prepare_pasted_text_source(root=self.repo_root,title=source.title,text=path.read_text(encoding="utf-8"),source_id=source.id)
        return self._index(source.knowledge_base_id,prepared,uri=source.uri)

    def _index(self, knowledge_base_id: str, prepared: Any, *, uri: str | None = None) -> Any:
        settings=self.store.get_settings(); base=self.store.get_knowledge_base(knowledge_base_id); profile=self.store.get_embedding_profile(base.embedding_model_profile_id); validate_source_limits(prepared.text,prepared.size_bytes,settings); chunks=chunk_source_text(prepared.text,settings=settings,knowledge_base=base,source_title=prepared.title,source_uri=uri or prepared.uri); embedded=embed_chunks(backend=self.model_backend,profile=profile,chunks=chunks,settings=settings,provider_profile_store=self.provider_profiles,repo_root=self.repo_root)
        source=KnowledgeSource(id=prepared.source_id,knowledge_base_id=knowledge_base_id,source_type=prepared.source_type,uri=uri or prepared.uri,title=prepared.title,relative_path=prepared.relative_path,virtual_path=prepared.virtual_path,folder_path=prepared.folder_path,file_name=prepared.file_name,extension=prepared.extension,path_depth=prepared.path_depth,source_mtime=prepared.source_mtime,source_size_bytes=prepared.size_bytes,mime_type=prepared.mime_type,size_bytes=prepared.size_bytes,content_hash=prepared.content_hash,status="indexing",metadata=prepared.metadata)
        return self.store.upsert_indexed_source(source=source,chunks=chunks,vectors=embedded.get("vectors") or [],embedding_model_profile=profile,embedding_dimension=int(embedded.get("dimension") or (len((embedded.get("vectors") or [[]])[0]))),search_texts=[build_search_text(prepared.title,item.heading_path,item.content,item.metadata) for item in chunks])
