from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_workbench.core.inference.multimodal_runtime import (
    MultimodalEmbeddingInput,
    MultimodalEmbeddingResult,
    MultimodalRuntimeError,
    register_multimodal_embedding_runtime_factory,
)

from ai_workbench.core.inference.clip_runtime import (
    _assign_feature_vectors,
    _load_image_from_base64,
    _move_batch,
    _normalize_vector,
    _resolve_image_embedding_model_dir,
    _resolve_runtime_device,
    _select_torch_device,
    _vectors_to_lists,
    _best_effort_collect,
)


class Siglip2EmbeddingRuntime:
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
            batch = _move_batch(processor(images=images, return_tensors="pt"), self.device)
            with _inference_context(torch):
                features = _extract_feature_vectors(model, batch, "image")
            _assign_feature_vectors(vectors, image_items, features)

        if text_items:
            texts = [item.text or "" for _, item in text_items]
            batch = _move_batch(processor(text=texts, padding=True, truncation=True, return_tensors="pt"), self.device)
            with _inference_context(torch):
                features = _extract_feature_vectors(model, batch, "text")
            _assign_feature_vectors(vectors, text_items, features)

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
            from transformers import AutoModel, AutoProcessor  # type: ignore
            import torch  # type: ignore
        except Exception as exc:
            raise MultimodalRuntimeError("SigLIP2 runtime dependencies are not installed.") from exc
        try:
            resolved_device = _select_torch_device(self.device, torch)
            model = AutoModel.from_pretrained(str(self.model_dir), local_files_only=True)
            processor = AutoProcessor.from_pretrained(str(self.model_dir), local_files_only=True)
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
            raise MultimodalRuntimeError("SigLIP2 runtime failed to load local model.") from exc


def register_siglip2_runtime_factory(*, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
    register_multimodal_embedding_runtime_factory(
        "siglip2",
        lambda profile: Siglip2EmbeddingRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store),
    )


def _extract_feature_vectors(model: Any, batch: Any, feature_kind: str) -> list[list[float]]:
    getter = getattr(model, f"get_{feature_kind}_features", None)
    if callable(getter):
        features = getter(**batch) if isinstance(batch, dict) else getter(**dict(batch))
        return _vectors_to_lists(features)
    if isinstance(batch, dict):
        output = model(**batch)
    else:
        output = model(**dict(batch))
    features = _extract_output_features(output, feature_kind)
    return _vectors_to_lists(features)


def _inference_context(torch: Any) -> Any:
    inference_mode = getattr(torch, "inference_mode", None)
    if callable(inference_mode):
        return inference_mode()
    return torch.no_grad()


def _extract_output_features(output: Any, feature_kind: str) -> Any:
    for key in (f"{feature_kind}_embeds", "pooler_output"):
        if isinstance(output, dict) and key in output:
            return output[key]
        if hasattr(output, key):
            value = getattr(output, key)
            if value is not None:
                return value
    if isinstance(output, dict):
        if "last_hidden_state" in output:
            return _first_token_features(output["last_hidden_state"])
    elif hasattr(output, "last_hidden_state"):
        return _first_token_features(getattr(output, "last_hidden_state"))
    if isinstance(output, (list, tuple)) and output:
        return output[0]
    return output


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
