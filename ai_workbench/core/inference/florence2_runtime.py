from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ai_workbench.core.inference.image_embedding_runtime_utils import (
    _best_effort_collect,
    _inference_context,
    _load_image_from_base64,
    _move_batch,
    _resolve_runtime_device,
    _select_torch_device,
)
from ai_workbench.core.inference.multimodal_runtime import MultimodalRuntimeError
from ai_workbench.core.inference.vision_runtime import (
    VisionRuntimeError,
    VisionRuntimeInput,
    VisionRuntimeInvalidRequest,
    VisionRuntimeResult,
    register_vision_runtime_factory,
)
from ai_workbench.core.knowledge_models import models_root_path
from ai_workbench.core.vision_profiles import normalize_vision_model_ref


FLORENCE2_TASK_PROMPTS = {
    "caption": "<CAPTION>",
    "detailed_caption": "<DETAILED_CAPTION>",
    "ocr": "<OCR>",
    "object_detection": "<OD>",
}
DEFAULT_MAX_NEW_TOKENS = {
    "caption": 64,
    "detailed_caption": 256,
    "ocr": 1024,
    "object_detection": 1024,
}
MAX_TEXT_OUTPUT_CHARS = 100_000


class Florence2VisionRuntime:
    def __init__(self, profile: Any, *, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
        self.repo_root = repo_root
        self.provider_profile_store = provider_profile_store
        self.model_dir = _resolve_vision_model_dir(profile, repo_root)
        self.device = _resolve_runtime_device(profile, provider_profile_store)
        self.trust_remote_code = _metadata_bool(profile, "trust_remote_code")
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None

    def run(
        self,
        *,
        profile: Any,
        task: str,
        input: VisionRuntimeInput,
        options: dict[str, Any],
    ) -> VisionRuntimeResult:
        if task not in FLORENCE2_TASK_PROMPTS:
            raise VisionRuntimeInvalidRequest("Unsupported vision task.")
        generation_options = _validate_generation_options(task, options)
        image = _load_vision_image(input.image_base64)
        image_size = _image_size(image)

        model, processor, torch = self._load()
        prompt = FLORENCE2_TASK_PROMPTS[task]
        try:
            batch = processor(text=prompt, images=image, return_tensors="pt")
            batch = _move_batch(batch, self.device)
            with _inference_context(torch):
                generated_ids = model.generate(
                    **batch,
                    max_new_tokens=generation_options["max_new_tokens"],
                    num_beams=generation_options["num_beams"],
                    do_sample=False,
                )
            decoded = processor.batch_decode(generated_ids, skip_special_tokens=False)
            generated_text = decoded[0] if isinstance(decoded, list) and decoded else str(decoded)
            parsed = _post_process(processor, generated_text, prompt, image_size)
            return VisionRuntimeResult(data=_normalize_task_output(task, prompt, parsed, image_size))
        except VisionRuntimeInvalidRequest:
            raise
        except VisionRuntimeError:
            raise
        except Exception as exc:
            raise VisionRuntimeError("Florence2 runtime failed.") from exc

    def unload(self) -> None:
        self._model = None
        self._processor = None
        _best_effort_collect(self._torch)
        self._torch = None

    def _load(self) -> tuple[Any, Any, Any]:
        if self._model is not None and self._processor is not None and self._torch is not None:
            return self._model, self._processor, self._torch
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore
        except Exception as exc:
            raise VisionRuntimeError("Florence2 runtime dependencies are not installed.") from exc
        try:
            resolved_device = _select_torch_device(self.device, torch)
            load_kwargs = {
                "local_files_only": True,
                "trust_remote_code": self.trust_remote_code,
            }
            model = AutoModelForCausalLM.from_pretrained(str(self.model_dir), **load_kwargs)
            processor = AutoProcessor.from_pretrained(str(self.model_dir), **load_kwargs)
            if hasattr(model, "to"):
                model = model.to(resolved_device)
            if hasattr(model, "eval"):
                model.eval()
            self.device = resolved_device
            self._model = model
            self._processor = processor
            self._torch = torch
            return model, processor, torch
        except MultimodalRuntimeError as exc:
            raise VisionRuntimeError("Florence2 runtime device is not available.") from exc
        except VisionRuntimeError:
            raise
        except Exception as exc:
            raise VisionRuntimeError("Florence2 runtime failed to load local model.") from exc


def register_florence2_runtime_factory(*, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
    register_vision_runtime_factory(
        "florence2",
        lambda profile: Florence2VisionRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store),
    )


def _resolve_vision_model_dir(profile: Any, repo_root: Path | None) -> Path:
    try:
        normalized = normalize_vision_model_ref(getattr(profile, "provider_model_id", ""))
        relative = normalized.removeprefix("vision/")
        root = (models_root_path(repo_root).resolve() / "vision").resolve()
        resolved = (root / relative).resolve()
        resolved.relative_to(root)
    except Exception as exc:
        raise VisionRuntimeError("Vision model reference is invalid.") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise VisionRuntimeError("Vision local model files are not available.")
    return resolved


def _load_vision_image(value: str | None) -> Any:
    try:
        return _load_image_from_base64(value)
    except Exception as exc:
        raise VisionRuntimeError("Invalid image input.") from exc


def _image_size(image: Any) -> tuple[int, int]:
    size = getattr(image, "size", None)
    if isinstance(size, tuple) and len(size) == 2:
        width = max(int(size[0]), 1)
        height = max(int(size[1]), 1)
        return (width, height)
    return (1, 1)


def _validate_generation_options(task: str, options: dict[str, Any]) -> dict[str, int]:
    allowed = {"max_new_tokens", "num_beams"}
    unknown = set(options) - allowed
    if unknown:
        raise VisionRuntimeInvalidRequest("Unsupported vision generation option.")
    max_new_tokens = options.get("max_new_tokens", DEFAULT_MAX_NEW_TOKENS[task])
    num_beams = options.get("num_beams", 3)
    if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool) or max_new_tokens < 1 or max_new_tokens > 1024:
        raise VisionRuntimeInvalidRequest("max_new_tokens must be an integer from 1 to 1024.")
    if not isinstance(num_beams, int) or isinstance(num_beams, bool) or num_beams < 1 or num_beams > 8:
        raise VisionRuntimeInvalidRequest("num_beams must be an integer from 1 to 8.")
    return {"max_new_tokens": max_new_tokens, "num_beams": num_beams}


def _post_process(processor: Any, generated_text: str, prompt: str, image_size: tuple[int, int]) -> Any:
    post_process = getattr(processor, "post_process_generation", None)
    if callable(post_process):
        return post_process(generated_text, task=prompt, image_size=image_size)
    return {prompt: generated_text}


def _normalize_task_output(task: str, prompt: str, parsed: Any, image_size: tuple[int, int]) -> dict[str, Any]:
    raw = _unwrap_prompt_result(parsed, prompt)
    if task in {"caption", "detailed_caption", "ocr"}:
        if isinstance(raw, dict):
            text = raw.get(task) or raw.get(prompt) or raw.get("text")
        else:
            text = raw
        if not isinstance(text, str) or len(text) > MAX_TEXT_OUTPUT_CHARS:
            raise VisionRuntimeError("Florence2 runtime returned invalid text output.")
        return {"type": "text", "text": text}
    if task == "object_detection":
        return {"type": "objects", "objects": _normalize_objects(raw, image_size)}
    raise VisionRuntimeInvalidRequest("Unsupported vision task.")


def _unwrap_prompt_result(value: Any, prompt: str) -> Any:
    if isinstance(value, dict):
        if prompt in value:
            return value[prompt]
        if len(value) == 1:
            return next(iter(value.values()))
    return value


def _normalize_objects(raw: Any, image_size: tuple[int, int]) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        labels = raw.get("labels") or raw.get("classes") or raw.get("class_names")
        boxes = raw.get("bboxes") or raw.get("boxes")
        scores = raw.get("scores")
        if isinstance(labels, list) and isinstance(boxes, list):
            score_values = scores if isinstance(scores, list) else [1.0] * len(labels)
            if len(labels) != len(boxes) or len(score_values) != len(labels):
                raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
            return [_normalize_object(label, score, box, image_size) for label, score, box in zip(labels, score_values, boxes, strict=True)]
        objects = raw.get("objects")
        if isinstance(objects, list):
            return [_normalize_object_from_mapping(item, image_size) for item in objects]
    if isinstance(raw, list):
        return [_normalize_object_from_mapping(item, image_size) for item in raw]
    raise VisionRuntimeError("Florence2 runtime returned invalid object output.")


def _normalize_object_from_mapping(item: Any, image_size: tuple[int, int]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    return _normalize_object(item.get("label"), item.get("score", 1.0), item.get("box") or item.get("bbox"), image_size)


def _normalize_object(label: Any, score: Any, box: Any, image_size: tuple[int, int]) -> dict[str, Any]:
    if not isinstance(label, str):
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    parsed_score = float(score)
    if not math.isfinite(parsed_score) or parsed_score < 0 or parsed_score > 1:
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    parsed_box = _normalize_box(box, image_size)
    return {"label": label, "score": parsed_score, "box": parsed_box}


def _normalize_box(value: Any, image_size: tuple[int, int]) -> dict[str, float]:
    if isinstance(value, dict):
        coords = [value.get("x_min"), value.get("y_min"), value.get("x_max"), value.get("y_max")]
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        coords = list(value)
    else:
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    x_min, y_min, x_max, y_max = [float(item) for item in coords]
    if not all(math.isfinite(item) for item in (x_min, y_min, x_max, y_max)):
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    width, height = image_size
    if max(x_min, y_min, x_max, y_max) > 1.0:
        x_min /= width
        x_max /= width
        y_min /= height
        y_max /= height
    normalized = {
        "x_min": _clamp_unit(x_min),
        "y_min": _clamp_unit(y_min),
        "x_max": _clamp_unit(x_max),
        "y_max": _clamp_unit(y_max),
    }
    if normalized["x_max"] < normalized["x_min"] or normalized["y_max"] < normalized["y_min"]:
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    return normalized


def _clamp_unit(value: float) -> float:
    if value < 0 or value > 1:
        raise VisionRuntimeError("Florence2 runtime returned invalid object output.")
    return value


def _metadata_bool(profile: Any, key: str) -> bool:
    metadata = getattr(profile, "metadata", {}) or {}
    return bool(isinstance(metadata, dict) and metadata.get(key) is True)
