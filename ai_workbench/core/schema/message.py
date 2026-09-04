from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ai_workbench.core.time import isoformat_utc, utc_now


MessageRole = Literal["user", "assistant", "system", "tool"]
SpeakerType = Literal["user", "assistant", "system", "tool"]


class MessageSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    session_id: str
    role: MessageRole
    speaker_type: Optional[SpeakerType] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    origin: Optional[str] = None
    run_id: Optional[str] = None
    content_version: int = 2
    parts: list[Dict[str, Any]] = Field(default_factory=list)
    parent_message_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


def infer_speaker_identity(
    role: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    speaker_type: Optional[str] = None,
    speaker_id: Optional[str] = None,
    speaker_name: Optional[str] = None,
    origin: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    metadata = metadata or {}
    if role == "user":
        inferred = ("user", "local_user", "User", "user_message")
    elif role == "assistant":
        inferred = ("assistant", str(metadata.get("target") or "chat"), str(metadata.get("speaker_name") or "Assistant"), "assistant_reply")
    elif role == "tool":
        inferred = ("tool", str(metadata.get("tool") or "tool"), str(metadata.get("tool_name") or metadata.get("tool") or "Tool"), "tool_result")
    elif role == "system":
        inferred = ("system", None, "System", str(metadata.get("event_type") or "system_notice"))
    else:
        inferred = (None, None, None, None)
    return {
        "speaker_type": speaker_type or inferred[0],
        "speaker_id": speaker_id or inferred[1],
        "speaker_name": speaker_name or inferred[2],
        "origin": origin or inferred[3],
    }
