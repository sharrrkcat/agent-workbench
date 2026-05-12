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
UTILITY_GENERATION_FAILED = "utility_generation_failed"
UTILITY_INTENTS = {"chat", "image_generation", "knowledge_query", "agent_route", "command_like", "unknown"}


@dataclass
class UtilityGeneration:
    text: str
    model_path: str
    device: str


class UtilityLLMError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def utility_backend_status() -> dict[str, Any]:
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
        "transformers_available": transformers_available,
        "torch_available": torch_available,
        "cuda_available": cuda_available,
    }


def normalize_utility_model_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Utility LLM model path must be a safe relative path inside data/models.")
    if len(path.parts) != 2 or path.parts[0] != "utility_llms":
        raise ValueError("Utility LLM model path must be shaped as utility_llms/<folder>.")
    return path.as_posix()


def resolve_utility_model_path(model_path: str, root: Path | None = None) -> Path:
    normalized = normalize_utility_model_path(model_path)
    if not normalized:
        raise UtilityLLMError(UTILITY_MODEL_NOT_CONFIGURED, "Utility LLM model path is not configured.")
    base = models_root_path(root).resolve()
    resolved = (base / normalized).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Utility LLM model path must stay inside data/models.") from exc
    return resolved


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
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def status(self, settings: Any) -> dict[str, Any]:
        try:
            model_path = normalize_utility_model_path(getattr(settings, "intent_routing_utility_llm_model_path", ""))
        except ValueError:
            model_path = str(getattr(settings, "intent_routing_utility_llm_model_path", "") or "")
            path_invalid = True
        else:
            path_invalid = False
        device = getattr(settings, "intent_routing_device", "auto") or "auto"
        backend = utility_backend_status()
        loaded = any(key[0] == model_path for key in self._cache) if model_path else False
        base = {
            "available": False,
            "configured": bool(model_path),
            "loaded": loaded,
            "model_path": model_path,
            "device": device,
            "resolved_device": None,
            "backend": backend,
            "reason": None,
        }
        if not model_path:
            return {**base, "reason": UTILITY_MODEL_NOT_CONFIGURED}
        if path_invalid:
            return {**base, "reason": UTILITY_MODEL_PATH_INVALID}
        if not backend["transformers_available"] or not backend["torch_available"]:
            return {**base, "reason": UTILITY_BACKEND_UNAVAILABLE}
        try:
            resolved_device = resolve_utility_device(device)
            absolute_path = resolve_utility_model_path(model_path, self.root)
        except Exception as exc:
            return {**base, "reason": getattr(exc, "code", UTILITY_MODEL_PATH_INVALID)}
        if not absolute_path.is_dir():
            return {**base, "resolved_device": resolved_device, "reason": UTILITY_MODEL_NOT_FOUND}
        return {**base, "available": True, "resolved_device": resolved_device, "reason": None}

    async def generate(self, prompt: str, settings: Any, *, max_new_tokens: int = 128) -> UtilityGeneration:
        model_path = normalize_utility_model_path(getattr(settings, "intent_routing_utility_llm_model_path", ""))
        if not model_path:
            raise UtilityLLMError(UTILITY_MODEL_NOT_CONFIGURED, "Utility LLM model path is not configured.")
        backend = utility_backend_status()
        if not backend["transformers_available"] or not backend["torch_available"]:
            raise UtilityLLMError(UTILITY_BACKEND_UNAVAILABLE, "Optional Utility LLM dependencies are not installed.", backend)
        device = resolve_utility_device(getattr(settings, "intent_routing_device", "auto") or "auto")
        absolute_path = resolve_utility_model_path(model_path, self.root)
        if not absolute_path.is_dir():
            raise UtilityLLMError(UTILITY_MODEL_NOT_FOUND, f"Utility LLM model not found: {model_path}")
        text = await asyncio.to_thread(self._generate_sync, absolute_path, model_path, device, prompt, max_new_tokens)
        return UtilityGeneration(text=text, model_path=model_path, device=device)

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
        return {"title": title, "backend": "utility_llm", "model_path": raw.model_path}

    async def extract_intent_json(self, text: str, settings: Any, context: dict[str, Any] | None = None) -> dict[str, Any]:
        compact_context = json.dumps(context or {}, ensure_ascii=False)[:6000]
        prompt = (
            "Classify the user's message for internal shadow diagnostics only.\n"
            "Return strict JSON with keys: intent, confidence, target_agent_hint, kb_hint, query, command_hint, target_agent_id, kb_id, match_source.\n"
            "Allowed intent values: chat, image_generation, knowledge_query, agent_route, command_like, unknown.\n"
            "Use compact candidates only; do not invent agent ids or knowledge base ids outside the candidates.\n"
            "Safety: command_like must not be executed automatically. Generic agent_route requires future confirmation. image_generation may target comfyui_agent. knowledge_query may provide kb_hint and query only.\n"
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

    def _generate_sync(self, absolute_path: Path, model_path: str, device: str, prompt: str, max_new_tokens: int) -> str:
        key = (model_path, device)
        if key not in self._cache:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

            tokenizer = AutoTokenizer.from_pretrained(str(absolute_path), local_files_only=True, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(str(absolute_path), local_files_only=True, trust_remote_code=True)
            model.to(device)
            model.eval()
            self._cache[key] = {"tokenizer": tokenizer, "model": model}
        tokenizer = self._cache[key]["tokenizer"]
        model = self._cache[key]["model"]
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
    }


def _slot(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:200] if text else None


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
