import json
import os
from typing import Any, Dict, List, Optional

import httpx

from ai_workbench.core.config_schema import MASKED_SECRET
from ai_workbench.core.llm_stream import LLMStreamChunk


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
        return {
            "success": False,
            "unsupported": True,
            "message": "OpenAI-compatible unload is not supported by this runtime.",
        }

    def list_models(self, model_config: Optional[Dict[str, Any]] = None) -> List[str]:
        config = _resolve_config(model_config or {}, require_model=False)
        headers = {}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        with httpx.Client(timeout=float(config.get("timeout", 60))) as client:
            response = client.get(f"{config['base_url'].rstrip('/')}/models", headers=headers)
            response.raise_for_status()
            data = response.json()

        models = data.get("data") or []
        return [item.get("id", "") for item in models if isinstance(item, dict) and item.get("id")]


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
