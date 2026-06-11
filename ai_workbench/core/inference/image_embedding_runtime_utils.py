from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
from typing import Any

from ai_workbench.core.inference.multimodal_runtime import (
    MultimodalEmbeddingInput,
    MultimodalRuntimeError,
)
from ai_workbench.core.knowledge_models import models_root_path
from ai_workbench.core.multimodal_profiles import normalize_image_embedding_model_ref
from ai_workbench.core.provider_runtime import provider_runtime_settings


DEFAULT_MAX_IMAGE_PIXELS = 89_478_485


def _resolve_image_embedding_model_dir(profile: Any, repo_root: Path | None) -> Path:
    try:
        normalized = normalize_image_embedding_model_ref(getattr(profile, "provider_model_id", ""))
        relative = normalized.removeprefix("image_embedding/")
        root = (models_root_path(repo_root).resolve() / "image_embeddings").resolve()
        resolved = (root / relative).resolve()
        resolved.relative_to(root)
    except Exception as exc:
        raise MultimodalRuntimeError("Multimodal embedding model reference is invalid.") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise MultimodalRuntimeError("Multimodal embedding local model files are not available.")
    return resolved


def _resolve_runtime_device(profile: Any, provider_profile_store: Any) -> str:
    provider = None
    provider_id = getattr(profile, "provider_profile_id", None)
    if provider_id and provider_profile_store is not None:
        try:
            provider = provider_profile_store.get(provider_id)
        except Exception:
            provider = None
    return str(provider_runtime_settings(provider)["local_runtime_device"])


def _select_torch_device(requested: str, torch: Any) -> str:
    requested = (requested or "auto").lower()
    cuda_available = bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)())
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    mps_available = bool(mps_backend and getattr(mps_backend, "is_available", lambda: False)())
    if requested == "cuda":
        if not cuda_available:
            raise MultimodalRuntimeError("CUDA was selected, but it is not available.")
        return "cuda"
    if requested == "mps":
        if not mps_available:
            raise MultimodalRuntimeError("MPS was selected, but it is not available.")
        return "mps"
    if requested == "auto":
        if cuda_available:
            return "cuda"
        if mps_available:
            return "mps"
        return "cpu"
    return "cpu"


def _load_image_from_base64(value: str | None) -> Any:
    if not value:
        raise MultimodalRuntimeError("Invalid image input.")
    text = value.strip()
    if text.startswith("data:"):
        _, separator, payload = text.partition(",")
        if not separator:
            raise MultimodalRuntimeError("Invalid image input.")
        text = payload
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MultimodalRuntimeError("Invalid image input.") from exc
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:
        raise MultimodalRuntimeError("Image runtime dependency is not installed.") from exc
    try:
        if getattr(Image, "MAX_IMAGE_PIXELS", None) is None:
            Image.MAX_IMAGE_PIXELS = DEFAULT_MAX_IMAGE_PIXELS
        image = Image.open(BytesIO(raw))
        image.load()
        return image.convert("RGB") if hasattr(image, "convert") else image
    except Exception as exc:
        raise MultimodalRuntimeError("Invalid image input.") from exc


def _move_batch(batch: Any, device: str) -> Any:
    if hasattr(batch, "to"):
        return batch.to(device)
    if isinstance(batch, dict):
        return {key: value.to(device) if hasattr(value, "to") else value for key, value in batch.items()}
    return batch


def _vectors_to_lists(vectors: Any) -> list[list[float]]:
    detached = vectors.detach() if hasattr(vectors, "detach") else vectors
    cpu = detached.cpu() if hasattr(detached, "cpu") else detached
    rows = cpu.tolist() if hasattr(cpu, "tolist") else cpu
    return [[float(value) for value in row] for row in rows]


def _assign_feature_vectors(
    destination: list[list[float] | None],
    indexed_items: list[tuple[int, MultimodalEmbeddingInput]],
    feature_rows: list[list[float]],
) -> None:
    if len(feature_rows) != len(indexed_items):
        raise MultimodalRuntimeError("Multimodal embedding runtime returned invalid feature count.")
    for (index, _), vector in zip(indexed_items, feature_rows, strict=True):
        destination[index] = vector


def _normalize_vector(vector: list[float]) -> list[float]:
    total = sum(value * value for value in vector)
    if total <= 0:
        return vector
    norm = total ** 0.5
    return [value / norm for value in vector]


def _inference_context(torch: Any) -> Any:
    inference_mode = getattr(torch, "inference_mode", None)
    if callable(inference_mode):
        return inference_mode()
    return torch.no_grad()


def _first_token_features(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "__getitem__"):
        try:
            return value[:, 0, :]
        except Exception:
            try:
                return value[:, 0]
            except Exception:
                return value
    return value


def _best_effort_collect(torch: Any) -> None:
    try:
        import gc

        gc.collect()
        if torch is not None and getattr(getattr(torch, "cuda", None), "is_available", lambda: False)():
            torch.cuda.empty_cache()
    except Exception:
        return
