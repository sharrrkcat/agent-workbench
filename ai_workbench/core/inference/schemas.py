from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


INFERENCE_A12_VERSION = "a1.2"
MODEL_LIST_ALLOWLIST_REASON = "external_model_allowlist_not_implemented"


def status_response(*, enabled: bool, auth_required: bool, api_key_configured: bool, max_request_mb: int) -> dict[str, Any]:
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
            "llm_chat": "planned",
            "text_embeddings": "planned",
            "multimodal_embeddings": "planned",
            "vision_tasks": "planned",
        },
        "implementation": {
            "real_inference": False,
            "version": INFERENCE_A12_VERSION,
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
            "reason": MODEL_LIST_ALLOWLIST_REASON,
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

    target: Literal["llm", "embedding", "image_embedding", "vision_task", "all"] = "all"
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


class VisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    task: Literal["caption", "detailed_caption", "ocr", "object_detection"]
    image_base64: str
    options: dict[str, Any] = Field(default_factory=dict)
