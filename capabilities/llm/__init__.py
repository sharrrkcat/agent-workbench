import json
import os
import gc
import importlib.util
import threading
from typing import Any, Dict, List, Optional

import httpx

from ai_workbench.core.config_schema import MASKED_SECRET
from ai_workbench.core.llm_stream import LLMStreamChunk
from ai_workbench.core.provider_inventory import (
    internal_provider_backend_status,
    is_internal_provider,
    resolve_internal_llm_model_ref,
    scan_internal_provider_models,
)


INTERNAL_MODEL_CACHE: Dict[tuple[Any, ...], Dict[str, Any]] = {}
INTERNAL_MODEL_CACHE_LOCK = threading.RLock()


class CapabilityRuntime:
    def generate(
        self,
        prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> str:
        return self.chat(
            messages=[{"role": "user", "content": prompt}],
            model_config=model_config,
            stream=stream,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> str:
        result = self.chat_raw(messages=messages, model_config=model_config, stream=stream)
        return result.get("content") or ""

    def chat_raw(
        self,
        messages: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        if stream:
            raise ValueError("Use chat_stream for streaming responses.")
        config = _resolve_config(model_config or {})
        if is_internal_provider((model_config or {}).get("provider")):
            return _internal_chat_raw(messages=messages, model_config=model_config or {}, config=config)
        headers = {}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        payload = {
            "model": config["model"],
            "messages": messages,
            "stream": stream,
        }
        with httpx.Client(timeout=float(config.get("timeout", 60))) as client:
            response = client.post(
                f"{config['base_url'].rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            return {"content": "", "reasoning_content": None, "usage": data.get("usage"), "raw": data}
        message = choices[0].get("message") or {}
        reasoning_content = message.get("reasoning_content")
        return {
            "content": message.get("content") or "",
            "reasoning_content": reasoning_content if isinstance(reasoning_content, str) and reasoning_content else None,
            "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
            "raw": data,
        }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]] = None,
    ):
        if is_internal_provider((model_config or {}).get("provider")):
            raise ValueError("Internal LLM providers do not support streaming in this build.")
        config = _resolve_config(model_config or {})
        headers = {}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        payload = {
            "model": config["model"],
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            async for chunk in _stream_chat_completion(config, headers, payload):
                yield chunk
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.lower()
            if exc.response.status_code == 400 and "stream_options" in body:
                retry_payload = dict(payload)
                retry_payload.pop("stream_options", None)
                async for chunk in _stream_chat_completion(config, headers, retry_payload):
                    yield chunk
                return
            raise

    async def generate_stream(
        self,
        prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
    ):
        async for chunk in self.chat_stream(
            messages=[{"role": "user", "content": prompt}],
            model_config=model_config,
        ):
            yield chunk

    def unload(self, model_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        provider = (model_config or {}).get("provider")
        if is_internal_provider(provider):
            removed = unload_internal_model(provider=provider, model_ref=(model_config or {}).get("model_id") or (model_config or {}).get("model"))
            return {
                "success": True,
                "unsupported": False,
                "removed": removed,
                "message": "Internal LLM cache released." if removed else "No matching internal LLM cache was loaded.",
            }
        return {
            "success": False,
            "unsupported": True,
            "message": "OpenAI-compatible unload is not supported by this runtime.",
        }

    def list_models(self, model_config: Optional[Dict[str, Any]] = None) -> List[str]:
        return [item["id"] for item in self.list_model_items(model_config=model_config) if item.get("id")]

    def list_model_items(self, model_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        config = _resolve_config(model_config or {}, require_model=False)
        provider = (model_config or {}).get("provider") or "openai_compatible"
        if is_internal_provider(provider):
            inventory = scan_internal_provider_models(provider)
            return [item for item in inventory["models"] if item.get("kind") == "llm" or str(item.get("id") or "").startswith("llm/")]
        headers = {}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        with httpx.Client(timeout=float(config.get("timeout", 60))) as client:
            if provider == "lm_studio":
                try:
                    response = client.get(_lm_studio_native_models_url(config["base_url"]), headers=headers)
                    response.raise_for_status()
                    native_models = _extract_lm_studio_native_models(response.json())
                    if native_models is not None:
                        return [_lm_studio_model_item(item) for item in native_models if _lm_studio_model_identifier(item)]
                except httpx.HTTPError:
                    pass
            response = client.get(f"{config['base_url'].rstrip('/')}/models", headers=headers)
            response.raise_for_status()
            data = response.json()

        models = data.get("data") or []
        return [_openai_model_item(item) for item in models if isinstance(item, dict) and item.get("id")]


def _resolve_config(model_config: Dict[str, Any], require_model: bool = True) -> Dict[str, Any]:
    base_url = os.getenv("AGENT_WORKBENCH_LLM_BASE_URL") or model_config.get("base_url") or "http://localhost:1234/v1"
    model = os.getenv("AGENT_WORKBENCH_LLM_MODEL") or model_config.get("model")
    api_key = os.getenv("AGENT_WORKBENCH_LLM_API_KEY") or model_config.get("api_key") or ""
    if api_key == MASKED_SECRET:
        api_key = ""
    timeout = os.getenv("AGENT_WORKBENCH_LLM_TIMEOUT") or model_config.get("timeout") or 60

    if require_model and not model:
        raise ValueError("LLM model is required by manifest or AGENT_WORKBENCH_LLM_MODEL.")

    return {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "timeout": timeout,
    }


def _internal_chat_raw(messages: List[Dict[str, str]], model_config: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    provider = str(model_config.get("provider") or "")
    model_ref = str(model_config.get("model_id") or config.get("model") or "")
    try:
        if provider == "internal_llama_cpp":
            content = _internal_llama_cpp_generate(messages, model_config, model_ref)
        elif provider == "internal_transformers":
            content = _internal_transformers_generate(messages, model_config, model_ref)
        else:
            raise ValueError(f"Unsupported internal LLM provider: {provider}")
    except Exception as exc:
        code = getattr(exc, "code", None) or _internal_error_code(provider, exc)
        raise RuntimeError(f"{code}: {str(exc) or 'Internal LLM generation failed.'}") from exc
    return {
        "content": content,
        "reasoning_content": None,
        "usage": None,
        "raw": {"model": model_ref, "provider": provider},
    }


def _internal_llama_cpp_generate(messages: List[Dict[str, str]], model_config: Dict[str, Any], model_ref: str) -> str:
    if importlib.util.find_spec("llama_cpp") is None:
        raise RuntimeError("llama_cpp_unavailable")
    path = resolve_internal_llm_model_ref("internal_llama_cpp", model_ref)
    key = ("internal_llama_cpp", model_ref, int(model_config.get("context_size") or 4096), int(model_config.get("gpu_layers") or 0), model_config.get("threads"))
    with INTERNAL_MODEL_CACHE_LOCK:
        if key not in INTERNAL_MODEL_CACHE:
            from llama_cpp import Llama  # type: ignore

            kwargs: dict[str, Any] = {
                "model_path": str(path),
                "n_ctx": int(model_config.get("context_size") or 4096),
                "n_gpu_layers": int(model_config.get("gpu_layers") or 0),
                "verbose": False,
            }
            if model_config.get("threads") is not None:
                kwargs["n_threads"] = int(model_config["threads"])
            INTERNAL_MODEL_CACHE[key] = {"llm": Llama(**kwargs)}
        llm = INTERNAL_MODEL_CACHE[key]["llm"]
        max_tokens = _max_tokens(model_config)
        temperature = _temperature(model_config)
        top_p = _top_p(model_config)
        stop = _stop(model_config)
        chat_completion = getattr(llm, "create_chat_completion", None)
        if callable(chat_completion):
            result = chat_completion(messages=_safe_messages(messages), max_tokens=max_tokens, temperature=temperature, top_p=top_p, stop=stop)
        else:
            result = llm.create_completion(prompt=_messages_to_prompt(messages), max_tokens=max_tokens, temperature=temperature, top_p=top_p, stop=stop)
    return _extract_llama_cpp_text(result)


def _internal_transformers_generate(messages: List[Dict[str, str]], model_config: Dict[str, Any], model_ref: str) -> str:
    if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
        raise RuntimeError("transformers_unavailable")
    path = resolve_internal_llm_model_ref("internal_transformers", model_ref)
    device = str(model_config.get("device") or "auto")
    key = ("internal_transformers", model_ref, device)
    with INTERNAL_MODEL_CACHE_LOCK:
        if key not in INTERNAL_MODEL_CACHE:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

            resolved_device = _resolve_torch_device(torch, device)
            tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(str(path), local_files_only=True, trust_remote_code=True)
            model.to(resolved_device)
            model.eval()
            INTERNAL_MODEL_CACHE[key] = {"tokenizer": tokenizer, "model": model, "device": resolved_device}
        tokenizer = INTERNAL_MODEL_CACHE[key]["tokenizer"]
        model = INTERNAL_MODEL_CACHE[key]["model"]
        resolved_device = INTERNAL_MODEL_CACHE[key]["device"]
        rendered = _render_chat_prompt(tokenizer, _safe_messages(messages))
        inputs = tokenizer(rendered, return_tensors="pt")
        inputs = {name: value.to(resolved_device) for name, value in inputs.items()}
        output_ids = model.generate(
            **inputs,
            max_new_tokens=_max_tokens(model_config),
            do_sample=_temperature(model_config) > 0,
            temperature=_temperature(model_config) if _temperature(model_config) > 0 else None,
            top_p=_top_p(model_config),
            pad_token_id=getattr(tokenizer, "eos_token_id", None),
        )
        prompt_len = inputs["input_ids"].shape[-1]
        generated = output_ids[0][prompt_len:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def unload_internal_model(provider: str | None = None, model_ref: str | None = None) -> int:
    removed = 0
    with INTERNAL_MODEL_CACHE_LOCK:
        for key in list(INTERNAL_MODEL_CACHE):
            if provider and key[0] != provider:
                continue
            if model_ref and len(key) > 1 and key[1] != model_ref:
                continue
            INTERNAL_MODEL_CACHE.pop(key, None)
            removed += 1
    if removed:
        gc.collect()
        if importlib.util.find_spec("torch") is not None:
            try:
                import torch  # type: ignore

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
    return removed


def internal_model_loaded(provider: str, model_ref: str) -> bool:
    with INTERNAL_MODEL_CACHE_LOCK:
        return any(key[0] == provider and len(key) > 1 and key[1] == model_ref for key in INTERNAL_MODEL_CACHE)


def _lm_studio_native_models_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/api/v1"):
        trimmed = trimmed[:-7]
    if trimmed.endswith("/v1"):
        trimmed = trimmed[:-3]
    return f"{trimmed}/api/v1/models"


def _extract_lm_studio_native_models(data: Any) -> List[Dict[str, Any]] | None:
    if not isinstance(data, dict):
        return None
    if "models" in data:
        models = data.get("models")
    elif "data" in data:
        models = data.get("data")
    else:
        return None
    if not isinstance(models, list):
        return None
    return [item for item in models if isinstance(item, dict)]


def _lm_studio_model_identifier(item: Dict[str, Any]) -> str:
    return str(item.get("key") or item.get("id") or "").strip()


def _model_type(item: Dict[str, Any]) -> str:
    value = str(item.get("type") or "").strip().lower()
    return value if value in {"llm", "embedding"} else "unknown"


def _loaded_instances(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    instances = item.get("loaded_instances")
    if not isinstance(instances, list):
        return []
    return [instance for instance in instances if isinstance(instance, dict)]


def _capabilities(item: Dict[str, Any]) -> Dict[str, bool]:
    raw = item.get("capabilities")
    if not isinstance(raw, dict):
        return {}
    return {
        "vision": bool(raw.get("vision") or raw.get("image_input")),
        "tools": bool(raw.get("tools") or raw.get("trained_for_tool_use")),
        "reasoning": bool(raw.get("reasoning") or raw.get("reasoning_output")),
    }


def _lm_studio_model_item(item: Dict[str, Any]) -> Dict[str, Any]:
    model_id = _lm_studio_model_identifier(item)
    instances = _loaded_instances(item)
    return {
        "id": model_id,
        "name": item.get("display_name") or item.get("name") or model_id,
        "type": _model_type(item),
        "loaded": bool(instances),
        "loaded_instance_ids": [str(instance.get("id")) for instance in instances if instance.get("id")],
        "capabilities": _capabilities(item),
        "raw": item,
    }


def _openai_model_item(item: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(item.get("id") or "").strip()
    return {
        "id": model_id,
        "name": item.get("name") or item.get("display_name") or model_id,
        "type": _model_type(item),
        "loaded": None,
        "loaded_instance_ids": [],
        "capabilities": _capabilities(item),
        "raw": item,
    }


def _safe_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role") or "user")
        if role not in {"system", "user", "assistant"}:
            role = "user"
        result.append({"role": role, "content": str(item.get("content") or "")})
    return result


def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
    return "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in _safe_messages(messages)).strip()


def _render_chat_prompt(tokenizer: Any, messages: List[Dict[str, str]]) -> str:
    template = getattr(tokenizer, "apply_chat_template", None)
    if callable(template):
        try:
            return template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        except TypeError:
            return template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            pass
    return _messages_to_prompt(messages)


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


def _max_tokens(model_config: Dict[str, Any]) -> int:
    try:
        return max(1, min(int(model_config.get("max_tokens") or 256), 4096))
    except (TypeError, ValueError):
        return 256


def _temperature(model_config: Dict[str, Any]) -> float:
    try:
        return max(0.0, float(model_config.get("temperature") if model_config.get("temperature") is not None else 0.0))
    except (TypeError, ValueError):
        return 0.0


def _top_p(model_config: Dict[str, Any]) -> float:
    try:
        return max(0.0, min(float(model_config.get("top_p") if model_config.get("top_p") is not None else 1.0), 1.0))
    except (TypeError, ValueError):
        return 1.0


def _stop(model_config: Dict[str, Any]) -> list[str] | None:
    value = model_config.get("stop")
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()][:8]
    return ["</s>", "<|im_end|>"]


def _resolve_torch_device(torch: Any, requested: str) -> str:
    device = str(requested or "auto").strip().lower()
    cuda_available = bool(torch.cuda.is_available())
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    mps_available = bool(mps_backend and mps_backend.is_available())
    if device == "auto":
        if cuda_available:
            return "cuda"
        if mps_available:
            return "mps"
        return "cpu"
    if device == "cuda" and not cuda_available:
        raise RuntimeError("cuda_unavailable")
    if device == "mps" and not mps_available:
        raise RuntimeError("mps_unavailable")
    if device in {"cpu", "cuda", "mps"}:
        return device
    raise ValueError("local_runtime_device must be auto, cpu, cuda, or mps.")


def _internal_error_code(provider: str, exc: Exception) -> str:
    text = str(exc)
    if "llama_cpp_unavailable" in text:
        return "llama_cpp_unavailable"
    if "transformers_unavailable" in text:
        return "transformers_unavailable"
    if "cuda_unavailable" in text:
        return "cuda_unavailable"
    if "mps_unavailable" in text:
        return "mps_unavailable"
    if provider == "internal_llama_cpp" and not internal_provider_backend_status(provider).get("available"):
        return "llama_cpp_unavailable"
    if provider == "internal_transformers" and not internal_provider_backend_status(provider).get("available"):
        return "transformers_unavailable"
    if isinstance(exc, FileNotFoundError):
        return "model_not_found"
    if isinstance(exc, ValueError):
        return "model_ref_invalid"
    return "internal_llm_generation_failed"


async def _stream_chat_completion(config: Dict[str, Any], headers: Dict[str, str], payload: Dict[str, Any]):
    async with httpx.AsyncClient(timeout=float(config.get("timeout", 60))) as client:
        async with client.stream(
            "POST",
            f"{config['base_url'].rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                chunk = _parse_sse_line(line)
                if chunk is not None:
                    yield chunk


def _parse_sse_line(line: str) -> Optional[LLMStreamChunk]:
    value = line.strip()
    if not value or value.startswith(":"):
        return None
    if value.startswith("data:"):
        value = value[5:].strip()
    if not value or value == "[DONE]":
        return None
    data = json.loads(value)
    choices = data.get("choices") or []
    content_delta = None
    reasoning_delta = None
    finish_reason = None
    for choice in choices:
        delta = choice.get("delta") or {}
        if content_delta is None:
            content_delta = delta.get("content")
        if reasoning_delta is None:
            reasoning_delta = delta.get("reasoning_content")
        if finish_reason is None:
            finish_reason = choice.get("finish_reason")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return LLMStreamChunk(
        content_delta=content_delta,
        reasoning_delta=reasoning_delta,
        finish_reason=finish_reason,
        usage=usage,
        raw=data,
    )
