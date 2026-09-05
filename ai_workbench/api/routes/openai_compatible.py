from __future__ import annotations

import base64
import json
import struct
import time
from contextlib import aclosing
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.http import guard, read_request
from ai_workbench.core.models.schema import ChatRequest, EmbeddingRequest

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


@router.get("/models")
async def list_models(request: Request, state: RuntimeState = Depends(get_state)):
    guard(request, state.model_settings.get())
    return {"object": "list", "data": [
        {"id": p.alias, "object": "model", "created": int(p.created_at.timestamp()), "owned_by": "workbench"}
        for p in state.model_profiles.list() if p.enabled and p.external_enabled and p.kind in {"llm", "embedding"}
    ]}


@router.post("/chat/completions")
async def chat(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, ChatRequest)
    manager = state.model_manager
    profile = manager.external_profile(payload.model, "llm")
    manager.validate_chat(profile, payload)
    identity = {"id": "chatcmpl-" + uuid4().hex, "created": int(time.time()), "model": profile.alias}
    if not payload.stream:
        result = await manager.chat(profile.id, payload)
        response = {**identity, "object": "chat.completion", "choices": [
            {"index": 0, "message": {**result.message.model_dump(exclude_none=True), "content": result.message.content}, "finish_reason": result.finish_reason}
        ]}
        if result.usage:
            response["usage"] = result.usage.model_dump()
        return response

    # Resolve backend/queue failures before headers; inference failures after
    # headers use an explicit SSE error followed by the terminal sentinel.
    await manager.load(profile.id)

    async def events():
        try:
            async with aclosing(manager.chat_stream(profile.id, payload)) as chunks:
                async for chunk in chunks:
                    delta = chunk.delta.model_dump(exclude_none=True)
                    data = {**identity, "object": "chat.completion.chunk",
                            "choices": [{"index": 0, "delta": delta, "finish_reason": chunk.finish_reason}] if delta or chunk.finish_reason else []}
                    if payload.stream_options and payload.stream_options.include_usage:
                        data["usage"] = chunk.usage.model_dump() if chunk.usage else None
                    if data["choices"] or data.get("usage"):
                        yield "data: " + json.dumps(data, ensure_ascii=True) + "\n\n"
        except ModelError as exc:
            request.state.inference_error_code = exc.code
            yield "data: " + json.dumps(exc.payload()) + "\n\n"
        except Exception:
            request.state.inference_error_code = "INTERNAL_ERROR"
            yield "data: " + json.dumps(ModelError("INTERNAL_ERROR", "Streaming inference failed.", 500).payload()) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/embeddings")
async def embeddings(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, EmbeddingRequest)
    profile = state.model_manager.external_profile(payload.model, "embedding")
    inputs = [payload.input] if isinstance(payload.input, str) else payload.input
    result = await state.model_manager.embed(profile.id, inputs, purpose="document", dimensions=payload.dimensions)
    def encode(vector):
        if payload.encoding_format == "base64":
            return base64.b64encode(struct.pack("<" + "f" * len(vector), *vector)).decode("ascii")
        return vector
    response = {"object": "list", "model": profile.alias,
                "data": [{"object": "embedding", "index": i, "embedding": encode(v)} for i, v in enumerate(result.vectors)]}
    if result.usage:
        response["usage"] = result.usage.model_dump(exclude={"completion_tokens"})
    return response
