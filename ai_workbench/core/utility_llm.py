from __future__ import annotations

import asyncio
import gc
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

from ai_workbench.core.knowledge_models import models_root_path
from ai_workbench.core.llm_config import LLMConfigError, resolve_llm_config


UTILITY_BACKEND_UNAVAILABLE = "UTILITY_LLM_BACKEND_UNAVAILABLE"
UTILITY_MODEL_PROFILE_NOT_CONFIGURED = "model_profile_not_configured"
UTILITY_MODEL_PROFILE_NOT_FOUND = "model_profile_not_found"
UTILITY_MODEL_PROFILE_DISABLED = "model_profile_disabled"
UTILITY_PROVIDER_PROFILE_UNAVAILABLE = "provider_profile_unavailable"
UTILITY_MODEL_PROFILE_GENERATION_FAILED = "model_profile_generation_failed"
UTILITY_INVALID_JSON = "utility_llm_invalid_json"
UTILITY_MODEL_NOT_CONFIGURED = "model_path_not_configured"
UTILITY_MODEL_NOT_FOUND = "model_not_found"
UTILITY_MODEL_PATH_INVALID = "model_path_invalid"
UTILITY_MODEL_PATH_MISMATCH = "backend_model_path_mismatch"
UTILITY_LLAMA_CPP_UNAVAILABLE = "llama_cpp_unavailable"
UTILITY_GENERATION_FAILED = "utility_generation_failed"
UTILITY_INTENTS = {"chat", "image_generation", "knowledge_query", "pet_command", "web_query", "agent_route", "command_like", "unknown"}
PET_DOMAINS = {"workbench_pet", "real_pet", "fictional_character", "unclear"}
PET_ACTIONS = {"status", "wake", "tuck", "select", "reload", "unknown"}
UTILITY_BACKENDS = {"transformers", "llama_cpp", "model_profile"}
GGUF_PLACEMENT_HELP = "GGUF files must be placed under data/models/utility_llms/<model-folder>/<file>.gguf"


@dataclass
class UtilityGeneration:
    text: str
    model_path: str | None
    device: str | None
    backend: str
    model_profile_id: str | None = None
    model_profile_name: str | None = None
    provider_profile_id: str | None = None
    provider_label: str | None = None
    requested_model_id: str | None = None


class UtilityLLMError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def utility_backend_status() -> dict[str, Any]:
    torch_available = importlib.util.find_spec("torch") is not None
    transformers_available = importlib.util.find_spec("transformers") is not None
    llama_cpp_available = importlib.util.find_spec("llama_cpp") is not None
    cuda_available = False
    if torch_available:
        try:
            import torch  # type: ignore

            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    return {
        "transformers_available": transformers_available,
        "torch_available": torch_available,
        "llama_cpp_available": llama_cpp_available,
        "cuda_available": cuda_available,
    }


def normalize_utility_backend(value: Any) -> str:
    backend = str(value or "transformers").strip() or "transformers"
    if backend not in UTILITY_BACKENDS:
        raise ValueError("Utility LLM backend must be transformers, llama_cpp, or model_profile.")
    return backend


def normalize_utility_model_path(value: str, backend: str = "transformers") -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "\\" in raw:
        raise ValueError("Utility LLM model path must use POSIX-style forward slashes.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Utility LLM model path must be a safe relative path inside data/models.")
    backend = normalize_utility_backend(backend)
    if backend == "model_profile":
        return path.as_posix()
    if path.parts[0] != "utility_llms":
        raise ValueError("Utility LLM model path must be under utility_llms.")
    if backend == "transformers":
        if len(path.parts) != 2 or path.suffix.casefold() == ".gguf":
            raise ValueError("Transformers Utility LLM model path must be shaped as utility_llms/<folder>.")
    else:
        if len(path.parts) != 3 or path.suffix.casefold() != ".gguf":
            raise ValueError(GGUF_PLACEMENT_HELP)
    return path.as_posix()


def classify_utility_model_path(model_path: str) -> str:
    raw = str(model_path or "").strip()
    if not raw:
        return "empty"
    if "\\" in raw:
        return "invalid"
    try:
        path = PurePosixPath(raw)
    except Exception:
        return "invalid"
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or not path.parts or path.parts[0] != "utility_llms":
        return "invalid"
    if len(path.parts) == 2 and path.suffix.casefold() != ".gguf":
        return "transformers"
    if len(path.parts) == 3 and path.suffix.casefold() == ".gguf":
        return "llama_cpp"
    if path.suffix.casefold() == ".gguf":
        return "invalid"
    return "unknown"


def normalize_utility_options(settings: Any) -> dict[str, Any]:
    return {
        "context_size": int(getattr(settings, "intent_routing_utility_llm_context_size", 4096) or 4096),
        "gpu_layers": int(getattr(settings, "intent_routing_utility_llm_gpu_layers", 0) or 0),
        "threads": getattr(settings, "intent_routing_utility_llm_threads", None),
    }


def validate_utility_model_path_for_backend(model_path: str, backend: str) -> str:
    normalized = normalize_utility_model_path(model_path, backend)
    kind = classify_utility_model_path(normalized)
    if normalized and kind != backend:
        raise UtilityLLMError(UTILITY_MODEL_PATH_MISMATCH, "Utility LLM backend and model path do not match.")
    return normalized


def scan_utility_models(root: Path | None = None) -> dict[str, Any]:
    base = models_root_path(root)
    utility_root = base / "utility_llms"
    utility_root.mkdir(parents=True, exist_ok=True)
    transformers_models: list[dict[str, Any]] = []
    gguf_models: list[dict[str, Any]] = []
    warnings: list[str] = []
    root_ggufs = [item for item in utility_root.glob("*.gguf") if item.is_file()]
    if root_ggufs:
        warnings.append("root_gguf_ignored")
    for child in sorted(utility_root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.is_symlink():
            continue
        if (child / "config.json").is_file() or (child / "tokenizer_config.json").is_file():
            transformers_models.append({"model_path": f"utility_llms/{child.name}", "name": child.name, "type": "transformers", "exists": True})
        for gguf in sorted(child.glob("*.gguf"), key=lambda item: item.name.lower()):
            if gguf.is_file() and not gguf.is_symlink():
                gguf_models.append(
                    {
                        "model_path": f"utility_llms/{child.name}/{gguf.name}",
                        "name": gguf.name,
                        "folder": child.name,
                        "type": "llama_cpp",
                        "exists": True,
                    }
                )
    return {
        "models_root": "data/models",
        "utility_root": "data/models/utility_llms",
        "transformers_models": transformers_models,
        "gguf_models": gguf_models,
        "backend": utility_backend_status(),
        "warnings": warnings,
    }


def resolve_utility_model_path(model_path: str, root: Path | None = None, backend: str = "transformers") -> Path:
    normalized = validate_utility_model_path_for_backend(model_path, backend)
    if not normalized:
        raise UtilityLLMError(UTILITY_MODEL_NOT_CONFIGURED, "Utility LLM model path is not configured.")
    base = models_root_path(root).resolve()
    resolved = (base / normalized).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Utility LLM model path must stay inside data/models.") from exc
    return resolved


def legacy_normalize_utility_model_path(value: str) -> str:
    try:
        return normalize_utility_model_path(value, "transformers")
    except ValueError:
        return normalize_utility_model_path(value, "llama_cpp")


def _mismatch_or_invalid_reason(model_path: str, backend: str) -> str:
    kind = classify_utility_model_path(model_path)
    if kind in {"transformers", "llama_cpp"} and kind != backend:
        return UTILITY_MODEL_PATH_MISMATCH
    return UTILITY_MODEL_PATH_INVALID


class TransformersUtilityLlmBackend:
    backend = "transformers"

    def cache_key(self, model_path: str, device: str, options: dict[str, Any]) -> tuple[Any, ...]:
        return (self.backend, model_path, device)

    def available(self) -> bool:
        status = utility_backend_status()
        return bool(status["transformers_available"] and status["torch_available"])

    def reason_unavailable(self) -> str:
        return UTILITY_BACKEND_UNAVAILABLE

    def path_exists(self, absolute_path: Path) -> bool:
        return absolute_path.is_dir()

    def generate(self, cache: dict[tuple[Any, ...], dict[str, Any]], absolute_path: Path, model_path: str, device: str, options: dict[str, Any], prompt: str, max_new_tokens: int) -> str:
        key = self.cache_key(model_path, device, options)
        if key not in cache:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

            tokenizer = AutoTokenizer.from_pretrained(str(absolute_path), local_files_only=True, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(str(absolute_path), local_files_only=True, trust_remote_code=True)
            model.to(device)
            model.eval()
            cache[key] = {"tokenizer": tokenizer, "model": model}
        tokenizer = cache[key]["tokenizer"]
        model = cache[key]["model"]
        rendered = _render_chat_prompt(tokenizer, prompt)
        inputs = tokenizer(rendered, return_tensors="pt")
        inputs = {name: value.to(device) for name, value in inputs.items()}
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max(1, min(int(max_new_tokens), 256)),
            do_sample=False,
            temperature=None,
            pad_token_id=getattr(tokenizer, "eos_token_id", None),
        )
        prompt_len = inputs["input_ids"].shape[-1]
        generated = output_ids[0][prompt_len:]
        return tokenizer.decode(generated, skip_special_tokens=True).strip()


class LlamaCppUtilityLlmBackend:
    backend = "llama_cpp"

    def cache_key(self, model_path: str, device: str, options: dict[str, Any]) -> tuple[Any, ...]:
        return (self.backend, model_path, int(options["context_size"]), int(options["gpu_layers"]), options.get("threads"))

    def available(self) -> bool:
        return bool(utility_backend_status()["llama_cpp_available"])

    def reason_unavailable(self) -> str:
        return UTILITY_LLAMA_CPP_UNAVAILABLE

    def path_exists(self, absolute_path: Path) -> bool:
        return absolute_path.is_file()

    def generate(self, cache: dict[tuple[Any, ...], dict[str, Any]], absolute_path: Path, model_path: str, device: str, options: dict[str, Any], prompt: str, max_new_tokens: int) -> str:
        key = self.cache_key(model_path, device, options)
        if key not in cache:
            from llama_cpp import Llama  # type: ignore

            kwargs: dict[str, Any] = {
                "model_path": str(absolute_path),
                "n_ctx": int(options["context_size"]),
                "n_gpu_layers": int(options["gpu_layers"]),
                "verbose": False,
            }
            if options.get("threads") is not None:
                kwargs["n_threads"] = int(options["threads"])
            cache[key] = {"llm": Llama(**kwargs)}
        llm = cache[key]["llm"]
        messages = [{"role": "user", "content": prompt}]
        chat_completion = getattr(llm, "create_chat_completion", None)
        if callable(chat_completion):
            result = chat_completion(messages=messages, max_tokens=max(1, min(int(max_new_tokens), 256)), temperature=0, stop=["</s>", "<|im_end|>"])
        else:
            result = llm.create_completion(prompt=prompt, max_tokens=max(1, min(int(max_new_tokens), 256)), temperature=0, stop=["</s>", "<|im_end|>"])
        return _extract_llama_cpp_text(result)


def _extract_llama_cpp_text(result: Any) -> str:
    if isinstance(result, dict):
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            if "content" in message:
                return str(message.get("content") or "").strip()
            if "text" in first:
                return str(first.get("text") or "").strip()
    return str(result or "").strip()


def _backend_for(settings: Any) -> str:
    return normalize_utility_backend(getattr(settings, "intent_routing_utility_llm_backend", "transformers"))


def _backend_instance(backend: str) -> TransformersUtilityLlmBackend | LlamaCppUtilityLlmBackend:
    return LlamaCppUtilityLlmBackend() if backend == "llama_cpp" else TransformersUtilityLlmBackend()


def resolve_utility_device(requested: str) -> str:
    requested = requested or "auto"
    backend = utility_backend_status()
    if requested == "auto":
        return "cuda" if backend["torch_available"] and backend["cuda_available"] else "cpu"
    if requested == "cuda":
        if not backend["torch_available"] or not backend["cuda_available"]:
            raise UtilityLLMError(UTILITY_BACKEND_UNAVAILABLE, "CUDA was selected, but torch CUDA is not available.", backend)
        return "cuda"
    if requested == "cpu":
        return "cpu"
    raise ValueError("Utility LLM device must be auto, cpu, or cuda.")


class UtilityLLMService:
    def __init__(
        self,
        root: Path | None = None,
        *,
        llm_runtime: Any = None,
        llm_profile_store: Any = None,
        provider_profile_store: Any = None,
        capability_registry: Any = None,
        capability_config_store: Any = None,
        llm_defaults_store: Any = None,
    ) -> None:
        self.root = root
        self.llm_runtime = llm_runtime
        self.llm_profile_store = llm_profile_store
        self.provider_profile_store = provider_profile_store
        self.capability_registry = capability_registry
        self.capability_config_store = capability_config_store
        self.llm_defaults_store = llm_defaults_store
        self._cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def configure(
        self,
        *,
        llm_runtime: Any = None,
        llm_profile_store: Any = None,
        provider_profile_store: Any = None,
        capability_registry: Any = None,
        capability_config_store: Any = None,
        llm_defaults_store: Any = None,
    ) -> None:
        if llm_runtime is not None:
            self.llm_runtime = llm_runtime
        if llm_profile_store is not None:
            self.llm_profile_store = llm_profile_store
        if provider_profile_store is not None:
            self.provider_profile_store = provider_profile_store
        if capability_registry is not None:
            self.capability_registry = capability_registry
        if capability_config_store is not None:
            self.capability_config_store = capability_config_store
        if llm_defaults_store is not None:
            self.llm_defaults_store = llm_defaults_store

    def status(self, settings: Any) -> dict[str, Any]:
        backend_status = utility_backend_status()
        try:
            backend = _backend_for(settings)
        except ValueError:
            backend = str(getattr(settings, "intent_routing_utility_llm_backend", "transformers") or "transformers")
            backend_invalid = True
        else:
            backend_invalid = False
        options = normalize_utility_options(settings)
        raw_model_path = str(getattr(settings, "intent_routing_utility_llm_model_path", "") or "")
        try:
            model_path = validate_utility_model_path_for_backend(raw_model_path, backend) if not backend_invalid else raw_model_path
        except (ValueError, UtilityLLMError):
            model_path = str(getattr(settings, "intent_routing_utility_llm_model_path", "") or "")
            path_invalid = True
        else:
            path_invalid = False
        device = getattr(settings, "intent_routing_device", "auto") or "auto"
        if backend == "model_profile" and not backend_invalid:
            return self._model_profile_status(settings)
        loaded = any(len(key) >= 2 and key[0] == backend and key[1] == model_path for key in self._cache) if model_path else False
        base = {
            "available": False,
            "configured": bool(model_path),
            "loaded": loaded,
            "backend": backend,
            "model_path": model_path,
            "device": device,
            "resolved_device": None,
            "options": options,
            "backend_status": backend_status,
            "reason": None,
        }
        if backend_invalid:
            return {**base, "reason": "invalid_backend"}
        if not model_path:
            return {**base, "reason": UTILITY_MODEL_NOT_CONFIGURED}
        if path_invalid:
            return {**base, "reason": _mismatch_or_invalid_reason(model_path, backend)}
        backend_impl = _backend_instance(backend)
        if not backend_impl.available():
            return {**base, "reason": backend_impl.reason_unavailable()}
        try:
            resolved_device = "cpu" if backend == "llama_cpp" else resolve_utility_device(device)
            absolute_path = resolve_utility_model_path(model_path, self.root, backend)
        except Exception as exc:
            return {**base, "reason": getattr(exc, "code", UTILITY_MODEL_PATH_INVALID)}
        if not backend_impl.path_exists(absolute_path):
            return {**base, "resolved_device": resolved_device, "reason": UTILITY_MODEL_NOT_FOUND}
        return {**base, "available": True, "resolved_device": resolved_device, "reason": None}

    def _model_profile_status(self, settings: Any) -> dict[str, Any]:
        profile_id = str(getattr(settings, "intent_routing_utility_llm_model_profile_id", "") or "").strip()
        base = {
            "available": False,
            "configured": bool(profile_id),
            "loaded": False,
            "backend": "model_profile",
            "model_path": None,
            "model_profile_id": profile_id or None,
            "model_profile_name": None,
            "provider_profile_id": None,
            "provider_label": None,
            "requested_model_id": None,
            "device": None,
            "resolved_device": None,
            "options": normalize_utility_options(settings),
            "backend_status": {"type": "model_profile"},
            "reason": None,
            "warnings": [],
        }
        if not profile_id:
            return {**base, "reason": UTILITY_MODEL_PROFILE_NOT_CONFIGURED}
        profile, provider, reason = self._lookup_model_profile(profile_id)
        if profile is None:
            return {**base, "reason": reason}
        provider_label = getattr(provider, "name", None) or getattr(profile, "provider", None)
        compact_status = {
            "type": "model_profile",
            "profile_enabled": bool(getattr(profile, "enabled", False)),
            "provider_enabled": bool(getattr(provider, "enabled", True)) if provider is not None else None,
            "provider": getattr(provider, "provider", None) or getattr(profile, "provider", None),
            "api_key_set": bool(getattr(provider, "api_key", "") or getattr(profile, "api_key", "")),
        }
        payload = {
            **base,
            "configured": True,
            "model_profile_id": getattr(profile, "id", profile_id),
            "model_profile_name": getattr(profile, "name", None) or getattr(profile, "alias", None),
            "provider_profile_id": getattr(provider, "id", None) or getattr(profile, "provider_profile_id", None),
            "provider_label": provider_label,
            "requested_model_id": getattr(profile, "model_id", None),
            "backend_status": compact_status,
        }
        if reason:
            return {**payload, "reason": reason}
        return {**payload, "available": True, "reason": None}

    async def generate(self, prompt: str, settings: Any, *, max_new_tokens: int = 128) -> UtilityGeneration:
        backend = _backend_for(settings)
        if backend == "model_profile":
            return await self._generate_model_profile(prompt, settings, max_new_tokens=max_new_tokens)
        model_path = validate_utility_model_path_for_backend(getattr(settings, "intent_routing_utility_llm_model_path", ""), backend)
        if not model_path:
            raise UtilityLLMError(UTILITY_MODEL_NOT_CONFIGURED, "Utility LLM model path is not configured.")
        backend_impl = _backend_instance(backend)
        if not backend_impl.available():
            raise UtilityLLMError(backend_impl.reason_unavailable(), "Optional Utility LLM backend dependency is not installed.", utility_backend_status())
        device = "cpu" if backend == "llama_cpp" else resolve_utility_device(getattr(settings, "intent_routing_device", "auto") or "auto")
        options = normalize_utility_options(settings)
        absolute_path = resolve_utility_model_path(model_path, self.root, backend)
        if not backend_impl.path_exists(absolute_path):
            raise UtilityLLMError(UTILITY_MODEL_NOT_FOUND, f"Utility LLM model not found: {model_path}")
        text = await asyncio.to_thread(backend_impl.generate, self._cache, absolute_path, model_path, device, options, prompt, max_new_tokens)
        return UtilityGeneration(text=text, model_path=model_path, device=device, backend=backend)

    async def _generate_model_profile(self, prompt: str, settings: Any, *, max_new_tokens: int) -> UtilityGeneration:
        profile_id = str(getattr(settings, "intent_routing_utility_llm_model_profile_id", "") or "").strip()
        profile, provider, reason = self._lookup_model_profile(profile_id)
        if reason:
            raise UtilityLLMError(reason, f"Utility LLM Model Profile is unavailable: {reason}")
        if profile is None:
            raise UtilityLLMError(UTILITY_MODEL_PROFILE_NOT_FOUND, "Utility LLM Model Profile was not found.")
        if self.llm_runtime is None:
            raise UtilityLLMError(UTILITY_MODEL_PROFILE_GENERATION_FAILED, "LLM runtime is not configured for Utility LLM Model Profile backend.")
        try:
            model_config = self._resolve_model_profile_config(profile.id, max_new_tokens=max_new_tokens)
        except LLMConfigError as exc:
            code = UTILITY_PROVIDER_PROFILE_UNAVAILABLE if "PROVIDER" in exc.code or "PROFILE" in exc.code else UTILITY_MODEL_PROFILE_GENERATION_FAILED
            raise UtilityLLMError(code, exc.message) from exc
        try:
            chat = getattr(self.llm_runtime, "chat", None)
            if callable(chat):
                raw = chat(messages=[{"role": "user", "content": prompt}], model_config=model_config, stream=False)
            else:
                generate = getattr(self.llm_runtime, "generate")
                raw = generate(prompt=prompt, model_config=model_config, stream=False)
            if asyncio.iscoroutine(raw) or hasattr(raw, "__await__"):
                raw = await raw
            text = _extract_llm_text(raw)
        except Exception as exc:
            raise UtilityLLMError(UTILITY_MODEL_PROFILE_GENERATION_FAILED, str(exc) or "Utility LLM Model Profile generation failed.") from exc
        return UtilityGeneration(
            text=text,
            model_path=None,
            device=None,
            backend="model_profile",
            model_profile_id=getattr(profile, "id", profile.id),
            model_profile_name=getattr(profile, "name", None) or getattr(profile, "alias", None),
            provider_profile_id=getattr(provider, "id", None) or getattr(profile, "provider_profile_id", None),
            provider_label=getattr(provider, "name", None) or getattr(profile, "provider", None),
            requested_model_id=getattr(profile, "model_id", None),
        )

    def _resolve_model_profile_config(self, profile_id: str, *, max_new_tokens: int) -> dict[str, Any]:
        try:
            capability = self.capability_registry.get("llm") if self.capability_registry is not None else None
        except KeyError:
            capability = None
        capability_config = self.capability_config_store.get_config("llm") if self.capability_config_store is not None else {}
        config = resolve_llm_config(
            agent_schema=SimpleNamespace(llm={"profile": profile_id}, model=None),
            capability_schema=capability,
            capability_config=capability_config,
            llm_profile_store=self.llm_profile_store,
            provider_profile_store=self.provider_profile_store,
            llm_defaults_store=self.llm_defaults_store,
            explicit_override={"temperature": 0, "top_p": 1, "max_tokens": max_new_tokens},
        )
        values = dict(config.values)
        values["stream"] = False
        return values

    def _lookup_model_profile(self, profile_id: str) -> tuple[Any | None, Any | None, str | None]:
        if not profile_id:
            return None, None, UTILITY_MODEL_PROFILE_NOT_CONFIGURED
        if self.llm_profile_store is None:
            return None, None, UTILITY_MODEL_PROFILE_NOT_FOUND
        try:
            profile = self.llm_profile_store.get_by_id_or_alias(profile_id)
        except KeyError:
            return None, None, UTILITY_MODEL_PROFILE_NOT_FOUND
        if not getattr(profile, "enabled", False):
            return profile, None, UTILITY_MODEL_PROFILE_DISABLED
        provider = None
        provider_id = getattr(profile, "provider_profile_id", None)
        if provider_id:
            if self.provider_profile_store is None:
                return profile, None, UTILITY_PROVIDER_PROFILE_UNAVAILABLE
            try:
                provider = self.provider_profile_store.get(provider_id)
            except KeyError:
                return profile, None, UTILITY_PROVIDER_PROFILE_UNAVAILABLE
            if not getattr(provider, "enabled", False) or not getattr(provider, "base_url", ""):
                return profile, provider, UTILITY_PROVIDER_PROFILE_UNAVAILABLE
        elif not getattr(profile, "base_url", ""):
            return profile, None, UTILITY_PROVIDER_PROFILE_UNAVAILABLE
        if not getattr(profile, "model_id", ""):
            return profile, provider, UTILITY_PROVIDER_PROFILE_UNAVAILABLE
        return profile, provider, None

    async def generate_title(self, user_input: str, settings: Any) -> dict[str, Any]:
        from ai_workbench.core.session_titles import TITLE_MAX_LENGTH, normalize_generated_title, render_title_prompt

        prompt = (
            "Return a strict JSON object with one key: title.\n"
            "The title must use the same language as the user's message, be short, and contain no explanation.\n"
            f"Maximum title length: {TITLE_MAX_LENGTH} characters.\n\n"
            f"{render_title_prompt(settings.session_title_prompt, user_input)}"
        )
        raw = await self.generate(prompt, settings, max_new_tokens=64)
        try:
            data = extract_json_object(raw.text)
            title = normalize_generated_title(data.get("title", "") if isinstance(data, dict) else "")
        except Exception:
            retry = await self.generate(prompt + "\n\nReturn JSON only, for example {\"title\":\"Short title\"}.", settings, max_new_tokens=64)
            data = extract_json_object(retry.text)
            title = normalize_generated_title(data.get("title", "") if isinstance(data, dict) else "")
        if not title:
            raise UtilityLLMError(UTILITY_GENERATION_FAILED, "Utility LLM returned an empty title.")
        return {
            "title": title,
            "backend": f"utility_llm:{raw.backend}",
            "model_path": raw.model_path,
            "model_profile_id": raw.model_profile_id,
            "model_profile_name": raw.model_profile_name,
            "provider_profile_id": raw.provider_profile_id,
            "provider_label": raw.provider_label,
            "requested_model_id": raw.requested_model_id,
        }

    async def extract_intent_json(self, text: str, settings: Any, context: dict[str, Any] | None = None) -> dict[str, Any]:
        compact_context = json.dumps(context or {}, ensure_ascii=False)[:6000]
        prompt = (
            "Classify the user's message for internal shadow diagnostics only.\n"
            "Return strict JSON with keys: intent, confidence, target_agent_hint, kb_hint, query, use_original_query, command_hint, target_agent_id, kb_id, match_source, domain, action, target_pet_hint, source_pet_hint, target_pet_explicit, source_pet_explicit, freshness, domain_hints, language_hint.\n"
            "Allowed intent values: chat, image_generation, knowledge_query, pet_command, web_query, agent_route, command_like, unknown.\n"
            "Use compact top RouteSpec/ActionSpec candidates and slot schemas only; do not invent agent ids or knowledge base ids outside the candidates.\n"
            "Safety: command_like must not be executed automatically. Generic agent_route requires future confirmation. image_generation may target comfyui_agent. knowledge_query must provide query and may provide kb_hint; only set use_original_query=true when the original message is the best retrieval query. web_query must provide query or use_original_query=true, may set freshness to any/recent/today, and is diagnostic-only without web search execution. pet_command must set domain to workbench_pet only for the app's desktop pet, never for real pets or fictional-character questions.\n"
            "Use null for unknown slots. Do not explain.\n\n"
            f"Compact candidates:\n{compact_context}\n\n"
            f"User message:\n{text}"
        )
        raw = await self.generate(prompt, settings, max_new_tokens=512 if _backend_for(settings) == "model_profile" else 192)
        try:
            data = extract_json_object(raw.text)
        except Exception as exc:
            raise UtilityLLMError(UTILITY_INVALID_JSON, "Utility LLM returned invalid JSON.") from exc
        result = validate_intent_prediction(data)
        _validate_extracted_slots(result, context)
        if raw.backend == "model_profile":
            result["_utility_backend"] = "utility_llm:model_profile"
            result["_model_profile_id"] = raw.model_profile_id
            result["_model_profile_name"] = raw.model_profile_name
            result["_provider_label"] = raw.provider_label
            result["_requested_model_id"] = raw.requested_model_id
        return result

    async def extract_web_context_plan_json(self, text: str, settings: Any) -> dict[str, Any]:
        prompt = (
            "Decide whether this single user message should trigger internal Web Context search.\n"
            "Return strict JSON only with keys: should_search, query, reason, confidence.\n"
            "Allowed reason values: explicit_search_request, external_fact_question, time_sensitive_fact_question, incidental_mentions_only, personal_preference_or_emotion, conversation_continuation, insufficient_external_fact_request.\n"
            "Allowed confidence values: low, medium, high.\n"
            "Search only when the user requests external facts, current/recent information, news, prices, releases, official information, current status, real-world events, or verification that needs the web.\n"
            "Treat 'do you know / have you heard / did you see' plus yesterday/today/recently and a real-world event as a likely time-sensitive external fact question.\n"
            "When the user explicitly asks to search/check/look up, asks for latest/current status, or asks about a recent collaboration/release, extract a compact query.\n"
            "Do not search when the user is only expressing emotions/preferences, roleplaying, continuing conversation, acknowledging, or incidentally mentioning real entities without asking for information.\n"
            "Long messages can contain either explicit search requests or incidental mentions. Keywords alone are not enough; decide whether the user is asking for information.\n"
            "If should_search=true, query must be the smallest useful search query, not the whole message, and at most 160 characters.\n"
            "Positive example input: 帮我搜一下堡垒之夜最新的联动内容，我现在特别想知道，我好久没有玩堡垒之夜了，堡垒之夜确实是一个很好玩的游戏，不过我很久没有打了，还是有一点想玩\n"
            "Positive example JSON: {\"should_search\":true,\"query\":\"堡垒之夜 最新 联动 内容\",\"reason\":\"explicit_search_request\",\"confidence\":\"high\"}\n"
            "Positive example input: 你知道昨天晚上的流星雨吗\n"
            "Positive example JSON: {\"should_search\":true,\"query\":\"昨天晚上 流星雨\",\"reason\":\"time_sensitive_fact_question\",\"confidence\":\"high\"}\n"
            "Negative example input: 我最近有点不想搞这个了，昨天刚出门买了一点花，昨天晚上又买了一点猫粮，准备喂给家里的小猫吃。不过今天早上的金价波动也太大了，金价的最新消息一出来我就绷不住了。不过还是小猫好，小猫会一直呆在我身边\n"
            "Negative example JSON: {\"should_search\":false,\"query\":\"\",\"reason\":\"incidental_mentions_only\",\"confidence\":\"high\"}\n\n"
            "Negative example input: 我不是很喜欢吃西湖醋鱼\n"
            "Negative example JSON: {\"should_search\":false,\"query\":\"\",\"reason\":\"personal_preference_or_emotion\",\"confidence\":\"high\"}\n"
            "Negative example input: 我没想到，原来你是这样的人啊！\n"
            "Negative example JSON: {\"should_search\":false,\"query\":\"\",\"reason\":\"conversation_continuation\",\"confidence\":\"high\"}\n\n"
            f"User message:\n{text}"
        )
        raw = await self.generate(prompt, settings, max_new_tokens=192)
        try:
            return extract_json_object(raw.text)
        except Exception as exc:
            raise UtilityLLMError(UTILITY_INVALID_JSON, "Utility LLM returned invalid JSON.") from exc

    def unload(self, settings: Any | None = None) -> dict[str, Any]:
        if settings is not None:
            try:
                if _backend_for(settings) == "model_profile":
                    return {"ok": True, "status": "no_local_utility_cache", "reason": "no_local_utility_cache", "removed": 0}
            except ValueError:
                pass
        removed = len(self._cache)
        self._cache.clear()
        if removed:
            _collect_model_memory()
        return {"ok": True, "status": "unloaded", "removed": removed}


def extract_json_object(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        raise ValueError("empty JSON output")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        balanced = _first_balanced_json_object(value)
        if balanced is None:
            raise
        parsed = json.loads(balanced)
    if not isinstance(parsed, dict):
        raise ValueError("Utility LLM JSON output must be an object.")
    return parsed


def _first_balanced_json_object(value: str) -> str | None:
    start = value.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(value)):
            char = value[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return value[start : index + 1]
        start = value.find("{", start + 1)
    return None


def validate_intent_prediction(data: dict[str, Any]) -> dict[str, Any]:
    intent = str(data.get("intent") or "unknown").strip()
    if intent not in UTILITY_INTENTS:
        intent = "unknown"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "intent": intent,
        "confidence": round(confidence, 2),
        "target_agent_hint": _slot(data.get("target_agent_hint")),
        "target_agent_id": _slot(data.get("target_agent_id")),
        "kb_hint": _slot(data.get("kb_hint")),
        "kb_id": _slot(data.get("kb_id")),
        "match_source": _slot(data.get("match_source")),
        "query": _slot(data.get("query")),
        "use_original_query": bool(data.get("use_original_query")) if data.get("use_original_query") is not None else None,
        "command_hint": _slot(data.get("command_hint")),
        "domain": _pet_domain(data.get("domain")),
        "action": _pet_action(data.get("action")),
        "target_pet_hint": _slot(data.get("target_pet_hint")),
        "source_pet_hint": _slot(data.get("source_pet_hint")),
        "target_pet_explicit": _optional_bool(data.get("target_pet_explicit")),
        "source_pet_explicit": _optional_bool(data.get("source_pet_explicit")),
        "freshness": _freshness(data.get("freshness")),
        "domain_hints": _slot_list(data.get("domain_hints")),
        "language_hint": _slot(data.get("language_hint")),
    }


def _validate_extracted_slots(result: dict[str, Any], context: dict[str, Any] | None) -> None:
    route_specs = (context or {}).get("top_route_specs") if isinstance(context, dict) else None
    route_spec = route_specs[0] if isinstance(route_specs, list) and route_specs and isinstance(route_specs[0], dict) else {}
    intent = str(route_spec.get("intent") or route_spec.get("id") or "")
    if not intent:
        return
    if result.get("intent") != intent:
        raise UtilityLLMError("utility_slots_failed", "Utility LLM slots do not match the expected intent.")
    schema = route_spec.get("slot_schema") if isinstance(route_spec.get("slot_schema"), dict) else {}
    required = schema.get("required") if isinstance(schema, dict) else []
    for field in required if isinstance(required, list) else []:
        if result.get(str(field)) in (None, ""):
            raise UtilityLLMError("utility_slots_failed", "Utility LLM slots are missing required fields.")
    if intent == "pet_command":
        if result.get("domain") not in PET_DOMAINS:
            raise UtilityLLMError("utility_slots_failed", "Utility LLM pet domain slot is invalid.")
        if result.get("action") not in PET_ACTIONS:
            raise UtilityLLMError("utility_slots_failed", "Utility LLM pet action slot is invalid.")
    if intent == "web_query" and result.get("freshness") not in (None, "any", "recent", "today"):
        raise UtilityLLMError("utility_slots_failed", "Utility LLM web freshness slot is invalid.")


def _slot(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:200] if text else None


def _slot_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text:
            items.append(text[:120])
        if len(items) >= 5:
            break
    return items


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _pet_domain(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in PET_DOMAINS else None


def _pet_action(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in PET_ACTIONS else None


def _freshness(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in {"any", "recent", "today"} else None


def _render_chat_prompt(tokenizer: Any, prompt: str) -> str:
    messages = [{"role": "user", "content": prompt}]
    template = getattr(tokenizer, "apply_chat_template", None)
    if callable(template):
        try:
            return template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        except TypeError:
            return template(messages, tokenize=False, add_generation_prompt=True)
    return prompt


def _collect_model_memory() -> None:
    gc.collect()
    if importlib.util.find_spec("torch") is None:
        return
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def _extract_llm_text(raw: Any) -> str:
    if isinstance(raw, dict):
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            if "content" in message:
                return str(message.get("content") or "").strip()
            if "text" in first:
                return str(first.get("text") or "").strip()
        if "content" in raw:
            return str(raw.get("content") or "").strip()
    return str(raw or "").strip()
