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
from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.knowledge_indexing import (
    KnowledgeIndexError,
    prepare_attachment_text_source,
    prepare_file_source,
    prepare_pasted_text_source,
)
from ai_workbench.core.knowledge_models import KnowledgeModelError, scan_local_models
from ai_workbench.core.knowledge_settings import KnowledgeSettingsPatch
from ai_workbench.core.knowledge_store import (
    EmbeddingModelProfile,
    EmbeddingModelProfileCreate,
    EmbeddingModelProfilePatch,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBasePatch,
    KnowledgeSource,
)
from ai_workbench.db.models import KnowledgeChunkRecord, KnowledgeEmbeddingRecord, KnowledgeSourceRecord


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
SOURCE_PREVIEW_MAX_CHARS = 20_000
CHUNK_CONTENT_PREVIEW_MAX_CHARS = 2_000


class EmbeddingTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    purpose: Literal["query", "document"] = "query"


class EmbeddingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_id: str
    purpose: Literal["query", "document"]
    inputs: list[str] = Field(min_length=1)


class SessionKnowledgePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_ids: list[str]


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
        return state.knowledge.patch_settings(patch.model_dump(exclude_unset=True)).model_dump(mode="json")
    except ValidationError as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_SETTING")


@router.get("/models/scan")
def scan_models(state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    inventory = scan_local_models(state.repo_root)
    # Independent reranker model management is intentionally deferred.
    inventory.pop("reranker_models", None)
    return inventory


@router.get("/embedding-models")
def list_embedding_models(state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in state.knowledge.list_embedding_profiles()]


@router.post("/embedding-models")
def create_embedding_model(payload: EmbeddingModelProfileCreate, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        profile = EmbeddingModelProfile.model_validate(payload.model_dump())
        return state.knowledge.create_embedding_profile(profile).model_dump(mode="json")
    except ValidationError as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_EMBEDDING_MODEL")
    except ValueError as exc:
        _store_error(exc)


@router.get("/embedding-models/{profile_id}")
def get_embedding_model(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        return state.knowledge.get_embedding_profile_by_id_or_alias(profile_id).model_dump(mode="json")
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")


@router.patch("/embedding-models/{profile_id}")
def patch_embedding_model(profile_id: str, payload: EmbeddingModelProfilePatch, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        return state.knowledge.update_embedding_profile(profile_id, payload.model_dump(exclude_unset=True)).model_dump(mode="json")
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    except (ValidationError, ValueError) as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_EMBEDDING_MODEL")


@router.delete("/embedding-models/{profile_id}")
def delete_embedding_model(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        profile = state.knowledge.delete_embedding_profile(profile_id)
        return {"deleted": True, "profile_id": profile.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    except ValueError as exc:
        _store_error(exc)


@router.post("/embedding-models/{profile_id}/test")
def test_embedding_model(profile_id: str, payload: EmbeddingTestRequest, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    if not payload.text.strip():
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Text must not be empty.")
    try:
        profile = state.knowledge.get_embedding_profile_by_id_or_alias(profile_id)
        settings = state.knowledge.get_settings()
        result = embed_texts(
            backend=state.knowledge_model_backend,
            profile=profile,
            texts=[payload.text],
            purpose=payload.purpose,
            device=settings.local_model_device,
            provider_profile_store=state.provider_profiles,
            repo_root=state.repo_root,
        )
        vector = (result.get("vectors") or [[]])[0]
        return {
            "ok": True,
            "model_profile_id": profile.id,
            "purpose": payload.purpose,
            "dimension": result.get("dimension", len(vector)),
            "normalized": profile.normalize,
            "sample": vector[:8],
            "provider_profile_id": result.get("provider_profile_id"),
        }
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/embeddings")
def create_embeddings(payload: EmbeddingsRequest, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    settings = state.knowledge.get_settings()
    if len(payload.inputs) > settings.embedding_batch_size:
        raise_error(422, "KNOWLEDGE_EMBEDDING_BATCH_TOO_LARGE", "Inputs exceed embedding_batch_size.")
    if any(not item.strip() for item in payload.inputs):
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Embedding inputs must not be empty.")
    try:
        profile = state.knowledge.get_embedding_profile_by_id_or_alias(payload.model_profile_id)
        return embed_texts(
            backend=state.knowledge_model_backend,
            profile=profile,
            texts=payload.inputs,
            purpose=payload.purpose,
            device=settings.local_model_device,
            provider_profile_store=state.provider_profiles,
            repo_root=state.repo_root,
        )
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {payload.model_profile_id}")
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/search")
def search(payload: KnowledgeSearchRequest, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Query must not be empty.")
    if not payload.knowledge_base_ids and not payload.session_id:
        raise_error(422, "KNOWLEDGE_SEARCH_TARGET_REQUIRED", "knowledge_base_ids or session_id is required.")
    if payload.session_id:
        _require_session(state, payload.session_id)
    try:
        state.knowledge_service.model_backend = state.knowledge_model_backend
        response = state.knowledge_service.search(
            query=query,
            knowledge_base_ids=payload.knowledge_base_ids,
            session_id=payload.session_id,
            top_k=payload.top_k,
            max_context_chars=payload.max_context_chars,
            include_debug=payload.debug,
        )
        response["context_preview"] = _context_preview(response, state)
        return response
    except KeyError as exc:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", str(exc))
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


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
        return _base_payload(state.knowledge.update_knowledge_base(knowledge_base_id, updates))
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    except ValidationError as exc:
        _validation_error(exc, "INVALID_KNOWLEDGE_BASE")


@router.delete("/bases/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
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
def create_knowledge_source(knowledge_base_id: str, payload: KnowledgeSourceCreate, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        state.knowledge.get_knowledge_base(knowledge_base_id)
        prepared = _prepare_source(payload, state)
        return _index_prepared(knowledge_base_id, prepared, state).model_dump(mode="json")
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    except KnowledgeIndexError as exc:
        raise_error(400 if exc.code.startswith("KNOWLEDGE_ATTACHMENT") else 422, exc.code, exc.message, exc.details)
    except KnowledgeModelError as exc:
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
def reindex_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        state.knowledge_service.model_backend = state.knowledge_model_backend
        return state.knowledge_service.reindex(source_id).model_dump(mode="json")
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")
    except KnowledgeIndexError as exc:
        raise_error(422, exc.code, exc.message, exc.details)
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/bases/{knowledge_base_id}/reindex")
def reindex_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict[str, Any]:
    try:
        state.knowledge_service.model_backend = state.knowledge_model_backend
        state.knowledge.get_knowledge_base(knowledge_base_id)
        results = []
        for source in state.knowledge.list_sources(knowledge_base_id):
            try:
                results.append(state.knowledge_service.reindex(source.id).model_dump(mode="json"))
            except (KnowledgeIndexError, KnowledgeModelError) as exc:
                results.append({"source_id": source.id, "status": "failed", "chunks": source.chunks, "error": str(exc)})
        return {"knowledge_base_id": knowledge_base_id, "sources": results}
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.get("/sessions/{session_id}/bindings")
def get_session_knowledge_bases(session_id: str, state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    return list_session_knowledge_bases(session_id, state)


@router.patch("/sessions/{session_id}/bindings")
def update_session_knowledge_bases(session_id: str, payload: SessionKnowledgePatch, state: RuntimeState = Depends(get_state)) -> list[dict[str, Any]]:
    return patch_session_knowledge_bases(session_id, payload, state)


def list_session_knowledge_bases(session_id: str, state: RuntimeState) -> list[dict[str, Any]]:
    _require_session(state, session_id)
    return [item.model_dump(mode="json") for item in state.knowledge.list_session_bindings(session_id)]


def patch_session_knowledge_bases(session_id: str, payload: SessionKnowledgePatch, state: RuntimeState) -> list[dict[str, Any]]:
    _require_session(state, session_id)
    try:
        return [item.model_dump(mode="json") for item in state.knowledge.replace_session_bindings(session_id, payload.knowledge_base_ids)]
    except KeyError as exc:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", str(exc))


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


def _index_prepared(knowledge_base_id: str, prepared: Any, state: RuntimeState):
    state.knowledge_service.model_backend = state.knowledge_model_backend
    return state.knowledge_service._index(knowledge_base_id, prepared)


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
    try:
        profile = state.knowledge.get_embedding_profile_by_id_or_alias(profile_id)
    except KeyError:
        raise_error(400, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    if not profile.enabled:
        raise_error(400, "KNOWLEDGE_EMBEDDING_MODEL_DISABLED", f"Embedding model profile is disabled: {profile_id}")


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


def _store_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "KNOWLEDGE_EMBEDDING_ALIAS_EXISTS":
        raise_error(409, "KNOWLEDGE_EMBEDDING_ALIAS_EXISTS", "Embedding model alias already exists.")
    if message == "KNOWLEDGE_EMBEDDING_MODEL_IN_USE":
        raise_error(409, "KNOWLEDGE_EMBEDDING_MODEL_IN_USE", "Embedding model profile is in use.")
    raise_error(422, "INVALID_KNOWLEDGE_MODEL", message)
