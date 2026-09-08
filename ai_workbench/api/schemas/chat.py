"""Public chat payloads; private run snapshots never enter these models."""

from typing import Annotated, Literal

from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, JsonObject, patch_model, public_model
from ai_workbench.core import message_parts as parts
from ai_workbench.core.conversation_history import HistoryPruned
from ai_workbench.core.json_data import JsonValue
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.persona import Persona, PersonaInput, ResolvedChatConfig, SessionPersona
from ai_workbench.core.schema.run import RunSchema, RunStepSchema
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session


class JsonPart(parts.JsonPart):
    data: JsonObject | list[JsonValue] = Field(description="User JSON content rendered as data.")


class ToolCallPart(parts.ToolCallPart):
    arguments: JsonObject = Field(default_factory=dict, description="Arguments validated against the selected tool's catalog schema.")


class ToolResultPart(parts.ToolResultPart):
    data: JsonValue = Field(default=None, description="Finite JSON result supplied by the selected built-in tool.")


MessagePart = Annotated[
    parts.TextPart | parts.ReasoningPart | JsonPart | parts.FilePart | parts.ImagePart |
    parts.AudioPart | parts.VideoPart | parts.MediaGroupPart | parts.NoticePart |
    parts.ErrorPart | ToolCallPart | ToolResultPart,
    Field(discriminator="type"),
]

PersonaResponse = public_model("PersonaResponse", Persona)
PersonaPatch = patch_model("PersonaPatch", PersonaInput)
ResolvedConfiguration = public_model("ResolvedConfiguration", ResolvedChatConfig,
    omit={"system_prompt", "group_transcript_instruction"})


class SessionMember(SessionPersona):
    name: str
    avatar_attachment_id: str | None


SessionResponse = public_model("SessionResponse", Session, fields={
    "personas": (list[SessionMember], ...),
    "effective": (ResolvedConfiguration, ...),
    "title_generation_metadata": (JsonObject, Field(description="Auxiliary-title status diagnostics, without prompts or model content.")),
})
RunStepResponse = public_model("RunStepResponse", RunStepSchema, fields={
    "metadata": (JsonObject, Field(description="Compact public step diagnostics and tool identity; never private continuation state.")),
})
RunResponse = public_model("RunResponse", RunSchema, fields={
    "metadata": (JsonObject, Field(description="Public ids, timings, counts and configuration summaries; no prompts or private snapshots.")),
    "steps": (list[RunStepResponse], Field(default_factory=list, description="Included by run reads and execution responses.")),
})
MessageResponse = public_model("MessageResponse", MessageSchema, fields={
    "parts": (list[MessagePart], ...),
    "metadata": (JsonObject, Field(description="Public speaker, attachment and context diagnostics; not full history or secrets.")),
    "run": (RunResponse | None, None),
    "run_steps": (list[RunStepResponse], Field(default_factory=list)),
})
RunEventFields = public_model("RunEventFields", RunEventSchema, omit={"type", "payload"})


class RunStatePayload(ApiModel):
    run: RunResponse
    error: str | None = None
    error_code: str | None = None


class RunFailurePayload(ApiModel):
    error: str
    error_code: str | None
    run: RunResponse | None = None


class StepEventPayload(ApiModel):
    step: RunStepResponse


class ToolCallIdentity(ApiModel):
    id: str
    name: str


class MessageEventPayload(ApiModel):
    message: MessageResponse
    seq: int | None = None
    tool_calls: list[ToolCallIdentity] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    status: Literal["success", "error", "rejected", "cancelled"] | None = None


class MessageDeltaPayload(ApiModel):
    seq: int = Field(ge=1)
    part_id: str
    part_type: Literal["text", "reasoning"]
    delta: str


class ApprovalRequestedPayload(ApiModel):
    run: RunResponse
    tool_call_id: str
    tool_name: str
    arguments: JsonObject = Field(description="Public tool arguments validated by the selected tool's schema.")
    step_id: str
    risk: Literal["safe", "file", "network"]
    service_url: str | None = None


class ApprovalResolvedPayload(ApiModel):
    run: RunResponse
    tool_call_id: str
    tool_name: str
    decision: Literal["approve", "reject"]


class RunStateEvent(RunEventFields):
    type: Literal["run_started", "run_updated", "run_completed", "run_cancel_requested", "run_cancelled"]
    payload: RunStatePayload


class RunFailureEvent(RunEventFields):
    type: Literal["run_failed"]
    payload: RunFailurePayload


class RunStepEvent(RunEventFields):
    type: Literal["run_step_created", "run_step_updated"]
    payload: StepEventPayload


class RunMessageEvent(RunEventFields):
    type: Literal["message_started", "message_updated", "message_completed", "tool_call_created", "tool_result_created"]
    payload: MessageEventPayload


class RunMessageDelta(RunEventFields):
    type: Literal["message_delta"]
    payload: MessageDeltaPayload


class ApprovalRequestedEvent(RunEventFields):
    type: Literal["approval_requested"]
    payload: ApprovalRequestedPayload


class ApprovalResolvedEvent(RunEventFields):
    type: Literal["approval_resolved"]
    payload: ApprovalResolvedPayload


RunEventResponse = Annotated[
    RunStateEvent | RunFailureEvent | RunStepEvent | RunMessageEvent | RunMessageDelta |
    ApprovalRequestedEvent | ApprovalResolvedEvent, Field(discriminator="type"),
]


class SessionPersonasResponse(ApiModel):
    personas: list[SessionMember]
    current_persona_id: str


class KnowledgeBindingsResponse(ApiModel):
    knowledge_base_ids: list[str]


class WorldbookBindingsResponse(ApiModel):
    worldbook_ids: list[str]


class SessionKnowledgeResponse(KnowledgeBindingsResponse):
    session_id: str
    persona_knowledge_base_ids: list[str]
    effective_knowledge_base_ids: list[str]


class SessionWorldbooksResponse(WorldbookBindingsResponse):
    session_id: str
    persona_worldbook_ids: list[str]
    effective_worldbook_ids: list[str]


class SessionDeleted(ApiModel):
    deleted: bool
    session_id: str


class PersonaDeleted(ApiModel):
    deleted: bool
    persona_id: str


class ChatResult(ApiModel):
    success: bool
    data: str | MessageResponse | JsonObject | None = Field(description="Chat text, an edited message, or a direct tool's JSON result.")
    error: str | None
    error_code: str | None = None
    run: RunResponse | None
    session: SessionResponse
    messages: list[MessageResponse]


class HistoryResult(ChatResult, HistoryPruned):
    pass


class ToolResult(ApiModel):
    run: RunResponse
    session: SessionResponse
    messages: list[MessageResponse]


class RunCancellation(ApiModel):
    run: RunResponse
    cancelled: bool
    task_cancelled: bool | None = None
    reason: str


class ToolCatalogItem(ApiModel):
    name: str
    description: str
    parameters: JsonObject = Field(description="Draft 2020-12 JSON object schema for this built-in tool's arguments.")
    risk: Literal["safe", "file", "network"]
    requires_approval: bool
    direct_callable: bool


class NotificationMetadata(ApiModel):
    run_kind: Literal["chat", "tool"]
    persona_id: str
    parent_message_id: str | None


class RunNotification(ApiModel):
    id: str
    session_id: str
    run_id: str
    severity: Literal["error"]
    code: str
    message: str
    created_at: ApiTimestamp
    metadata: NotificationMetadata
    run: RunResponse
    run_steps: list[RunStepResponse]


class MessageTimelineItem(ApiModel):
    kind: Literal["message"]
    message: MessageResponse


class NotificationTimelineItem(ApiModel):
    kind: Literal["notification"]
    notification: RunNotification


TimelineItem = Annotated[MessageTimelineItem | NotificationTimelineItem, Field(discriminator="kind")]


class NotificationDismissed(ApiModel):
    ok: bool
    notification_id: str
    dismissed: bool
