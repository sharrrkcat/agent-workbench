"""Public QQ timeline records and lightweight run summaries."""
from typing import Annotated, Literal
from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, public_model
from ai_workbench.api.schemas.chat import RunResponse
from ai_workbench.core.qq_transcript import BINDING_PRIVATE
from ai_workbench.core.schema.qq import QQSegment, QQImageAttachment
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQDelivery

BindingResponse = public_model("QQBindingResponse", QQBinding, omit=BINDING_PRIVATE, fields={
    "target_kind": (Literal["group", "friend"], ...), "history_version": (int, ...), "busy": (bool, ...)})


class QQReference(ApiModel):
    type: Literal["at", "reply"]
    id: str
    name: str | None = None
    is_self: bool = False


MessageResponse = public_model("QQMessageResponse", QQMessage, omit={"references_json", "deleted", "image_generation_keyword"}, fields={
    "id": (int, ...), "references": (list[QQReference], ...), "segments": (list[QQSegment], ...),
    "disposition": (Literal["pending", "batched", "skipped", "command"], ...),
    "kind": (Literal["chat", "command"], ...), "command_status": (Literal["pending", "done"] | None, ...),
})
DeliveryResponse = public_model("QQDeliveryResponse", QQDelivery, omit={"deleted"}, fields={
    "id": (int, ...), "status": (Literal["pending", "sending", "sent", "failed", "unknown", "cancelled"], ...),
    "origin": (Literal["model", "command", "notification"], ...),
    "kind": (Literal["text", "generated_image", "resource_image"], ...),
    "attachment": (QQImageAttachment | None, ...), "description": (str | None, ...),
})


class QQPosition(ApiModel):
    id: str
    cursor: str
    created_at: ApiTimestamp


class QQIncoming(QQPosition):
    kind: Literal["incoming"]
    message: MessageResponse


class QQReply(QQPosition):
    kind: Literal["reply"]
    run: RunResponse = Field(description="Public run with model/compaction call statistics only; no processing bodies.")
    deliveries: list[DeliveryResponse]


class QQProgram(QQPosition):
    kind: Literal["program"]
    delivery: DeliveryResponse


class QQHistoryPage(ApiModel):
    items: list[Annotated[QQIncoming | QQReply | QQProgram, Field(discriminator="kind")]]
    binding: BindingResponse
    history_version: int
    before_cursor: str | None
    after_cursor: str | None
    has_before: bool
    has_after: bool
    active_run: RunResponse | None
    latest_run: RunResponse | None = Field(description="Latest run with a settled model call, for the context meter outside the viewed window.")
