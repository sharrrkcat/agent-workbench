from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx
from httpx_sse import aconnect_sse, SSEError
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.models.adapter import ChatInputCapture
from ai_workbench.core.models.llm_metrics import LLMUsage, NativeGenerationTiming
from ai_workbench.core.models.schema import (
    ChatChunk, ChatDelta, ChatRequest, ChatResult, EmbeddingPurpose, EmbeddingResult,
    ModelProfile, ExternalConnection, AudioOutput, GeneratedImage, ImageGenerationResult,
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
    def __init__(self, provider: ExternalConnection, transport: httpx.AsyncBaseTransport | None = None):
        self.allow_unindexed_complete_tool_call = provider.allow_unindexed_complete_tool_call
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

    async def generate_images(self, profile: ModelProfile, prompt: str, options: dict) -> ImageGenerationResult:
        payload = dict(options, model=profile.model_ref, prompt=prompt)
        try:
            async with self.client.stream("POST", "images/generations", json=payload) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > 64 * 1024 * 1024:
                        raise ValueError("Image generation response too large")
                    data.extend(chunk)
            value = strict_json_loads(data)
            if not isinstance(value, dict) or "error" in value or not isinstance(value.get("data"), list):
                raise ValueError("Invalid image generation response")
            if not 1 <= len(value["data"]) <= options["n"]:
                raise ValueError("Invalid image count")
            images = []
            for item in value["data"]:
                if not isinstance(item, dict):
                    raise ValueError("Invalid generated image")
                # Upstream metadata is not part of the public image result.
                image = GeneratedImage.model_validate({key: item[key] for key in GeneratedImage.model_fields if key in item})
                requested_format = options.get("response_format")
                if requested_format is not None and getattr(image, requested_format) is None:
                    raise ValueError("Unexpected image response format")
                images.append(image)
            return ImageGenerationResult(created=int(time.time()), data=images)
        except (httpx.HTTPError, ValueError) as exc:
            raise transport_error(exc) from exc

    async def speech(self, profile: ModelProfile, text: str, voice: str, speed: float,
                     response_format: str, language: str | None) -> AudioOutput:
        payload = dict(model=profile.model_ref, input=text, voice=voice, speed=speed, response_format=response_format)
        try:
            async with self.client.stream("POST", "audio/speech", json=payload) as response:
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                allowed = {"mp3": {"audio/mpeg", "audio/mp3"}, "wav": {"audio/wav", "audio/x-wav", "audio/wave"}}
                if mime not in allowed[response_format]:
                    raise ValueError("Unexpected audio content type")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > 32 * 1024 * 1024:
                        raise ValueError("Audio response too large")
                    data.extend(chunk)
            if response_format == "wav":
                valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
            else:
                valid = (len(data) >= 10 and data[:3] == b"ID3") or (
                    len(data) >= 4 and data[0] == 255 and data[1] & 0xE0 == 0xE0
                    and data[1] & 0x06 == 0x02 and (data[1] >> 3) & 3 != 1
                    and (data[2] >> 4) not in {0, 15} and (data[2] >> 2) & 3 != 3)
            if not valid:
                raise ValueError("Invalid audio signature")
            return AudioOutput(data=bytes(data), response_format=response_format)
        except (httpx.HTTPError, ValueError) as exc:
            raise transport_error(exc) from exc

    @staticmethod
    def _payload(profile: ModelProfile, request: ChatRequest) -> dict:
        from ai_workbench.core.models.runtimes.schema import is_transformers
        from ai_workbench.core.models.schema import LocalSource
        payload = {**profile.parameters, **request.model_dump(exclude_none=True, by_alias=True, exclude_unset=True, exclude={"cogita", "reasoning"})}
        payload.update(model=profile.model_ref, stream=request.stream)
        if request.reasoning is not None:
            if isinstance(profile.source, LocalSource):
                payload["chat_template_kwargs"] = {"enable_thinking": request.reasoning}
            else:
                payload["reasoning_effort"] = "medium" if request.reasoning else "none"
        if is_transformers(profile):
            payload["cogita_request_options"] = profile.request_options.model_dump(exclude={"streaming"})
        return payload

    async def chat(self, profile: ModelProfile, request: ChatRequest, *, capture: ChatInputCapture | None = None) -> ChatResult:
        payload = self._payload(profile, request)
        if capture is not None:
            capture(payload)
        data = await self._json("POST", "chat/completions", payload)
        try:
            if len(data["choices"]) != 1 or data["choices"][0]["index"] != 0:
                raise ValueError("expected one choice")
            choice = data["choices"][0]
            message = dict(choice["message"])
            if message.pop("refusal", None):
                raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
            result = ChatResult(message=message, finish_reason=choice["finish_reason"],
                                usage=LLMUsage.from_provider(data["usage"]) if data.get("usage") is not None else None,
                                timings=NativeGenerationTiming.from_provider(data["timings"]) if data.get("timings") is not None else None)
            if result.message.role != "assistant":
                raise ValueError("expected assistant message")
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise transport_error(exc) from exc

    async def chat_stream(self, profile: ModelProfile, request: ChatRequest, *, capture: ChatInputCapture | None = None) -> AsyncIterator[ChatChunk]:
        finished = False
        seen_tool_delta = False
        tool_ids: dict[int, str] = {}
        tool_names: dict[int, str] = {}
        payload = self._payload(profile, request)
        if capture is not None:
            capture(payload)
        try:
            async with aconnect_sse(self.client, "POST", "chat/completions", json=payload) as source:
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
                    usage = LLMUsage.from_provider(data["usage"]) if data.get("usage") is not None else None
                    timings = NativeGenerationTiming.from_provider(data["timings"]) if data.get("timings") is not None else None
                    if not choices:
                        if usage is not None or timings is not None:
                            yield ChatChunk(usage=usage, timings=timings)
                        continue
                    if finished or len(choices) != 1 or choices[0]["index"] != 0:
                        raise ValueError("invalid stream choice")
                    choice = choices[0]
                    delta_data = dict(choice["delta"])
                    if delta_data.pop("refusal", None):
                        raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
                    calls = delta_data.get("tool_calls")
                    if (self.allow_unindexed_complete_tool_call and not seen_tool_delta
                            and choice.get("finish_reason") == "tool_calls"
                            and isinstance(calls, list) and len(calls) == 1
                            and isinstance(calls[0], dict) and "index" not in calls[0]):
                        call = calls[0]
                        function = call.get("function")
                        if (isinstance(call.get("id"), str) and call["id"]
                                and call.get("type") == "function" and isinstance(function, dict)
                                and isinstance(function.get("name"), str) and function["name"]
                                and isinstance(function.get("arguments"), str)
                                and isinstance(strict_json_loads(function["arguments"]), dict)):
                            # Observed on elysia.h-e.top: a complete terminal call omits index.
                            # Disable this opt-in once the upstream reliably supplies standard indices.
                            delta_data["tool_calls"] = [{**call, "index": 0}]
                    seen_tool_delta = seen_tool_delta or bool(calls)
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
                    chunk = ChatChunk(delta=delta, finish_reason=finish, usage=usage, timings=timings)
                    finished = finish is not None
                    yield chunk
                raise ValueError("stream ended without DONE")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, SSEError) as exc:
            raise transport_error(exc) from exc

    async def embed(self, profile: ModelProfile, texts: list[str], dimensions: int | None, *, purpose: EmbeddingPurpose = "document") -> EmbeddingResult:
        instruction = profile.parameters[purpose + "_instruction"]
        payload = {"model": profile.model_ref, "input": [instruction + text for text in texts], "encoding_format": "float"}
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
        raise ModelError("MODEL_UNAVAILABLE", "Providers do not support reranking.", 503)

    async def image_embed(self, profile, tower, inputs):
        raise ModelError("MODEL_UNAVAILABLE", "Providers do not support image embedding.", 503)

    async def vision(self, profile, images):
        raise ModelError("MODEL_UNAVAILABLE", "Providers do not support standalone vision models.", 503)

    async def close(self) -> None:
        await self.client.aclose()
