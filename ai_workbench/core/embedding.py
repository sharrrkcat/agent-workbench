from pathlib import Path
from typing import Any, Literal
import math

import httpx

from ai_workbench.core.knowledge_models import KnowledgeModelError, LocalKnowledgeModelBackend
from ai_workbench.core.knowledge_store import EmbeddingModelProfile
from ai_workbench.core.provider_inventory import resolve_internal_embedding_model_ref
from ai_workbench.core.schema.llm_profile import ProviderProfileSchema


EmbeddingPurpose = Literal["query", "document"]
EXTERNAL_EMBEDDING_FAILED = "KNOWLEDGE_EXTERNAL_EMBEDDING_FAILED"
EMBEDDING_PROVIDER_NOT_CONFIGURED = "KNOWLEDGE_EMBEDDING_PROVIDER_NOT_CONFIGURED"
EMBEDDING_PROVIDER_UNSUPPORTED = "KNOWLEDGE_EMBEDDING_PROVIDER_UNSUPPORTED"
INTERNAL_EMBEDDING_UNAVAILABLE = "KNOWLEDGE_INTERNAL_EMBEDDING_UNAVAILABLE"


def embed_texts(
    *,
    backend: LocalKnowledgeModelBackend,
    profile: EmbeddingModelProfile,
    texts: list[str],
    purpose: EmbeddingPurpose,
    device: str,
    provider_profile_store: Any | None = None,
    repo_root: Path | None = None,
) -> dict:
    prepared = [_apply_instruction(text, profile, purpose) for text in texts]
    provider: ProviderProfileSchema | None = None
    if profile.provider_profile_id:
        if provider_profile_store is None:
            raise KnowledgeModelError(
                EMBEDDING_PROVIDER_NOT_CONFIGURED,
                "Embedding provider profile store is not configured.",
                {"provider_profile_id": profile.provider_profile_id},
            )
        try:
            provider = provider_profile_store.get(profile.provider_profile_id)
        except KeyError as exc:
            raise KnowledgeModelError(
                EMBEDDING_PROVIDER_NOT_CONFIGURED,
                "Embedding provider profile was not found.",
                {"provider_profile_id": profile.provider_profile_id},
            ) from exc
        if not provider.enabled:
            raise KnowledgeModelError(
                EMBEDDING_PROVIDER_NOT_CONFIGURED,
                "Embedding provider profile is disabled.",
                {"provider_profile_id": provider.id},
            )
        vectors = _embed_with_provider(provider=provider, profile=profile, prepared=prepared, normalize=profile.normalize, device=device, backend=backend, repo_root=repo_root)
    else:
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
        "provider_profile_id": provider.id if provider is not None else profile.provider_profile_id,
        "provider": provider.provider if provider is not None else None,
        "provider_model_id": profile.provider_model_id,
        "purpose": purpose,
        "dimension": dimension,
        "vectors": vectors,
    }


def legacy_model_path_for_embedding_ref(model_ref: str) -> str:
    normalized = str(model_ref or "").strip()
    if not normalized.startswith("embedding/"):
        raise ValueError("Embedding provider model id must start with embedding/.")
    return "embeddings/" + normalized.removeprefix("embedding/")


def unload_model_path_for_profile(profile: EmbeddingModelProfile, provider: ProviderProfileSchema | None = None) -> str:
    if provider is not None and provider.provider == "internal_transformers" and profile.provider_model_id:
        return legacy_model_path_for_embedding_ref(profile.provider_model_id)
    return profile.model_path


def _embed_with_provider(
    *,
    provider: ProviderProfileSchema,
    profile: EmbeddingModelProfile,
    prepared: list[str],
    normalize: bool,
    device: str,
    backend: LocalKnowledgeModelBackend,
    repo_root: Path | None,
) -> list[list[float]]:
    model_id = str(profile.provider_model_id or "").strip()
    if not model_id:
        raise KnowledgeModelError(
            EMBEDDING_PROVIDER_NOT_CONFIGURED,
            "Embedding provider model id is not configured.",
            {"provider_profile_id": provider.id},
        )
    if provider.provider == "internal_transformers":
        try:
            resolve_internal_embedding_model_ref(provider.provider, model_id, repo_root)
            return backend.embed_texts(legacy_model_path_for_embedding_ref(model_id), prepared, normalize=normalize, device=device)
        except KnowledgeModelError:
            raise
        except Exception as exc:
            raise KnowledgeModelError(INTERNAL_EMBEDDING_UNAVAILABLE, str(exc), {"provider_profile_id": provider.id, "provider_model_id": model_id}) from exc
    if provider.provider == "internal_llama_cpp":
        return _embed_with_llama_cpp(provider=provider, model_id=model_id, texts=prepared, normalize=normalize, repo_root=repo_root, backend=backend)
    if provider.provider in {"openai_compatible", "lm_studio"}:
        return _embed_openai_compatible(provider=provider, model_id=model_id, texts=prepared)
    if provider.provider == "ollama":
        return _embed_ollama(provider=provider, model_id=model_id, texts=prepared)
    raise KnowledgeModelError(
        EMBEDDING_PROVIDER_UNSUPPORTED,
        f"Provider does not support embedding generation: {provider.provider}",
        {"provider_profile_id": provider.id, "provider": provider.provider},
    )


def _embed_openai_compatible(*, provider: ProviderProfileSchema, model_id: str, texts: list[str]) -> list[list[float]]:
    url = _join_url(provider.base_url, "embeddings")
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    try:
        with httpx.Client(timeout=float(provider.timeout_seconds or 60)) as client:
            response = client.post(url, headers=headers, json={"model": model_id, "input": texts})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise KnowledgeModelError(EXTERNAL_EMBEDDING_FAILED, "External embedding provider request failed.", {"provider_profile_id": provider.id}) from exc
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise KnowledgeModelError(EXTERNAL_EMBEDDING_FAILED, "External embedding provider returned an invalid response.", {"provider_profile_id": provider.id})
    vectors: list[list[float]] = []
    for row in sorted(rows, key=lambda item: int(item.get("index", len(vectors))) if isinstance(item, dict) else len(vectors)):
        embedding = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(embedding, list):
            raise KnowledgeModelError(EXTERNAL_EMBEDDING_FAILED, "External embedding provider returned an invalid vector.", {"provider_profile_id": provider.id})
        vectors.append([float(value) for value in embedding])
    return vectors


def _embed_ollama(*, provider: ProviderProfileSchema, model_id: str, texts: list[str]) -> list[list[float]]:
    url = _join_url(provider.base_url, "api/embed")
    try:
        with httpx.Client(timeout=float(provider.timeout_seconds or 60)) as client:
            response = client.post(url, json={"model": model_id, "input": texts})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise KnowledgeModelError(EXTERNAL_EMBEDDING_FAILED, "Ollama embedding provider request failed.", {"provider_profile_id": provider.id}) from exc
    embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return [[float(value) for value in vector] for vector in embeddings]
    embedding = data.get("embedding") if isinstance(data, dict) else None
    if isinstance(embedding, list):
        return [[float(value) for value in embedding]]
    raise KnowledgeModelError(EXTERNAL_EMBEDDING_FAILED, "Ollama embedding provider returned an invalid response.", {"provider_profile_id": provider.id})


def _embed_with_llama_cpp(*, provider: ProviderProfileSchema, model_id: str, texts: list[str], normalize: bool, repo_root: Path | None, backend: LocalKnowledgeModelBackend) -> list[list[float]]:
    try:
        model_path = resolve_internal_embedding_model_ref(provider.provider, model_id, repo_root)
        embed = getattr(backend, "llama_cpp_embed_texts", None)
        if not callable(embed):
            raise KnowledgeModelError(INTERNAL_EMBEDDING_UNAVAILABLE, "llama.cpp embedding backend is not configured.", {"provider_profile_id": provider.id, "provider_model_id": model_id})
        return embed(model_path, texts, normalize=normalize)
    except KnowledgeModelError:
        raise
    except ImportError as exc:
        raise KnowledgeModelError(INTERNAL_EMBEDDING_UNAVAILABLE, "llama-cpp-python is not installed.", {"provider_profile_id": provider.id, "provider_model_id": model_id}) from exc
    except Exception as exc:
        raise KnowledgeModelError(INTERNAL_EMBEDDING_UNAVAILABLE, str(exc), {"provider_profile_id": provider.id, "provider_model_id": model_id}) from exc


def _join_url(base_url: str, suffix: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise KnowledgeModelError(EXTERNAL_EMBEDDING_FAILED, "Embedding provider base URL is not configured.")
    if suffix == "embeddings" and base.endswith("/v1"):
        return f"{base}/embeddings"
    if suffix == "embeddings":
        return f"{base}/v1/embeddings"
    return f"{base}/{suffix.lstrip('/')}"


def _apply_instruction(text: str, profile: EmbeddingModelProfile, purpose: EmbeddingPurpose) -> str:
    instruction = profile.query_instruction if purpose == "query" else profile.document_instruction
    instruction = (instruction or "").strip()
    return f"{instruction}\n{text}" if instruction else text


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
