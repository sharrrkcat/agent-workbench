from __future__ import annotations

from contextlib import contextmanager
import importlib.metadata
import importlib.util
import math
from pathlib import Path
import sys
import threading
from typing import Any

from ai_workbench.core.inference.image_embedding_runtime_utils import (
    _best_effort_collect,
    _inference_context,
    _load_image_from_base64,
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
FLORENCE2_TRUST_REMOTE_CODE_REQUIRED_MESSAGE = "Florence2 runtime requires metadata.trust_remote_code=true."
LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS = {
    "forced_bos_token_id": None,
    "forced_eos_token_id": None,
    "suppress_tokens": None,
    "begin_suppress_tokens": None,
}
LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS = {
    "_supports_flash_attn": False,
    "_supports_flash_attn_2": False,
    "_supports_sdpa": False,
    "_supports_flex_attn": False,
}
FLORENCE2_SHARED_LANGUAGE_WEIGHT_PATH = "language_model.model.shared.weight"
FLORENCE2_TIED_LANGUAGE_WEIGHT_PATHS = (
    "language_model.model.encoder.embed_tokens.weight",
    "language_model.model.decoder.embed_tokens.weight",
    "language_model.lm_head.weight",
)
_LEGACY_CONFIG_PATCH_LOCK = threading.RLock()
_LEGACY_MODEL_PATCH_LOCK = threading.RLock()
_LEGACY_TOKENIZER_PATCH_LOCK = threading.RLock()
_MISSING = object()


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
        self._ensure_trust_remote_code()
        image = _load_vision_image(input.image_base64)
        image_size = _image_size(image)

        model, processor, torch = self._load()
        prompt = FLORENCE2_TASK_PROMPTS[task]
        try:
            batch = processor(text=prompt, images=image, return_tensors="pt")
            batch = _move_florence2_batch(batch, device=self.device, model=model, torch=torch)
            with _temporary_florence2_runtime_config_attrs(model, processor):
                with _inference_context(torch):
                    generated_ids = model.generate(
                        **batch,
                        max_new_tokens=generation_options["max_new_tokens"],
                        num_beams=generation_options["num_beams"],
                        do_sample=False,
                        # Florence2 remote code expects legacy tuple caches; transformers 5 passes Cache objects.
                        use_cache=False,
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
        self._ensure_trust_remote_code()
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoProcessor, PretrainedConfig  # type: ignore
            try:
                from transformers import PreTrainedModel  # type: ignore
            except Exception:
                PreTrainedModel = None  # type: ignore
            try:
                from transformers import PreTrainedTokenizerBase  # type: ignore
            except Exception:
                PreTrainedTokenizerBase = None  # type: ignore
        except Exception as exc:
            raise VisionRuntimeError("Florence2 runtime dependencies are not installed.") from exc
        try:
            resolved_device = _select_torch_device(self.device, torch)
            load_kwargs = {
                "local_files_only": True,
                "trust_remote_code": self.trust_remote_code,
                "attn_implementation": "eager",
            }
            with _temporary_florence2_transformers_compat(PretrainedConfig, PreTrainedModel, PreTrainedTokenizerBase):
                model = AutoModelForCausalLM.from_pretrained(str(self.model_dir), **load_kwargs)
                processor = AutoProcessor.from_pretrained(str(self.model_dir), **load_kwargs)
            _materialize_legacy_transformers_config_attrs(model, processor)
            _materialize_legacy_transformers_model_attrs(model)
            _repair_florence2_tied_language_weights(model)
            if hasattr(model, "to"):
                model = model.to(resolved_device)
            model = _normalize_florence2_model_dtype(model, device=resolved_device, torch=torch)
            _validate_florence2_tied_language_weights(model)
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

    def _ensure_trust_remote_code(self) -> None:
        if not self.trust_remote_code:
            raise VisionRuntimeInvalidRequest(FLORENCE2_TRUST_REMOTE_CODE_REQUIRED_MESSAGE)


def register_florence2_runtime_factory(*, repo_root: Path | None = None, provider_profile_store: Any = None) -> None:
    register_vision_runtime_factory(
        "florence2",
        lambda profile: Florence2VisionRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store),
    )


def preflight_florence2_runtime(
    profile: Any,
    *,
    repo_root: Path | None = None,
    provider_profile_store: Any = None,
    load_model: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    profile_id = str(getattr(profile, "id", ""))
    architecture = str(getattr(profile, "architecture", ""))

    def add_check(check_id: str, status: str, message: str) -> None:
        checks.append({"id": check_id, "status": status, "message": message})

    if architecture == "florence2":
        add_check("architecture", "pass", "Vision profile uses the Florence2 architecture.")
    else:
        add_check("architecture", "fail", "Vision profile architecture is not supported by this preflight.")

    dependencies_ok = _preflight_dependencies_available(add_check)
    model_dir: Path | None = None
    try:
        model_dir = _resolve_vision_model_dir(profile, repo_root)
        add_check("model_dir", "pass", "Local model directory is available.")
    except Exception:
        add_check("model_dir", "fail", "Local model directory is not available.")

    trust_remote_code = _metadata_bool(profile, "trust_remote_code")
    if trust_remote_code:
        add_check("trust_remote_code", "pass", "metadata.trust_remote_code=true is set.")
    else:
        add_check("trust_remote_code", "fail", FLORENCE2_TRUST_REMOTE_CODE_REQUIRED_MESSAGE)

    device_ok = True
    if dependencies_ok:
        device_ok = _preflight_device_available(profile, provider_profile_store, add_check)

    if architecture == "florence2" and dependencies_ok and model_dir is not None and trust_remote_code:
        _preflight_transformers_objects(model_dir, add_check)
        if load_model and device_ok:
            _preflight_model_load(profile, repo_root=repo_root, provider_profile_store=provider_profile_store, add_check=add_check)
        elif load_model:
            add_check("model_load", "fail", "Model load was skipped because the configured local runtime device is not available.")
    elif load_model:
        add_check("model_load", "fail", "Model load was skipped because earlier preflight checks failed.")

    return {
        "ok": all(check["status"] == "pass" for check in checks),
        "profile_id": profile_id,
        "architecture": architecture,
        "load_model": bool(load_model),
        "checks": checks,
        "runtime": _florence2_runtime_info(),
    }


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


@contextmanager
def _temporary_florence2_transformers_compat(
    pretrained_config_cls: Any,
    pretrained_model_cls: Any,
    tokenizer_base_cls: Any,
):
    with (
        _temporary_legacy_transformers_config_attrs(pretrained_config_cls),
        _temporary_legacy_transformers_model_attrs(pretrained_model_cls),
        _temporary_legacy_transformers_tokenizer_attrs(tokenizer_base_cls),
    ):
        yield


@contextmanager
def _temporary_legacy_transformers_config_attrs(pretrained_config_cls: Any):
    with _temporary_legacy_transformers_config_class_attrs([pretrained_config_cls]):
        yield


@contextmanager
def _temporary_legacy_transformers_config_class_attrs(config_classes: list[Any]):
    originals: dict[tuple[Any, str], Any] = {}
    with _LEGACY_CONFIG_PATCH_LOCK:
        for config_cls in _unique_patchable_classes(config_classes):
            for attr, default in LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS.items():
                key = (config_cls, attr)
                class_dict = getattr(config_cls, "__dict__", {}) or {}
                if attr in class_dict:
                    originals[key] = class_dict[attr]
                else:
                    originals[key] = _MISSING
                setattr(config_cls, attr, default)
        try:
            yield
        finally:
            for (config_cls, attr), original in reversed(list(originals.items())):
                try:
                    if original is _MISSING:
                        delattr(config_cls, attr)
                    else:
                        setattr(config_cls, attr, original)
                except AttributeError:
                    continue


@contextmanager
def _temporary_legacy_transformers_model_attrs(pretrained_model_cls: Any):
    if pretrained_model_cls is None:
        yield
        return
    originals: dict[str, Any] = {}
    with _LEGACY_MODEL_PATCH_LOCK:
        for attr, default in LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS.items():
            try:
                originals[attr] = getattr(pretrained_model_cls, attr)
            except AttributeError:
                originals[attr] = _MISSING
                setattr(pretrained_model_cls, attr, default)
        try:
            yield
        finally:
            for attr, original in originals.items():
                try:
                    if original is _MISSING:
                        delattr(pretrained_model_cls, attr)
                    else:
                        setattr(pretrained_model_cls, attr, original)
                except AttributeError:
                    continue


@contextmanager
def _temporary_legacy_transformers_tokenizer_attrs(tokenizer_base_cls: Any):
    if tokenizer_base_cls is None:
        yield
        return
    attr = "additional_special_tokens"
    with _LEGACY_TOKENIZER_PATCH_LOCK:
        try:
            original = getattr(tokenizer_base_cls, attr)
        except AttributeError:
            original = _MISSING
            setattr(
                tokenizer_base_cls,
                attr,
                property(_legacy_tokenizer_additional_special_tokens, _set_legacy_tokenizer_additional_special_tokens),
            )
        try:
            yield
        finally:
            try:
                if original is _MISSING:
                    delattr(tokenizer_base_cls, attr)
                else:
                    setattr(tokenizer_base_cls, attr, original)
            except AttributeError:
                pass


def _materialize_legacy_transformers_config_attrs(*roots: Any) -> None:
    seen: set[int] = set()
    for root in roots:
        for attr in ("config", "generation_config"):
            _materialize_config_object(_safe_getattr(root, attr), seen)


@contextmanager
def _temporary_florence2_runtime_config_attrs(*roots: Any):
    config_classes = _collect_config_classes(*roots)
    with _temporary_legacy_transformers_config_class_attrs(config_classes):
        yield


def _collect_config_classes(*roots: Any) -> list[Any]:
    seen: set[int] = set()
    config_classes: list[Any] = []
    for root in roots:
        for attr in ("config", "generation_config"):
            _collect_config_object_classes(_safe_getattr(root, attr), seen, config_classes)
    return config_classes


def _collect_config_object_classes(value: Any, seen: set[int], config_classes: list[Any], depth: int = 0) -> None:
    if value is None or depth > 4:
        return
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    config_classes.append(type(value))
    for attr in ("config", "generation_config", "language_config", "text_config", "vision_config", "encoder", "decoder"):
        child = _safe_getattr(value, attr)
        if child is not value:
            _collect_config_object_classes(child, seen, config_classes, depth + 1)


def _unique_patchable_classes(config_classes: list[Any]) -> list[Any]:
    seen: set[int] = set()
    unique: list[Any] = []
    for config_cls in config_classes:
        if config_cls is None or not isinstance(config_cls, type):
            continue
        identity = id(config_cls)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(config_cls)
    return unique


def _materialize_legacy_transformers_model_attrs(model: Any) -> None:
    if model is None:
        return
    for attr, default in LEGACY_TRANSFORMERS_MODEL_ATTR_DEFAULTS.items():
        try:
            getattr(model, attr)
        except AttributeError:
            try:
                setattr(model, attr, default)
            except Exception:
                pass
        except Exception:
            pass


def _repair_florence2_tied_language_weights(model: Any) -> None:
    if not _has_florence2_language_weight_layout(model):
        return
    shared_weight = _get_nested_attr(model, FLORENCE2_SHARED_LANGUAGE_WEIGHT_PATH)
    if shared_weight is _MISSING:
        raise VisionRuntimeError("Florence2 tied language weights are not available.")
    for path in FLORENCE2_TIED_LANGUAGE_WEIGHT_PATHS:
        if _get_nested_attr(model, path) is _MISSING:
            raise VisionRuntimeError("Florence2 tied language weights are not available.")
        _set_nested_attr(model, path, shared_weight)
    _validate_florence2_tied_language_weights(model)


def _validate_florence2_tied_language_weights(model: Any) -> None:
    if not _has_florence2_language_weight_layout(model):
        return
    shared_weight = _get_nested_attr(model, FLORENCE2_SHARED_LANGUAGE_WEIGHT_PATH)
    if shared_weight is _MISSING:
        raise VisionRuntimeError("Florence2 tied language weights are not available.")
    for path in FLORENCE2_TIED_LANGUAGE_WEIGHT_PATHS:
        tied_weight = _get_nested_attr(model, path)
        if tied_weight is _MISSING or not _same_tensor_storage(shared_weight, tied_weight):
            raise VisionRuntimeError("Florence2 tied language weights are not shared.")


def _has_florence2_language_weight_layout(model: Any) -> bool:
    language_model = _safe_getattr(model, "language_model")
    if language_model is None:
        return False
    return _safe_getattr(language_model, "model") is not None


def _get_nested_attr(root: Any, path: str) -> Any:
    value = root
    for part in path.split("."):
        try:
            value = getattr(value, part)
        except Exception:
            return _MISSING
    return value


def _set_nested_attr(root: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    parent_path = ".".join(parts[:-1])
    parent = _get_nested_attr(root, parent_path)
    if parent is _MISSING:
        raise VisionRuntimeError("Florence2 tied language weights are not available.")
    try:
        setattr(parent, parts[-1], value)
    except Exception as exc:
        raise VisionRuntimeError("Florence2 tied language weights could not be repaired.") from exc


def _same_tensor_storage(left: Any, right: Any) -> bool:
    if left is right:
        return True
    left_data_ptr = getattr(left, "data_ptr", None)
    right_data_ptr = getattr(right, "data_ptr", None)
    if callable(left_data_ptr) and callable(right_data_ptr):
        try:
            return left_data_ptr() == right_data_ptr()
        except Exception:
            return False
    return False


def _materialize_config_object(value: Any, seen: set[int], depth: int = 0) -> None:
    if value is None or depth > 4:
        return
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    for attr, default in LEGACY_TRANSFORMERS_CONFIG_ATTR_DEFAULTS.items():
        try:
            getattr(value, attr)
        except AttributeError:
            try:
                setattr(value, attr, default)
            except Exception:
                pass
        except Exception:
            pass
    for attr in ("config", "generation_config", "language_config", "text_config", "vision_config", "encoder", "decoder"):
        child = _safe_getattr(value, attr)
        if child is not value:
            _materialize_config_object(child, seen, depth + 1)


def _safe_getattr(value: Any, attr: str) -> Any:
    try:
        return getattr(value, attr)
    except Exception:
        return None


def _legacy_tokenizer_additional_special_tokens(tokenizer: Any) -> list[Any]:
    data = getattr(tokenizer, "__dict__", {}) or {}
    for key in ("_additional_special_tokens", "additional_special_tokens"):
        tokens = _normalize_special_tokens(data.get(key))
        if tokens is not None:
            return tokens
    for key in ("special_tokens_map_extended", "special_tokens_map"):
        token_map = _safe_getattr(tokenizer, key)
        if isinstance(token_map, dict):
            tokens = _normalize_special_tokens(token_map.get("additional_special_tokens"))
            if tokens is not None:
                return tokens
    extra_tokens = _safe_getattr(tokenizer, "extra_special_tokens")
    tokens = _normalize_special_tokens(extra_tokens)
    if tokens is not None:
        return tokens
    return []


def _set_legacy_tokenizer_additional_special_tokens(tokenizer: Any, value: Any) -> None:
    tokens = _normalize_special_tokens(value) or []
    data = getattr(tokenizer, "__dict__", None)
    if isinstance(data, dict):
        data["_additional_special_tokens"] = list(tokens)
        for key in ("special_tokens_map", "special_tokens_map_extended"):
            token_map = data.get(key)
            if isinstance(token_map, dict):
                token_map["additional_special_tokens"] = list(tokens)


def _normalize_special_tokens(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return None


def _preflight_dependencies_available(add_check: Any) -> bool:
    missing: list[str] = []
    if not _module_available("torch"):
        missing.append("torch")
    if not _module_available("transformers"):
        missing.append("transformers")
    if not _module_available("PIL"):
        missing.append("Pillow")
    if missing:
        add_check("dependencies", "fail", "Missing Florence2 runtime dependencies.")
        return False
    add_check("dependencies", "pass", "Florence2 runtime dependencies are available.")
    return True


def _preflight_device_available(profile: Any, provider_profile_store: Any, add_check: Any) -> bool:
    try:
        import torch  # type: ignore

        requested = _resolve_runtime_device(profile, provider_profile_store)
        resolved = _select_torch_device(requested, torch)
        add_check("device", "pass", f"Local runtime device is available: {resolved}.")
        return True
    except MultimodalRuntimeError:
        add_check("device", "fail", "Configured local runtime device is not available.")
        return False
    except Exception:
        add_check("device", "fail", "Local runtime device could not be checked.")
        return False


def _preflight_transformers_objects(model_dir: Path, add_check: Any) -> None:
    try:
        from transformers import AutoConfig, AutoProcessor, PretrainedConfig  # type: ignore
        try:
            from transformers import PreTrainedModel  # type: ignore
        except Exception:
            PreTrainedModel = None  # type: ignore
        try:
            from transformers import PreTrainedTokenizerBase  # type: ignore
        except Exception:
            PreTrainedTokenizerBase = None  # type: ignore
    except Exception:
        add_check("transformers_import", "fail", "Transformers could not be imported for Florence2 preflight.")
        return

    try:
        with _temporary_florence2_transformers_compat(PretrainedConfig, PreTrainedModel, PreTrainedTokenizerBase):
            AutoConfig.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=True)
        add_check("config", "pass", "Florence2 config is constructable.")
    except Exception:
        add_check("config", "fail", "Florence2 config could not be constructed.")

    try:
        with _temporary_florence2_transformers_compat(PretrainedConfig, PreTrainedModel, PreTrainedTokenizerBase):
            AutoProcessor.from_pretrained(
                str(model_dir),
                local_files_only=True,
                trust_remote_code=True,
                attn_implementation="eager",
            )
        add_check("processor_tokenizer", "pass", "Florence2 processor and tokenizer are constructable.")
    except Exception:
        add_check("processor_tokenizer", "fail", "Florence2 processor or tokenizer could not be constructed.")


def _preflight_model_load(profile: Any, *, repo_root: Path | None, provider_profile_store: Any, add_check: Any) -> None:
    runtime: Florence2VisionRuntime | None = None
    try:
        runtime = Florence2VisionRuntime(profile, repo_root=repo_root, provider_profile_store=provider_profile_store)
        runtime._load()
        add_check("model_load", "pass", "Florence2 model weights loaded successfully.")
    except VisionRuntimeInvalidRequest:
        add_check("model_load", "fail", FLORENCE2_TRUST_REMOTE_CODE_REQUIRED_MESSAGE)
    except Exception:
        add_check("model_load", "fail", "Florence2 model weights could not be loaded.")
    finally:
        if runtime is not None:
            runtime.unload()


def _florence2_runtime_info() -> dict[str, Any]:
    torch_info = _torch_runtime_info()
    return {
        "transformers_version": _package_version("transformers"),
        "torch_available": _module_available("torch"),
        **torch_info,
    }


def _torch_runtime_info() -> dict[str, Any]:
    if not _module_available("torch"):
        return {
            "torch_version": "not_installed",
            "cuda_available": False,
            "torch_cuda_version": None,
        }
    try:
        import torch  # type: ignore

        return {
            "torch_version": str(getattr(torch, "__version__", "unknown")),
            "cuda_available": bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)()),
            "torch_cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
        }
    except Exception:
        return {
            "torch_version": "unknown",
            "cuda_available": False,
            "torch_cuda_version": None,
        }


def _package_version(package_name: str) -> str:
    module = sys.modules.get(package_name)
    version = getattr(module, "__version__", None) if module is not None else None
    if version:
        return str(version)
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def _module_available(module_name: str) -> bool:
    if module_name in sys.modules:
        return sys.modules[module_name] is not None
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _move_florence2_batch(batch: Any, *, device: str, model: Any, torch: Any) -> Any:
    target_dtype = _model_floating_dtype(model, torch)

    def move_value(value: Any) -> Any:
        items = getattr(value, "items", None)
        if callable(items) and not _looks_like_tensor(value):
            return {key: move_value(item) for key, item in items()}
        if isinstance(value, tuple):
            return tuple(move_value(item) for item in value)
        if isinstance(value, list):
            return [move_value(item) for item in value]
        if not hasattr(value, "to"):
            return value
        if target_dtype is not None and _is_floating_tensor(value, torch):
            return _move_tensor(value, device=device, dtype=target_dtype)
        return _move_tensor(value, device=device, dtype=None)

    return move_value(batch)


def _move_tensor(value: Any, *, device: str, dtype: Any | None) -> Any:
    try:
        return value.to(device=device, dtype=dtype) if dtype is not None else value.to(device=device)
    except TypeError:
        pass
    try:
        return value.to(device, dtype=dtype) if dtype is not None else value.to(device)
    except TypeError:
        pass
    moved = value.to(device)
    if dtype is None:
        return moved
    try:
        return moved.to(dtype=dtype)
    except TypeError:
        return moved


def _normalize_florence2_model_dtype(model: Any, *, device: str, torch: Any) -> Any:
    if _device_kind(device) != "cpu":
        return model
    dtype = _model_floating_dtype(model, torch)
    if not _is_low_precision_dtype(dtype, torch):
        return model
    convert = getattr(model, "float", None)
    if callable(convert):
        try:
            return convert() or model
        except Exception:
            return model
    return model


def _model_floating_dtype(model: Any, torch: Any) -> Any | None:
    dtype = _safe_getattr(model, "dtype")
    if _is_floating_dtype(dtype, torch):
        return dtype
    parameters = getattr(model, "parameters", None)
    if callable(parameters):
        try:
            for parameter in parameters():
                dtype = _safe_getattr(parameter, "dtype")
                if _is_floating_dtype(dtype, torch):
                    return dtype
        except Exception:
            return None
    return None


def _is_floating_tensor(value: Any, torch: Any) -> bool:
    is_floating_point = getattr(value, "is_floating_point", None)
    if callable(is_floating_point):
        try:
            return bool(is_floating_point())
        except Exception:
            return False
    is_torch_floating_point = getattr(torch, "is_floating_point", None)
    if callable(is_torch_floating_point):
        try:
            return bool(is_torch_floating_point(value))
        except Exception:
            return False
    return _is_floating_dtype(_safe_getattr(value, "dtype"), torch)


def _looks_like_tensor(value: Any) -> bool:
    return hasattr(value, "to") and (hasattr(value, "dtype") or callable(getattr(value, "is_floating_point", None)))


def _is_floating_dtype(dtype: Any, torch: Any) -> bool:
    if dtype is None:
        return False
    floating_dtypes = {
        getattr(torch, "float16", None),
        getattr(torch, "bfloat16", None),
        getattr(torch, "float32", None),
        getattr(torch, "float64", None),
        getattr(torch, "float", None),
        getattr(torch, "double", None),
    }
    if dtype in floating_dtypes:
        return True
    name = str(dtype).lower()
    return any(token in name for token in ("float", "half", "bfloat"))


def _is_low_precision_dtype(dtype: Any, torch: Any) -> bool:
    if dtype is None:
        return False
    low_precision_dtypes = {
        getattr(torch, "float16", None),
        getattr(torch, "bfloat16", None),
        getattr(torch, "half", None),
    }
    if dtype in low_precision_dtypes:
        return True
    name = str(dtype).lower()
    return "float16" in name or "bfloat16" in name or name.endswith(".half") or name == "half"


def _device_kind(device: str) -> str:
    return str(device or "cpu").split(":", 1)[0].lower()


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
