from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
    prepare_pasted_text_source,
    source_content_hash,
    validate_source_limits,
)
from ai_workbench.core.knowledge_models import (
    KnowledgeModelError,
    normalize_model_path,
    scan_local_models,
)
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
from ai_workbench.core.rerank import rerank_documents
from ai_workbench.core.retrieval import search_knowledge
from ai_workbench.db.models import KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeSourceRecord


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


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


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_ids: list[str] | None = None
    session_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    max_context_chars: int | None = Field(default=None, ge=100, le=200000)
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
    try:
        profile = state.knowledge.get_embedding_profile(profile_id)
        result = embed_texts(
            backend=state.knowledge_model_backend,
            profile=profile,
            texts=[payload.text],
            purpose=payload.purpose,
            device=state.knowledge.get_settings().local_model_device,
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
        return embed_texts(
            backend=state.knowledge_model_backend,
            profile=profile,
            texts=payload.inputs,
            purpose=payload.purpose,
            device=settings.local_model_device,
        )
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
        return rerank_documents(
            backend=state.knowledge_model_backend,
            model_path=model_path,
            query=payload.query,
            documents=documents,
            device=settings.local_model_device,
        )
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
        return search_knowledge(
            engine=engine,
            knowledge_store=state.knowledge,
            model_backend=state.knowledge_model_backend,
            query=query,
            knowledge_base_ids=payload.knowledge_base_ids,
            session_id=payload.session_id,
            top_k=payload.top_k,
            max_context_chars=payload.max_context_chars,
            include_debug=payload.debug,
        )
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
        }


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
        sources = state.knowledge.list_sources(knowledge_base_id)
    except KeyError:
        raise_error(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base not found: {knowledge_base_id}")
    results = []
    for source in sources:
        try:
            source_text = _load_existing_source_text(source.id, state)
            results.append(_index_prepared_source(knowledge_base_id, source_text, state).model_dump())
        except KnowledgeIndexError as exc:
            results.append({"source_id": source.id, "status": "failed", "chunks": source.chunks, "error": exc.message})
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
    prepared = prepare_attachment_text_source(attachment_id=source.uri)
    return prepared.__class__(**{**prepared.__dict__, "source_id": source.id, "title": source.title})


def _index_prepared_source(knowledge_base_id: str, source_text, state: RuntimeState):
    settings = state.knowledge.get_settings()
    knowledge_base = state.knowledge.get_knowledge_base(knowledge_base_id)
    profile = state.knowledge.get_embedding_profile(knowledge_base.embedding_model_profile_id)
    source = KnowledgeSource(
        id=source_text.source_id,
        knowledge_base_id=knowledge_base_id,
        source_type=source_text.source_type,
        uri=source_text.uri,
        title=source_text.title,
        mime_type=source_text.mime_type,
        size_bytes=source_text.size_bytes,
        content_hash=source_text.content_hash,
        status="indexing",
        metadata=source_text.metadata,
    )
    try:
        validate_source_limits(source_text.text, source_text.size_bytes, settings)
        chunks = chunk_source_text(source_text.text, settings=settings, knowledge_base=knowledge_base)
        try:
            embedding_result = embed_chunks(
                backend=state.knowledge_model_backend,
                profile=profile,
                chunks=chunks,
                device=settings.local_model_device,
            )
        except KnowledgeModelError as exc:
            raise model_error_to_index_error(exc) from exc
        search_texts = [build_search_text(source.title, chunk.heading_path, chunk.content) for chunk in chunks]
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


def _require_session(state: RuntimeState, session_id: str) -> None:
    try:
        state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


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
