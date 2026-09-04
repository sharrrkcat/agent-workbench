"""Deterministic source preparation and single-profile chunking."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from ai_workbench.core.attachments import read_attachment_text, resolve_attachment_uri
from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.knowledge_models import KnowledgeModelError, knowledge_sources_path
from ai_workbench.core.knowledge_settings import KnowledgeSettings
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase


class KnowledgeIndexError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message); self.code=code; self.message=message; self.details=details or {}


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    heading_path: str
    content: str
    char_start: int
    char_end: int
    token_count: int
    content_hash: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SourceText:
    source_id: str
    source_type: Literal["pasted_text", "attachment_text", "file"]
    title: str
    text: str
    uri: str
    mime_type: str
    size_bytes: int
    content_hash: str
    metadata: dict[str, Any]
    relative_path: str = ""
    virtual_path: str = ""
    folder_path: str = ""
    file_name: str = ""
    extension: str = ""
    path_depth: int = 0
    source_mtime: Any = None


def source_content_hash(text: str) -> str: return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_pasted_text_source(*, root: Path, title: str, text: str, source_id: str | None = None) -> SourceText:
    source_id=source_id or str(uuid4()); content=text or ""; target=knowledge_sources_path(root)/(source_id+".txt"); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content,encoding="utf-8")
    return SourceText(source_id=source_id,source_type="pasted_text",title=title.strip() or "Pasted text",text=content,uri=f"data/knowledge/sources/{source_id}.txt",mime_type="text/plain",size_bytes=len(content.encode()),content_hash=source_content_hash(content),metadata={})


def with_source_overrides(source: SourceText, *, folder_path: str = "") -> SourceText:
    folder="/".join(part.strip() for part in folder_path.replace("\\","/").split("/") if part.strip() not in {".",".."}); name=source.file_name or re.sub(r"[^A-Za-z0-9._ -]+","-",Path(source.title).name).strip() or "source.txt"; virtual=f"{folder}/{name}" if folder else name
    return SourceText(**{**source.__dict__,"folder_path":folder,"file_name":name,"virtual_path":virtual,"path_depth":len([p for p in virtual.split("/") if p]),"metadata":{**source.metadata,"virtual_path":virtual,"folder_path":folder,"file_name":name}})


def prepare_attachment_text_source(*, attachment_id: str) -> SourceText:
    try: path=resolve_attachment_uri(attachment_id)
    except ValueError as exc: raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_FOUND","Attachment was not found.") from exc
    if not path.is_file(): raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_FOUND","Attachment file was not found.")
    mime=mimetypes.guess_type(path.name)[0] or "text/plain"; payload=read_attachment_text({"id":path.stem,"type":"file","mime_type":mime,"name":path.name,"size":path.stat().st_size,"uri":f"local://attachments/{path.name}"}); text=str(payload["content"])
    return SourceText(source_id=str(uuid4()),source_type="attachment_text",title=path.name,text=text,uri=f"local://attachments/{path.name}",mime_type=mime,size_bytes=len(text.encode()),content_hash=source_content_hash(text),metadata={"attachment_id":attachment_id})


def prepare_file_source(*, path: Path, root: Path, source_id: str | None = None) -> SourceText:
    resolved=path.resolve(); base=root.resolve()
    try: relative=resolved.relative_to(base)
    except ValueError as exc: raise KnowledgeIndexError("KNOWLEDGE_FILE_PATH_INVALID","Source path must stay inside the workspace.") from exc
    if not resolved.is_file(): raise KnowledgeIndexError("KNOWLEDGE_FILE_NOT_FOUND","Source file was not found.")
    text=resolved.read_text(encoding="utf-8"); stat=resolved.stat(); rel=relative.as_posix()
    return SourceText(source_id=source_id or str(uuid4()),source_type="file",title=rel,text=text,uri=rel,mime_type=mimetypes.guess_type(resolved.name)[0] or "text/plain",size_bytes=stat.st_size,content_hash=source_content_hash(text),metadata={},relative_path=rel,virtual_path=rel,file_name=resolved.name,folder_path=relative.parent.as_posix() if str(relative.parent)!="." else "",extension=resolved.suffix.lower(),path_depth=len(relative.parts),source_mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))


def validate_source_limits(text: str, size_bytes: int, settings: KnowledgeSettings) -> None:
    if size_bytes > settings.max_source_size_bytes: raise KnowledgeIndexError("KNOWLEDGE_SOURCE_TOO_LARGE","Source exceeds the configured size limit.")
    if len(text) > settings.max_total_index_chars_per_source: raise KnowledgeIndexError("KNOWLEDGE_SOURCE_TOO_LARGE","Source exceeds the configured character limit.")


def chunk_source_text(text: str, *, settings: KnowledgeSettings, knowledge_base: KnowledgeBase, source_title: str = "", source_uri: str = "") -> list[ChunkDraft]:
    size = settings.default_chunk_size
    overlap = settings.default_chunk_overlap
    if overlap >= size: raise KnowledgeIndexError("KNOWLEDGE_INVALID_CHUNKING","Chunk overlap must be smaller than chunk size.")
    chunks=[]; start=0
    while start < len(text):
        end=min(len(text),start+size); content=text[start:end]; heading=_heading_at(text,start)
        chunks.append(ChunkDraft(len(chunks),heading,content,start,end,max(1,round(len(content)/4)),source_content_hash(content),{"chunk_size":size,"chunk_overlap":overlap}))
        if end>=len(text): break
        start=end-overlap
    if len(chunks)>settings.max_chunks_per_source: raise KnowledgeIndexError("KNOWLEDGE_TOO_MANY_CHUNKS","Source text produced too many chunks.",{"chunks":len(chunks)})
    return chunks


def build_embedding_input(source_title: str, chunk: ChunkDraft) -> str:
    return f"{source_title}\n{chunk.heading_path}\n{chunk.content}".strip()


def build_search_text(title: str, heading_path: str, content: str, metadata: dict[str, Any] | None = None) -> str:
    return "\n".join(item for item in (title,heading_path,content) if item)


def embed_chunks(*, backend: Any, profile: EmbeddingModelProfile, chunks: list[ChunkDraft], settings: KnowledgeSettings, provider_profile_store: Any = None, repo_root: Any = None) -> dict[str, Any]:
    try:
        result=embed_texts(backend=backend,profile=profile,texts=[build_embedding_input("",c) for c in chunks],purpose="document",device=settings.local_model_device,provider_profile_store=provider_profile_store,repo_root=repo_root)
    except Exception as exc:
        if isinstance(exc,KnowledgeModelError): raise KnowledgeIndexError(exc.code,exc.message,exc.details) from exc
        raise
    return result


def model_error_to_index_error(exc: KnowledgeModelError) -> KnowledgeIndexError: return KnowledgeIndexError(exc.code,exc.message,exc.details)


def _heading_at(text: str, offset: int) -> str:
    headings=[]
    for match in re.finditer(r"(?m)^\s*(#{1,6})\s+(.+?)\s*$",text):
        if match.start()<=offset: headings.append(match.group(2).strip())
    return " > ".join(headings[-3:])
