"""QQ-owned tool identities and durable batch data."""
from typing import Literal

from pydantic import ConfigDict, TypeAdapter


QQ_TOOLS = ("qq_send_message", "qq_skip_reply")
QQTriggerKind = Literal["keyword", "followup", "private"]
participant_epochs = TypeAdapter(dict[str, int], config=ConfigDict(strict=True))
