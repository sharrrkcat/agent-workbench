from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from ai_workbench.core.forms import ActionFormBlock
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


class CommandButton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    message: str = Field(min_length=1)


class CommandButtonsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["command_buttons"]
    buttons: list[CommandButton]


ChatContentBlock = Annotated[
    Union[TextContentBlock, MarkdownContentBlock, ImageContentBlock, FileContentBlock, ActionFormBlock, CommandButtonsBlock],
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
    content: Any = ""
    speaker_type: Optional[Literal["user", "agent", "capability", "system"]] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    origin: Optional[str] = None
    agent_id: Optional[str] = None
    command_name: Optional[str] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    output_type: Optional[str] = None
    content_version: Optional[int] = 2
    parts: list[Dict[str, Any]] = Field(default_factory=list)
    parent_message_id: Optional[str] = None
    available_actions: list = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


def infer_speaker_identity(
    role: str,
    *,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    command_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    speaker_type: Optional[str] = None,
    speaker_id: Optional[str] = None,
    speaker_name: Optional[str] = None,
    origin: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    metadata = metadata or {}
    if role == "user":
        inferred = {
            "speaker_type": "user",
            "speaker_id": "local_user",
            "speaker_name": "User",
            "origin": "user_message",
        }
    elif metadata.get("kind") == "command_result" or metadata.get("producer") == "capability" or command_name or role in {"tool", "command"}:
        capability_id = str(metadata.get("capability_id") or "") or None
        inferred = {
            "speaker_type": "capability",
            "speaker_id": capability_id,
            "speaker_name": str(metadata.get("capability_name") or command_name or capability_id or "Command result"),
            "origin": "command_result",
        }
    elif role in {"assistant", "agent"}:
        resolved_agent_id = agent_id or metadata.get("agent_id")
        inferred = {
            "speaker_type": "agent",
            "speaker_id": str(resolved_agent_id) if resolved_agent_id else None,
            "speaker_name": agent_name or str(metadata.get("agent_name") or resolved_agent_id or "Assistant"),
            "origin": "agent_reply",
        }
    elif role == "system":
        inferred = {
            "speaker_type": "system",
            "speaker_id": None,
            "speaker_name": "System",
            "origin": str(metadata.get("event_type") or "system_notice"),
        }
    else:
        inferred = {
            "speaker_type": None,
            "speaker_id": None,
            "speaker_name": None,
            "origin": None,
        }
    return {
        "speaker_type": speaker_type or inferred["speaker_type"],
        "speaker_id": speaker_id or inferred["speaker_id"],
        "speaker_name": speaker_name or inferred["speaker_name"],
        "origin": origin or inferred["origin"],
    }
