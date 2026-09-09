from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_workbench.core.json_data import JsonValue
from ai_workbench.core.time import utc_now
from ai_workbench.core.models.runtimes.schema import RuntimeStatus

ModelKind = Literal["llm", "embedding", "reranker", "image_embedding", "vision", "tts"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProviderInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    protocol: Literal["openai_compatible"] = "openai_compatible"
    base_url: str
    api_key: str = Field(default="", description="PATCH omission retains the key; an empty string clears it.", json_schema_extra={"writeOnly": True})
    timeout_seconds: float = Field(default=60, gt=0, le=3600)
    concurrency: int = Field(default=1, ge=1, le=64)
    queue_size: int = Field(default=32, ge=0, le=1024)
    queue_timeout_seconds: float = Field(default=30, gt=0, le=3600)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("base_url must be an HTTP(S) API root without credentials, query or fragment")
        return value.rstrip("/")

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name must not be empty")
        return value.strip()


class ProviderProfile(ProviderInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Capabilities(StrictModel):
    streaming: bool = False
    tools: bool = False
    vision: bool = False
    json_object: bool = False
    json_schema: bool = False


class Lifecycle(StrictModel):
    unload: Literal["manual", "after_request", "idle"] = "manual"
    idle_seconds: float = Field(default=300, gt=0, le=86400)


class GenerationParameters(StrictModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    seed: int | None = None
    stop: str | list[str] | None = None

    @field_validator("stop")
    @classmethod
    def valid_stop(cls, value):
        if isinstance(value, list) and (not value or len(value) > 4):
            raise ValueError("stop requires one to four sequences")
        return value


class EmbeddingParameters(StrictModel):
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    normalize: bool = True
    document_instruction: str = ""
    query_instruction: str = ""
    batch_size: int = Field(default=16, ge=1, le=2048)


class RerankParameters(StrictModel):
    batch_size: int = Field(default=16, ge=1, le=2048)


class ImageEmbeddingParameters(StrictModel):
    architecture: Literal["clip", "siglip2"] = "clip"
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    normalize: bool = True
    batch_size: int = Field(default=1, ge=1, le=256)


class VisionParameters(StrictModel):
    architecture: Literal["wd14"] = "wd14"
    task: Literal["tags"] = "tags"
    batch_size: int = Field(default=1, ge=1, le=256)


class TTSParameters(StrictModel):
    architecture: Literal["kokoro"] = "kokoro"
    speed: float = Field(default=1.0, ge=0.25, le=4.0, strict=True)
    response_format: Literal["mp3", "wav"] = "mp3"


PARAMETERS = {"llm": GenerationParameters, "embedding": EmbeddingParameters, "reranker": RerankParameters,
              "image_embedding": ImageEmbeddingParameters, "vision": VisionParameters, "tts": TTSParameters}


class ModelInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    kind: ModelKind
    provider_profile_id: str | None = None
    runtime_id: Literal["llama-server", "python-worker"] | None = None
    runtime_variant: Literal["cpu", "cuda", "transformers-cuda", "onnx-cpu", "infinity-cuda", "audio-cuda"] | None = None
    runtime_options: dict[str, Any] = Field(default_factory=dict)
    model_ref: str = Field(min_length=1, max_length=1024)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    parameters: dict[str, Any] = Field(default_factory=dict)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)
    enabled: bool = True
    external_enabled: bool = False

    @model_validator(mode="after")
    def validate_parameters(self):
        from ai_workbench.core.models.runtimes.schema import OnnxCPUOptions, TransformersOptions, is_transformers, llama_options, relative_ref
        if self.runtime_id:
            if self.provider_profile_id or not self.runtime_variant:
                raise ValueError("A managed model requires a runtime variant and no external connection")
            relative_ref(self.model_ref)
            if self.runtime_id == "llama-server":
                if self.kind != "llm" or self.runtime_variant not in {"cpu", "cuda"}:
                    raise ValueError("llama-server requires llm kind and cpu/cuda variant")
                self.runtime_options = llama_options(self.runtime_variant).model_validate(self.runtime_options).model_dump()
                if not self.model_ref.endswith(".gguf"):
                    raise ValueError("llama-server requires a local GGUF file")
                if self.capabilities.vision:
                    raise ValueError("Managed llama image input requires a future projector configuration")
            else:
                if is_transformers(self):
                    if self.kind != "llm":
                        raise ValueError("transformers-cuda requires llm kind")
                    if self.capabilities.vision or self.capabilities.json_object or self.capabilities.json_schema:
                        raise ValueError("Transformers currently supports text and tool calls only")
                    options_schema = TransformersOptions
                elif self.runtime_variant == "onnx-cpu" and self.kind in {"tts", "vision"}:
                    options_schema = OnnxCPUOptions
                elif self.runtime_variant == "infinity-cuda" and self.kind in {"embedding", "reranker", "image_embedding"}:
                    options_schema = TransformersOptions
                elif self.runtime_variant == "audio-cuda" and self.kind == "tts":
                    options_schema = TransformersOptions
                else:
                    raise ValueError("This managed Python backend is not implemented for the model kind")
                self.runtime_options = options_schema.model_validate(self.runtime_options).model_dump()
        elif self.runtime_variant or self.runtime_options:
            raise ValueError("Runtime variant and options require runtime_id")
        if self.kind == "tts" and (self.provider_profile_id or self.runtime_id and self.runtime_variant != "onnx-cpu"):
            raise ValueError("TTS execution requires the managed onnx-cpu backend")
        self.parameters = PARAMETERS[self.kind].model_validate(self.parameters).model_dump(exclude_none=True)
        if is_transformers(self) and any(self.parameters.get(key, 0) != 0 for key in ("presence_penalty", "frequency_penalty")):
            raise ValueError("Transformers does not support nonzero presence or frequency penalties")
        if not self.name.strip() or not self.model_ref.strip():
            raise ValueError("Name and model_ref must not be empty")
        if self.kind != "llm" and any(self.capabilities.model_dump().values()):
            raise ValueError("Chat capabilities apply only to llm profiles")
        return self


class ModelProfile(ModelInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ModelSettings(StrictModel):
    default_model_profile_id: str | None = None
    utility_model_profile_id: str | None = None
    external_enabled: bool = False
    external_api_key: str = Field(default="", description="PATCH omission retains the key; an empty string clears it.", json_schema_extra={"writeOnly": True})
    max_request_mb: int = Field(default=10, ge=1, le=100)


class ImageURL(StrictModel):
    url: str = Field(min_length=1)
    detail: Literal["auto", "low", "high"] = "auto"

    @field_validator("url")
    @classmethod
    def valid_image_url(cls, value: str):
        if not value.startswith(("https://", "http://", "data:image/")):
            raise ValueError("image_url must be an HTTP(S) URL or image data URL")
        return value


class TextPart(StrictModel):
    type: Literal["text"]
    text: str


class ImagePart(StrictModel):
    type: Literal["image_url"]
    image_url: ImageURL


class FunctionCall(StrictModel):
    name: str = Field(min_length=1)
    arguments: str


class ToolCall(StrictModel):
    id: str = Field(min_length=1)
    type: Literal["function"] = "function"
    function: FunctionCall


class ChatMessage(StrictModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[TextPart | ImagePart] | None = None
    reasoning_content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def valid_role_fields(self):
        if self.reasoning_content is not None and self.role != "assistant":
            raise ValueError("Only assistant messages may contain reasoning_content")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages may contain tool_calls")
        if (self.role == "tool") != bool(self.tool_call_id):
            raise ValueError("tool messages require tool_call_id; other roles must omit it")
        if self.content is None and not self.tool_calls and self.reasoning_content is None:
            raise ValueError("Message requires content or tool_calls")
        if isinstance(self.content, list) and (not self.content or any(isinstance(p, ImagePart) for p in self.content) and self.role != "user"):
            raise ValueError("Image content is supported only in user messages")
        return self


class FunctionSpec(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema describing the function's arguments; forwarded as data, never executed by /v1.")
    strict: bool | None = None


class ToolSpec(StrictModel):
    type: Literal["function"] = "function"
    function: FunctionSpec


class NamedFunction(StrictModel):
    name: str


class ToolChoice(StrictModel):
    type: Literal["function"] = "function"
    function: NamedFunction


class JSONSchema(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = None
    schema_: dict[str, JsonValue] = Field(alias="schema", description="Caller-supplied JSON Schema for structured model output.")
    strict: bool | None = None


class ResponseFormat(StrictModel):
    type: Literal["text", "json_object", "json_schema"]
    json_schema: JSONSchema | None = None

    @model_validator(mode="after")
    def valid_schema(self):
        if (self.type == "json_schema") != (self.json_schema is not None):
            raise ValueError("json_schema is required only for type=json_schema")
        return self


class StreamOptions(StrictModel):
    include_usage: bool = False


class ChatRequest(GenerationParameters):
    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    n: Literal[1] = 1
    tools: list[ToolSpec] | None = Field(default=None, min_length=1)
    tool_choice: Literal["none", "auto", "required"] | ToolChoice | None = None
    parallel_tool_calls: bool | None = None
    response_format: ResponseFormat | None = None
    stream_options: StreamOptions | None = None

    @model_validator(mode="after")
    def valid_tools(self):
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires stream=true")
        if (self.tool_choice is not None or self.parallel_tool_calls is not None) and not self.tools:
            raise ValueError("tool_choice and parallel_tool_calls require tools")
        names = [t.function.name for t in self.tools or []]
        if len(names) != len(set(names)):
            raise ValueError("Tool names must be unique")
        if isinstance(self.tool_choice, ToolChoice) and self.tool_choice.function.name not in names:
            raise ValueError("tool_choice must name a supplied tool")
        pending: set[str] = set()
        seen: set[str] = set()
        for message in self.messages:
            if pending and message.role != "tool":
                raise ValueError("Every tool call requires a matching tool result")
            if message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("Unknown or duplicate tool_call_id")
                pending.remove(message.tool_call_id)
            for call in message.tool_calls or []:
                if call.id in seen:
                    raise ValueError("Duplicate tool call id")
                seen.add(call.id)
                pending.add(call.id)
        if pending:
            raise ValueError("Tool calls must have results before generating another completion")
        return self


class EmbeddingRequest(StrictModel):
    model: str = Field(min_length=1)
    input: str | list[str]
    encoding_format: Literal["float", "base64"] = "float"
    dimensions: int | None = Field(default=None, ge=1, le=65536)

    @field_validator("input")
    @classmethod
    def valid_input(cls, value):
        inputs = [value] if isinstance(value, str) else value
        if not inputs or any(not text.strip() for text in inputs):
            raise ValueError("Embedding input must contain non-empty strings")
        return value


class TTSExtensions(StrictModel):
    language: Literal["en-US", "en-GB", "ja-JP", "zh-CN", "es-ES", "fr-FR", "hi-IN", "it-IT", "pt-BR"] | None = None


class SpeechRequest(StrictModel):
    model: str = Field(min_length=1)
    input: str = Field(min_length=1, max_length=4096)
    voice: str = Field(min_length=1, max_length=128)
    speed: float | None = Field(default=None, ge=0.25, le=4.0, strict=True)
    response_format: Literal["mp3", "wav"] | None = None
    stream_format: Literal["audio"] = "audio"
    tts: TTSExtensions = Field(default_factory=TTSExtensions)

    @field_validator("input")
    @classmethod
    def nonempty_input(cls, value):
        if not value.strip():
            raise ValueError("Speech input must not be blank")
        return value


class Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ChatResult(StrictModel):
    message: ChatMessage
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"]
    usage: Usage | None = None


class FunctionDelta(StrictModel):
    name: str | None = None
    arguments: str | None = None


class ToolDelta(StrictModel):
    index: int = Field(ge=0)
    id: str | None = None
    type: Literal["function"] | None = None
    function: FunctionDelta | None = None


class ChatDelta(StrictModel):
    content: str | None = None
    reasoning_content: str | None = None
    role: Literal["assistant"] | None = None
    tool_calls: list[ToolDelta] | None = None


class ChatChunk(StrictModel):
    delta: ChatDelta = Field(default_factory=ChatDelta)
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"] | None = None
    usage: Usage | None = None


class EmbeddingResult(StrictModel):
    vectors: list[list[float]]
    usage: Usage | None = None


class RerankResult(StrictModel):
    scores: list[float]


class VisionResult(StrictModel):
    outputs: list[dict[str, Any]]


class AudioOutput(StrictModel):
    data: bytes
    response_format: Literal["mp3", "wav"]


class ModelStatus(StrictModel):
    state: Literal["unknown", "ready", "unavailable", "failed", "unloaded"] = "unknown"
    residency: Literal["unknown", "loaded", "unloaded"] = "unknown"
    unload_supported: bool = False
    active: int = 0
    queued: int = 0
    error_code: str | None = None
    runtime: RuntimeStatus | None = None
