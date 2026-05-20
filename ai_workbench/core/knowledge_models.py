from __future__ import annotations

import gc
import importlib.util
import logging
import math
from pathlib import Path, PurePosixPath
from typing import Any


LOCAL_MODEL_BACKEND_UNAVAILABLE = "KNOWLEDGE_LOCAL_MODEL_BACKEND_UNAVAILABLE"
MODEL_NOT_FOUND = "KNOWLEDGE_MODEL_NOT_FOUND"
logger = logging.getLogger(__name__)


class KnowledgeModelError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def models_root_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "models"


def knowledge_sources_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "knowledge" / "sources"


def ensure_knowledge_directories(root: Path | None = None) -> None:
    base = models_root_path(root)
    (base / "embeddings").mkdir(parents=True, exist_ok=True)
    (base / "rerankers").mkdir(parents=True, exist_ok=True)
    knowledge_sources_path(root).mkdir(parents=True, exist_ok=True)


def normalize_model_path(value: str, expected_kind: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("Model path must not be empty.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Model path must be a safe relative path inside data/models.")
    if len(path.parts) != 2 or path.parts[0] != expected_kind:
        raise ValueError(f"Model path must be shaped as {expected_kind}/<folder>.")
    return path.as_posix()


def resolve_model_path(model_path: str, expected_kind: str, root: Path | None = None) -> Path:
    normalized = normalize_model_path(model_path, expected_kind)
    base = models_root_path(root).resolve()
    resolved = (base / normalized).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Model path must stay inside data/models.") from exc
    return resolved


def scan_local_models(root: Path | None = None) -> dict[str, Any]:
    ensure_knowledge_directories(root)
    base = models_root_path(root)
    return {
        "models_root": "data/models",
        "embedding_models": _scan_directories(base / "embeddings", "embeddings"),
        "reranker_models": _scan_directories(base / "rerankers", "rerankers"),
        "backend": backend_availability(),
    }


def _scan_directories(path: Path, prefix: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and not child.is_symlink():
            items.append({"model_path": f"{prefix}/{child.name}", "name": child.name, "exists": True})
    return items


def backend_availability() -> dict[str, Any]:
    sentence_transformers_available = importlib.util.find_spec("sentence_transformers") is not None
    torch_available = importlib.util.find_spec("torch") is not None
    transformers_available = importlib.util.find_spec("transformers") is not None
    cuda_available = False
    if torch_available:
        try:
            import torch  # type: ignore

            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    return {
        "sentence_transformers_available": sentence_transformers_available,
        "torch_available": torch_available,
        "transformers_available": transformers_available,
        "cuda_available": cuda_available,
        "available": sentence_transformers_available and torch_available,
    }


def resolve_device(requested: str) -> str:
    requested = requested or "auto"
    availability = backend_availability()
    if requested == "cuda":
        if not availability["torch_available"] or not availability["cuda_available"]:
            raise KnowledgeModelError(
                LOCAL_MODEL_BACKEND_UNAVAILABLE,
                "CUDA was selected, but torch CUDA is not available.",
                availability,
            )
        return "cuda"
    if requested == "auto":
        return "cuda" if availability["torch_available"] and availability["cuda_available"] else "cpu"
    if requested == "cpu":
        return "cpu"
    raise ValueError("local_model_device must be auto, cpu, or cuda.")


class LocalKnowledgeModelBackend:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or repo_root()
        self._embedding_cache: dict[tuple[str, str], Any] = {}
        self._reranker_cache: dict[tuple[str, str], Any] = {}
        self._active_embedding_calls = 0
        self._active_reranker_calls = 0

    def embed_texts(self, model_path: str, texts: list[str], normalize: bool, device: str) -> list[list[float]]:
        self._active_embedding_calls += 1
        try:
            availability = backend_availability()
            if not availability["sentence_transformers_available"] or not availability["torch_available"]:
                raise KnowledgeModelError(LOCAL_MODEL_BACKEND_UNAVAILABLE, "Optional local model dependencies are not installed.", availability)
            resolved_device = resolve_device(device)
            absolute_path = resolve_model_path(model_path, "embeddings", self.root)
            if not absolute_path.is_dir():
                raise KnowledgeModelError(MODEL_NOT_FOUND, f"Embedding model not found: {model_path}")
            model = self._load_embedding_model(absolute_path, resolved_device)
            vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=normalize)
            return _vectors_to_lists(vectors, normalize=normalize)
        finally:
            self._active_embedding_calls = max(0, self._active_embedding_calls - 1)

    def rerank(self, model_path: str, query: str, documents: list[dict[str, str]], device: str) -> list[dict[str, Any]]:
        self._active_reranker_calls += 1
        try:
            availability = backend_availability()
            if not availability["sentence_transformers_available"] or not availability["torch_available"]:
                raise KnowledgeModelError(LOCAL_MODEL_BACKEND_UNAVAILABLE, "Optional local model dependencies are not installed.", availability)
            resolved_device = resolve_device(device)
            absolute_path = resolve_model_path(model_path, "rerankers", self.root)
            if not absolute_path.is_dir():
                raise KnowledgeModelError(MODEL_NOT_FOUND, f"Reranker model not found: {model_path}")
            model = self._load_reranker_model(absolute_path, resolved_device)
            scores = model.predict([(query, document["text"]) for document in documents])
            results = [
                {"id": document["id"], "score": float(score)}
                for document, score in zip(documents, list(scores), strict=False)
            ]
            return sorted(results, key=lambda item: item["score"], reverse=True)
        finally:
            self._active_reranker_calls = max(0, self._active_reranker_calls - 1)

    def _load_embedding_model(self, path: Path, device: str) -> Any:
        key = (str(path), device)
        if key not in self._embedding_cache:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._embedding_cache[key] = SentenceTransformer(str(path), device=device)
        return self._embedding_cache[key]

    def _load_reranker_model(self, path: Path, device: str) -> Any:
        key = (str(path), device)
        if key not in self._reranker_cache:
            from sentence_transformers import CrossEncoder  # type: ignore

            self._reranker_cache[key] = CrossEncoder(str(path), device=device)
        return self._reranker_cache[key]

    def embedding_model_loaded(self, model_path: str, device: str | None = None) -> bool:
        absolute_path = resolve_model_path(model_path, "embeddings", self.root)
        resolved_device = resolve_device(device) if device else None
        return any(path == str(absolute_path) and (resolved_device is None or cached_device == resolved_device) for path, cached_device in self._embedding_cache)

    def reranker_model_loaded(self, model_path: str, device: str | None = None) -> bool:
        absolute_path = resolve_model_path(model_path, "rerankers", self.root)
        resolved_device = resolve_device(device) if device else None
        return any(path == str(absolute_path) and (resolved_device is None or cached_device == resolved_device) for path, cached_device in self._reranker_cache)

    def unload_embedding_model(self, model_path: str, device: str | None = None) -> bool:
        absolute_path = resolve_model_path(model_path, "embeddings", self.root)
        resolved_device = resolve_device(device) if device else None
        removed = _drop_cache_entries(self._embedding_cache, str(absolute_path), resolved_device)
        if removed:
            _collect_model_memory()
        return bool(removed)

    def unload_all_embedding_models(self) -> int:
        removed = len(self._embedding_cache)
        self._embedding_cache.clear()
        if removed:
            _collect_model_memory()
        return removed

    def unload_reranker_model(self, model_path: str | None = None, device: str | None = None) -> bool:
        resolved_path = str(resolve_model_path(model_path, "rerankers", self.root)) if model_path else None
        resolved_device = resolve_device(device) if device else None
        removed = _drop_cache_entries(self._reranker_cache, resolved_path, resolved_device)
        if removed:
            _collect_model_memory()
        return bool(removed)

    def unload_all_reranker_models(self) -> int:
        removed = len(self._reranker_cache)
        self._reranker_cache.clear()
        if removed:
            _collect_model_memory()
        return removed

    def embedding_busy(self) -> bool:
        return self._active_embedding_calls > 0

    def reranker_busy(self) -> bool:
        return self._active_reranker_calls > 0


def safe_unload_embedding_model(
    backend: Any,
    model_path: str,
    device: str,
    warnings: list[str] | None = None,
) -> bool:
    unload = getattr(backend, "unload_embedding_model", None)
    if not callable(unload):
        return False
    try:
        unloaded = bool(unload(model_path, device=device))
        if unloaded and warnings is not None:
            warnings.append("Embedding unloaded after use.")
        return unloaded
    except Exception as exc:
        logger.warning("Failed to unload embedding model after use: %s", exc)
        if warnings is not None:
            warnings.append(f"Embedding unload after use failed: {exc}")
        return False


def safe_unload_reranker_model(
    backend: Any,
    model_path: str | None,
    device: str,
    warnings: list[str] | None = None,
) -> bool:
    unload = getattr(backend, "unload_reranker_model", None)
    if not callable(unload):
        return False
    try:
        unloaded = bool(unload(model_path, device=device))
        if unloaded and warnings is not None:
            warnings.append("Reranker unloaded after use.")
        return unloaded
    except Exception as exc:
        logger.warning("Failed to unload reranker model after use: %s", exc)
        if warnings is not None:
            warnings.append(f"Reranker unload after use failed: {exc}")
        return False


def _drop_cache_entries(cache: dict[tuple[str, str], Any], path: str | None, device: str | None) -> int:
    keys = [
        key
        for key in cache
        if (path is None or key[0] == path) and (device is None or key[1] == device)
    ]
    for key in keys:
        del cache[key]
    return len(keys)


def _collect_model_memory() -> None:
    gc.collect()
    if importlib.util.find_spec("torch") is None:
        return
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as exc:
        logger.warning("Failed to empty torch CUDA cache after model unload: %s", exc)


def _vectors_to_lists(vectors: Any, normalize: bool) -> list[list[float]]:
    rows = vectors.tolist() if hasattr(vectors, "tolist") else vectors
    result = [[float(value) for value in row] for row in rows]
    if normalize:
        return [_normalize_vector(row) for row in result]
    return result


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
