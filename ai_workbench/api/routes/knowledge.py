import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import select
from sqlmodel import Session as DbSession

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.knowledge_indexing import (
    KnowledgeIndexError,
    build_search_text,
    chunk_source_text,
    embed_chunks,
    model_error_to_index_error,
    prepare_attachment_text_source,
    prepare_origin_file_source,
    prepare_pasted_text_source,
    source_content_hash,
    validate_source_limits,
)
from ai_workbench.core.knowledge_context import render_knowledge_context_preview
from ai_workbench.core.knowledge_models import (
    KnowledgeModelError,
    normalize_model_path,
    safe_unload_embedding_model,
    safe_unload_reranker_model,
    scan_local_models,
)
from ai_workbench.core.knowledge_origins import (
    mark_origin_imported,
    origin_root_for_slug,
    safe_origin_slug,
    scan_origin_files,
    validate_origin_root,
)
from ai_workbench.core.knowledge_settings import KnowledgeSettingsPatch
from ai_workbench.core.knowledge_store import (
    EmbeddingModelProfile,
    EmbeddingModelProfileCreate,
    EmbeddingModelProfilePatch,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBasePatch,
    KnowledgeOrigin,
    KnowledgeOriginCreate,
    KnowledgeOriginPatch,
    KnowledgeSource,
)
from ai_workbench.core.rerank import rerank_documents
from ai_workbench.core.retrieval import expand_query_variants, search_knowledge
from ai_workbench.db.models import KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeEmbeddingRecord, KnowledgeOriginRecord, KnowledgeSourceRecord


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


class RerankDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class RerankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    documents: list[RerankDocument] = Field(min_length=1)


class SessionKnowledgePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_ids: list[str]


class KnowledgeSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["pasted_text", "attachment_text"]
    title: str | None = None
    text: str | None = None
    attachment_id: str | None = None


class KnowledgeOriginImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ids: list[str] | None = None


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_ids: list[str] | None = None
    session_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    max_context_chars: int | None = Field(default=None, ge=100, le=200000)
    min_score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    max_chunks_per_source: int | None = Field(default=None, ge=1, le=100)
    max_chunks_per_knowledge_base: int | None = Field(default=None, ge=1, le=100)
    expand_query: bool | None = None
    debug: bool = False


@router.get("/settings")
def get_knowledge_settings(state: RuntimeState = Depends(get_state)) -> dict:
    return state.knowledge.get_settings().model_dump()


@router.patch("/settings")
def patch_knowledge_settings(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        patch = KnowledgeSettingsPatch.model_validate(payload)
        updates = patch.model_dump(exclude_unset=True)
        if "reranker_model_path" in updates and updates["reranker_model_path"]:
            updates["reranker_model_path"] = normalize_model_path(updates["reranker_model_path"], "rerankers")
        return state.knowledge.patch_settings(updates).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except ValueError as exc:
        raise_error(422, "INVALID_KNOWLEDGE_SETTING", str(exc))


@router.get("/models/scan")
def scan_models(state: RuntimeState = Depends(get_state)) -> dict:
    return scan_local_models(state.repo_root)


@router.get("/embedding-models")
def list_embedding_models(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [profile.model_dump() for profile in state.knowledge.list_embedding_profiles()]


@router.post("/embedding-models")
def create_embedding_model(payload: EmbeddingModelProfileCreate, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = EmbeddingModelProfile.model_validate(
            {**payload.model_dump(), "model_path": normalize_model_path(payload.model_path, "embeddings")}
        )
        return state.knowledge.create_embedding_profile(profile).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except ValueError as exc:
        _raise_store_error(exc)


@router.get("/embedding-models/{profile_id}")
def get_embedding_model(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.knowledge.get_embedding_profile(profile_id).model_dump()
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")


@router.patch("/embedding-models/{profile_id}")
def patch_embedding_model(profile_id: str, payload: EmbeddingModelProfilePatch, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        updates = payload.model_dump(exclude_unset=True)
        if "model_path" in updates:
            updates["model_path"] = normalize_model_path(updates["model_path"], "embeddings")
        return state.knowledge.update_embedding_profile(profile_id, updates).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    except ValueError as exc:
        _raise_store_error(exc)


@router.delete("/embedding-models/{profile_id}")
def delete_embedding_model(profile_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        profile = state.knowledge.delete_embedding_profile(profile_id)
        return {"deleted": True, "profile_id": profile.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    except ValueError as exc:
        _raise_store_error(exc)


@router.post("/embedding-models/{profile_id}/test")
def test_embedding_model(profile_id: str, payload: EmbeddingTestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    if not payload.text.strip():
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Text must not be empty.")
    settings = state.knowledge.get_settings()
    try:
        profile = state.knowledge.get_embedding_profile(profile_id)
        try:
            result = embed_texts(
                backend=state.knowledge_model_backend,
                profile=profile,
                texts=[payload.text],
                purpose=payload.purpose,
                device=settings.local_model_device,
            )
            vector = result["vectors"][0]
            return {
                "ok": True,
                "model_profile_id": profile.id,
                "model_path": profile.model_path,
                "purpose": payload.purpose,
                "dimension": result["dimension"],
                "normalized": profile.normalize,
                "sample": vector[:8],
            }
        finally:
            if settings.unload_embedding_model_after_use:
                safe_unload_embedding_model(state.knowledge_model_backend, profile.model_path, settings.local_model_device)
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/embeddings")
def create_embeddings(payload: EmbeddingsRequest, state: RuntimeState = Depends(get_state)) -> dict:
    settings = state.knowledge.get_settings()
    if len(payload.inputs) > settings.embedding_batch_size:
        raise_error(422, "KNOWLEDGE_EMBEDDING_BATCH_TOO_LARGE", "Inputs exceed embedding_batch_size.")
    if any(not text.strip() for text in payload.inputs):
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Embedding inputs must not be empty.")
    try:
        profile = state.knowledge.get_embedding_profile(payload.model_profile_id)
        try:
            return embed_texts(
                backend=state.knowledge_model_backend,
                profile=profile,
                texts=payload.inputs,
                purpose=payload.purpose,
                device=settings.local_model_device,
            )
        finally:
            if settings.unload_embedding_model_after_use:
                safe_unload_embedding_model(state.knowledge_model_backend, profile.model_path, settings.local_model_device)
    except KeyError:
        raise_error(404, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {payload.model_profile_id}")
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/rerank")
def rerank(payload: RerankRequest, state: RuntimeState = Depends(get_state)) -> dict:
    settings = state.knowledge.get_settings()
    if not settings.reranker_enabled:
        raise_error(400, "KNOWLEDGE_RERANKER_DISABLED", "Reranker is disabled.")
    if not settings.reranker_model_path:
        raise_error(400, "KNOWLEDGE_RERANKER_MODEL_NOT_CONFIGURED", "Reranker model path is not configured.")
    if not payload.query.strip():
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Query must not be empty.")
    if len(payload.documents) > settings.reranker_candidate_limit:
        raise_error(422, "KNOWLEDGE_RERANKER_CANDIDATE_LIMIT_EXCEEDED", "Documents exceed reranker_candidate_limit.")
    max_text_chars = settings.default_max_context_chars
    documents = []
    for document in payload.documents:
        if not document.text.strip():
            raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Document text must not be empty.")
        if len(document.text) > max_text_chars:
            raise_error(422, "KNOWLEDGE_DOCUMENT_TOO_LARGE", "Document text exceeds max context chars.")
        documents.append(document.model_dump())
    try:
        model_path = normalize_model_path(settings.reranker_model_path, "rerankers")
        try:
            return rerank_documents(
                backend=state.knowledge_model_backend,
                model_path=model_path,
                query=payload.query,
                documents=documents,
                device=settings.local_model_device,
            )
        finally:
            if settings.unload_reranker_model_after_use:
                safe_unload_reranker_model(state.knowledge_model_backend, model_path, settings.local_model_device)
    except ValueError as exc:
        raise_error(422, "INVALID_KNOWLEDGE_MODEL_PATH", str(exc))
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.post("/search")
def search(payload: KnowledgeSearchRequest, state: RuntimeState = Depends(get_state)) -> dict:
    query = payload.query.strip()
    if not query:
        raise_error(422, "KNOWLEDGE_EMPTY_INPUT", "Query must not be empty.")
    if not payload.knowledge_base_ids and not payload.session_id:
        raise_error(422, "KNOWLEDGE_SEARCH_TARGET_REQUIRED", "knowledge_base_ids or session_id is required.")
    if payload.session_id and not payload.knowledge_base_ids:
        _require_session(state, payload.session_id)
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        raise_error(400, "KNOWLEDGE_SEARCH_STORE_UNAVAILABLE", "Knowledge search requires the SQLite knowledge store.")
    try:
        response = search_knowledge(
            engine=engine,
            knowledge_store=state.knowledge,
            model_backend=state.knowledge_model_backend,
            query=query,
            knowledge_base_ids=payload.knowledge_base_ids,
            session_id=payload.session_id,
            top_k=payload.top_k,
            max_context_chars=payload.max_context_chars,
            include_debug=payload.debug,
            min_score_threshold=payload.min_score_threshold,
            max_chunks_per_source=payload.max_chunks_per_source,
            max_chunks_per_knowledge_base=payload.max_chunks_per_knowledge_base,
            expand_query=payload.expand_query,
            query_expander=_api_query_expander(state, payload.session_id),
        )
        response["context_preview"] = _context_preview_for_search_response(response, state)
        return response
    except KeyError as exc:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", str(exc))
    except KnowledgeModelError as exc:
        raise_error(400, exc.code, exc.message, exc.details)


@router.get("/chunks/{chunk_id}")
def get_knowledge_chunk(chunk_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        raise_error(400, "KNOWLEDGE_STORE_UNAVAILABLE", "Knowledge chunks require the SQLite knowledge store.")
    with DbSession(engine) as session:
        chunk = session.get(KnowledgeChunkRecord, chunk_id)
        if chunk is None:
            raise_error(404, "KNOWLEDGE_CHUNK_NOT_FOUND", f"Knowledge chunk not found: {chunk_id}")
        source = session.get(KnowledgeSourceRecord, chunk.source_id)
        knowledge_base = session.get(KnowledgeBaseRecord, chunk.knowledge_base_id)
        if source is None or knowledge_base is None:
            raise_error(404, "KNOWLEDGE_CHUNK_NOT_FOUND", f"Knowledge chunk not found: {chunk_id}")
        return {
            "chunk_id": chunk.id,
            "knowledge_base_id": chunk.knowledge_base_id,
            "knowledge_base_name": knowledge_base.name,
            "source_id": chunk.source_id,
            "source_title": source.title,
            "heading_path": chunk.heading_path,
            "content": chunk.content,
            "chunk_index": chunk.chunk_index,
            "metadata": _loads_json(chunk.metadata_json, {}),
        }


@router.get("/sources/{source_id}/preview")
def get_knowledge_source_preview(source_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        source = state.knowledge.get_source(source_id)
        source_text = _load_existing_source_text(source_id, state)
    except KnowledgeIndexError as exc:
        raise_error(404, exc.code, exc.message, exc.details)
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")
    preview = source_text.text[:SOURCE_PREVIEW_MAX_CHARS]
    return {
        "source_id": source.id,
        "title": source.title,
        "source_type": source.source_type,
        "preview": preview,
        "truncated": len(source_text.text) > SOURCE_PREVIEW_MAX_CHARS,
        "size_bytes": source_text.size_bytes,
    }


@router.get("/sources/{source_id}/chunks")
def list_knowledge_source_chunks(source_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        raise_error(400, "KNOWLEDGE_STORE_UNAVAILABLE", "Knowledge chunks require the SQLite knowledge store.")
    with DbSession(engine) as session:
        source = session.get(KnowledgeSourceRecord, source_id)
        if source is None or source.status == "deleted":
            raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")
        chunks = session.exec(
            select(KnowledgeChunkRecord)
            .where(KnowledgeChunkRecord.source_id == source_id)
            .order_by(KnowledgeChunkRecord.chunk_index)
        ).all()
        payload = []
        for chunk in chunks:
            embedding = session.exec(
                select(KnowledgeEmbeddingRecord)
                .where(KnowledgeEmbeddingRecord.chunk_id == chunk.id)
                .order_by(KnowledgeEmbeddingRecord.created_at.desc())
            ).first()
            content_preview = chunk.content[:CHUNK_CONTENT_PREVIEW_MAX_CHARS]
            payload.append(
                {
                    "chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "heading_path": chunk.heading_path,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "metadata": _loads_json(chunk.metadata_json, {}),
                    "content": chunk.content,
                    "content_preview": content_preview,
                    "truncated": len(chunk.content) > CHUNK_CONTENT_PREVIEW_MAX_CHARS,
                    "embedding_dimension": embedding.embedding_dimension if embedding is not None else None,
                }
            )
        return {"source_id": source_id, "chunks": payload}


@router.get("/bases")
def list_knowledge_bases(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [knowledge_base.model_dump() for knowledge_base in state.knowledge.list_knowledge_bases()]


@router.post("/bases")
def create_knowledge_base(payload: KnowledgeBaseCreate, state: RuntimeState = Depends(get_state)) -> dict:
    _require_embedding_profile(state, payload.embedding_model_profile_id)
    try:
        knowledge_base = KnowledgeBase.model_validate(payload.model_dump())
        return state.knowledge.create_knowledge_base(knowledge_base).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)


@router.get("/bases/{knowledge_base_id}")
def get_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.knowledge.get_knowledge_base(knowledge_base_id).model_dump()
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.patch("/bases/{knowledge_base_id}")
def patch_knowledge_base(knowledge_base_id: str, payload: KnowledgeBasePatch, state: RuntimeState = Depends(get_state)) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if "embedding_model_profile_id" in updates:
        _require_embedding_profile(state, updates["embedding_model_profile_id"])
    try:
        return state.knowledge.update_knowledge_base(knowledge_base_id, updates).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.delete("/bases/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        knowledge_base = state.knowledge.delete_knowledge_base(knowledge_base_id)
        return {"deleted": True, "knowledge_base_id": knowledge_base.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.get("/bases/{knowledge_base_id}/sources")
def list_knowledge_sources(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    try:
        return [source.model_dump() for source in state.knowledge.list_sources(knowledge_base_id)]
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.get("/bases/{knowledge_base_id}/origins")
def list_knowledge_origins(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    try:
        return [origin.model_dump() for origin in state.knowledge.list_origins(knowledge_base_id)]
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.post("/bases/{knowledge_base_id}/origins")
def create_knowledge_origin(knowledge_base_id: str, payload: KnowledgeOriginCreate, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        state.knowledge.get_knowledge_base(knowledge_base_id)
        slug = safe_origin_slug(payload.slug)
        root = origin_root_for_slug(state.repo_root or Path("."), slug)
        root.mkdir(parents=True, exist_ok=True)
        root_path = root.relative_to((state.repo_root or Path(".")).resolve()).as_posix()
        origin = KnowledgeOrigin(
            knowledge_base_id=knowledge_base_id,
            name=payload.name,
            slug=slug,
            root_path=root_path,
            include_globs=payload.include_globs or "**/*",
            exclude_globs=payload.exclude_globs or "",
            default_chunk_profile=payload.default_chunk_profile,
        )
        return state.knowledge.create_origin(origin).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    except ValueError as exc:
        if str(exc) == "KNOWLEDGE_ORIGIN_SLUG_EXISTS":
            raise_error(409, "KNOWLEDGE_ORIGIN_SLUG_EXISTS", "Knowledge origin slug already exists for this knowledge base.")
        raise_error(422, "INVALID_KNOWLEDGE_ORIGIN", str(exc))


@router.post("/bases/{knowledge_base_id}/sources")
def create_knowledge_source(knowledge_base_id: str, payload: KnowledgeSourceCreate, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        source_text = _prepare_source_input(knowledge_base_id, payload, state)
        return _index_prepared_source(knowledge_base_id, source_text, state).model_dump()
    except KnowledgeIndexError as exc:
        raise_error(400 if exc.code.startswith("KNOWLEDGE_ATTACHMENT") else 422, exc.code, exc.message, exc.details)
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")


@router.get("/sources/{source_id}")
def get_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.knowledge.get_source(source_id).model_dump()
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")


@router.get("/origins/{origin_id}")
def get_knowledge_origin(origin_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.knowledge.get_origin(origin_id).model_dump()
    except KeyError:
        raise_error(404, "KNOWLEDGE_ORIGIN_NOT_FOUND", f"Knowledge origin not found: {origin_id}")


@router.patch("/origins/{origin_id}")
def patch_knowledge_origin(origin_id: str, payload: KnowledgeOriginPatch, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        updates = payload.model_dump(exclude_unset=True)
        updates.pop("slug", None)
        return state.knowledge.update_origin(origin_id, updates).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except KeyError:
        raise_error(404, "KNOWLEDGE_ORIGIN_NOT_FOUND", f"Knowledge origin not found: {origin_id}")
    except ValueError as exc:
        raise_error(422, "INVALID_KNOWLEDGE_ORIGIN", str(exc))


@router.delete("/origins/{origin_id}")
def delete_knowledge_origin(origin_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        origin = state.knowledge.delete_origin(origin_id)
        return {"deleted": True, "origin_id": origin.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_ORIGIN_NOT_FOUND", f"Knowledge origin not found: {origin_id}")


@router.post("/origins/{origin_id}/scan")
def scan_knowledge_origin(origin_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        raise_error(400, "KNOWLEDGE_STORE_UNAVAILABLE", "Knowledge origins require the SQLite knowledge store.")
    try:
        return scan_origin_files(
            engine=engine,
            origin_id=origin_id,
            repo_root=state.repo_root or Path("."),
            settings=state.knowledge.get_settings(),
        )
    except KeyError:
        raise_error(404, "KNOWLEDGE_ORIGIN_NOT_FOUND", f"Knowledge origin not found: {origin_id}")
    except ValueError as exc:
        raise_error(422, "INVALID_KNOWLEDGE_ORIGIN", str(exc))


@router.post("/origins/{origin_id}/import")
def import_knowledge_origin(origin_id: str, payload: KnowledgeOriginImportRequest | None = None, state: RuntimeState = Depends(get_state)) -> dict:
    engine = getattr(state.knowledge, "engine", None)
    if engine is None:
        raise_error(400, "KNOWLEDGE_STORE_UNAVAILABLE", "Knowledge origins require the SQLite knowledge store.")
    try:
        origin = state.knowledge.get_origin(origin_id)
    except KeyError:
        raise_error(404, "KNOWLEDGE_ORIGIN_NOT_FOUND", f"Knowledge origin not found: {origin_id}")
    requested = set((payload.source_ids if payload else None) or [])
    with DbSession(engine) as session:
        query = (
            select(KnowledgeSourceRecord)
            .where(KnowledgeSourceRecord.origin_id == origin_id)
            .where(
                or_(
                    KnowledgeSourceRecord.status.in_(["new", "needs_reindex", "failed", "missing"]),
                    KnowledgeSourceRecord.file_status.in_(["changed", "new"]),
                )
            )
            .order_by(KnowledgeSourceRecord.relative_path)
        )
        records = session.exec(query).all()
        candidates = [record for record in records if not requested or record.id in requested]
    summary: dict[str, Any] = {
        "origin_id": origin_id,
        "imported_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "new_count": 0,
        "changed_count": 0,
        "missing_count": 0,
        "unchanged_count": 0,
        "warnings": [],
        "sources": [],
    }
    root = validate_origin_root(state.repo_root or Path("."), origin.slug, origin.root_path)
    try:
        for record in candidates:
            if record.status == "missing":
                summary["missing_count"] += 1
                summary["skipped_count"] += 1
                continue
            source_path = (root / record.relative_path).resolve()
            try:
                source_text = prepare_origin_file_source(
                    origin_id=origin_id,
                    path=source_path,
                    root=root,
                    uri_prefix=f"data/knowledge/origins/{origin.slug}",
                    source_id=record.id,
                )
                result = _index_prepared_source(origin.knowledge_base_id, source_text, state).model_dump()
                summary["imported_count"] += 1
                if record.indexed_at is None:
                    summary["new_count"] += 1
                else:
                    summary["changed_count"] += 1
                summary["sources"].append(result)
            except KnowledgeIndexError as exc:
                state.knowledge.mark_source_failed(_source_from_origin_record(record), exc.message)
                summary["failed_count"] += 1
                summary["warnings"].append(f"{record.relative_path}: {exc.message}")
                summary["sources"].append({"source_id": record.id, "status": "failed", "chunks": 0, "error": exc.message})
    finally:
        mark_origin_imported(engine=engine, origin_id=origin_id, summary=summary)
    return summary


@router.delete("/sources/{source_id}")
def delete_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        source = state.knowledge.delete_source(source_id)
        return {"deleted": True, "source_id": source.id}
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")


@router.post("/sources/{source_id}/reindex")
def reindex_knowledge_source(source_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        source = state.knowledge.get_source(source_id)
        source_text = _load_existing_source_text(source_id, state)
        return _index_prepared_source(source.knowledge_base_id, source_text, state).model_dump()
    except KnowledgeIndexError as exc:
        raise_error(400 if exc.code.startswith("KNOWLEDGE_ATTACHMENT") else 422, exc.code, exc.message, exc.details)
    except KeyError:
        raise_error(404, "KNOWLEDGE_SOURCE_NOT_FOUND", f"Knowledge source not found: {source_id}")


@router.post("/bases/{knowledge_base_id}/reindex")
def reindex_knowledge_base(knowledge_base_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        knowledge_base = state.knowledge.get_knowledge_base(knowledge_base_id)
        profile = state.knowledge.get_embedding_profile(knowledge_base.embedding_model_profile_id)
        sources = state.knowledge.list_sources(knowledge_base_id)
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    results = []
    settings = state.knowledge.get_settings()
    try:
        for source in sources:
            try:
                source_text = _load_existing_source_text(source.id, state)
                results.append(_index_prepared_source(knowledge_base_id, source_text, state, unload_after_use=False).model_dump())
            except KnowledgeIndexError as exc:
                results.append({"source_id": source.id, "status": "failed", "chunks": source.chunks, "error": exc.message})
    finally:
        if settings.unload_embedding_model_after_use:
            safe_unload_embedding_model(state.knowledge_model_backend, profile.model_path, settings.local_model_device)
    return {"knowledge_base_id": knowledge_base_id, "sources": results}


def list_session_knowledge_bases(session_id: str, state: RuntimeState) -> list[dict]:
    _require_session(state, session_id)
    return [binding.model_dump() for binding in state.knowledge.list_session_bindings(session_id)]


def patch_session_knowledge_bases(session_id: str, payload: SessionKnowledgePatch, state: RuntimeState) -> list[dict]:
    _require_session(state, session_id)
    try:
        return [binding.model_dump() for binding in state.knowledge.replace_session_bindings(session_id, payload.knowledge_base_ids)]
    except KeyError as exc:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", str(exc))


def _require_embedding_profile(state: RuntimeState, profile_id: str) -> None:
    try:
        profile = state.knowledge.get_embedding_profile(profile_id)
    except KeyError:
        raise_error(400, "KNOWLEDGE_EMBEDDING_MODEL_NOT_FOUND", f"Embedding model profile not found: {profile_id}")
    if not profile.enabled:
        raise_error(400, "KNOWLEDGE_EMBEDDING_MODEL_DISABLED", f"Embedding model profile is disabled: {profile_id}")


def _prepare_source_input(knowledge_base_id: str, payload: KnowledgeSourceCreate, state: RuntimeState):
    state.knowledge.get_knowledge_base(knowledge_base_id)
    if payload.source_type == "pasted_text":
        if not payload.text or not payload.text.strip():
            raise KnowledgeIndexError("KNOWLEDGE_EMPTY_INPUT", "Pasted text must not be empty.")
        prepared = prepare_pasted_text_source(root=state.repo_root or Path("."), title=payload.title or "Pasted text", text=payload.text)
    else:
        if not payload.attachment_id:
            raise KnowledgeIndexError("KNOWLEDGE_ATTACHMENT_NOT_FOUND", "attachment_id is required.")
        prepared = prepare_attachment_text_source(attachment_id=payload.attachment_id)
        if payload.title and payload.title.strip():
            prepared = prepared.__class__(**{**prepared.__dict__, "title": payload.title.strip()})
    return prepared


def _load_existing_source_text(source_id: str, state: RuntimeState):
    source = state.knowledge.get_source(source_id)
    if source.source_type == "pasted_text":
        root = state.repo_root or Path(".")
        path = (root / source.uri).resolve()
        sources_root = (root / "data" / "knowledge" / "sources").resolve()
        try:
            path.relative_to(sources_root)
        except ValueError as exc:
            raise KnowledgeIndexError("KNOWLEDGE_SOURCE_NOT_READABLE", "Pasted text source path is invalid.") from exc
        if not path.is_file():
            raise KnowledgeIndexError("KNOWLEDGE_SOURCE_NOT_READABLE", "Pasted text source file was not found.")
        text = path.read_text(encoding="utf-8")
        return prepare_pasted_text_source(root=root, title=source.title, text=text, source_id=source.id)
    if source.source_type == "origin_file":
        if not source.origin_id:
            raise KnowledgeIndexError("KNOWLEDGE_ORIGIN_NOT_FOUND", "Origin source has no origin_id.")
        origin = state.knowledge.get_origin(source.origin_id)
        root = validate_origin_root(state.repo_root or Path("."), origin.slug, origin.root_path)
        if not source.relative_path:
            raise KnowledgeIndexError("KNOWLEDGE_ORIGIN_PATH_INVALID", "Origin source has no relative path.")
        return prepare_origin_file_source(
            origin_id=origin.id,
            path=root / source.relative_path,
            root=root,
            uri_prefix=f"data/knowledge/origins/{origin.slug}",
            source_id=source.id,
        )
    prepared = prepare_attachment_text_source(attachment_id=source.uri)
    return prepared.__class__(**{**prepared.__dict__, "source_id": source.id, "title": source.title})


def _index_prepared_source(knowledge_base_id: str, source_text, state: RuntimeState, *, unload_after_use: bool = True):
    settings = state.knowledge.get_settings()
    knowledge_base = state.knowledge.get_knowledge_base(knowledge_base_id)
    profile = state.knowledge.get_embedding_profile(knowledge_base.embedding_model_profile_id)
    source = KnowledgeSource(
        id=source_text.source_id,
        knowledge_base_id=knowledge_base_id,
        origin_id=source_text.origin_id,
        source_type=source_text.source_type,
        uri=source_text.uri,
        title=source_text.title,
        relative_path=source_text.relative_path,
        virtual_path=source_text.virtual_path,
        folder_path=source_text.folder_path,
        file_name=source_text.file_name,
        extension=source_text.extension,
        path_depth=source_text.path_depth,
        file_status="ready",
        source_mtime=source_text.source_mtime,
        source_size_bytes=source_text.size_bytes,
        mime_type=source_text.mime_type,
        size_bytes=source_text.size_bytes,
        content_hash=source_text.content_hash,
        status="indexing",
        metadata=source_text.metadata,
    )
    try:
        validate_source_limits(source_text.text, source_text.size_bytes, settings)
        chunks = chunk_source_text(
            source_text.text,
            settings=settings,
            knowledge_base=knowledge_base,
            source_title=source.title,
            source_uri=source.uri,
            origin_default_chunk_profile=_origin_default_chunk_profile(state, source_text.origin_id),
        )
        source.metadata = _source_profile_metadata(source.metadata, chunks)
        try:
            embedding_result = embed_chunks(
                backend=state.knowledge_model_backend,
                profile=profile,
                chunks=chunks,
                device=settings.local_model_device,
            )
        except KnowledgeModelError as exc:
            raise model_error_to_index_error(exc) from exc
        search_texts = [build_search_text(source.title, chunk.heading_path, chunk.content, chunk.metadata) for chunk in chunks]
        return state.knowledge.upsert_indexed_source(
            source=source,
            chunks=chunks,
            vectors=embedding_result["vectors"],
            embedding_model_profile=profile,
            embedding_dimension=embedding_result["dimension"],
            search_texts=search_texts,
        )
    except KnowledgeIndexError as exc:
        state.knowledge.mark_source_failed(source, exc.message)
        raise
    finally:
        if unload_after_use and settings.unload_embedding_model_after_use:
            safe_unload_embedding_model(state.knowledge_model_backend, profile.model_path, settings.local_model_device)


def _require_session(state: RuntimeState, session_id: str) -> None:
    try:
        state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _api_query_expander(state: RuntimeState, session_id: str | None):
    if not session_id:
        return None
    try:
        state.sessions.get_session(session_id)
    except KeyError:
        return None
    try:
        llm_runtime = state.runtimes.get_runtime("llm")
    except KeyError:
        return None

    def expand(query: str, max_variants: int, prompt_template: str) -> list[str]:
        return expand_query_variants(
            llm_runtime=llm_runtime,
            query=query,
            max_variants=max_variants,
            prompt_template=prompt_template,
            model_config={},
        )

    return expand


def _context_preview_for_search_response(response: dict, state: RuntimeState) -> str:
    results = list(response.get("results") or []) if isinstance(response, dict) else []
    kb_names = {}
    for result in results:
        knowledge_base_id = result.get("knowledge_base_id") if isinstance(result, dict) else None
        if not knowledge_base_id or knowledge_base_id in kb_names:
            continue
        try:
            kb_names[str(knowledge_base_id)] = state.knowledge.get_knowledge_base(str(knowledge_base_id)).name
        except KeyError:
            kb_names[str(knowledge_base_id)] = str(knowledge_base_id)
    return render_knowledge_context_preview(settings=state.knowledge.get_settings(), results=results, knowledge_base_names=kb_names)


def _raise_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_KNOWLEDGE_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_KNOWLEDGE_VALUE"
    loc = ".".join(str(item) for item in error.get("loc", []))
    message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
    raise_error(422, code, message)


def _raise_store_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "KNOWLEDGE_EMBEDDING_ALIAS_EXISTS":
        raise_error(409, "KNOWLEDGE_EMBEDDING_ALIAS_EXISTS", "Embedding model alias already exists.")
    if message == "KNOWLEDGE_EMBEDDING_MODEL_IN_USE":
        raise_error(409, "KNOWLEDGE_EMBEDDING_MODEL_IN_USE", "Embedding model profile is used by a knowledge base.")
    raise_error(422, "INVALID_KNOWLEDGE_VALUE", message)


def _source_from_origin_record(record: KnowledgeSourceRecord) -> KnowledgeSource:
    return KnowledgeSource(
        id=record.id,
        knowledge_base_id=record.knowledge_base_id,
        origin_id=record.origin_id,
        source_type="origin_file",
        uri=record.uri,
        title=record.title or record.relative_path or record.id,
        relative_path=record.relative_path,
        virtual_path=record.virtual_path,
        folder_path=record.folder_path,
        file_name=record.file_name,
        extension=record.extension,
        path_depth=record.path_depth,
        file_status=record.file_status,
        source_mtime=record.source_mtime,
        source_size_bytes=record.source_size_bytes,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        content_hash=record.content_hash,
        status="failed",
        metadata=_loads_json(record.metadata_json, {}),
    )


def _origin_default_chunk_profile(state: RuntimeState, origin_id: str | None) -> str | None:
    if not origin_id:
        return None
    try:
        return state.knowledge.get_origin(origin_id).default_chunk_profile
    except KeyError:
        return None


def _source_profile_metadata(metadata: dict, chunks: list) -> dict:
    first = next((chunk.metadata for chunk in chunks if getattr(chunk, "metadata", None)), {})
    compact_keys = [
        "chunk_profile_requested",
        "chunk_profile_effective",
        "chunk_profile_confidence",
        "profile_source",
        "entity_level",
        "title_source",
        "type_source",
    ]
    compact = {key: first.get(key) for key in compact_keys if first.get(key) is not None}
    return {**(metadata or {}), **compact}


def _loads_json(value: str, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
