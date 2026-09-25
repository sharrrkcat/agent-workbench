from __future__ import annotations

from datetime import datetime
import math
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, RootModel, TypeAdapter, field_validator, model_validator

from ai_workbench.core.json_data import JsonValue
from ai_workbench.core.time import utc_now
from ai_workbench.core.models.runtimes.schema import RuntimeStatus
from ai_workbench.workers.model_catalog import DirectoryInformation

ModelKind = Literal["llm", "embedding", "reranker", "image_embedding", "vision", "tts", "asr"]
EmbeddingPurpose = Literal["query", "document"]
EmbeddingSimilarity = Literal["cosine", "dot"]
Tower = Literal["image", "text"]
ModelDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$", strict=True)]
MAX_RERANK_BYTES = 32 * 1024 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExternalConnection(StrictModel):
    base_url: str
    api_key: str = Field(default="", description="PATCH omission retains the key; an empty string clears it.", json_schema_extra={"writeOnly": True})
    timeout_seconds: float = Field(default=60, gt=0, le=3600)
    concurrency: int = Field(default=1, ge=1, le=64)
    queue_size: int = Field(default=32, ge=0, le=1024)
    queue_timeout_seconds: float = Field(default=30, gt=0, le=3600)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("base_url must be an HTTP(S) API root without credentials, query or fragment")
        return value.rstrip("/")

class ProviderInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    connection: ExternalConnection

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


class ProviderSource(StrictModel):
    type: Literal["provider"]
    provider_profile_id: str = Field(min_length=1)


class LocalSource(StrictModel):
    type: Literal["local"]
    execution_options: dict[str, Any] = Field(default_factory=dict)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)


ModelSource = Annotated[ProviderSource | LocalSource, Field(discriminator="type")]


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


class LocalEmbeddingParameters(StrictModel):
    query_prompt_name: str | None = Field(default=None, min_length=1, strict=True,
        description="A directory-declared prompt name; null selects the automatic retrieval prompt.")
    document_prompt_name: str | None = Field(default=None, min_length=1, strict=True,
        description="A directory-declared prompt name; null follows native document prompt selection.")


class RerankParameters(StrictModel):
    """Processing and scoring come from the native model directory."""


class ImageEmbeddingParameters(StrictModel):
    unload_other_tower_on_call: bool = Field(default=True, strict=True,
        description="Stop the other SigLIP tower before loading or calling the requested tower. False permits both towers to remain resident; inference is still serial.")


ASRLanguage = Annotated[str, Field(pattern=r"^(auto|[a-z]{2,3})$", strict=True)]
TranscriptionFormat = Literal["json", "text", "verbose_json"]


class ASRParameters(StrictModel):
    language: ASRLanguage = Field(default="auto", description="Native language code, or auto for language detection.")
    prompt: str = Field(default="", strict=True, description="Transcription context or vocabulary; empty clears the prompt.")
    temperature: float = Field(default=0.0, ge=0, le=1, strict=True,
        description="Zero uses deterministic decoding; positive values enable sampling.")
    response_format: TranscriptionFormat = Field(default="json",
        description="JSON/text omit timestamps; verbose_json returns segment timestamps.")


class TranscriptionRequest(StrictModel):
    language: ASRLanguage | None = Field(default=None, description="Omitted/null inherits the profile; auto restores detection.")
    prompt: str | None = Field(default=None, strict=True, description="Omitted/null inherits the profile; empty clears its prompt.")
    temperature: float | None = Field(default=None, ge=0, le=1, strict=True)
    response_format: TranscriptionFormat | None = None
    timestamp_granularities: list[Literal["segment"]] | None = Field(default=None, min_length=1, max_length=1,
        description="Only segment is supported, and only with the effective verbose_json response format.")


class TranscriptionSegment(StrictModel):
    id: int = Field(ge=0, strict=True)
    start: float = Field(ge=0, strict=True)
    end: float = Field(ge=0, strict=True)
    text: str = Field(strict=True)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end < self.start:
            raise ValueError("Segment end precedes its start")
        return self


class TranscriptionResult(StrictModel):
    response_format: TranscriptionFormat
    task: Literal["transcribe"] = "transcribe"
    language: str | None = Field(strict=True)
    duration: float = Field(gt=0, strict=True)
    text: str = Field(strict=True)
    segments: list[TranscriptionSegment] | None = None

    @model_validator(mode="after")
    def valid_segments(self):
        if (self.response_format == "verbose_json") != (self.segments is not None):
            raise ValueError("Only verbose transcription results contain segments")
        if self.segments is not None and [item.id for item in self.segments] != list(range(len(self.segments))):
            raise ValueError("Transcription segment IDs must match their order")
        return self


class VisionThresholds(StrictModel):
    general: float = Field(default=0.35, ge=0, le=1, strict=True)
    character: float = Field(default=0.85, ge=0, le=1, strict=True)


class VisionThresholdOverrides(StrictModel):
    general: float | None = Field(default=None, ge=0, le=1, strict=True,
        description="General-tag score cutoff. Omitted/null inherits the model default; zero is valid.")
    character: float | None = Field(default=None, ge=0, le=1, strict=True,
        description="Character-tag score cutoff. Omitted/null inherits the model default; zero is valid.")


class VisionParameters(StrictModel):
    task: Literal["tags"] = "tags"
    thresholds: VisionThresholds = Field(default_factory=VisionThresholds)


class SpeechOutputParameters(StrictModel):
    speed: float = Field(default=1.0, ge=0.25, le=4.0, strict=True, description="Speech rate multiplier; 1 is the original speed.")
    response_format: Literal["mp3", "wav"] = Field(default="mp3", description="Complete 24 kHz mono audio file format.")


class KokoroParameters(SpeechOutputParameters):
    """Kokoro ONNX uses preset voices and has no generation model_options."""


class ChatterboxParameters(SpeechOutputParameters):
    """English Chatterbox uses a temporary voice ID or one-request reference audio."""
    seed: int | None = Field(default=None, ge=0, le=4294967295, strict=True, description="Fixed speech seed; null leaves randomness unfixed. Controls randomness without guaranteeing identical audio.")
    exaggeration: float = Field(default=0.5, ge=0.0, le=2.0, strict=True, description="Expressiveness of the reference-conditioned voice.")
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0, strict=True, description="Classifier-free conditioning guidance strength.")
    temperature: float = Field(default=0.8, gt=0.0, le=5.0, strict=True, description="Sampling temperature; higher values increase randomness.")
    repetition_penalty: float = Field(default=1.2, ge=1.0, le=2.0, strict=True, description="Penalty for repeated tokens; 1 disables the penalty.")
    min_p: float = Field(default=0.05, ge=0.0, le=1.0, strict=True, description="Minimum token probability relative to the most likely token.")
    top_p: float = Field(default=1.0, gt=0.0, le=1.0, strict=True, description="Cumulative probability cutoff for nucleus sampling.")


class Qwen3TTSParameters(SpeechOutputParameters):
    """Qwen3-TTS 12Hz Base cloning; request model_options override these saved defaults."""
    seed: int | None = Field(default=None, ge=0, le=4294967295, strict=True, description="Fixed speech seed for main and secondary-codebook sampling; null leaves randomness unfixed. Does not guarantee identical audio.")
    do_sample: bool = Field(default=True, strict=True, description="Enable main talker sampling; false uses greedy decoding. Secondary-codebook sampling stays enabled.")
    temperature: float = Field(default=0.9, gt=0.0, strict=True, description="Main talker sampling temperature; used when do_sample is true.")
    top_p: float = Field(default=1.0, gt=0.0, le=1.0, strict=True, description="Main talker nucleus sampling cutoff; used when do_sample is true.")
    top_k: int = Field(default=50, ge=0, strict=True, description="Main talker sampling candidate count; 0 disables top-k filtering. Used when do_sample is true.")
    repetition_penalty: float = Field(default=1.05, gt=0.0, strict=True, description="Codec-token repetition penalty; 1 is neutral, values above 1 discourage repetition.")
    max_new_tokens: int = Field(default=2048, ge=1, le=8192, strict=True, description="Maximum generated codec tokens; reaching this limit can end speech before the full text is spoken.")


class TTSParameters(RootModel):
    root: KokoroParameters | ChatterboxParameters | Qwen3TTSParameters = Field(default_factory=KokoroParameters)


PARAMETERS = {"llm": GenerationParameters, "embedding": EmbeddingParameters, "reranker": RerankParameters,
              "image_embedding": ImageEmbeddingParameters, "vision": VisionParameters, "tts": TTSParameters,
              "asr": ASRParameters}


class ModelInput(StrictModel):
    _directory: DirectoryInformation | None = PrivateAttr(default=None)
    name: str = Field(min_length=1, max_length=128)
    alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    kind: ModelKind
    source: ModelSource | None = None
    model_ref: str = Field(min_length=1, max_length=1024)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    external_enabled: bool = False

    @model_validator(mode="before")
    @classmethod
    def local_only_source(cls, values):
        if isinstance(values, dict) and values.get("kind") in {"image_embedding", "vision", "tts", "asr"}:
            if "source" not in values:
                return {**values, "source": {"type": "local"}}
            source = values["source"]
            if not isinstance(source, LocalSource) and not (isinstance(source, dict) and source.get("type") == "local"):
                raise ValueError("This model kind requires Local Runtime")
        return values

    @model_validator(mode="after")
    def validate_parameters(self):
        from ai_workbench.core.models.runtimes.schema import LlamaCPUOptions, LlamaCUDAOptions, OnnxCPUOptions, PythonOptions, engine_options, local_engine, relative_ref
        local_embedding = self.kind == "embedding" and (isinstance(self.source, LocalSource)
            or self.source is None and bool(self.parameters.keys() & LocalEmbeddingParameters.model_fields.keys()))
        parameters_schema = LocalEmbeddingParameters if local_embedding else PARAMETERS[self.kind]
        parsed = parameters_schema.model_validate(self.parameters)
        self.parameters = ({**SpeechOutputParameters().model_dump(), **parsed.model_dump(exclude_unset=True)}
            if self.kind == "tts" else parsed.model_dump(exclude_none=not local_embedding))
        engine = local_engine(self)
        if isinstance(self.source, LocalSource):
            relative_ref(self.model_ref)
            if self.kind in {"llm", "tts", "vision"}:
                if self.kind == "llm" and self.model_ref.lower().endswith(".gguf"):
                    raise ValueError("Local LLM model_ref must reference a directory, not a GGUF file")
                options = {"llm": LlamaCPUOptions | LlamaCUDAOptions | PythonOptions,
                    "tts": OnnxCPUOptions | PythonOptions, "vision": OnnxCPUOptions}[self.kind]
                self.source.execution_options = TypeAdapter(options).validate_python(self.source.execution_options).model_dump(exclude_unset=True)
            else:
                self.source.execution_options = engine_options(engine, self.source.execution_options).model_validate(self.source.execution_options).model_dump()
        elif isinstance(self.source, ProviderSource) and self.kind not in {"llm", "embedding"}:
            raise ValueError("Providers support only LLM and text embedding models")
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
    purpose: EmbeddingPurpose = Field(default="document",
        description="Cogita extension: selects query or document preprocessing. Omission encodes documents.")

    @field_validator("input")
    @classmethod
    def valid_input(cls, value):
        inputs = [value] if isinstance(value, str) else value
        if not inputs or any(not text.strip() for text in inputs):
            raise ValueError("Embedding input must contain non-empty strings")
        return value


class RerankRequest(StrictModel):
    model: str = Field(min_length=1, strict=True)
    query: str = Field(min_length=1, strict=True)
    documents: list[Annotated[str, Field(min_length=1, strict=True)]] = Field(min_length=1, max_length=2048)
    top_n: int | None = Field(default=None, ge=1, strict=True,
        description="Return at most this many ranked results; omission/null returns all. Every input is scored.")
    return_documents: bool = Field(default=False, strict=True,
        description="Include original input text, even when native model processing truncates it.")

    @field_validator("query", "documents")
    @classmethod
    def nonblank_text(cls, value):
        if any(not text.strip() for text in ([value] if isinstance(value, str) else value)):
            raise ValueError("Reranking requires a nonblank query and nonblank documents")
        return value


class ImageEmbeddingRequest(StrictModel):
    model: str = Field(min_length=1, strict=True)
    input_type: Tower
    input: Annotated[str, Field(min_length=1, strict=True)] | Annotated[list[Annotated[str, Field(min_length=1, strict=True)]], Field(min_length=1, max_length=16)] = Field(
        description="One string or 1..16 strings. image requires static inline PNG/JPEG/WebP base64 data URLs; text uses the model's native tokenizer and position limit.")
    encoding_format: Literal["float", "base64"] = "float"

    @field_validator("input")
    @classmethod
    def valid_input(cls, value):
        inputs = [value] if isinstance(value, str) else value
        if any(not text.strip() for text in inputs):
            raise ValueError("Supply 1..16 nonblank image-embedding inputs")
        return value


class ModelLoadRequest(StrictModel):
    tower: Tower = Field(description="Required for image_embedding profiles. Other kinds reject this field.")


class VisionRequest(StrictModel):
    model: str = Field(min_length=1)
    images: list[Annotated[str, Field(min_length=1, strict=True)]] = Field(min_length=1, max_length=16,
        description="Static PNG, JPEG or WebP base64 data URLs, in result order. No remote URLs or file paths.")
    thresholds: VisionThresholdOverrides | None = None


class ReferenceTranscript(StrictModel):
    reference_text: str | None = Field(default=None, min_length=1, max_length=4096, strict=True,
        description="Qwen Base only: the reference audio's transcript. Omit for speaker-embedding cloning; provide nonblank text for full audio-and-transcript conditioning. Never transcribed automatically.")

    @field_validator("reference_text")
    @classmethod
    def nonblank_transcript(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Reference transcript must not be blank")
        return value


class ReferenceAudio(ReferenceTranscript):
    format: Literal["wav", "mp3"]
    data_base64: str = Field(min_length=4, max_length=16 * 1024 * 1024)

    @field_validator("data_base64")
    @classmethod
    def valid_base64(cls, value: str):
        import base64
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("reference audio must be valid base64") from exc
        if not decoded or len(decoded) > 8 * 1024 * 1024:
            raise ValueError("reference audio is empty or too large")
        return value


class ChatterboxRequestOptions(StrictModel):
    """Chatterbox-only overrides. Omitted/null values inherit the saved profile."""
    seed: int | None = Field(default=None, ge=0, le=4294967295, strict=True, description="Speech seed override; 0 is valid. Omitted/null inherits the profile, whose default is null (unfixed). Does not guarantee identical audio.")
    exaggeration: float | None = Field(default=None, ge=0.0, le=2.0, strict=True, description="Expressiveness override; profile default 0.5.")
    cfg_weight: float | None = Field(default=None, ge=0.0, le=1.0, strict=True, description="Conditioning guidance override; profile default 0.5.")
    temperature: float | None = Field(default=None, gt=0.0, le=5.0, strict=True, description="Sampling temperature override; profile default 0.8.")
    repetition_penalty: float | None = Field(default=None, ge=1.0, le=2.0, strict=True, description="Repetition penalty override; profile default 1.2.")
    min_p: float | None = Field(default=None, ge=0.0, le=1.0, strict=True, description="Relative probability cutoff override; profile default 0.05.")
    top_p: float | None = Field(default=None, gt=0.0, le=1.0, strict=True, description="Nucleus sampling cutoff override; profile default 1.")


class Qwen3TTSRequestOptions(StrictModel):
    """Qwen Base-only overrides. Omitted/null values inherit the saved profile. Secondary-codebook settings are fixed: sampling=true, temperature=0.9, top_p=1, top_k=50."""
    seed: int | None = Field(default=None, ge=0, le=4294967295, strict=True, description="Seed override for main and secondary-codebook sampling; 0 is valid. Omitted/null inherits the profile, whose default is null (unfixed). Does not guarantee identical audio.")
    do_sample: bool | None = Field(default=None, strict=True, description="Main talker sampling override; profile default true. Does not disable secondary-codebook sampling.")
    temperature: float | None = Field(default=None, gt=0.0, strict=True, description="Main talker sampling temperature override; profile default 0.9. Used when do_sample is true.")
    top_p: float | None = Field(default=None, gt=0.0, le=1.0, strict=True, description="Main talker nucleus cutoff override; profile default 1. Used when do_sample is true.")
    top_k: int | None = Field(default=None, ge=0, strict=True, description="Main talker candidate count override; profile default 50, 0 disables filtering. Used when do_sample is true.")
    repetition_penalty: float | None = Field(default=None, gt=0.0, strict=True, description="Codec-token repetition penalty override; profile default 1.05, 1 is neutral.")
    max_new_tokens: int | None = Field(default=None, ge=1, le=8192, strict=True, description="Codec-token output limit override; profile default 2048. Reaching the limit can stop speech before the text ends.")


AUDIO_REQUEST_OPTIONS = {"chatterbox": ChatterboxRequestOptions, "qwen3tts": Qwen3TTSRequestOptions}


class TTSExtensions(StrictModel):
    language: Literal["auto", "en-US", "en-GB", "ja-JP", "zh-CN", "es-ES", "fr-FR", "hi-IN", "it-IT", "pt-BR", "de-DE", "ko-KR", "ru-RU"] | None = Field(default=None,
        description="Kokoro: must match the preset. Chatterbox: en-US only. Qwen: ten languages, excluding hi-IN; en-US/en-GB both select English without an accent guarantee. Qwen omission/null/auto selects Auto.")
    model_options: ChatterboxRequestOptions | Qwen3TTSRequestOptions | None = Field(default=None,
        description="Overrides validated against the selected model architecture before queue admission. Kokoro rejects this field when non-null. Omitted/null option values inherit profile defaults.")
    reference_audio: ReferenceAudio | None = None


class SpeechRequest(StrictModel):
    model: str = Field(min_length=1)
    input: str = Field(min_length=1, max_length=4096)
    voice: str | None = Field(default=None, min_length=1, max_length=128)
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

    @model_validator(mode="after")
    def valid_voice_source(self):
        if (self.voice is None) == (self.tts.reference_audio is None):
            raise ValueError("Provide exactly one of voice or tts.reference_audio")
        return self


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
    similarity: EmbeddingSimilarity = "dot"


class RerankResult(StrictModel):
    scores: list[Annotated[float, Field(strict=True)]] = Field(min_length=1, max_length=2048)


class InferenceUsage(StrictModel):
    """Reserved internal accounting fields; no collection is implemented yet."""
    input_images: int | None = Field(default=None, ge=0, strict=True)
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)


class InferenceTiming(StrictModel):
    """Reserved internal milliseconds; no timing collection is implemented."""
    queue_ms: float | None = Field(default=None, ge=0, strict=True)
    load_ms: float | None = Field(default=None, ge=0, strict=True)
    preprocess_ms: float | None = Field(default=None, ge=0, strict=True)
    inference_ms: float | None = Field(default=None, ge=0, strict=True)
    total_ms: float | None = Field(default=None, ge=0, strict=True)


class SiglipTowerInfo(StrictModel):
    tower: Tower
    device: Literal["cpu", "cuda"]
    device_name: str = Field(min_length=1, strict=True)
    dtype: Literal["float16", "float32"]
    output_dtype: Literal["float32"]
    dimensions: int = Field(gt=0, strict=True)
    model_revision: ModelDigest
    vector_space_id: ModelDigest


class SiglipResult(SiglipTowerInfo):
    vectors: list[list[Annotated[float, Field(strict=True)]]] = Field(min_length=1)
    usage: InferenceUsage | None = None
    timing: InferenceTiming | None = None

    @model_validator(mode="after")
    def valid_vectors(self):
        if any(len(vector) != self.dimensions or not any(value != 0 for value in vector)
               or any(not math.isfinite(value) for value in vector) for vector in self.vectors):
            raise ValueError("Embedding vectors must have consistent dimensions and finite, nonzero values")
        return self


class SiglipTowerStatus(StrictModel):
    process_state: Literal["stopped", "starting", "ready", "failed"] = "stopped"
    residency: Literal["loaded", "unloaded"] = "unloaded"
    error_code: str | None = None
    info: SiglipTowerInfo | None = None


class SiglipTowers(StrictModel):
    image: SiglipTowerStatus = Field(default_factory=SiglipTowerStatus)
    text: SiglipTowerStatus = Field(default_factory=SiglipTowerStatus)
    active_tower: Tower | None = None
    model_revision: ModelDigest | None = None
    vector_space_id: ModelDigest | None = None
    dimensions: int | None = Field(default=None, gt=0, strict=True)


class ImageTag(StrictModel):
    name: str = Field(min_length=1, strict=True)
    category: Literal["general", "character"]
    score: float = Field(ge=0, le=1, strict=True)


class ImageTags(StrictModel):
    object: Literal["image.tags"] = "image.tags"
    index: int = Field(ge=0, strict=True)
    tags: list[ImageTag]


class VisionResult(StrictModel):
    outputs: list[ImageTags]
    usage: InferenceUsage | None = None


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
    towers: SiglipTowers | None = None
