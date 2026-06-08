from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
