from __future__ import annotations

import base64
import asyncio
import json
import struct
import time
from contextlib import aclosing
from uuid import uuid4
from typing import Literal
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from pydantic import ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import SSE_RESPONSE, request_body
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.schemas.inference import (ChatCompletion, EmbeddingResponse, ImageEmbeddingResponse, ImageTagsResponse, ModelList, RerankResponse, VoiceList,
    VoiceReferenceDeleted, VoiceReferenceResponse, VoiceReferenceUpload)
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.http import guard, read_body, read_request
from ai_workbench.core.models.images import MAX_TAGGING_BYTES
from ai_workbench.core.models.schema import ChatRequest, EmbeddingRequest, ImageEmbeddingRequest, MAX_RERANK_BYTES, ModelKind, RerankRequest, SpeechRequest, VisionRequest
from ai_workbench.core.models.voice_references import credential_id
from ai_workbench.workers.tts_catalog import FORMATS

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


@router.get("/models", response_model=ModelList, response_model_exclude_unset=True,
            responses=error_responses(401, 403, 422, 503), summary="List externally visible models; optional kind is a Cogita extension")
async def list_models(request: Request, kind: ModelKind | None = None, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    return {"object": "list", "data": [
        {"id": p.alias, "object": "model", "created": int(p.created_at.timestamp()), "owned_by": "cogita"}
        for p in state.model_profiles.list(kind) if p.enabled and p.external_enabled
    ]}


@router.post("/rerank", response_model=RerankResponse, response_model_exclude_none=True,
             openapi_extra=request_body(RerankRequest), summary="Rank text documents with a local CrossEncoder (Cogita extension)",
             responses=error_responses(400, 401, 403, 404, 409, 413, 422, 429, 499, 502, 503, 504))
async def rerank(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, RerankRequest, max_bytes=MAX_RERANK_BYTES)
    profile = state.model_manager.external_profile(payload.model, "reranker")
    result = await inference_until_disconnect(request,
        state.model_manager.rerank(profile.id, payload.query, payload.documents))
    order = sorted(range(len(result.scores)), key=lambda index: -result.scores[index])[:payload.top_n]
    return {"model": profile.alias, "results": [{"index": index, "relevance_score": result.scores[index],
        **({"document": {"text": payload.documents[index]}} if payload.return_documents else {})} for index in order]}


@router.post("/images/tags", response_model=ImageTagsResponse, openapi_extra=request_body(VisionRequest),
             summary="Tag static images with WD14 (Cogita extension)",
             responses=error_responses(400, 401, 403, 404, 409, 413, 422, 429, 499, 502, 503, 504))
async def image_tags(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, VisionRequest, max_bytes=MAX_TAGGING_BYTES)
    profile = state.model_manager.external_profile(payload.model, "vision")
    result = await inference_until_disconnect(request, state.model_manager.vision(profile.id, payload))
    return {"object": "list", "model": profile.alias, "data": result.outputs}


@router.post("/images/embeddings", response_model=ImageEmbeddingResponse, openapi_extra=request_body(ImageEmbeddingRequest),
             summary="Embed static images or text with local SigLIP (Cogita extension)",
             responses=error_responses(400, 401, 403, 404, 409, 413, 422, 429, 499, 503, 504))
async def image_embeddings(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, ImageEmbeddingRequest, max_bytes=MAX_TAGGING_BYTES)
    profile = state.model_manager.external_profile(payload.model, "image_embedding")
    result = await inference_until_disconnect(request, state.model_manager.image_embed(profile.id, payload))
    return {"object": "list", "model": profile.alias, "input_type": payload.input_type,
            "dimensions": result.dimensions, "model_revision": result.model_revision, "vector_space_id": result.vector_space_id,
            "data": embedding_data(result.vectors, payload.encoding_format)}


def embedding_data(vectors, encoding_format):
    def encode(vector):
        if encoding_format == "base64":
            return base64.b64encode(struct.pack("<" + "f" * len(vector), *vector)).decode("ascii")
        return vector
    return [{"object": "embedding", "index": index, "embedding": encode(vector)} for index, vector in enumerate(vectors)]


@router.get("/audio/voices", response_model=VoiceList, responses=error_responses(400, 401, 403, 404, 503),
            summary="List available voices (Cogita extension)")
async def audio_voices(request: Request, model: str | None = None, source: Literal["preset", "temporary"] | None = None,
                       state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    profiles = [state.model_manager.external_profile(model, "tts")] if model is not None else [
        p for p in state.model_profiles.list("tts") if p.enabled and p.external_enabled]
    data = []
    if source != "temporary":
        for profile in profiles:
            for item in await asyncio.to_thread(state.model_manager.voice_list, profile.id):
                if item["available"]:
                    data.append({key: value for key, value in item.items() if key != "available"})
    if source != "preset":
        for profile in profiles:
            data.extend(await asyncio.to_thread(state.model_manager.temporary_voice_list, profile.id, credential_id(settings.external_api_key)))
    return {"object": "list", "data": data}


@router.post("/audio/voice-references", response_model=VoiceReferenceResponse,
             openapi_extra=request_body(VoiceReferenceUpload, "multipart/form-data"),
             responses=error_responses(400, 401, 403, 404, 409, 413, 422, 429, 499, 502, 503, 504),
             summary="Create a temporary voice ID (Cogita extension)")
async def create_voice_reference(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    raw = await read_body(request, settings)
    async def stream():
        yield raw
    try:
        form = await MultiPartParser(request.headers, stream(), max_files=1, max_fields=2,
            max_part_size=settings.max_request_mb * 1024 * 1024).parse()
    except (MultiPartException, ValueError) as exc:
        raise ModelError("INVALID_REQUEST", "Upload model and exactly one WAV or MP3 file.") from exc
    try:
        if (len(form.multi_items()) != len(form) or not {"model", "file"} <= set(form)
                or set(form) - {"model", "file", "reference_text"}
                or not isinstance(form["model"], str) or not isinstance(form["file"], UploadFile)):
            raise ModelError("INVALID_REQUEST", "Upload model, exactly one file, and an optional Qwen reference_text.")
        profile = state.model_manager.external_profile(form["model"], "tts")
        audio_format = Path(form["file"].filename or "").suffix.lower().removeprefix(".")
        data = await form["file"].read(8 * 1024 * 1024 + 1)
        try:
            payload = VoiceReferenceUpload.model_validate({"model": form["model"], "file": data,
                **({"reference_text": form["reference_text"]} if "reference_text" in form else {})})
        except ValidationError as exc:
            raise ModelError("INVALID_REQUEST", "Reference transcript must contain 1 to 4096 nonblank characters.") from exc
        return await inference_until_disconnect(request, state.model_manager.create_voice_reference(
            profile.id, data, audio_format, credential_id(settings.external_api_key), reference_text=payload.reference_text))
    finally:
        await form.close()


@router.delete("/audio/voice-references/{voice_id}", response_model=VoiceReferenceDeleted,
               responses=error_responses(400, 401, 403, 404, 409, 503),
               summary="Delete an unused temporary voice ID (Cogita extension)")
async def delete_voice_reference(voice_id: str, request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    return await asyncio.to_thread(state.model_manager.delete_voice_reference, voice_id, credential_id(settings.external_api_key))


async def inference_until_disconnect(request: Request, operation):
    async def disconnected():
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return
    task = asyncio.create_task(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            request.state.inference_error_code = "REQUEST_CANCELLED"
            raise ModelError("REQUEST_CANCELLED", "The inference client disconnected.", 499)
        return await task
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


@router.post("/audio/speech", response_class=Response, openapi_extra=request_body(SpeechRequest),
             summary="Synthesize a complete speech file",
             responses={**error_responses(400, 401, 403, 404, 413, 422, 429, 499, 502, 503, 504),
                        200: {"description": "Complete audio bytes after synthesis.", "content": {
                            mime: {"schema": {"type": "string", "format": "binary"}} for mime in FORMATS.values()},
                              "headers": {"Content-Length": {"schema": {"type": "integer", "minimum": 1}}}}})
async def speech(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, SpeechRequest)
    profile = state.model_manager.external_profile(payload.model, "tts")
    result = await inference_until_disconnect(request, state.model_manager.speech(profile.id, payload, credential=credential_id(settings.external_api_key)))
    return Response(result.data, media_type=FORMATS[result.response_format], headers={"Cache-Control": "no-store"})


@router.post("/chat/completions", response_model=ChatCompletion, response_model_exclude_unset=True,
             openapi_extra=request_body(ChatRequest), summary="Create a chat completion",
             responses={**error_responses(400, 401, 403, 404, 413, 422, 429, 502, 503, 504), 200: SSE_RESPONSE})
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

    # Resolve source/queue failures before headers; inference failures after
    # headers use an explicit SSE error followed by the terminal sentinel.
    stream = await manager.prepare_chat_stream(profile.id, payload)

    async def events():
        try:
            async with aclosing(stream) as chunks:
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


@router.post("/embeddings", response_model=EmbeddingResponse, response_model_exclude_unset=True,
             openapi_extra=request_body(EmbeddingRequest), summary="Create text embeddings",
             responses=error_responses(400, 401, 403, 404, 409, 413, 422, 429, 499, 502, 503, 504))
async def embeddings(request: Request, state: RuntimeState = Depends(get_state)):
    settings = state.model_settings.get()
    guard(request, settings)
    payload = await read_request(request, settings, EmbeddingRequest)
    profile = state.model_manager.external_profile(payload.model, "embedding")
    inputs = [payload.input] if isinstance(payload.input, str) else payload.input
    result = await inference_until_disconnect(request,
        state.model_manager.embed(profile.id, inputs, purpose=payload.purpose, dimensions=payload.dimensions))
    response = {"object": "list", "model": profile.alias,
                "data": embedding_data(result.vectors, payload.encoding_format)}
    if result.usage:
        response["usage"] = result.usage.model_dump(exclude={"completion_tokens"})
    return response
