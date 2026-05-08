from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from ai_workbench.core.time import isoformat_utc, utc_now


class ImagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    alt: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("image url is required")
        return cleaned


class ImageGalleryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    images: list[ImagePayload]


class FileContentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: Optional[str] = None
    language: Optional[str] = None
    mime_type: Optional[str] = None
    content: str
    size: Optional[int] = None
    truncated: bool = False
    path: Optional[str] = None


class TextContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str


class MarkdownContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["markdown"]
    text: str


class ImageContentBlock(ImagePayload):
    type: Literal["image"]


class FileContentBlock(FileContentPayload):
    type: Literal["file_content"]


ChatContentBlock = Annotated[
    Union[TextContentBlock, MarkdownContentBlock, ImageContentBlock, FileContentBlock],
    Field(discriminator="type"),
]


class RichContentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[ChatContentBlock]


class MessageSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    session_id: str
    role: Literal["user", "assistant", "agent", "system", "tool", "command"]
    content: Any
    agent_id: Optional[str] = None
    command_name: Optional[str] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    output_type: str = "text"
    parent_message_id: Optional[str] = None
    available_actions: list = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""
