"""Private per-call inputs and the explicit context-detail read contract."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.models.schema import (
    ChatRequestOptions, GenerationParameters, ResponseFormat, StreamOptions, TextPart, ToolCall, ToolChoice, ToolSpec,
)
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.context_budget import ContextBudgetStats
from ai_workbench.core.time import isoformat_utc


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ContextAttachment(SnapshotModel):
    id: str = Field(description="Attachment-store filename, matching the saved URI.")
    name: str
    type: Literal["image", "file", "audio", "video"]
    mime_type: str
    size: int = Field(ge=0)
    uri: str


class SnapshotImageURL(SnapshotModel):
    url: str = Field(pattern=r"^local://attachments/[^/\\]+$")
    detail: Literal["auto", "low", "high"] = "auto"


class SnapshotImagePart(SnapshotModel):
    type: Literal["image_url"]
    image_url: SnapshotImageURL


class SnapshotMessage(SnapshotModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[Annotated[TextPart | SnapshotImagePart, Field(discriminator="type")]] | None = None
    reasoning_content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class SnapshotTemplateOptions(SnapshotModel):
    enable_thinking: bool


class SnapshotRequest(GenerationParameters):
    """The sent body, with binary image URLs replaced by attachment references."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: str
    messages: list[SnapshotMessage]
    stream: bool
    n: Literal[1] = 1
    tools: list[ToolSpec] | None = None
    tool_choice: Literal["none", "auto", "required"] | ToolChoice | None = None
    parallel_tool_calls: bool | None = None
    response_format: ResponseFormat | None = None
    stream_options: StreamOptions | None = None
    reasoning_effort: Literal["medium", "none"] | None = None
    chat_template_kwargs: SnapshotTemplateOptions | None = None
    cogita_request_options: ChatRequestOptions | None = None


SourceKind = Literal[
    "system", "agent_persona", "project_prompt", "cogita_persona", "knowledge", "knowledge_snippet",
    "history", "current_input", "attachment", "tool_call", "tool_result", "tools", "qq_runtime",
]


class ContextSource(SnapshotModel):
    id: str
    kind: SourceKind
    parent_id: str | None = None
    message_index: int | None = Field(default=None, ge=0)
    part_index: int | None = Field(default=None, ge=0)
    field: Literal["message", "content", "tools"] = "content"
    start: int = Field(default=0, ge=0)
    end: int | None = Field(default=None, ge=0)
    reference_id: str | None = None
    turn_id: str | None = None
    name: str | None = None
    citation: str | None = None
    knowledge_base_id: str | None = None
    source_id: str | None = None
    role: str | None = None
    attachment: ContextAttachment | None = None


class ContextExclusion(SnapshotModel):
    kind: SourceKind
    reason: Literal[
        "ineligible_history", "message_limit", "character_limit", "token_limit", "empty", "attachments_disabled",
        "images_unsupported", "qq_image_unavailable", "qq_history_image", "qq_system_face", "qq_image_limit",
        "file_text_disabled", "file_text_limit", "no_bindings", "no_results", "retrieval_failed",
    ]
    reference_id: str | None = None
    name: str | None = None
    count: int = Field(default=1, ge=1)


class ContextTrace(SnapshotModel):
    sources: list[ContextSource] = Field(default_factory=list)
    exclusions: list[ContextExclusion] = Field(default_factory=list)


class ContextSummary(SnapshotModel):
    available: Literal[True] = True
    message_count: int = Field(ge=0)
    tool_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    budget: ContextBudgetStats | None = None


class ContextSnapshot(SnapshotModel):
    run_id: str
    step_id: str
    captured_at: datetime
    model_profile_id: str
    model_alias: str
    source_type: Literal["local", "provider"]
    request: SnapshotRequest
    policy: ContextPolicy
    sources: list[ContextSource]
    exclusions: list[ContextExclusion]
    attachment_ids: list[str]
    budget: ContextBudgetStats | None = None

    @field_serializer("captured_at", when_used="json")
    def serialize_time(self, value: datetime) -> str:
        return isoformat_utc(value)

    def summary(self) -> ContextSummary:
        return ContextSummary(budget=self.budget, message_count=len(self.request.messages), tool_count=len(self.request.tools or []),
            image_count=sum(isinstance(part, SnapshotImagePart) for message in self.request.messages
                            if isinstance(message.content, list) for part in message.content))


class ContextSourceDetail(ContextSource):
    text: str
    char_count: int = Field(ge=0, description="Inspected text characters; binary image attachments contribute zero.")


class ContextDetail(ContextSnapshot):
    sources: list[ContextSourceDetail]
    reference_numbers: dict[str, int] = Field(default_factory=dict)
