"""Knowledge base HTTP API.

Phase 1 deliberately keeps this surface small: sources are created directly
from text, an attachment, or a workspace path. There is no origin/import
layer and no public reranker endpoint; retrieval always has an RRF fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session as DbSession, select

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.knowledge_indexing import (
    KnowledgeIndexError,
    prepare_attachment_text_source,
    prepare_file_source,
    prepare_pasted_text_source,
)
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.knowledge_settings import KnowledgeSettingsPatch
from ai_workbench.core.knowledge_store import (
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBasePatch,
    KnowledgeSource,
)
from ai_workbench.db.models import KnowledgeChunkRecord, KnowledgeEmbeddingRecord, KnowledgeSourceRecord


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
SOURCE_PREVIEW_MAX_CHARS = 20_000
CHUNK_CONTENT_PREVIEW_MAX_CHARS = 2_000


class KnowledgeSourceCreate(BaseModel):
    """Create a source directly; ``path`` and ``uri`` are workspace-relative."""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["pasted_text", "attachment_text", "file"] = "pasted_text"
    title: str | None = None
    text: str | None = None
    path: str | None = None
    uri: str | None = None
    attachment_id: str | None = None


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_ids: list[str] | None = None
    session_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    max_context_chars: int | None = Field(default=None, ge=100, le=200_000)
    min_score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    max_chunks_per_source: int | None = Field(default=None, ge=1, le=100)
    max_chunks_per_knowledge_base: int | None = Field(default=None, ge=1, le=100)
    debug: bool = False


@router.get("/settings")
def get_knowledge_settings(state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    return state.knowledge.get_settings().model_dump(mode="json")


@router.patch("/settings")
def patch_knowledge_settings(payload: dict[str, Any], state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        patch = KnowledgeSettingsPatch.model_validate(payload)
        if patch.reranker_model_profile_id:
            state.model_manager.profile(patch.reranker_model_profile_id, "reranker")
        return state.knowledge.patch_settings(patch.model_dump(exclude_unset=True)).model_dump(mode="json")
    except ValidationError as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_SETTING")


@router.post("/search")
async def search(payload: KnowledgeSearchRequest, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Query must not be empty.")
    if not payload.knowledge_base_ids and not payload.session_id:
        raise_error(422, "KNOWLEDGE_SEARCH_TARGET_REQUIRED", "knowledge_base_ids or session_id is required.")
    if payload.session_id:
        _require_session(state, payload.session_id)
    try:
        response = await state.knowledge_service.search(
            query=query,
            knowledge_base_ids=payload.knowledge_base_ids,
            session_id=payload.session_id,
            top_k=payload.top_k,
            max_context_chars=payload.max_context_chars,
            include_debug=payload.debug,
            min_score_threshold=payload.min_score_threshold,
            max_chunks_per_source=payload.max_chunks_per_source,
            max_chunks_per_knowledge_base=payload.max_chunks_per_knowledge_base,
        )
        response["context_preview"] = _context_preview(response, state)
        return response
    except KeyError as exc:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", str(exc))
    except ModelError as exc:
        raise_error(400, exc.code, exc.message)


@router.get("/chunks/{chunk_id}")
def get_knowledge_chunk(chunk_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        raise_error(404, "KNOWLEDGE_CHUNK_NOT_FOUND", f"Knowledge chunk not found: {chunk_id}")
    with DbSession(engine) as db:
        chunk = db.get(KnowledgeChunkRecord, chunk_id)
        if chunk is None:
            raise_error(404, "KNOWLEDGE_CHUNK_NOT_FOUND", f"Knowledge chunk not found: {chunk_id}")
        source = db.get(KnowledgeSourceRecord, chunk.source_id)
        return {
            "chunk_id": chunk.id,
            "knowledge_base_id": chunk.knowledge_base_id,
            "source_id": chunk.source_id,
            "source_title": source.title if source else "",
            "chunk_index": chunk.chunk_index,
            "heading_path": chunk.heading_path,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "content": chunk.content,
            "metadata": _json_load(chunk.metadata_json, {}),
        }


@router.get("/sources/{source_id}/preview")
def get_knowledge_source_preview(source_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    source = _source_or_404(state, source_id)
    text = _read_source_text(source, state)
    return {
        "source_id": source.id,
        "title": source.title,
        "uri": source.uri,
        "content": text[:SOURCE_PREVIEW_MAX_CHARS],
        "truncated": len(text) > SOURCE_PREVIEW_MAX_CHARS,
    }


@router.get("/sources/{source_id}/chunks")
def list_knowledge_source_chunks(source_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    source = _source_or_404(state, source_id)
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        chunks = [
            {"chunk_index": item.chunk_index, "heading_path": item.heading_path, "content": item.content}
            for item in state.knowledge.list_chunks(source_id)
        ]
        return {"source_id": source.id, "chunks": chunks}
    with DbSession(engine) as db:
        rows = db.exec(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.source_id == source_id).order_by(KnowledgeChunkRecord.chunk_index)).all()
        return {"source_id": source.id, "chunks": [_chunk_payload(row, db) for row in rows]}


@router.get("/bases")
def list_knowledge_bases(state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    return [_base_payload(item) for item in state.knowledge.list_knowledge_bases()]


@router.post("/bases")
def create_knowledge_base(payload: KnowledgeBaseCreate, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    _require_embedding_profile(state, payload.embedding_model_profile_id)
    try:
        base = KnowledgeBase.model_validate(payload.model_dump())
        return _base_payload(state.knowledge.create_knowledge_base(base))
    except ValidationError as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_BASE")


@router.get("/bases/{knowledge_base_id}")
def get_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        return _base_payload(state.knowledge.get_knowledge_base(knowledge_base_id))
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.patch("/bases/{knowledge_base_id}")
def patch_knowledge_base(knowledge_base_id: str, payload: KnowledgeBasePatch, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("embedding_model_profile_id"):
        _require_embedding_profile(state, updates["embedding_model_profile_id"])
    try:
        current = state.knowledge.get_knowledge_base(knowledge_base_id)
        if "embedding_model_profile_id" in updates and updates["embedding_model_profile_id"] != current.embedding_model_profile_id:
            state.knowledge.invalidate_base_index(knowledge_base_id)
            updates["index_status"] = "needs_reindex"
        return _base_payload(state.knowledge.update_knowledge_base(knowledge_base_id, updates))
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    except ValidationError as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_BASE")


@router.delete("/bases/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    if state.personas.references_resource("knowledge", knowledge_base_id):
        raise_error(409, "KNOWLEDGE_BASE_IN_USE", "Remove persona bindings before deleting this Knowledge Base.")
    try:
        base = state.knowledge.delete_knowledge_base(knowledge_base_id)
        return {"deleted": True, "knowledge_base_id": base.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.get("/bases/{knowledge_base_id}/sources")
def list_knowledge_sources(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    try:
        state.knowledge.get_knowledge_base(knowledge_base_id)
        return [item.model_dump(mode="json") for item in state.knowledge.list_sources(knowledge_base_id)]
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.post("/bases/{knowledge_base_id}/sources")
async def create_knowledge_source(knowledge_base_id: str, payload: KnowledgeSourceCreate, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        state.knowledge.get_knowledge_base(knowledge_base_id)
        prepared = _prepare_source(payload, state)
        return (await _index_prepared(knowledge_base_id, prepared, state)).model_dump(mode="json")
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    except KnowledgeIndexError as exc:
        raise_error(400 if exc.code.startswith("KNOWLEDGE_ATTACHMENT") else 422, exc.code, exc.message, exc.details)
    except ModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.get("/sources/{source_id}")
def get_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    return _source_or_404(state, source_id).model_dump(mode="json")


@router.delete("/sources/{source_id}")
def delete_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        source = state.knowledge.delete_source(source_id)
        return {"deleted": True, "source_id": source.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")


@router.post("/sources/{source_id}/reindex")
async def reindex_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        return (await state.knowledge_service.reindex(source_id)).model_dump(mode="json")
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")
    except KnowledgeIndexError as exc:
        raise_error(422, exc.code, exc.message, exc.details)
    except ModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/bases/{knowledge_base_id}/reindex")
async def reindex_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        state.knowledge.get_knowledge_base(knowledge_base_id)
        results = []
        for source in state.knowledge.list_sources(knowledge_base_id):
            try:
                results.append((await state.knowledge_service.reindex(source.id)).model_dump(mode="json"))
            except (KnowledgeIndexError, ModelError) as exc:
                results.append({"source_id": source.id, "status": "failed", "chunks": source.chunks, "error": str(exc)})
        return {"knowledge_base_id": knowledge_base_id, "sources": results}
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


def _prepare_source(payload: KnowledgeSourceCreate, state: RuntimeState):
    if payload.source_type == "pasted_text":
        if not payload.text or not payload.text.strip():
            raise KnowledgeIndexError("KNOWLEDGE_EMPTY_INPUT", "Pasted text must not be empty.")
        return prepare_pasted_text_source(root=state.repo_root, title=payload.title or "Pasted text", text=payload.text)
    if payload.source_type == "attachment_text":
        if not payload.attachment_id:
            raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_FOUND", "attachment_id is required.")
        source = prepare_attachment_text_source(attachment_id=payload.attachment_id)
        if payload.title:
            source = source.__class__(**{**source.__dict__, "title": payload.title.strip()})
        return source
    raw_path = payload.path or payload.uri
    if not raw_path:
        raise KnowledgeIndexError("KNOWLEDGE_FILE_NOT_FOUND", "path or uri is required for a file source.")
    path = Path(raw_path)
    if not path.is_absolute():
        path = state.repo_root / path
    source = prepare_file_source(path=path, root=state.repo_root)
    if payload.title:
        source = source.__class__(**{**source.__dict__, "title": payload.title.strip()})
    return source


def _require_session(state: RuntimeState, session_id: str) -> Any:
    try:
        return state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


async def _index_prepared(knowledge_base_id: str, prepared: Any, state: RuntimeState):
    return await state.knowledge_service.index_source(knowledge_base_id, prepared)


def _source_or_404(state: RuntimeState, source_id: str) -> KnowledgeSource:
    try:
        return state.knowledge.get_source(source_id)
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")


def _read_source_text(source: KnowledgeSource, state: RuntimeState) -> str:
    if source.source_type in {"pasted_text", "file"} and source.uri:
        path = (state.repo_root / source.uri).resolve()
        if source.source_type == "pasted_text":
            root = (state.repo_root / "data" / "knowledge" / "sources").resolve()
            try:
                path.relative_to(root)
            except ValueError:
                raise_error(422, "KNOWLEDGE_SOURCE_NOT_READABLE", "Source path is invalid.")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise_error(422, "KNOWLEDGE_SOURCE_NOT_READABLE", "Source cannot be read.")
    return str((source.metadata or {}).get("text") or "")


def _require_embedding_profile(state: RuntimeState, profile_id: str) -> None:
    state.model_manager.profile(profile_id, "embedding")


def _base_payload(base: KnowledgeBase) -> dict[str, Any]:
    return base.model_dump(mode="json")


def _context_preview(response: dict[str, Any], state: RuntimeState) -> str:
    from ai_workbench.core.knowledge_context import render_knowledge_context_preview

    return render_knowledge_context_preview(settings=state.knowledge.get_settings(), results=list(response.get("results") or []))


def _chunk_payload(row: Any, db: Any) -> dict[str, Any]:
    embedding = db.exec(select(KnowledgeEmbeddingRecord).where(KnowledgeEmbeddingRecord.chunk_id == row.id).order_by(KnowledgeEmbeddingRecord.created_at.desc())).first()
    return {
        "chunk_id": row.id,
        "chunk_index": row.chunk_index,
        "heading_path": row.heading_path,
        "char_start": row.char_start,
        "char_end": row.char_end,
        "content": row.content,
        "content_preview": row.content[:CHUNK_CONTENT_PREVIEW_MAX_CHARS],
        "truncated": len(row.content) > CHUNK_CONTENT_PREVIEW_MAX_CHARS,
        "metadata": _json_load(row.metadata_json, {}),
        "embedding_dimension": embedding.embedding_dimension if embedding else None,
    }


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback



def _validation_error(exc: Exception, code: str) -> None:
    errors = exc.errors() if hasattr(exc, "errors") else []
    first = errors[0] if errors else {}
    loc = ".".join(str(item) for item in first.get("loc", []))
    message = f"{loc}: {first.get('msg', 'Invalid value')}" if loc else str(exc)
    raise_error(422, code, message)
