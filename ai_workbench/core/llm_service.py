"""Provider-facing LLM service used by chat and utility generation."""

from __future__ import annotations

import inspect
from typing import Any, AsyncIterator

import httpx


class LLMService:
    """Small provider adapter shared by chat, utility work and ``/v1``."""

    def __init__(self, runtime: Any = None) -> None:
        self.runtime = runtime

    async def chat(self, messages: list[dict[str,str]], model_config: dict[str,Any] | None = None) -> str:
        return _content(await self.chat_response(messages, model_config))

    async def chat_response(
        self,
        messages: list[dict[str, str]],
        model_config: dict[str, Any] | None = None,
    ) -> Any:
        """Return the provider response without discarding usage metadata."""
        if self.runtime is not None:
            method=getattr(self.runtime,"chat",None)
            if callable(method):
                result = method(messages=messages, model_config=model_config or {}, stream=False)
                if inspect.isawaitable(result):
                    result = await result
                return result
            raw=getattr(self.runtime,"chat_raw",None)
            if callable(raw):
                result = raw(messages=messages, model_config=model_config or {}, stream=False)
                if inspect.isawaitable(result):
                    result = await result
                return result
        return await _http_chat_response(messages, model_config or {})

    async def chat_stream(self, messages: list[dict[str,str]], model_config: dict[str,Any] | None = None) -> AsyncIterator[str]:
        if self.runtime is not None:
            method=getattr(self.runtime,"chat_stream",None)
            if callable(method):
                stream = method(messages=messages, model_config=model_config or {})
                if inspect.isawaitable(stream):
                    stream = await stream
                if hasattr(stream, "__aiter__"):
                    async for chunk in stream:
                        value = _content(chunk)
                        if value:
                            yield value
                else:
                    for chunk in stream or ():
                        value = _content(chunk)
                        if value:
                            yield value
                return
            # A synchronous test runtime is still useful; expose one final delta.
            value = await self.chat(messages, model_config)
            if value:
                yield value
            return
        async for chunk in _http_stream(messages, model_config or {}):
            yield chunk

    async def generate(self, prompt: str, model_config: dict[str,Any] | None = None) -> str:
        if self.runtime is not None:
            method=getattr(self.runtime,"generate",None)
            if callable(method):
                result = method(prompt, model_config=model_config or {}, stream=False)
                if inspect.isawaitable(result):
                    result = await result
                return _content(result)
        return await self.chat([{"role":"user","content":prompt}],model_config)

    def unload(self, model_config: dict[str,Any] | None = None) -> dict[str,Any]:
        method=getattr(self.runtime,"unload",None) if self.runtime is not None else None
        if callable(method):
            try:
                result = method(model_config=model_config or {})
                # The public unload API is synchronous.  An awaitable is
                # intentionally reported as requested; close coroutine objects
                # so they do not leak an un-awaited warning.
                if inspect.isawaitable(result):
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                    return {"success": True, "status": "requested"}
                return result if isinstance(result, dict) else {"success": bool(result), "status": "unloaded"}
            except Exception as exc:
                return {"success": False, "unsupported": True, "message": str(exc)}
        return {"success": False, "unsupported": True, "message": "LLM unload is not supported by this provider."}

    def list_models(self, model_config: dict[str,Any] | None = None) -> list[str]:
        method=getattr(self.runtime,"list_models",None) if self.runtime is not None else None
        if callable(method):
            value = method(model_config=model_config or {})
            return list(value or [])
        return []


def _content(value: Any) -> str:
    if value is None: return ""
    if isinstance(value,str): return value
    if isinstance(value,dict):
        content = value.get("content") or value.get("text")
        if isinstance(content, (dict, list)):
            return str(content)
        if content is not None:
            return str(content)
        message = value.get("message")
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(message or "")
    return str(getattr(value,"content_delta",None) or getattr(value,"content",None) or value)


async def _http_chat(messages: list[dict[str,str]], config: dict[str,Any]) -> str:
    return _content(await _http_chat_response(messages, config))


async def _http_chat_response(messages: list[dict[str, str]], config: dict[str, Any]) -> dict[str, Any]:
    base=str(config.get("base_url") or "http://localhost:1234/v1").rstrip("/"); model=config.get("model") or config.get("model_id")
    if not model: raise RuntimeError("LLM_MODEL_NOT_SELECTED: Select a chat model in Settings before sending a message.")
    headers={"Authorization":f"Bearer {config['api_key']}"} if config.get("api_key") else {}
    async with httpx.AsyncClient(timeout=float(config.get("timeout") or 60)) as client:
        response = await client.post(
            f"{base}/chat/completions",
            json={"model": model, "messages": messages, "stream": False},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"content": str(data)}


async def _http_stream(messages: list[dict[str,str]], config: dict[str,Any]) -> AsyncIterator[str]:
    # Keep the core provider contract small; streaming parsing is deliberately
    # tolerant of OpenAI-compatible ``data:`` lines.
    base = str(config.get("base_url") or "http://localhost:1234/v1").rstrip("/")
    model = config.get("model") or config.get("model_id")
    if not model: raise RuntimeError("LLM_MODEL_NOT_SELECTED: Select a chat model in Settings before sending a message.")
    headers = {"Authorization": f"Bearer {config['api_key']}"} if config.get("api_key") else {}
    async with httpx.AsyncClient(timeout=float(config.get("timeout") or 60)) as client:
        async with client.stream(
            "POST",
            f"{base}/chat/completions",
            json={"model": model, "messages": messages, "stream": True},
            headers=headers,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try: data=__import__("json").loads(payload); choices=data.get("choices") or []; delta=(choices[0].get("delta") or {}) if choices else {}; value=delta.get("content")
                except Exception: value=None
                if value: yield str(value)
