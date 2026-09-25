"""The singleton user's background context, resolved before a chat run starts."""

from dataclasses import dataclass
from typing import Any


USER_PERSONA_BLOCK_TEMPLATE = """# Cogita Persona

The following user-maintained information is stable background context about the user.
Use it when relevant. Do not mention it unless it helps answer the user.

<user_persona>
{content}
</user_persona>"""


@dataclass
class UserPersonaContextResult:
    rendered_text: str
    metadata: dict[str, Any]


def build_user_persona_context(*, persona_id: str, content: str) -> UserPersonaContextResult:
    content = content.strip()
    return UserPersonaContextResult(
        rendered_text=USER_PERSONA_BLOCK_TEMPLATE.format(content=content) if content else "",
        metadata={"persona_id": persona_id, "injected": bool(content), "content_chars": len(content),
                  "skipped_reason": None if content else "empty"},
    )


def append_system_context(messages: list[dict[str, Any]], rendered_text: str) -> list[dict[str, Any]]:
    if not rendered_text:
        return messages
    next_messages = [dict(message) for message in messages]
    for index, message in enumerate(next_messages):
        if message.get("role") == "system":
            content = str(message.get("content") or "")
            next_messages[index] = {**message, "content": f"{content.rstrip()}\n\n{rendered_text}" if content.strip() else rendered_text}
            return next_messages
    return [{"role": "system", "content": rendered_text}, *next_messages]
