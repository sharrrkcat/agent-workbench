from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.stores import MessageStore


class ContextBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: List[Dict[str, str]]
    warnings: List[str] = Field(default_factory=list)


class ContextBuilder:
    def __init__(self, message_store: MessageStore) -> None:
        self.message_store = message_store

    def build(
        self,
        session_id: str,
        args: str,
        policy: ContextPolicy,
        source_message_id: Optional[str] = None,
        current_message_id: Optional[str] = None,
    ) -> ContextBuildResult:
        if policy.mode == "none":
            return ContextBuildResult(messages=[])

        if policy.mode == "current_message":
            return ContextBuildResult(messages=[{"role": "user", "content": args}])

        if policy.mode == "selected_message":
            if source_message_id:
                source = self.message_store.get_message(source_message_id)
                messages: List[Dict[str, str]] = []
                warnings: List[str] = []

                if policy.include_original_user_message:
                    if source.parent_message_id:
                        try:
                            parent = self.message_store.get_message(source.parent_message_id)
                            messages.append(_message_to_llm(parent.role, str(parent.content)))
                        except KeyError:
                            warnings.append("original user message was referenced but could not be found")
                    else:
                        warnings.append("source message has no parent_message_id for original user message")

                if policy.include_last_agent_message:
                    messages.append(_message_to_llm(source.role, str(source.content)))

                if not messages:
                    messages.append(_message_to_llm(source.role, str(source.content)))

                if args:
                    messages.append({"role": "user", "content": args})

                return ContextBuildResult(messages=messages, warnings=warnings)
            return ContextBuildResult(
                messages=[{"role": "user", "content": args}],
                warnings=["selected_message context requested without source_message_id; used current_message fallback"],
            )

        history = [
            _message_to_llm(message.role, str(message.content))
            for message in self.message_store.list_messages(session_id)
            if message.message_id != current_message_id and _message_can_enter_context(message)
        ]
        if policy.mode == "recent_messages" and policy.max_messages is not None:
            history = history[-policy.max_messages :]
        elif policy.mode == "session" and policy.max_messages is not None:
            history = history[-policy.max_messages :]

        history.append({"role": "user", "content": args})
        return ContextBuildResult(messages=_limit_chars(history, policy.max_chars))


def _message_to_llm(role: str, content: str) -> Dict[str, str]:
    if role in {"assistant", "agent"}:
        return {"role": "assistant", "content": content}
    if role == "system":
        return {"role": "system", "content": content}
    if role in {"tool", "command"}:
        return {"role": "tool", "content": content}
    return {"role": "user", "content": content}


def _message_can_enter_context(message) -> bool:
    if getattr(message, "output_type", "") in {"event", "error"}:
        return False
    metadata = getattr(message, "metadata", {}) or {}
    if metadata.get("event_type"):
        return False
    return True


def _limit_chars(messages: List[Dict[str, str]], max_chars: Optional[int]) -> List[Dict[str, str]]:
    if max_chars is None:
        return messages

    total = 0
    kept_reversed: List[Dict[str, str]] = []
    for message in reversed(messages):
        content_len = len(message["content"])
        if kept_reversed and total + content_len > max_chars:
            break
        kept_reversed.append(message)
        total += content_len
    return list(reversed(kept_reversed))
