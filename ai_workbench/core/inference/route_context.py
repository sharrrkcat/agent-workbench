from __future__ import annotations

from typing import Any

from ai_workbench.core.inference.observability import log_inference_failure
from ai_workbench.core.inference.stateless import StatelessInferenceError


def log_stateless_failure(
    state: Any,
    *,
    endpoint: str,
    exc: StatelessInferenceError,
    context: dict[str, Any],
) -> None:
    log_inference_failure(
        repo_root=getattr(state, "repo_root", None),
        endpoint=endpoint,
        status_code=exc.status_code,
        error_code=getattr(exc.code, "value", str(exc.code)),
        exception=exc,
        context=context,
    )


def chat_failure_context(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    return {
        "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
        "message_count": len(messages) if isinstance(messages, list) else None,
        "stream": payload.get("stream") is True,
    }


def embedding_failure_context(payload: dict[str, Any]) -> dict[str, Any]:
    input_value = payload.get("input")
    input_count = None
    if isinstance(input_value, str):
        input_count = 1
    elif isinstance(input_value, list):
        input_count = len(input_value)
    return {
        "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
        "input_count": input_count,
        "encoding_format": payload.get("encoding_format") if isinstance(payload.get("encoding_format"), str) else None,
    }


def multimodal_failure_context(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = payload.get("inputs")
    input_types = []
    if isinstance(inputs, list):
        for item in inputs:
            if isinstance(item, dict) and isinstance(item.get("type"), str):
                input_types.append(item["type"])
    return {
        "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
        "input_count": len(inputs) if isinstance(inputs, list) else None,
        "input_types": input_types,
        "normalize_present": "normalize" in payload,
    }


def vision_failure_context(payload: dict[str, Any]) -> dict[str, Any]:
    options = payload.get("options")
    return {
        "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
        "task": payload.get("task") if isinstance(payload.get("task"), str) else None,
        "option_keys": sorted(str(key) for key in options) if isinstance(options, dict) else [],
    }
