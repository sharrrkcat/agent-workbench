from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
from typing import Any

from ai_workbench.core.inference.multimodal_runtime import (
    MultimodalEmbeddingInput,
    MultimodalEmbeddingResult,
    MultimodalRuntimeError,
    register_multimodal_embedding_runtime_factory,
)
from ai_workbench.core.knowledge_models import models_root_path
from ai_workbench.core.multimodal_profiles import normalize_image_embedding_model_ref
from ai_workbench.core.provider_runtime import provider_runtime_settings


DEFAULT_OPEN_CLIP_CHECKPOINTS = ("open_clip_pytorch_model.bin", "model.pt", "model.bin", "checkpoint.pt")
DEFAULT_MAX_IMAGE_PIXELS = 89_478_485


class ClipEmbeddingRuntime:
    def __init__(self, profile: Any, *, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
        self.repo_root = repo_root
        self.provider_profile_store = provider_profile_store
        self.model_dir = _resolve_image_embedding_model_dir(profile, repo_root)
        self.device = _resolve_runtime_device(profile, provider_profile_store)
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None

    def embed(
        self,
        *,
        profile: Any,
        inputs: list[MultimodalEmbeddingInput],
        normalize: bool,
    ) -> MultimodalEmbeddingResult:
        vectors: list[list[float] | None] = [None] * len(inputs)

        image_items = [(index, item) for index, item in enumerate(inputs) if item.input_type == "image"]
        text_items = [(index, item) for index, item in enumerate(inputs) if item.input_type == "text"]
        images = [_load_image_from_base64(item.image_base64) for _, item in image_items] if image_items else []

        model, processor, torch = self._load()

        if image_items:
            batch = processor(images=images, return_tensors="pt")
            batch = _move_batch(batch, self.device)
            with torch.no_grad():
                features = model.get_image_features(**batch)
            _assign_feature_vectors(vectors, image_items, _vectors_to_lists(features))

        if text_items:
            texts = [item.text or "" for _, item in text_items]
            batch = processor(text=texts, padding=True, truncation=True, return_tensors="pt")
            batch = _move_batch(batch, self.device)
            with torch.no_grad():
                features = model.get_text_features(**batch)
            _assign_feature_vectors(vectors, text_items, _vectors_to_lists(features))

        result = [vector for vector in vectors if vector is not None]
        if len(result) != len(inputs):
            raise MultimodalRuntimeError("Multimodal embedding runtime failed.")
        if normalize:
            result = [_normalize_vector(vector) for vector in result]
        return MultimodalEmbeddingResult(vectors=result)

    def unload(self) -> None:
        self._model = None
        self._processor = None
        _best_effort_collect(self._torch)
        self._torch = None

    def _load(self) -> tuple[Any, Any, Any]:
        if self._model is not None and self._processor is not None and self._torch is not None:
            return self._model, self._processor, self._torch
        try:
            from transformers import CLIPModel, CLIPProcessor  # type: ignore
            import torch  # type: ignore
        except Exception as exc:
            raise MultimodalRuntimeError("CLIP runtime dependencies are not installed.") from exc
        try:
            resolved_device = _select_torch_device(self.device, torch)
            model = CLIPModel.from_pretrained(str(self.model_dir), local_files_only=True)
            processor = CLIPProcessor.from_pretrained(str(self.model_dir), local_files_only=True)
            if hasattr(model, "to"):
                model = model.to(resolved_device)
            if hasattr(model, "eval"):
                model.eval()
            self.device = resolved_device
            self._model = model
            self._processor = processor
            self._torch = torch
            return model, processor, torch
        except MultimodalRuntimeError:
            raise
        except Exception as exc:
            raise MultimodalRuntimeError("CLIP runtime failed to load local model.") from exc


class OpenClipEmbeddingRuntime:
    def __init__(self, profile: Any, *, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
        self.repo_root = repo_root
        self.provider_profile_store = provider_profile_store
        self.model_dir = _resolve_image_embedding_model_dir(profile, repo_root)
        self.model_name = _metadata_text(profile, "open_clip_model_name")
        if not self.model_name:
            raise MultimodalRuntimeError("OpenCLIP runtime requires a local model name.")
        self.checkpoint = _resolve_open_clip_checkpoint(profile, self.model_dir)
        self.device = _resolve_runtime_device(profile, provider_profile_store)
        self._model: Any = None
        self._preprocess: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None

    def embed(
        self,
        *,
        profile: Any,
        inputs: list[MultimodalEmbeddingInput],
        normalize: bool,
    ) -> MultimodalEmbeddingResult:
        vectors: list[list[float] | None] = [None] * len(inputs)

        image_items = [(index, item) for index, item in enumerate(inputs) if item.input_type == "image"]
        text_items = [(index, item) for index, item in enumerate(inputs) if item.input_type == "text"]
        images = [_load_image_from_base64(item.image_base64) for _, item in image_items] if image_items else []

        model, preprocess, tokenizer, torch = self._load()

        if image_items:
            image_tensors = [preprocess(image) for image in images]
            batch = torch.stack(image_tensors).to(self.device)
            with torch.no_grad():
                features = model.encode_image(batch)
            _assign_feature_vectors(vectors, image_items, _vectors_to_lists(features))

        if text_items:
            texts = [item.text or "" for _, item in text_items]
            tokens = tokenizer(texts)
            if hasattr(tokens, "to"):
                tokens = tokens.to(self.device)
            with torch.no_grad():
                features = model.encode_text(tokens)
            _assign_feature_vectors(vectors, text_items, _vectors_to_lists(features))

        result = [vector for vector in vectors if vector is not None]
        if len(result) != len(inputs):
            raise MultimodalRuntimeError("Multimodal embedding runtime failed.")
        if normalize:
            result = [_normalize_vector(vector) for vector in result]
        return MultimodalEmbeddingResult(vectors=result)

    def unload(self) -> None:
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        _best_effort_collect(self._torch)
        self._torch = None

    def _load(self) -> tuple[Any, Any, Any, Any]:
        if self._model is not None and self._preprocess is not None and self._tokenizer is not None and self._torch is not None:
            return self._model, self._preprocess, self._tokenizer, self._torch
        try:
            import open_clip  # type: ignore
            import torch  # type: ignore
        except Exception as exc:
            raise MultimodalRuntimeError("OpenCLIP runtime dependencies are not installed.") from exc
        try:
            resolved_device = _select_torch_device(self.device, torch)
            model, _, preprocess = open_clip.create_model_and_transforms(self.model_name, pretrained=None)
            checkpoint = _load_open_clip_checkpoint(torch, self.checkpoint)
            state = checkpoint.get("state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
            model.load_state_dict(state)
            if hasattr(model, "to"):
                model = model.to(resolved_device)
            if hasattr(model, "eval"):
                model.eval()
            tokenizer = open_clip.get_tokenizer(self.model_name)
            self.device = resolved_device
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = tokenizer
            self._torch = torch
            return model, preprocess, tokenizer, torch
        except MultimodalRuntimeError:
            raise
        except Exception as exc:
            raise MultimodalRuntimeError("OpenCLIP runtime failed to load local model.") from exc


def register_clip_open_clip_runtime_factories(*, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
    register_multimodal_embedding_runtime_factory(
        "clip",
        lambda profile: ClipEmbeddingRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store),
    )
    register_multimodal_embedding_runtime_factory(
        "open_clip",
        lambda profile: OpenClipEmbeddingRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store),
    )


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


def _resolve_open_clip_checkpoint(profile: Any, model_dir: Path) -> Path:
    requested = _metadata_text(profile, "open_clip_checkpoint")
    candidates = (requested,) if requested else DEFAULT_OPEN_CLIP_CHECKPOINTS
    for candidate in candidates:
        if not candidate or "/" in candidate or "\\" in candidate or candidate in {".", ".."}:
            continue
        path = (model_dir / candidate).resolve()
        try:
            path.relative_to(model_dir.resolve())
        except ValueError:
            continue
        if path.is_file() and not path.is_symlink():
            return path
    raise MultimodalRuntimeError("OpenCLIP local checkpoint is not available.")


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


def _load_open_clip_checkpoint(torch: Any, checkpoint: Path) -> Any:
    try:
        return torch.load(str(checkpoint), map_location="cpu", weights_only=True)
    except TypeError as exc:
        raise MultimodalRuntimeError("OpenCLIP checkpoint loading requires safe weights-only support.") from exc
    except MultimodalRuntimeError:
        raise
    except Exception as exc:
        raise MultimodalRuntimeError("OpenCLIP local checkpoint could not be loaded.") from exc


def _normalize_vector(vector: list[float]) -> list[float]:
    total = sum(value * value for value in vector)
    if total <= 0:
        return vector
    norm = total ** 0.5
    return [value / norm for value in vector]


def _metadata_text(profile: Any, key: str) -> str:
    metadata = getattr(profile, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get(key) or "").strip()


def _best_effort_collect(torch: Any) -> None:
    try:
        import gc

        gc.collect()
        if torch is not None and getattr(getattr(torch, "cuda", None), "is_available", lambda: False)():
            torch.cuda.empty_cache()
    except Exception:
        return
