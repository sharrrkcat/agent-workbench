from __future__ import annotations

from time import time
from typing import Any
from uuid import uuid4

from ai_workbench.core import embedding as embedding_module
from ai_workbench.core.inference.errors import InferenceErrorCode
from ai_workbench.core.knowledge_models import KnowledgeModelError


LLM_MODEL_PREFIX = "llm:"
EMBEDDING_MODEL_PREFIX = "embedding:"


class StatelessInferenceError(Exception):
    def __init__(self, code: InferenceErrorCode, message: str | None = None, *, status_code: int = 400) -> None:
        super().__init__(message or code.value)
        self.code = code
        self.message = message
        self.status_code = status_code


def openai_model_list(state: Any) -> dict[str, Any]:
    return {"object": "list", "data": [_openai_model_item(item) for item in list_external_models(state)]}


def workbench_model_list(state: Any) -> dict[str, Any]:
    data = list_external_models(state)
    return {
        "object": "list",
        "data": data,
        "summary": {
            "llm_profiles_available": sum(1 for item in data if item["type"] == "llm"),
            "embedding_profiles_available": sum(1 for item in data if item["type"] == "text_embedding"),
            "multimodal_profiles_available": 0,
            "vision_profiles_available": 0,
        },
    }


def inference_status_models_summary(state: Any) -> dict[str, int]:
    data = list_external_models(state)
    return {
        "llm_external_enabled_count": sum(1 for item in data if item["type"] == "llm"),
        "embedding_external_enabled_count": sum(1 for item in data if item["type"] == "text_embedding"),
    }


def list_external_models(state: Any) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    llm_profiles = getattr(state, "llm_profiles", None)
    if llm_profiles is not None:
        for profile in llm_profiles.list():
            if _llm_profile_servable(profile, state):
                models.append(
                    {
                        "id": f"{LLM_MODEL_PREFIX}{profile.id}",
                        "type": "llm",
                        "name": profile.name,
                        "capabilities": ["chat_completions"],
                        "profile_id": profile.id,
                        "provider_profile_id": profile.provider_profile_id,
                        "external_inference_enabled": True,
                    }
                )
    knowledge = getattr(state, "knowledge", None)
    if knowledge is not None:
        for profile in knowledge.list_embedding_profiles():
            if _embedding_profile_servable(profile, state):
                models.append(
                    {
                        "id": f"{EMBEDDING_MODEL_PREFIX}{profile.id}",
                        "type": "text_embedding",
                        "name": profile.name,
                        "capabilities": ["embeddings"],
                        "profile_id": profile.id,
                        "provider_profile_id": profile.provider_profile_id,
                        "external_inference_enabled": True,
                    }
                )
    return sorted(models, key=lambda item: (item["type"], item["id"]))


def create_chat_completion_response(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    model_id = _required_model(payload)
    if payload.get("stream") is True:
        raise StatelessInferenceError(InferenceErrorCode.NOT_IMPLEMENTED, status_code=501)
    messages = _validate_chat_messages(payload.get("messages"))
    model_config = _resolve_llm_model_config(state, model_id)
    for key in ("temperature", "top_p", "max_tokens"):
        if key in payload and payload[key] is not None:
            model_config[key] = payload[key]
    try:
        raw = state.runtimes.get_runtime("llm").chat(messages=messages, model_config=model_config, stream=False)
    except Exception as exc:
        raise _provider_exception(exc) from exc
    content, usage, actual_model = _extract_chat_result(raw)
    requested_model = model_id
    return {
        "id": f"chatcmpl_{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(usage, completion=True),
        **({"provider_model": actual_model} if actual_model and actual_model != requested_model else {}),
    }


def create_embeddings_response(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    model_id = _required_model(payload)
    if payload.get("encoding_format") not in (None, "float"):
        raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "Only encoding_format='float' is supported.")
    purpose = payload.get("purpose", "document")
    if purpose not in {"query", "document"}:
        raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "purpose must be 'query' or 'document'.")
    inputs = _validate_embedding_inputs(payload.get("input"))
    profile = _resolve_embedding_profile(state, model_id)
    settings = state.knowledge.get_settings()
    try:
        result = embedding_module.embed_texts(
            backend=state.knowledge_model_backend,
            profile=profile,
            texts=inputs,
            purpose=purpose,
            device=settings.local_model_device,
            provider_profile_store=state.provider_profiles,
            repo_root=state.repo_root,
        )
    except KnowledgeModelError as exc:
        raise _embedding_exception(exc) from exc
    vectors = result.get("vectors") or []
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": index, "embedding": vector} for index, vector in enumerate(vectors)],
        "model": model_id,
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def _openai_model_item(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "object": "model", "created": 0, "owned_by": "agent-workbench"}


def _provider_enabled(state: Any, provider_profile_id: str | None) -> bool:
    if not provider_profile_id:
        return True
    try:
        return bool(state.provider_profiles.get(provider_profile_id).enabled)
    except Exception:
        return False


def _llm_profile_servable(profile: Any, state: Any) -> bool:
    return bool(profile.enabled and getattr(profile, "external_inference_enabled", False) and profile.model_id and _provider_enabled(state, profile.provider_profile_id))


def _embedding_profile_servable(profile: Any, state: Any) -> bool:
    has_model = bool(profile.provider_model_id or profile.model_path)
    return bool(profile.enabled and getattr(profile, "external_inference_enabled", False) and has_model and _provider_enabled(state, profile.provider_profile_id))


def _required_model(payload: dict[str, Any]) -> str:
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "model is required.")
    return model.strip()


def _resolve_llm_model_config(state: Any, model_id: str) -> dict[str, Any]:
    if not model_id.startswith(LLM_MODEL_PREFIX):
        if model_id.startswith(EMBEDDING_MODEL_PREFIX):
            raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_ALLOWED, status_code=404)
        raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_FOUND, status_code=404)
    profile_id = model_id.removeprefix(LLM_MODEL_PREFIX)
    try:
        profile = state.llm_profiles.get(profile_id)
    except KeyError as exc:
        raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_FOUND, status_code=404) from exc
    if not _llm_profile_servable(profile, state):
        raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_ALLOWED, status_code=403)
    provider = state.provider_profiles.get(profile.provider_profile_id) if profile.provider_profile_id else None
    return {
        "provider": provider.provider if provider is not None else profile.provider,
        "base_url": provider.base_url if provider is not None else profile.base_url,
        "api_key": provider.api_key if provider is not None else profile.api_key,
        "model": profile.model_id,
        "model_id": profile.model_id,
        "timeout": (provider.timeout_seconds if provider is not None else profile.timeout) or 60,
        "provider_profile_id": provider.id if provider is not None else profile.provider_profile_id,
        "provider_profile_name": provider.name if provider is not None else None,
        "temperature": profile.temperature,
        "top_p": profile.top_p,
        "max_tokens": profile.max_tokens,
    }


def _resolve_embedding_profile(state: Any, model_id: str) -> Any:
    if not model_id.startswith(EMBEDDING_MODEL_PREFIX):
        if model_id.startswith(LLM_MODEL_PREFIX):
            raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_ALLOWED, status_code=404)
        raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_FOUND, status_code=404)
    profile_id = model_id.removeprefix(EMBEDDING_MODEL_PREFIX)
    try:
        profile = state.knowledge.get_embedding_profile(profile_id)
    except KeyError as exc:
        raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_FOUND, status_code=404) from exc
    if not _embedding_profile_servable(profile, state):
        raise StatelessInferenceError(InferenceErrorCode.MODEL_NOT_ALLOWED, status_code=403)
    return profile


def _validate_chat_messages(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "messages must be a non-empty array.")
    messages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "Each message must be an object.")
        role = item.get("role")
        content = item.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "Only system/user/assistant text messages are supported.")
        messages.append({"role": role, "content": content})
    return messages


def _validate_embedding_inputs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not value:
        raise StatelessInferenceError(InferenceErrorCode.INVALID_REQUEST, "input must be a string or non-empty array of strings.")
    if not all(isinstance(item, str) for item in value):
        raise StatelessInferenceError(InferenceErrorCode.MODEL_INPUT_TYPE_UNSUPPORTED)
    return list(value)


def _extract_chat_result(raw: Any) -> tuple[str, dict[str, Any] | None, str | None]:
    if isinstance(raw, str):
        return raw, None, None
    if isinstance(raw, dict):
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else None
        model = raw.get("model") if isinstance(raw.get("model"), str) else None
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"], usage, model
                if isinstance(first.get("text"), str):
                    return first["text"], usage, model
        if isinstance(raw.get("content"), str):
            return raw["content"], usage, model
    return "" if raw is None else str(raw), None, None


def _usage(usage: dict[str, Any] | None, *, completion: bool) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0} if completion else {"prompt_tokens": 0, "total_tokens": 0}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion_tokens))
    return {"prompt_tokens": prompt, "completion_tokens": completion_tokens, "total_tokens": total}


def _provider_exception(exc: Exception) -> StatelessInferenceError:
    lowered = str(exc).lower()
    if any(token in lowered for token in ("connect", "connection", "unreachable", "refused", "timeout")):
        return StatelessInferenceError(InferenceErrorCode.PROVIDER_UNAVAILABLE, status_code=502)
    return StatelessInferenceError(InferenceErrorCode.PROVIDER_ERROR, status_code=502)


def _embedding_exception(exc: KnowledgeModelError) -> StatelessInferenceError:
    lowered = (exc.code + " " + exc.message).lower()
    if any(token in lowered for token in ("unavailable", "not_configured", "disabled", "not found")):
        return StatelessInferenceError(InferenceErrorCode.PROVIDER_UNAVAILABLE, status_code=502)
    return StatelessInferenceError(InferenceErrorCode.PROVIDER_ERROR, status_code=502)
