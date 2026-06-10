from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.inference.multimodal_runtime import has_multimodal_embedding_runtime_factory, multimodal_runtime_cache_status


INFERENCE_A4_VERSION = "a4.1"


def status_response(
    *,
    enabled: bool,
    auth_required: bool,
    api_key_configured: bool,
    max_request_mb: int,
    models: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "auth_required": auth_required,
        "api_key_configured": api_key_configured,
        "max_request_mb": max_request_mb,
        "routes": {
            "openai_compatible": True,
            "workbench_native": True,
        },
        "capabilities": {
            "llm_chat": "available",
            "text_embeddings": "available",
            "multimodal_embeddings": "configured",
            "vision_tasks": "planned",
        },
        "models": models
        or {
            "llm_external_enabled_count": 0,
            "embedding_external_enabled_count": 0,
            "multimodal_external_enabled_count": 0,
        },
        "implementation": {
            "real_inference": True,
            "real_multimodal_inference": has_multimodal_embedding_runtime_factory(),
            "version": INFERENCE_A4_VERSION,
        },
        "runtime": {
            "multimodal_embedding_cache": multimodal_runtime_cache_status(),
        },
    }


def workbench_models_response() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [],
        "summary": {
            "llm_profiles_available": 0,
            "embedding_profiles_available": 0,
            "multimodal_profiles_available": 0,
            "vision_profiles_available": 0,
        },
    }


def openai_models_response() -> dict[str, Any]:
    return {"object": "list", "data": []}


class OpenAIChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    stream: bool = False


class OpenAIEmbeddingsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    input: Any = None


class InferenceUnloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["llm", "embedding", "image_embedding", "multimodal_embedding", "vision_task", "all"] = "all"
    model: str | None = None


class MultimodalEmbeddingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["image_base64", "text"]
    data: str | None = None
    text: str | None = None


class MultimodalEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    inputs: list[MultimodalEmbeddingInput]
    normalize: bool | None = None


class MultimodalEmbeddingResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["embedding"] = "embedding"
    index: int
    input_type: Literal["image", "text"]
    embedding: list[float]


class MultimodalEmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    model: str
    profile_id: str
    architecture: str
    embedding_space: str
    dimensions: int
    normalized: bool
    data: list[MultimodalEmbeddingResponseItem]
    usage: dict[str, int]


class VisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    task: Literal["caption", "detailed_caption", "ocr", "object_detection"]
    image_base64: str
    options: dict[str, Any] = Field(default_factory=dict)
