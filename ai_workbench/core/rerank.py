from pathlib import Path
from typing import Any

from ai_workbench.core.knowledge_models import KnowledgeModelError, LocalKnowledgeModelBackend
from ai_workbench.core.knowledge_store import RerankerModelProfile
from ai_workbench.core.provider_inventory import resolve_internal_reranker_model_ref
from ai_workbench.core.schema.llm_profile import ProviderProfileSchema


RERANKER_PROVIDER_NOT_CONFIGURED = "KNOWLEDGE_RERANKER_PROVIDER_NOT_CONFIGURED"
RERANKER_PROVIDER_UNSUPPORTED = "KNOWLEDGE_RERANKER_PROVIDER_UNSUPPORTED"
INTERNAL_RERANKER_UNAVAILABLE = "KNOWLEDGE_INTERNAL_RERANKER_UNAVAILABLE"


def rerank_documents(
    *,
    backend: LocalKnowledgeModelBackend,
    model_path: str,
    query: str,
    documents: list[dict[str, str]],
    device: str,
) -> dict:
    return {
        "ok": True,
        "model_path": model_path,
        "results": backend.rerank(model_path, query, documents, device=device),
    }


def rerank_with_profile(
    *,
    backend: LocalKnowledgeModelBackend,
    profile: RerankerModelProfile,
    provider_profile_store: Any,
    query: str,
    documents: list[dict[str, str]],
    device: str,
    repo_root: Path | None = None,
) -> dict:
    if not profile.enabled:
        raise KnowledgeModelError("KNOWLEDGE_RERANKER_MODEL_DISABLED", "Reranker model profile is disabled.", {"model_profile_id": profile.id})
    try:
        provider: ProviderProfileSchema = provider_profile_store.get(profile.provider_profile_id)
    except KeyError as exc:
        raise KnowledgeModelError(
            RERANKER_PROVIDER_NOT_CONFIGURED,
            "Reranker provider profile was not found.",
            {"provider_profile_id": profile.provider_profile_id},
        ) from exc
    if not provider.enabled:
        raise KnowledgeModelError(
            RERANKER_PROVIDER_NOT_CONFIGURED,
            "Reranker provider profile is disabled.",
            {"provider_profile_id": provider.id},
        )
    if provider.provider == "internal_transformers":
        try:
            resolve_internal_reranker_model_ref(provider.provider, profile.provider_model_id, repo_root)
            model_path = legacy_model_path_for_reranker_ref(profile.provider_model_id)
            result = rerank_documents(backend=backend, model_path=model_path, query=query, documents=documents, device=device)
            result.update({"model_profile_id": profile.id, "provider_profile_id": provider.id, "provider": provider.provider, "provider_model_id": profile.provider_model_id})
            return result
        except KnowledgeModelError:
            raise
        except Exception as exc:
            raise KnowledgeModelError(INTERNAL_RERANKER_UNAVAILABLE, str(exc), {"provider_profile_id": provider.id, "provider_model_id": profile.provider_model_id}) from exc
    if provider.provider == "internal_llama_cpp":
        return _rerank_with_llama_cpp(backend=backend, profile=profile, provider=provider, query=query, documents=documents, repo_root=repo_root)
    raise KnowledgeModelError(
        RERANKER_PROVIDER_UNSUPPORTED,
        f"Provider does not support reranking: {provider.provider}",
        {"provider_profile_id": provider.id, "provider": provider.provider},
    )


def legacy_model_path_for_reranker_ref(model_ref: str) -> str:
    normalized = str(model_ref or "").strip()
    if not normalized.startswith("reranker/"):
        raise ValueError("Reranker provider model id must start with reranker/.")
    return "rerankers/" + normalized.removeprefix("reranker/")


def unload_model_path_for_reranker_profile(profile: RerankerModelProfile, provider: ProviderProfileSchema | None = None) -> str:
    if provider is not None and provider.provider == "internal_transformers" and profile.provider_model_id:
        return legacy_model_path_for_reranker_ref(profile.provider_model_id)
    return ""


def _rerank_with_llama_cpp(
    *,
    backend: LocalKnowledgeModelBackend,
    profile: RerankerModelProfile,
    provider: ProviderProfileSchema,
    query: str,
    documents: list[dict[str, str]],
    repo_root: Path | None,
) -> dict:
    try:
        model_path = resolve_internal_reranker_model_ref(provider.provider, profile.provider_model_id, repo_root)
        rerank = getattr(backend, "llama_cpp_rerank", None)
        if not callable(rerank):
            raise KnowledgeModelError(INTERNAL_RERANKER_UNAVAILABLE, "llama.cpp reranker backend is not configured.", {"provider_profile_id": provider.id, "provider_model_id": profile.provider_model_id})
        return {
            "ok": True,
            "model_profile_id": profile.id,
            "provider_profile_id": provider.id,
            "provider": provider.provider,
            "provider_model_id": profile.provider_model_id,
            "results": rerank(model_path, query, documents),
        }
    except KnowledgeModelError:
        raise
    except ImportError as exc:
        raise KnowledgeModelError(INTERNAL_RERANKER_UNAVAILABLE, "llama-cpp-python is not installed.", {"provider_profile_id": provider.id, "provider_model_id": profile.provider_model_id}) from exc
    except Exception as exc:
        raise KnowledgeModelError(INTERNAL_RERANKER_UNAVAILABLE, str(exc), {"provider_profile_id": provider.id, "provider_model_id": profile.provider_model_id}) from exc
