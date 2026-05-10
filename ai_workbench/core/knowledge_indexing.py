from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from ai_workbench.core.attachments import read_attachment_text, resolve_attachment_uri
from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.knowledge_models import KnowledgeModelError, knowledge_sources_path
from ai_workbench.core.knowledge_settings import KnowledgeSettings
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase
from ai_workbench.core.time import utc_now


KnowledgeSourceType = Literal["pasted_text", "attachment_text"]


class KnowledgeIndexError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    heading_path: str
    content: str
    char_start: int
    char_end: int
    token_count: int
    content_hash: str


@dataclass(frozen=True)
class SourceText:
    source_id: str
    source_type: KnowledgeSourceType
    title: str
    text: str
    uri: str
    mime_type: str
    size_bytes: int
    content_hash: str
    metadata: dict[str, Any]


def source_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_pasted_text_source(*, root: Path, title: str, text: str, source_id: str | None = None) -> SourceText:
    source_id = source_id or str(uuid4())
    clean_title = title.strip() or "Pasted text"
    content = text or ""
    size_bytes = len(content.encode("utf-8"))
    target = knowledge_sources_path(root) / f"{source_id}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return SourceText(
        source_id=source_id,
        source_type="pasted_text",
        title=clean_title,
        text=content,
        uri=f"data/knowledge/sources/{source_id}.txt",
        mime_type="text/plain",
        size_bytes=size_bytes,
        content_hash=source_content_hash(content),
        metadata={},
    )


def prepare_attachment_text_source(*, attachment_id: str) -> SourceText:
    filename = attachment_id.strip()
    try:
        path = resolve_attachment_uri(filename)
    except ValueError as exc:
        raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_FOUND", "Attachment was not found or is not a local attachment.") from exc
    if not path.is_file():
        raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_FOUND", "Attachment file was not found.")
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    attachment = {
        "id": path.stem,
        "type": "file",
        "mime_type": mime_type,
        "name": path.name,
        "size": path.stat().st_size,
        "uri": f"local://attachments/{path.name}",
    }
    try:
        payload = read_attachment_text(attachment)
    except ValueError as exc:
        raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_TEXT", "Only text attachments can be indexed.") from exc
    text = str(payload["content"])
    return SourceText(
        source_id=str(uuid4()),
        source_type="attachment_text",
        title=str(payload.get("filename") or path.name),
        text=text,
        uri=f"local://attachments/{path.name}",
        mime_type=str(payload.get("mime_type") or mime_type),
        size_bytes=int(payload.get("size") or len(text.encode("utf-8"))),
        content_hash=source_content_hash(text),
        metadata={"attachment_id": path.name, "truncated": bool(payload.get("truncated"))},
    )


def validate_source_limits(text: str, size_bytes: int, settings: KnowledgeSettings) -> None:
    if size_bytes > settings.max_source_size_bytes:
        raise KnowledgeIndexError(
            "KNOWLEDGE_SOURCE_TOO_LARGE",
            "Source text exceeds max_source_size_bytes.",
            {"size_bytes": size_bytes, "limit": settings.max_source_size_bytes},
        )
    if len(text) > settings.max_total_index_chars_per_source:
        raise KnowledgeIndexError(
            "KNOWLEDGE_INDEX_LIMIT_EXCEEDED",
            "Source text exceeds max_total_index_chars_per_source.",
            {"chars": len(text), "limit": settings.max_total_index_chars_per_source},
        )


def chunk_source_text(text: str, *, settings: KnowledgeSettings, knowledge_base: KnowledgeBase) -> list[ChunkDraft]:
    chunk_size = knowledge_base.chunk_size_override or settings.default_chunk_size
    chunk_overlap = knowledge_base.chunk_overlap_override if knowledge_base.chunk_overlap_override is not None else settings.default_chunk_overlap
    if chunk_overlap >= chunk_size:
        raise KnowledgeIndexError("KNOWLEDGE_INVALID_CHUNKING", "Chunk overlap must be smaller than chunk size.")
    chunks: list[ChunkDraft] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + chunk_size, text_length)
        content = text[start:end]
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                heading_path="",
                content=content,
                char_start=start,
                char_end=end,
                token_count=max(1, round(len(content) / 4)),
                content_hash=source_content_hash(content),
            )
        )
        if end >= text_length:
            break
        start = end - chunk_overlap
    if len(chunks) > settings.max_chunks_per_source:
        raise KnowledgeIndexError(
            "KNOWLEDGE_TOO_MANY_CHUNKS",
            "Source text produced too many chunks.",
            {"chunks": len(chunks), "limit": settings.max_chunks_per_source},
        )
    return chunks


def build_search_text(title: str, heading_path: str, content: str) -> str:
    base = "\n".join(part for part in [title, heading_path, content] if part)
    bigrams = _cjk_bigrams(base)
    return f"{base}\n{' '.join(bigrams)}" if bigrams else base


def embed_chunks(
    *,
    backend: Any,
    profile: EmbeddingModelProfile,
    chunks: list[ChunkDraft],
    device: str,
) -> dict:
    return embed_texts(
        backend=backend,
        profile=profile,
        texts=[chunk.content for chunk in chunks],
        purpose="document",
        device=device,
    )


def model_error_to_index_error(exc: KnowledgeModelError) -> KnowledgeIndexError:
    return KnowledgeIndexError(exc.code, exc.message, exc.details)


def _cjk_bigrams(text: str) -> list[str]:
    tokens: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff\u3040-\u30ff]+", text):
        tokens.extend(run[index : index + 2] for index in range(0, max(0, len(run) - 1)))
    return tokens
