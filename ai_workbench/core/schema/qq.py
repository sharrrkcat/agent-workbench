"""QQ-owned tool identities and durable batch data."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


QQ_SEND_TOOLS = ("qq_send_message", "qq_generate_image")
QQ_TOOLS = (*QQ_SEND_TOOLS, "qq_skip_reply")
QQTriggerKind = Literal["keyword", "followup", "private", "icebreaker"]
participant_epochs = TypeAdapter(dict[str, int], config=ConfigDict(strict=True))


class QQMediaSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QQMediaSource(QQMediaSchema):
    url: str = ""
    file: str = ""
    face_id: str = ""
    emoji_id: str = ""


class QQImageAttachment(QQMediaSchema):
    id: str
    type: Literal["image"] = "image"
    name: str
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    size: int = Field(ge=1)
    uri: str = Field(pattern=r"^local://attachments/[a-f0-9-]+\.[a-z]+$")
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class QQTextSegment(QQMediaSchema):
    type: Literal["text"] = "text"
    text: str


class QQImageSegment(QQMediaSchema):
    type: Literal["image"] = "image"
    media_id: int
    asset_id: int | None = None
    description: str | None = None
    kind: Literal["image", "sticker", "face"]
    status: Literal["pending", "ready", "failed", "deleted"]
    label: str
    attachment: QQImageAttachment | None = None
    error_code: str | None = None


QQSegment = Annotated[QQTextSegment | QQImageSegment, Field(discriminator="type")]
