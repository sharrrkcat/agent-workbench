from typing import Literal

from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp
from ai_workbench.core.models.schema import ChatDelta, ChatMessage, ImageTags, ModelDigest, ReferenceTranscript, Tower, Usage, TranscriptionRequest, TranscriptionSegment, ImageProcessRequest


class PublicModel(ApiModel):
    id: str = Field(description="Enabled, externally visible model alias.")
    object: Literal["model"]
    created: int
    owned_by: Literal["cogita"]


class ModelList(ApiModel):
    object: Literal["list"]
    data: list[PublicModel]


class RerankDocument(ApiModel):
    text: str


class RerankItem(ApiModel):
    index: int = Field(ge=0)
    relevance_score: float = Field(strict=True, description="Native model score; higher is more relevant. Not a universal probability.")
    document: RerankDocument | None = None


class RerankResponse(ApiModel):
    model: str
    results: list[RerankItem]


class ImageTagsResponse(ApiModel):
    object: Literal["list"]
    model: str
    data: list[ImageTags]


class VoiceItem(ApiModel):
    id: str
    model: str
    source: Literal["preset", "temporary"]
    language: str | None = Field(description="Preset/architecture language, or null for Qwen references with no fixed synthesis language.")
    expires_at: ApiTimestamp | None = None


class VoiceAvailability(VoiceItem):
    available: bool


class VoiceReferenceResponse(ApiModel):
    voice_id: str
    model: str
    source: Literal["temporary"] = "temporary"
    expires_at: ApiTimestamp


class VoiceReferenceUpload(ReferenceTranscript, ApiModel):
    model: str = Field(min_length=1)
    file: bytes = Field(description="One WAV or MP3 reference, at most 8 MiB and 30 decoded seconds.", json_schema_extra={"format": "binary"})


class TranscriptionUpload(TranscriptionRequest, ApiModel):
    model: str = Field(min_length=1, description="An enabled, externally visible ASR alias.")
    file: bytes = Field(description="One complete WAV or MP3 file, subject to the configured HTTP body limit.",
        json_schema_extra={"format": "binary"})
    timestamp_granularities: list[Literal["segment"]] | None = Field(default=None,
        alias="timestamp_granularities[]", min_length=1, max_length=1,
        description="Only segment is supported; requires the effective verbose_json response format.")


class ImageProcessUpload(ImageProcessRequest, ApiModel):
    model: str = Field(min_length=1, description="An enabled, externally visible processor alias.")
    image: bytes = Field(description="One static PNG/JPEG/WebP; at most 8,388,608 pixels and 16,384 pixels per axis. Oriented dimensions and alpha are preserved.",
        json_schema_extra={"format": "binary"})


class TranscriptionTextResponse(ApiModel):
    text: str


class TranscriptionVerboseResponse(TranscriptionTextResponse):
    task: Literal["transcribe"]
    language: str | None = Field(description="Detected/selected language code, or null if no language was returned.")
    duration: float = Field(gt=0, description="Actual decoded input duration in seconds.")
    segments: list[TranscriptionSegment]


class VoiceReferenceDeleted(ApiModel):
    deleted: bool
    voice_id: str


class VoiceList(ApiModel):
    object: Literal["list"]
    data: list[VoiceItem]


class CompletionChoice(ApiModel):
    index: Literal[0]
    message: ChatMessage
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"]


class ChatCompletion(ApiModel):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[CompletionChoice] = Field(min_length=1, max_length=1)
    usage: Usage | None = None


class ChunkChoice(ApiModel):
    index: Literal[0]
    delta: ChatDelta
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"] | None


class ChatCompletionChunk(ApiModel):
    id: str
    object: Literal["chat.completion.chunk"]
    created: int
    model: str
    choices: list[ChunkChoice] = Field(max_length=1)
    usage: Usage | None = None


class EmbeddingUsage(ApiModel):
    prompt_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class EmbeddingItem(ApiModel):
    object: Literal["embedding"]
    index: int = Field(ge=0)
    embedding: list[float] | str = Field(description="Float vector, or base64-encoded little-endian float32 bytes when encoding_format=base64.")


class EmbeddingResponse(ApiModel):
    object: Literal["list"]
    model: str
    data: list[EmbeddingItem]
    usage: EmbeddingUsage | None = None


class ImageEmbeddingResponse(ApiModel):
    object: Literal["list"]
    model: str
    input_type: Tower
    dimensions: int = Field(gt=0)
    model_revision: ModelDigest
    vector_space_id: ModelDigest
    data: list[EmbeddingItem] = Field(min_length=1, max_length=16)
