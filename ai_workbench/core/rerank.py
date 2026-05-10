from ai_workbench.core.knowledge_models import LocalKnowledgeModelBackend


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
