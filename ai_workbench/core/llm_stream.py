from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any, Dict, Optional

from ai_workbench.core.time import isoformat_utc, utc_now


@dataclass
class LLMStreamChunk:
    content_delta: Optional[str] = None
    reasoning_delta: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class LLMResult:
    content: str
    reasoning_content: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None


class LLMMetricsRecorder:
    def __init__(self, streamed: bool) -> None:
        self.streamed = streamed
        self.request_started_at = utc_now()
        self.first_token_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def mark_first_token(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = utc_now()

    def complete(self, output: str, usage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.completed_at = utc_now()
        return build_llm_metrics(
            streamed=self.streamed,
            request_started_at=self.request_started_at,
            first_token_at=self.first_token_at,
            completed_at=self.completed_at,
            output=output,
            usage=usage,
        )


def build_llm_metrics(
    streamed: bool,
    request_started_at: datetime,
    first_token_at: Optional[datetime],
    completed_at: datetime,
    output: str,
    usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    usage = usage if isinstance(usage, dict) else None
    output_characters = len(output or "")
    prompt_tokens = _int_or_none((usage or {}).get("prompt_tokens"))
    completion_tokens = _int_or_none((usage or {}).get("completion_tokens"))
    total_tokens = _int_or_none((usage or {}).get("total_tokens"))
    estimated_completion_tokens = None
    usage_source = "unknown"
    if usage:
        usage_source = "provider"
    elif output_characters:
        estimated_completion_tokens = ceil(output_characters / 4)
        usage_source = "estimated"

    duration_ms = max(0, round((completed_at - request_started_at).total_seconds() * 1000))
    first_token_ms = None
    if first_token_at is not None:
        first_token_ms = max(0, round((first_token_at - request_started_at).total_seconds() * 1000))

    token_count = completion_tokens if completion_tokens is not None else estimated_completion_tokens
    generation_start = first_token_at or request_started_at
    generation_seconds = max((completed_at - generation_start).total_seconds(), 0)
    tokens_per_second = None
    if token_count is not None and generation_seconds > 0:
        tokens_per_second = round(token_count / generation_seconds, 2)

    return {
        "streamed": streamed,
        "request_started_at": isoformat_utc(request_started_at),
        "first_token_at": isoformat_utc(first_token_at) if first_token_at else None,
        "completed_at": isoformat_utc(completed_at),
        "duration_ms": duration_ms,
        "time_to_first_token_ms": first_token_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_completion_tokens": estimated_completion_tokens,
        "tokens_per_second": tokens_per_second,
        "output_characters": output_characters,
        "usage_source": usage_source,
    }


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
