from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.embedding import embed_texts
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
)
from ai_workbench.core.rerank import rerank_documents


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
