from __future__ import annotations

import asyncio
import gc
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ai_workbench.core.knowledge_models import models_root_path


UTILITY_BACKEND_UNAVAILABLE = "UTILITY_LLM_BACKEND_UNAVAILABLE"
UTILITY_MODEL_NOT_CONFIGURED = "model_path_not_configured"
UTILITY_MODEL_NOT_FOUND = "model_not_found"
UTILITY_MODEL_PATH_INVALID = "model_path_invalid"
UTILITY_MODEL_PATH_MISMATCH = "backend_model_path_mismatch"
UTILITY_LLAMA_CPP_UNAVAILABLE = "llama_cpp_unavailable"
UTILITY_GENERATION_FAILED = "utility_generation_failed"
UTILITY_INTENTS = {"chat", "image_generation", "knowledge_query", "pet_command", "agent_route", "command_like", "unknown"}
PET_DOMAINS = {"workbench_pet", "real_pet", "fictional_character", "unclear"}
PET_ACTIONS = {"status", "wake", "tuck", "select", "reload", "unknown"}
UTILITY_BACKENDS = {"transformers", "llama_cpp"}
GGUF_PLACEMENT_HELP = "GGUF files must be placed under data/models/utility_llms/<model-folder>/<file>.gguf"


@dataclass
class UtilityGeneration:
    text: str
    model_path: str
    device: str
    backend: str


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
        raise ValueError("Utility LLM backend must be transformers or llama_cpp.")
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
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self._cache: dict[tuple[Any, ...], dict[str, Any]] = {}

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

    async def generate(self, prompt: str, settings: Any, *, max_new_tokens: int = 128) -> UtilityGeneration:
        backend = _backend_for(settings)
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
        return {"title": title, "backend": f"utility_llm:{raw.backend}", "model_path": raw.model_path}

    async def extract_intent_json(self, text: str, settings: Any, context: dict[str, Any] | None = None) -> dict[str, Any]:
        compact_context = json.dumps(context or {}, ensure_ascii=False)[:6000]
        prompt = (
            "Classify the user's message for internal shadow diagnostics only.\n"
            "Return strict JSON with keys: intent, confidence, target_agent_hint, kb_hint, query, command_hint, target_agent_id, kb_id, match_source, domain, action, target_pet_hint, source_pet_hint.\n"
            "Allowed intent values: chat, image_generation, knowledge_query, pet_command, agent_route, command_like, unknown.\n"
            "Use compact candidates only; do not invent agent ids or knowledge base ids outside the candidates.\n"
            "Safety: command_like must not be executed automatically. Generic agent_route requires future confirmation. image_generation may target comfyui_agent. knowledge_query may provide kb_hint and query only. pet_command must set domain to workbench_pet only for the app's desktop pet, never for real pets or fictional-character questions.\n"
            "Use null for unknown slots. Do not explain.\n\n"
            f"Compact candidates:\n{compact_context}\n\n"
            f"User message:\n{text}"
        )
        raw = await self.generate(prompt, settings, max_new_tokens=192)
        return validate_intent_prediction(extract_json_object(raw.text))

    def unload(self) -> dict[str, Any]:
        removed = len(self._cache)
        self._cache.clear()
        if removed:
            _collect_model_memory()
        return {"ok": True, "status": "unloaded", "removed": removed}


def extract_json_object(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        raise ValueError("empty JSON output")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Utility LLM JSON output must be an object.")
    return parsed


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
        "command_hint": _slot(data.get("command_hint")),
        "domain": _pet_domain(data.get("domain")),
        "action": _pet_action(data.get("action")),
        "target_pet_hint": _slot(data.get("target_pet_hint")),
        "source_pet_hint": _slot(data.get("source_pet_hint")),
    }


def _slot(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:200] if text else None


def _pet_domain(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in PET_DOMAINS else None


def _pet_action(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in PET_ACTIONS else None


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
