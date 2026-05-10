from typing import Literal
import math

from ai_workbench.core.knowledge_models import KnowledgeModelError, LocalKnowledgeModelBackend
from ai_workbench.core.knowledge_store import EmbeddingModelProfile


EmbeddingPurpose = Literal["query", "document"]


def embed_texts(
    *,
    backend: LocalKnowledgeModelBackend,
    profile: EmbeddingModelProfile,
    texts: list[str],
    purpose: EmbeddingPurpose,
    device: str,
) -> dict:
    prepared = [_apply_instruction(text, profile, purpose) for text in texts]
    vectors = backend.embed_texts(profile.model_path, prepared, normalize=profile.normalize, device=device)
    if profile.normalize:
        vectors = [_normalize_vector(vector) for vector in vectors]
    dimension = len(vectors[0]) if vectors else 0
    if profile.dimension is not None and profile.dimension != dimension:
        raise KnowledgeModelError(
            "KNOWLEDGE_EMBEDDING_DIMENSION_MISMATCH",
            f"Embedding dimension mismatch: expected {profile.dimension}, got {dimension}.",
            {"expected": profile.dimension, "actual": dimension},
        )
    return {
        "model_profile_id": profile.id,
        "model_path": profile.model_path,
        "purpose": purpose,
        "dimension": dimension,
        "vectors": vectors,
    }


def _apply_instruction(text: str, profile: EmbeddingModelProfile, purpose: EmbeddingPurpose) -> str:
    instruction = profile.query_instruction if purpose == "query" else profile.document_instruction
    instruction = (instruction or "").strip()
    return f"{instruction}\n{text}" if instruction else text


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
