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
from ai_workbench.core.knowledge_settings import ChunkProfile, KnowledgeSettings, VALID_CHUNK_PROFILES
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase


KnowledgeSourceType = Literal["pasted_text", "attachment_text", "origin_file"]


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
    metadata: dict[str, Any]


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
    origin_id: str | None = None
    relative_path: str = ""
    virtual_path: str = ""
    folder_path: str = ""
    file_name: str = ""
    extension: str = ""
    path_depth: int = 0
    source_mtime: Any = None


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


def prepare_origin_file_source(
    *,
    origin_id: str,
    path: Path,
    root: Path,
    uri_prefix: str,
    source_id: str | None = None,
) -> SourceText:
    try:
        resolved = path.resolve()
        origin_root = root.resolve()
        relative = resolved.relative_to(origin_root)
    except ValueError as exc:
        raise KnowledgeIndexError("KNOWLEDGE_ORIGIN_PATH_INVALID", "Origin file path must stay inside the origin root.") from exc
    if not resolved.is_file():
        raise KnowledgeIndexError("KNOWLEDGE_ORIGIN_FILE_NOT_FOUND", "Origin file was not found.")
    text = resolved.read_text(encoding="utf-8")
    stat = resolved.stat()
    relative_path = relative.as_posix()
    folder_path = relative.parent.as_posix() if str(relative.parent) != "." else ""
    file_name = relative.name
    extension = resolved.suffix.lower()
    uri = f"{uri_prefix.rstrip('/')}/{relative_path}"
    return SourceText(
        source_id=source_id or str(uuid4()),
        source_type="origin_file",
        title=relative_path,
        text=text,
        uri=uri,
        mime_type=mimetypes.guess_type(resolved.name)[0] or "text/plain",
        size_bytes=stat.st_size,
        content_hash=source_content_hash(text),
        metadata={
            "origin_id": origin_id,
            "relative_path": relative_path,
            "virtual_path": relative_path,
            "folder_path": folder_path,
            "file_name": file_name,
            "extension": extension,
            "path_depth": len(relative.parts),
        },
        origin_id=origin_id,
        relative_path=relative_path,
        virtual_path=relative_path,
        folder_path=folder_path,
        file_name=file_name,
        extension=extension,
        path_depth=len(relative.parts),
        source_mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
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


ENTITY_TYPE_BY_CATEGORY = {
    "characters": "Character",
    "people": "Person",
    "locations": "Location",
    "planets": "Planet",
    "factions": "Faction",
    "species": "Species",
    "organizations": "Organization",
    "items": "Item",
    "concepts": "Concept",
    "events": "Event",
    "episodes": "Episode",
    "quests": "Quest",
}

DOCUMENT_SECTION_HEADINGS = {
    "summary",
    "overview",
    "history",
    "relationships",
    "abilities",
    "notes",
    "background",
    "role",
    "role in fallen order",
    "details",
}
COLLECTION_CATEGORY_HEADINGS = set(ENTITY_TYPE_BY_CATEGORY)


@dataclass(frozen=True)
class MarkdownHeading:
    level: int
    title: str
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    path: tuple[str, ...]


@dataclass(frozen=True)
class MarkdownParseResult:
    frontmatter: dict[str, str]
    body_start_char: int
    headings: list[MarkdownHeading]
    line_starts: list[int]


@dataclass(frozen=True)
class MarkdownSection:
    heading: MarkdownHeading | None
    heading_path: str
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    content: str


@dataclass(frozen=True)
class ProfileDecision:
    requested: str
    effective: str
    confidence: float
    document_score: int
    collection_score: int
    profile_source: str
    entity_level: int | None = None


def chunk_source_text(
    text: str,
    *,
    settings: KnowledgeSettings,
    knowledge_base: KnowledgeBase,
    source_title: str = "",
    source_uri: str = "",
    origin_default_chunk_profile: str | None = None,
) -> list[ChunkDraft]:
    chunk_size = knowledge_base.chunk_size_override or settings.default_chunk_size
    chunk_overlap = knowledge_base.chunk_overlap_override if knowledge_base.chunk_overlap_override is not None else settings.default_chunk_overlap
    if chunk_overlap >= chunk_size:
        raise KnowledgeIndexError("KNOWLEDGE_INVALID_CHUNKING", "Chunk overlap must be smaller than chunk size.")
    parse = parse_markdown(text)
    requested, profile_source = _requested_chunk_profile(
        parse,
        source_title=source_title,
        source_uri=source_uri,
        text=text,
        origin_default_chunk_profile=origin_default_chunk_profile,
        knowledge_base_default_chunk_profile=knowledge_base.default_chunk_profile,
        settings_default_chunk_profile=settings.default_chunk_profile,
    )
    if requested == "plain_text":
        return _plain_text_chunks(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, settings=settings, profile_source=profile_source)
    chunks = _markdown_chunks(
        text,
        parse=parse,
        requested_profile=requested,
        profile_source=profile_source,
        source_title=source_title,
        source_uri=source_uri,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        settings=settings,
    )
    if chunks:
        return chunks
    return _plain_text_chunks(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, settings=settings, profile_source="fallback")


def _plain_text_chunks(text: str, *, chunk_size: int, chunk_overlap: int, settings: KnowledgeSettings, profile_source: str = "fallback") -> list[ChunkDraft]:
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
                metadata={
                    "chunk_profile_requested": "plain_text",
                    "chunk_profile_effective": "plain_text",
                    "chunk_profile_confidence": 1.0,
                    "profile_source": profile_source,
                },
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


def parse_markdown(text: str) -> MarkdownParseResult:
    frontmatter: dict[str, str] = {}
    body_start_char = 0
    lines = text.splitlines(keepends=True)
    line_starts: list[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line)
    if text and (not lines or offset < len(text)):
        line_starts.append(offset)

    if lines and lines[0].strip() == "---":
        fm_end_index: int | None = None
        for index in range(1, len(lines)):
            if lines[index].strip() in {"---", "..."}:
                fm_end_index = index
                break
        if fm_end_index is not None:
            raw_frontmatter = "".join(lines[1:fm_end_index])
            frontmatter = _parse_simple_frontmatter(raw_frontmatter)
            body_start_char = sum(len(line) for line in lines[: fm_end_index + 1])

    headings: list[MarkdownHeading] = []
    stack: list[MarkdownHeading] = []
    in_fence = False
    fence_marker = ""
    fence_re = re.compile(r"^[ \t]{0,3}(```+|~~~+)")
    heading_re = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
    for line_number, line in enumerate(lines, start=1):
        char_start = line_starts[line_number - 1]
        if char_start < body_start_char:
            continue
        stripped = line.rstrip("\r\n")
        fence_match = fence_re.match(stripped)
        if fence_match:
            marker = fence_match.group(1)
            marker_kind = marker[0]
            if not in_fence:
                in_fence = True
                fence_marker = marker_kind
            elif marker_kind == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        match = heading_re.match(stripped)
        if not match:
            continue
        level = len(match.group(1))
        title = _clean_heading_title(match.group(2))
        if not title:
            continue
        while stack and stack[-1].level >= level:
            stack.pop()
        path = tuple([item.title for item in stack] + [title])
        heading = MarkdownHeading(
            level=level,
            title=title,
            char_start=char_start,
            char_end=char_start + len(line),
            line_start=line_number,
            line_end=line_number,
            path=path,
        )
        headings.append(heading)
        stack.append(heading)
    return MarkdownParseResult(frontmatter=frontmatter, body_start_char=body_start_char, headings=headings, line_starts=line_starts)


def _parse_simple_frontmatter(raw: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        clean_key = key.strip()
        if not clean_key:
            continue
        clean_value = value.strip().strip("\"'")
        data[clean_key] = clean_value
    return data


def _markdown_chunks(
    text: str,
    *,
    parse: MarkdownParseResult,
    requested_profile: str,
    profile_source: str,
    source_title: str,
    source_uri: str,
    chunk_size: int,
    chunk_overlap: int,
    settings: KnowledgeSettings,
) -> list[ChunkDraft]:
    decision = _profile_decision(requested_profile, parse=parse, source_title=source_title, source_uri=source_uri, profile_source=profile_source)
    document_title = _document_title(parse=parse, source_title=source_title)
    source_path = _source_path(source_title=source_title, source_uri=source_uri)
    if decision.effective == "markdown_collection":
        entity_level = _collection_entity_level(parse.headings)
        decision = ProfileDecision(
            requested=decision.requested,
            effective=decision.effective,
            confidence=decision.confidence,
            document_score=decision.document_score,
            collection_score=decision.collection_score,
            profile_source=decision.profile_source,
            entity_level=entity_level,
        )
        sections = _collection_sections(text, parse=parse, entity_level=entity_level)
    else:
        sections = _document_sections(text, parse=parse)
    drafts: list[ChunkDraft] = []
    for section in sections:
        if not section.content.strip():
            continue
        metadata_base = _section_metadata(
            section=section,
            parse=parse,
            decision=decision,
            document_title=document_title,
            source_title=source_title,
            source_path=source_path,
        )
        drafts.extend(
            _split_section(
                section,
                metadata_base=metadata_base,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                start_index=len(drafts),
            )
        )
    if len(drafts) > settings.max_chunks_per_source:
        raise KnowledgeIndexError(
            "KNOWLEDGE_TOO_MANY_CHUNKS",
            "Source text produced too many chunks.",
            {"chunks": len(drafts), "limit": settings.max_chunks_per_source},
        )
    return drafts


def _requested_chunk_profile(
    parse: MarkdownParseResult,
    *,
    source_title: str,
    source_uri: str,
    text: str,
    origin_default_chunk_profile: str | None,
    knowledge_base_default_chunk_profile: str | None,
    settings_default_chunk_profile: str | None,
) -> tuple[str, str]:
    override = str(parse.frontmatter.get("chunk_profile") or "").strip()
    if override:
        if override not in VALID_CHUNK_PROFILES:
            raise KnowledgeIndexError(
                "KNOWLEDGE_INVALID_CHUNK_PROFILE",
                "Frontmatter chunk_profile must be plain_text, markdown_document, markdown_collection, or markdown_auto.",
                {"chunk_profile": override},
            )
        return override, "frontmatter"
    if origin_default_chunk_profile:
        _validate_profile(origin_default_chunk_profile, "Origin default chunk profile")
        return origin_default_chunk_profile, "origin_default"
    if knowledge_base_default_chunk_profile:
        _validate_profile(knowledge_base_default_chunk_profile, "Knowledge base default chunk profile")
        return knowledge_base_default_chunk_profile, "kb_default"
    if settings_default_chunk_profile:
        _validate_profile(settings_default_chunk_profile, "Knowledge default chunk profile")
        return settings_default_chunk_profile, "kb_default"
    if _looks_like_markdown(source_title=source_title, source_uri=source_uri, text=text, parse=parse):
        return "markdown_auto", "auto_detector"
    return "markdown_document", "fallback"


def _validate_profile(value: str, label: str) -> None:
    if value not in VALID_CHUNK_PROFILES:
        raise KnowledgeIndexError(
            "KNOWLEDGE_INVALID_CHUNK_PROFILE",
            f"{label} must be plain_text, markdown_document, markdown_collection, or markdown_auto.",
            {"chunk_profile": value},
        )


def _looks_like_markdown(*, source_title: str, source_uri: str, text: str, parse: MarkdownParseResult) -> bool:
    lower_title = source_title.lower()
    lower_uri = source_uri.lower()
    if lower_title.endswith((".md", ".markdown")) or lower_uri.endswith((".md", ".markdown")):
        return True
    if parse.frontmatter:
        return True
    if parse.headings:
        return True
    return bool(re.search(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+\S", text))


def _profile_decision(requested_profile: str, *, parse: MarkdownParseResult, source_title: str, source_uri: str, profile_source: str) -> ProfileDecision:
    if requested_profile in {"plain_text", "markdown_document", "markdown_collection"}:
        return ProfileDecision(requested=requested_profile, effective=requested_profile, confidence=1.0, document_score=0, collection_score=0, profile_source=profile_source)
    document_score, collection_score = _profile_scores(parse=parse, source_title=source_title, source_uri=source_uri)
    diff = collection_score - document_score
    if collection_score >= 3 and diff >= 2:
        confidence = min(0.95, 0.55 + (diff * 0.1))
        return ProfileDecision("markdown_auto", "markdown_collection", confidence, document_score, collection_score, profile_source)
    confidence = 0.55 if abs(diff) <= 1 else min(0.9, 0.55 + (abs(diff) * 0.08))
    return ProfileDecision("markdown_auto", "markdown_document", confidence, document_score, collection_score, profile_source)


def _profile_scores(*, parse: MarkdownParseResult, source_title: str, source_uri: str) -> tuple[int, int]:
    document_score = 0
    collection_score = 0
    filename_title = _titleized_filename(_source_path(source_title=source_title, source_uri=source_uri))
    h1 = next((heading.title for heading in parse.headings if heading.level == 1), "")
    if h1 and filename_title and _similar_title(h1, filename_title):
        document_score += 2
    if _path_entity_type(_source_path(source_title=source_title, source_uri=source_uri)) != "Document":
        document_score += 2
    for heading in parse.headings:
        normalized = _normalize_label(heading.title)
        if heading.level in {2, 3} and normalized in DOCUMENT_SECTION_HEADINGS:
            document_score += 1
        if normalized in COLLECTION_CATEGORY_HEADINGS:
            collection_score += 2
    sibling_groups: dict[tuple[int, tuple[str, ...]], list[MarkdownHeading]] = {}
    for heading in parse.headings:
        parent = heading.path[:-1]
        sibling_groups.setdefault((heading.level, parent), []).append(heading)
    for (_level, parent), siblings in sibling_groups.items():
        if len(siblings) >= 2 and parent and all(len(item.title.split()) <= 5 for item in siblings):
            collection_score += 2
            parent_label = _normalize_label(parent[-1])
            if parent_label in COLLECTION_CATEGORY_HEADINGS:
                collection_score += 2
    source_path = _source_path(source_title=source_title, source_uri=source_uri).lower()
    stem = Path(source_path.replace("\\", "/")).stem
    if stem in COLLECTION_CATEGORY_HEADINGS or (stem and _path_entity_type(source_path) == "Document" and "-" in stem):
        collection_score += 1
    return document_score, collection_score


def _document_title(*, parse: MarkdownParseResult, source_title: str) -> str:
    fm_title = str(parse.frontmatter.get("title") or "").strip()
    if fm_title:
        return fm_title
    h1 = next((heading.title for heading in parse.headings if heading.level == 1), "")
    return h1 or _titleized_filename(source_title) or (source_title.strip() or "Document")


def _document_sections(text: str, *, parse: MarkdownParseResult) -> list[MarkdownSection]:
    headings = parse.headings
    if not headings:
        return [
            MarkdownSection(
                heading=None,
                heading_path="",
                char_start=0,
                char_end=len(text),
                line_start=1,
                line_end=_line_for_char(parse.line_starts, len(text)),
                content=text,
            )
        ]
    sections: list[MarkdownSection] = []
    if parse.body_start_char < headings[0].char_start and text[parse.body_start_char : headings[0].char_start].strip():
        sections.append(
            MarkdownSection(
                heading=None,
                heading_path="",
                char_start=parse.body_start_char,
                char_end=headings[0].char_start,
                line_start=_line_for_char(parse.line_starts, parse.body_start_char),
                line_end=max(_line_for_char(parse.line_starts, headings[0].char_start) - 1, 1),
                content=text[parse.body_start_char : headings[0].char_start],
            )
        )
    for index, heading in enumerate(headings):
        next_start = headings[index + 1].char_start if index + 1 < len(headings) else len(text)
        sections.append(
            MarkdownSection(
                heading=heading,
                heading_path=" > ".join(heading.path),
                char_start=heading.char_start,
                char_end=next_start,
                line_start=heading.line_start,
                line_end=_line_for_char(parse.line_starts, next_start),
                content=text[heading.char_start : next_start],
            )
        )
    return sections


def _collection_sections(text: str, *, parse: MarkdownParseResult, entity_level: int) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    entity_headings = [heading for heading in parse.headings if heading.level == entity_level]
    for heading in entity_headings:
        end = len(text)
        for candidate in parse.headings:
            if candidate.char_start <= heading.char_start:
                continue
            if candidate.level <= entity_level:
                end = candidate.char_start
                break
        sections.append(
            MarkdownSection(
                heading=heading,
                heading_path=" > ".join(heading.path),
                char_start=heading.char_start,
                char_end=end,
                line_start=heading.line_start,
                line_end=_line_for_char(parse.line_starts, end),
                content=text[heading.char_start:end],
            )
        )
    return sections or _document_sections(text, parse=parse)


def _collection_entity_level(headings: list[MarkdownHeading]) -> int:
    for category_level, entity_level in ((2, 3), (1, 2)):
        categories = [heading for heading in headings if heading.level == category_level and _normalize_label(heading.title) in COLLECTION_CATEGORY_HEADINGS]
        for category in categories:
            children = [heading for heading in headings if heading.level == entity_level and heading.path[:-1] == category.path]
            if len(children) >= 2:
                return entity_level
        if categories:
            return entity_level
    levels = sorted({heading.level for heading in headings})
    return levels[1] if len(levels) > 1 else (levels[0] if levels else 1)


def _section_metadata(
    *,
    section: MarkdownSection,
    parse: MarkdownParseResult,
    decision: ProfileDecision,
    document_title: str,
    source_title: str,
    source_path: str,
) -> dict[str, Any]:
    fm_type = str(parse.frontmatter.get("type") or "").strip()
    if decision.effective == "markdown_collection" and section.heading is not None:
        chunk_title = section.heading.title
        title_source = "heading"
        parent = section.heading.path[-2] if len(section.heading.path) >= 2 else ""
        entity_type = fm_type or _entity_type_from_category(parent) or "Document"
        type_source = "frontmatter" if fm_type else ("parent_heading" if _entity_type_from_category(parent) else "fallback")
    else:
        chunk_title = document_title
        title_source = "frontmatter" if parse.frontmatter.get("title") else ("h1" if any(h.level == 1 for h in parse.headings) else "filename")
        entity_type = fm_type or _path_entity_type(source_path) or "Document"
        type_source = "frontmatter" if fm_type else ("path" if _path_entity_type(source_path) != "Document" else "fallback")
    return {
        "chunk_title": chunk_title,
        "document_title": document_title,
        "entity_type": entity_type,
        "heading_path": section.heading_path,
        "line_start": section.line_start,
        "line_end": section.line_end,
        "char_start": section.char_start,
        "char_end": section.char_end,
        "chunk_profile_requested": decision.requested,
        "chunk_profile_effective": decision.effective,
        "chunk_profile_confidence": round(decision.confidence, 3),
        "profile_source": decision.profile_source,
        "entity_level": decision.entity_level,
        "title_source": title_source,
        "type_source": type_source,
        "path": source_path or source_title,
    }


def _split_section(
    section: MarkdownSection,
    *,
    metadata_base: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    start_index: int,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    section_length = section.char_end - section.char_start
    local_start = 0
    while local_start < section_length:
        local_end = min(local_start + chunk_size, section_length)
        char_start = section.char_start + local_start
        char_end = section.char_start + local_end
        content = section.content[local_start:local_end]
        metadata = {
            **metadata_base,
            "line_start": _line_for_char_from_section(section, char_start),
            "line_end": _line_for_char_from_section(section, char_end),
            "char_start": char_start,
            "char_end": char_end,
        }
        drafts.append(
            ChunkDraft(
                chunk_index=start_index + len(drafts),
                heading_path=section.heading_path,
                content=content,
                char_start=char_start,
                char_end=char_end,
                token_count=max(1, round(len(content) / 4)),
                content_hash=source_content_hash(content),
                metadata=metadata,
            )
        )
        if local_end >= section_length:
            break
        local_start = local_end - chunk_overlap
    return drafts


def build_embedding_input(source_title: str, chunk: ChunkDraft) -> str:
    metadata = chunk.metadata or {}
    chunk_title = str(metadata.get("chunk_title") or source_title or "").strip()
    document_title = str(metadata.get("document_title") or "").strip()
    entity_type = str(metadata.get("entity_type") or "").strip()
    path = str(metadata.get("path") or source_title or "").strip()
    heading_path = str(metadata.get("heading_path") or chunk.heading_path or "").strip()
    header = [f"Title: {chunk_title}" if chunk_title else ""]
    if document_title and document_title != chunk_title:
        header.append(f"Document: {document_title}")
    if entity_type:
        header.append(f"Type: {entity_type}")
    if path:
        header.append(f"Path: {path}")
    if heading_path:
        header.append(f"Section: {heading_path}")
    return "\n".join([part for part in header if part] + ["", chunk.content])


def build_search_text(title: str, heading_path: str, content: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    base = "\n".join(
        part
        for part in [
            str(metadata.get("chunk_title") or ""),
            str(metadata.get("document_title") or ""),
            str(metadata.get("entity_type") or ""),
            title,
            heading_path,
            content,
        ]
        if part
    )
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
        texts=[build_embedding_input("", chunk) for chunk in chunks],
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


def _clean_heading_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("#").strip())


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _entity_type_from_category(value: str) -> str | None:
    return ENTITY_TYPE_BY_CATEGORY.get(_normalize_label(value).replace(" ", ""))


def _path_entity_type(source_path: str) -> str:
    normalized = source_path.replace("\\", "/").lower()
    parts = [part for part in normalized.split("/") if part]
    for part in parts[:-1]:
        mapped = _entity_type_from_category(part)
        if mapped:
            return mapped
    return "Document"


def _source_path(*, source_title: str, source_uri: str) -> str:
    title = source_title.strip()
    if "/" in title or "\\" in title or title.lower().endswith((".md", ".markdown", ".txt")):
        return title
    uri = source_uri.strip()
    return uri or title


def _titleized_filename(path: str) -> str:
    name = Path(path.replace("\\", "/")).name or path
    stem = re.sub(r"\.(md|markdown|txt)$", "", name, flags=re.IGNORECASE)
    words = [word for word in re.split(r"[-_\s]+", stem) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _similar_title(left: str, right: str) -> bool:
    left_norm = re.sub(r"[^a-z0-9]+", "", left.lower())
    right_norm = re.sub(r"[^a-z0-9]+", "", right.lower())
    return bool(left_norm and right_norm and (left_norm == right_norm or left_norm in right_norm or right_norm in left_norm))


def _line_for_char(line_starts: list[int], char_offset: int) -> int:
    line = 1
    for index, start in enumerate(line_starts, start=1):
        if start > char_offset:
            break
        line = index
    return line


def _line_for_char_from_section(section: MarkdownSection, char_offset: int) -> int:
    if char_offset <= section.char_start:
        return section.line_start
    prefix = section.content[: max(0, char_offset - section.char_start)]
    return section.line_start + prefix.count("\n")
