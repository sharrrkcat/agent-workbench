from typing import Literal

from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp
from ai_workbench.core.models.schema import ChatDelta, ChatMessage, ReferenceTranscript, Usage


class PublicModel(ApiModel):
    id: str = Field(description="Enabled, externally visible model alias.")
    object: Literal["model"]
    created: int
    owned_by: Literal["workbench"]


class ModelList(ApiModel):
    object: Literal["list"]
    data: list[PublicModel]


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
