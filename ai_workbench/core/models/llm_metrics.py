"""LLM accounting and request-scoped measurements, independent of chat persistence."""
from __future__ import annotations

from datetime import datetime, timedelta
from time import perf_counter
from typing import Annotated, Callable, Literal, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from ai_workbench.core.time import isoformat_utc, utc_now

if TYPE_CHECKING:
    from ai_workbench.core.models.schema import ChatChunk, ChatResult


TokenCount = Annotated[int, Field(ge=0, strict=True)]
Milliseconds = Annotated[float, Field(ge=0, strict=True)]


class MetricsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PromptTokenDetails(MetricsModel):
    cached_tokens: TokenCount | None = None


class CompletionTokenDetails(MetricsModel):
    reasoning_tokens: TokenCount | None = None


class LLMUsage(MetricsModel):
    prompt_tokens: TokenCount | None = None
    completion_tokens: TokenCount | None = None
    total_tokens: TokenCount | None = None
    prompt_tokens_details: PromptTokenDetails | None = None
    completion_tokens_details: CompletionTokenDetails | None = None

    @model_validator(mode="after")
    def total_when_known(self):
        if self.total_tokens is None and self.prompt_tokens is not None and self.completion_tokens is not None:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self

    @classmethod
    def from_provider(cls, value: dict) -> LLMUsage:
        # Providers may expose other accounting dimensions. Only these documented
        # fields cross into our strict internal/public schema.
        if not isinstance(value, dict):
            raise ValueError("Expected a usage object")
        fields = {key: item for key, item in value.items() if key in cls.model_fields}
        for key, detail in (("prompt_tokens_details", PromptTokenDetails),
                            ("completion_tokens_details", CompletionTokenDetails)):
            if isinstance(fields.get(key), dict):
                fields[key] = {name: item for name, item in fields[key].items() if name in detail.model_fields}
        return cls.model_validate(fields)


class NativeGenerationTiming(MetricsModel):
    predicted_n: TokenCount | None = None
    predicted_ms: Milliseconds | None = None

    @classmethod
    def from_provider(cls, value: dict) -> NativeGenerationTiming:
        if not isinstance(value, dict):
            raise ValueError("Expected a timings object")
        return cls.model_validate({key: item for key, item in value.items() if key in cls.model_fields})


class LLMTiming(MetricsModel):
    first_response_ms: Milliseconds | None = None
    total_ms: Milliseconds | None = None
    queue_ms: Milliseconds | None = None
    load_ms: Milliseconds | None = None
    generation_ms: Milliseconds | None = None
    generation_tokens: TokenCount | None = None
    tokens_per_second: Annotated[float, Field(ge=0, strict=True)] | None = None
    tps_source: Literal["native", "estimated"] | None = None


class LLMCallSnapshot(MetricsModel):
    model_profile_id: str
    model: str
    message_id: str
    started_at: datetime
    first_response_at: datetime | None = None
    completed: bool
    usage: LLMUsage | None = None
    timing: LLMTiming

    @field_serializer("started_at", "first_response_at", when_used="json")
    def serialize_time(self, value: datetime | None) -> str | None:
        return isoformat_utc(value)


class LLMCallMetrics:
    def __init__(self, *, clock: Callable[[], float] = perf_counter):
        self.clock = clock
        self.started_at: datetime | None = None
        self.started = 0.0
        self.ended: float | None = None
        self.first: float | None = None
        self.finished_output: float | None = None
        self.finish_reason: str | None = None
        self.output_chunks = 0
        self.completed = False
        self.usage: LLMUsage | None = None
        self.native: NativeGenerationTiming | None = None
        self.queue_ms: float | None = None
        self.load_ms: float | None = None

    def start(self) -> None:
        self.started_at, self.started = utc_now(), self.clock()

    def add_duration(self, field: Literal["queue_ms", "load_ms"], started: float) -> None:
        setattr(self, field, (getattr(self, field) or 0.0) + (self.clock() - started) * 1000)

    def observe(self, chunk: ChatChunk) -> None:
        now = self.clock()
        delta = chunk.delta
        if delta.content or delta.reasoning_content or any(
            tool.function and (tool.function.name or tool.function.arguments) for tool in delta.tool_calls or []
        ):
            self.output_chunks += 1
            if self.first is None:
                self.first = now
        if chunk.finish_reason is not None:
            self.finished_output = now
            self.finish_reason = chunk.finish_reason
        if chunk.usage is not None:
            self.usage = chunk.usage
        if chunk.timings is not None:
            self.native = chunk.timings

    def observe_result(self, result: ChatResult) -> None:
        self.usage, self.native = result.usage, result.timings
        # A complete JSON response does not reveal the first generated token.
        self.finish(completed=True)

    def finish(self, *, completed: bool = False) -> None:
        if self.ended is None:
            self.ended, self.completed = self.clock(), completed

    def timing(self) -> LLMTiming:
        generation_ms = generation_tokens = source = None
        if self.native is not None and self.native.predicted_n is not None and self.native.predicted_ms:
            generation_ms, generation_tokens, source = self.native.predicted_ms, self.native.predicted_n, "native"
        elif (self.completed and self.finish_reason in {"stop", "tool_calls"} and self.output_chunks >= 2 and self.usage is not None
              and self.usage.completion_tokens is not None and self.first is not None
              and self.finished_output is not None and self.finished_output > self.first):
            generation_ms = (self.finished_output - self.first) * 1000
            generation_tokens, source = self.usage.completion_tokens, "estimated"
        return LLMTiming(
            first_response_ms=(self.first - self.started) * 1000 if self.first is not None else None,
            total_ms=(self.ended - self.started) * 1000 if self.ended is not None else None,
            queue_ms=self.queue_ms, load_ms=self.load_ms,
            generation_ms=generation_ms, generation_tokens=generation_tokens, tps_source=source,
            tokens_per_second=generation_tokens * 1000 / generation_ms if generation_ms else None,
        )

    def snapshot(self, profile_id: str, model: str, message_id: str) -> LLMCallSnapshot:
        return LLMCallSnapshot(
            model_profile_id=profile_id, model=model, message_id=message_id, started_at=self.started_at,
            first_response_at=self.started_at + timedelta(seconds=self.first - self.started) if self.first is not None else None,
            completed=self.completed, usage=self.usage, timing=self.timing(),
        )
