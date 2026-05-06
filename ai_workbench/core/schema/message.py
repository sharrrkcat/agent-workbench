from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ImagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    alt: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None


class ImageGalleryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    images: list[ImagePayload]


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


ChatContentBlock = Annotated[
    Union[TextContentBlock, MarkdownContentBlock, ImageContentBlock],
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
