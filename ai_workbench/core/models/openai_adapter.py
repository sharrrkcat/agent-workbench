from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from httpx_sse import aconnect_sse, SSEError
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import (
    ChatChunk, ChatDelta, ChatRequest, ChatResult, EmbeddingResult,
    ModelProfile, ModelStatus, ProviderProfile, Usage,
)


def transport_error(exc: Exception) -> ModelError:
    if isinstance(exc, httpx.TimeoutException):
        return ModelError("MODEL_TIMEOUT", "Provider request timed out.", 504)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return ModelError("PROVIDER_ERROR", f"Provider returned HTTP {status}.", 502)
    if isinstance(exc, httpx.RequestError):
        return ModelError("MODEL_UNAVAILABLE", "Cannot connect to the configured provider.", 503)
    return ModelError("PROVIDER_PROTOCOL_ERROR", "Provider returned an invalid inference response.", 502)


class OpenAIAdapter:
    def __init__(self, provider: ProviderProfile, transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(
            base_url=provider.base_url + "/",
            headers={"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {},
            timeout=provider.timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            response = await self.client.request(method, path, json=payload)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict) or "error" in value:
                raise ValueError("invalid response")
            return value
        except (httpx.HTTPError, ValueError) as exc:
            raise transport_error(exc) from exc

    async def models(self) -> list[str]:
        data = await self._json("GET", "models")
        try:
            ids = [item["id"] for item in data["data"]]
            if any(not isinstance(item, str) or not item for item in ids):
                raise ValueError("invalid model id")
            return sorted(set(ids))
        except (ValueError, KeyError, TypeError) as exc:
            raise transport_error(exc) from exc

    async def health(self, profile: ModelProfile) -> ModelStatus:
        if profile.kind not in {"llm", "embedding"}:
            raise ModelError("MODEL_UNAVAILABLE", "This model kind requires a managed backend.", 503)
        if profile.model_ref not in await self.models():
            raise ModelError("MODEL_NOT_FOUND", "model_ref is not advertised by the configured provider.", 404)
        return ModelStatus(state="ready")

    async def load(self, profile: ModelProfile) -> ModelStatus:
        return await self.health(profile)

    async def unload(self, profile: ModelProfile) -> ModelStatus:
        raise ModelError("UNLOAD_UNSUPPORTED", "OpenAI-compatible connections do not expose model unload.", 409)

    @staticmethod
    def _payload(profile: ModelProfile, request: ChatRequest) -> dict:
        payload = {**profile.parameters, **request.model_dump(exclude_none=True, by_alias=True, exclude_unset=True)}
        payload.update(model=profile.model_ref, stream=request.stream)
        return payload

    async def chat(self, profile: ModelProfile, request: ChatRequest) -> ChatResult:
        data = await self._json("POST", "chat/completions", self._payload(profile, request))
        try:
            if len(data["choices"]) != 1 or data["choices"][0]["index"] != 0:
                raise ValueError("expected one choice")
            choice = data["choices"][0]
            message = dict(choice["message"])
            if message.pop("refusal", None):
                raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
            result = ChatResult(message=message, finish_reason=choice["finish_reason"], usage=data.get("usage"))
            if result.message.role != "assistant":
                raise ValueError("expected assistant message")
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise transport_error(exc) from exc

    async def chat_stream(self, profile: ModelProfile, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        finished = False
        tool_ids: dict[int, str] = {}
        tool_names: dict[int, str] = {}
        try:
            async with aconnect_sse(self.client, "POST", "chat/completions", json=self._payload(profile, request)) as source:
                source.response.raise_for_status()
                async for event in source.aiter_sse():
                    if event.data == "[DONE]":
                        if not finished:
                            raise ValueError("stream ended without finish reason")
                        return
                    if not event.data:
                        continue
                    data = json.loads(event.data)
                    if "error" in data:
                        raise ModelError("PROVIDER_ERROR", "Provider reported an error during streaming.", 502)
                    choices = data["choices"]
                    usage = Usage.model_validate(data["usage"]) if data.get("usage") else None
                    if not choices:
                        if usage:
                            yield ChatChunk(usage=usage)
                        continue
                    if finished or len(choices) != 1 or choices[0]["index"] != 0:
                        raise ValueError("invalid stream choice")
                    choice = choices[0]
                    delta_data = dict(choice["delta"])
                    if delta_data.pop("refusal", None):
                        raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
                    delta = ChatDelta.model_validate(delta_data)
                    for tool in delta.tool_calls or []:
                        if tool.id:
                            if tool.index in tool_ids and tool_ids[tool.index] != tool.id:
                                raise ValueError("tool id changed")
                            tool_ids[tool.index] = tool.id
                        if tool.function and tool.function.name:
                            tool_names[tool.index] = tool_names.get(tool.index, "") + tool.function.name
                    finish = choice.get("finish_reason")
                    if finish == "tool_calls" and (not tool_ids or set(tool_ids) != set(tool_names) or any(not value for value in tool_ids.values())):
                        raise ValueError("incomplete tool call")
                    if tool_ids and finish and finish != "tool_calls":
                        raise ValueError("invalid tool finish reason")
                    chunk = ChatChunk(delta=delta, finish_reason=finish, usage=usage)
                    finished = finish is not None
                    yield chunk
                raise ValueError("stream ended without DONE")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, SSEError) as exc:
            raise transport_error(exc) from exc

    async def embed(self, profile: ModelProfile, texts: list[str], dimensions: int | None) -> EmbeddingResult:
        payload = {"model": profile.model_ref, "input": texts, "encoding_format": "float"}
        if dimensions is not None:
            payload["dimensions"] = dimensions
        data = await self._json("POST", "embeddings", payload)
        try:
            rows = sorted(data["data"], key=lambda item: item["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError("embedding count or index mismatch")
            return EmbeddingResult(vectors=[row["embedding"] for row in rows], usage=data.get("usage"))
        except (KeyError, TypeError, ValueError) as exc:
            raise transport_error(exc) from exc

    async def rerank(self, profile, query, documents):
        raise ModelError("MODEL_UNAVAILABLE", "Reranking requires a managed backend.", 503)

    async def image_embed(self, profile, images):
        raise ModelError("MODEL_UNAVAILABLE", "Image embedding requires a managed backend.", 503)

    async def vision(self, profile, images):
        raise ModelError("MODEL_UNAVAILABLE", "Vision models require a managed backend.", 503)

    async def close(self) -> None:
        await self.client.aclose()
