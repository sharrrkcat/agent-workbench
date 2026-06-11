from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_workbench.core.inference.image_embedding_runtime_utils import (
    _assign_feature_vectors,
    _best_effort_collect,
    _first_token_features,
    _inference_context,
    _load_image_from_base64,
    _move_batch,
    _normalize_vector,
    _resolve_image_embedding_model_dir,
    _resolve_runtime_device,
    _select_torch_device,
    _vectors_to_lists,
)
from ai_workbench.core.inference.multimodal_runtime import (
    MultimodalEmbeddingInput,
    MultimodalEmbeddingResult,
    MultimodalRuntimeError,
    register_multimodal_embedding_runtime_factory,
)


class Dinov2EmbeddingRuntime:
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
        if any(item.input_type != "image" for item in inputs):
            raise MultimodalRuntimeError("DINOv2 runtime supports image inputs only.")

        indexed_items = list(enumerate(inputs))
        images = [_load_image_from_base64(item.image_base64) for _, item in indexed_items]

        model, processor, torch = self._load()
        batch = _move_batch(processor(images=images, return_tensors="pt"), self.device)
        with _inference_context(torch):
            output = model(**batch) if isinstance(batch, dict) else model(**dict(batch))
        vectors = _vectors_to_lists(_extract_dinov2_features(output))

        result: list[list[float] | None] = [None] * len(inputs)
        _assign_feature_vectors(result, indexed_items, vectors)
        completed = [vector for vector in result if vector is not None]
        if len(completed) != len(inputs):
            raise MultimodalRuntimeError("Multimodal embedding runtime failed.")
        if normalize:
            completed = [_normalize_vector(vector) for vector in completed]
        return MultimodalEmbeddingResult(vectors=completed)

    def unload(self) -> None:
        self._model = None
        self._processor = None
        _best_effort_collect(self._torch)
        self._torch = None

    def _load(self) -> tuple[Any, Any, Any]:
        if self._model is not None and self._processor is not None and self._torch is not None:
            return self._model, self._processor, self._torch
        try:
            from transformers import AutoImageProcessor, AutoModel  # type: ignore
            import torch  # type: ignore
        except Exception as exc:
            raise MultimodalRuntimeError("DINOv2 runtime dependencies are not installed.") from exc
        try:
            resolved_device = _select_torch_device(self.device, torch)
            model = AutoModel.from_pretrained(str(self.model_dir), local_files_only=True)
            processor = AutoImageProcessor.from_pretrained(str(self.model_dir), local_files_only=True)
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
            raise MultimodalRuntimeError("DINOv2 runtime failed to load local model.") from exc


def register_dinov2_runtime_factory(*, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
    register_multimodal_embedding_runtime_factory(
        "dinov2",
        lambda profile: Dinov2EmbeddingRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store),
    )


def _extract_dinov2_features(output: Any) -> Any:
    if isinstance(output, dict):
        if output.get("pooler_output") is not None:
            return output["pooler_output"]
        if output.get("last_hidden_state") is not None:
            return _first_token_features(output["last_hidden_state"])
    else:
        pooler_output = getattr(output, "pooler_output", None)
        if pooler_output is not None:
            return pooler_output
        last_hidden_state = getattr(output, "last_hidden_state", None)
        if last_hidden_state is not None:
            return _first_token_features(last_hidden_state)
    if isinstance(output, (list, tuple)) and output:
        return output[0]
    return output

