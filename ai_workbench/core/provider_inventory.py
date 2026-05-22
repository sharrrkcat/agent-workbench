from __future__ import annotations

import importlib.util
import os
from pathlib import Path, PurePosixPath
from typing import Any

from ai_workbench.core.knowledge_models import models_root_path


INTERNAL_PROVIDERS = {"internal_transformers", "internal_llama_cpp"}
MODEL_KIND_DIRS = {
    "llms": "llm",
    "embeddings": "embedding",
    "rerankers": "reranker",
}
TRANSFORMERS_MARKERS = {
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentence_bert_config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "pytorch_model.bin",
    "model.safetensors",
}


def is_internal_provider(provider: str | None) -> bool:
    return str(provider or "") in INTERNAL_PROVIDERS


def scan_internal_provider_models(provider: str, root: Path | None = None) -> dict[str, Any]:
    if provider not in INTERNAL_PROVIDERS:
        raise ValueError(f"Unsupported internal provider: {provider}")
    base = _ensure_internal_model_roots(root)
    warnings = _legacy_warnings(base)
    if provider == "internal_transformers":
        models = _scan_transformers_models(base, provider)
    else:
        models = _scan_llama_cpp_models(base, provider)
    return {
        "models_root": "data/models",
        "provider": provider,
        "models": models,
        "warnings": warnings,
        "backend": internal_provider_backend_status(provider),
    }


def internal_provider_backend_status(provider: str) -> dict[str, Any]:
    if provider == "internal_transformers":
        transformers_available = importlib.util.find_spec("transformers") is not None
        sentence_transformers_available = importlib.util.find_spec("sentence_transformers") is not None
        torch_available = importlib.util.find_spec("torch") is not None
        return {
            "available": (transformers_available or sentence_transformers_available) and torch_available,
            "transformers_available": transformers_available,
            "sentence_transformers_available": sentence_transformers_available,
            "torch_available": torch_available,
        }
    if provider == "internal_llama_cpp":
        llama_cpp_available = importlib.util.find_spec("llama_cpp") is not None
        return {
            "available": llama_cpp_available,
            "llama_cpp_available": llama_cpp_available,
        }
    return {"available": False}


def resolve_internal_llm_model_ref(provider: str, model_ref: str, root: Path | None = None) -> Path:
    normalized = normalize_internal_llm_model_ref(model_ref)
    base = models_root_path(root).resolve()
    llm_root = _safe_child(base, "llms")
    relative = normalized.removeprefix("llm/")
    resolved = (llm_root / relative).resolve()
    if not _is_safe_descendant(resolved, llm_root):
        raise ValueError("Internal LLM model ref must stay inside data/models/llms.")
    if provider == "internal_llama_cpp":
        if resolved.suffix.casefold() != ".gguf":
            raise ValueError("internal_llama_cpp model refs must point to a .gguf file.")
        if not resolved.is_file() or resolved.is_symlink():
            raise FileNotFoundError("Internal llama.cpp model file was not found.")
        return resolved
    if provider == "internal_transformers":
        if resolved.suffix.casefold() == ".gguf":
            raise ValueError("internal_transformers model refs must point to a model directory, not a GGUF file.")
        if not resolved.is_dir() or resolved.is_symlink() or not _looks_like_transformers_model(resolved):
            raise FileNotFoundError("Internal transformers model directory was not found.")
        return resolved
    raise ValueError(f"Unsupported internal provider: {provider}")


def resolve_internal_embedding_model_ref(provider: str, model_ref: str, root: Path | None = None) -> Path:
    normalized = normalize_internal_embedding_model_ref(model_ref)
    base = models_root_path(root).resolve()
    embedding_root = _safe_child(base, "embeddings")
    relative = normalized.removeprefix("embedding/")
    resolved = (embedding_root / relative).resolve()
    if not _is_safe_descendant(resolved, embedding_root):
        raise ValueError("Internal embedding model ref must stay inside data/models/embeddings.")
    if provider == "internal_llama_cpp":
        if resolved.suffix.casefold() != ".gguf":
            raise ValueError("internal_llama_cpp embedding refs must point to a .gguf file.")
        if not resolved.is_file() or resolved.is_symlink():
            raise FileNotFoundError("Internal llama.cpp embedding model file was not found.")
        return resolved
    if provider == "internal_transformers":
        if resolved.suffix.casefold() == ".gguf":
            raise ValueError("internal_transformers embedding refs must point to a model directory, not a GGUF file.")
        if not resolved.is_dir() or resolved.is_symlink() or not _looks_like_transformers_model(resolved):
            raise FileNotFoundError("Internal transformers embedding model directory was not found.")
        return resolved
    raise ValueError(f"Unsupported internal provider: {provider}")


def resolve_internal_reranker_model_ref(provider: str, model_ref: str, root: Path | None = None) -> Path:
    normalized = normalize_internal_reranker_model_ref(model_ref)
    base = models_root_path(root).resolve()
    reranker_root = _safe_child(base, "rerankers")
    relative = normalized.removeprefix("reranker/")
    resolved = (reranker_root / relative).resolve()
    if not _is_safe_descendant(resolved, reranker_root):
        raise ValueError("Internal reranker model ref must stay inside data/models/rerankers.")
    if provider == "internal_llama_cpp":
        if resolved.suffix.casefold() != ".gguf":
            raise ValueError("internal_llama_cpp reranker refs must point to a .gguf file.")
        if not resolved.is_file() or resolved.is_symlink():
            raise FileNotFoundError("Internal llama.cpp reranker model file was not found.")
        return resolved
    if provider == "internal_transformers":
        if resolved.suffix.casefold() == ".gguf":
            raise ValueError("internal_transformers reranker refs must point to a model directory, not a GGUF file.")
        if not resolved.is_dir() or resolved.is_symlink() or not _looks_like_transformers_model(resolved):
            raise FileNotFoundError("Internal transformers reranker model directory was not found.")
        return resolved
    raise ValueError(f"Unsupported internal provider: {provider}")


def normalize_internal_llm_model_ref(model_ref: str) -> str:
    raw = str(model_ref or "").strip()
    if not raw:
        raise ValueError("Internal LLM model ref must not be empty.")
    if "\\" in raw:
        raise ValueError("Internal LLM model ref must use POSIX-style forward slashes.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Internal LLM model ref must be a safe relative ref.")
    if not path.parts or path.parts[0] != "llm":
        raise ValueError("Internal LLM model ref must start with llm/.")
    if len(path.parts) < 2:
        raise ValueError("Internal LLM model ref must include a model name.")
    return path.as_posix()


def normalize_internal_embedding_model_ref(model_ref: str) -> str:
    raw = str(model_ref or "").strip()
    if not raw:
        raise ValueError("Internal embedding model ref must not be empty.")
    if "\\" in raw:
        raise ValueError("Internal embedding model ref must use POSIX-style forward slashes.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Internal embedding model ref must be a safe relative ref.")
    if not path.parts or path.parts[0] != "embedding":
        raise ValueError("Internal embedding model ref must start with embedding/.")
    if len(path.parts) < 2:
        raise ValueError("Internal embedding model ref must include a model name.")
    return path.as_posix()


def normalize_internal_reranker_model_ref(model_ref: str) -> str:
    raw = str(model_ref or "").strip()
    if not raw:
        raise ValueError("Internal reranker model ref must not be empty.")
    if "\\" in raw:
        raise ValueError("Internal reranker model ref must use POSIX-style forward slashes.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Internal reranker model ref must be a safe relative ref.")
    if not path.parts or path.parts[0] != "reranker":
        raise ValueError("Internal reranker model ref must start with reranker/.")
    if len(path.parts) < 2:
        raise ValueError("Internal reranker model ref must include a model name.")
    return path.as_posix()


def internal_llm_model_ref_exists(provider: str, model_ref: str, root: Path | None = None) -> tuple[bool, str | None]:
    try:
        resolve_internal_llm_model_ref(provider, model_ref, root)
        return True, None
    except FileNotFoundError:
        return False, "model_not_found"
    except ValueError:
        return False, "model_ref_invalid"


def internal_embedding_model_ref_exists(provider: str, model_ref: str, root: Path | None = None) -> tuple[bool, str | None]:
    try:
        resolve_internal_embedding_model_ref(provider, model_ref, root)
        return True, None
    except FileNotFoundError:
        return False, "model_not_found"
    except ValueError:
        return False, "model_ref_invalid"


def internal_reranker_model_ref_exists(provider: str, model_ref: str, root: Path | None = None) -> tuple[bool, str | None]:
    try:
        resolve_internal_reranker_model_ref(provider, model_ref, root)
        return True, None
    except FileNotFoundError:
        return False, "model_not_found"
    except ValueError:
        return False, "model_ref_invalid"


def _ensure_internal_model_roots(root: Path | None = None) -> Path:
    base = models_root_path(root).resolve()
    for dirname in MODEL_KIND_DIRS:
        _safe_child(base, dirname).mkdir(parents=True, exist_ok=True)
    return base


def _scan_transformers_models(base: Path, provider: str) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for dirname, kind in MODEL_KIND_DIRS.items():
        kind_dir = _safe_child(base, dirname)
        for child in sorted(kind_dir.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir() or child.is_symlink() or not _is_safe_descendant(child, base):
                continue
            if _looks_like_transformers_model(child):
                ref = f"{kind}/{child.name}"
                models.append(_model_item(ref, child.name, kind, provider, _relative_to_models(child, base)))
    return models


def _scan_llama_cpp_models(base: Path, provider: str) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for dirname, kind in MODEL_KIND_DIRS.items():
        kind_dir = _safe_child(base, dirname)
        paths: list[Path] = []
        for root, dirs, files in os.walk(kind_dir, followlinks=False):
            root_path = Path(root)
            dirs[:] = [name for name in dirs if not (root_path / name).is_symlink() and _is_safe_descendant(root_path / name, base)]
            for filename in files:
                path = root_path / filename
                if filename.lower().endswith(".gguf"):
                    paths.append(path)
        for path in sorted(paths, key=lambda item: item.relative_to(kind_dir).as_posix().lower()):
            if path.is_symlink() or not path.is_file() or not _is_safe_descendant(path, base):
                continue
            relative = path.relative_to(kind_dir).as_posix()
            ref = f"{kind}/{relative}"
            models.append(_model_item(ref, path.name, kind, provider, _relative_to_models(path, base)))
    return models


def _looks_like_transformers_model(path: Path) -> bool:
    try:
        children = [child for child in path.iterdir() if not child.is_symlink()]
    except OSError:
        return False
    if not children:
        return False
    if any(child.is_file() and child.name.lower().endswith(".gguf") for child in children):
        non_gguf_markers = [child for child in children if child.name in TRANSFORMERS_MARKERS and not child.name.lower().endswith(".gguf")]
        return bool(non_gguf_markers)
    if any(child.is_file() and child.name in TRANSFORMERS_MARKERS for child in children):
        return True
    if any(child.is_file() and child.name.lower().endswith(".safetensors") for child in children):
        return True
    if any(child.is_dir() and child.name.endswith("_Pooling") for child in children):
        return True
    return False


def _model_item(ref: str, display_name: str, kind: str, provider: str, relative_path: str) -> dict[str, Any]:
    return {
        "id": ref,
        "model_ref": ref,
        "name": display_name,
        "display_name": display_name,
        "type": kind,
        "kind": kind,
        "source": "internal",
        "backend": provider,
        "relative_path": relative_path,
        "loaded": None,
        "loaded_instance_ids": [],
        "capabilities": None,
        "raw": {},
    }


def _safe_child(base: Path, name: str) -> Path:
    child = (base / name).resolve()
    if not _is_safe_descendant(child, base):
        raise ValueError("Internal model directory must stay inside data/models.")
    return child


def _is_safe_descendant(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _relative_to_models(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _legacy_warnings(base: Path) -> list[str]:
    utility_root = base / "utility_llms"
    if utility_root.exists():
        return ["legacy_utility_llms_not_scanned"]
    return []
