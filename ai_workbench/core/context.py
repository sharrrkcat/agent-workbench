"""Conversation context projection for the single chat path."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.settings import DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION


class ContextBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[dict[str, str]]
    warnings: list[str] = Field(default_factory=list)


class LLMContextError(Exception):
    def __init__(self, message: str, code: str = "LLM_CONTEXT_INVALID") -> None:
        super().__init__(message); self.code=code; self.message=message


class ContextBuilder:
    def __init__(self, message_store: Any) -> None:
        self.message_store = message_store

    def build(self, session_id: str, text: str, policy: ContextPolicy | None = None, *,
              source_message_id: str | None = None, current_message_id: str | None = None,
              context_mode: str = "single_assistant", group_instruction: str | None = None,
              persona_name: str | None = None, persona_id: str | None = None) -> ContextBuildResult:
        policy = policy or ContextPolicy(mode="session")
        current = self._current_text(text, current_message_id)
        history = [m for m in self.message_store.list_messages(session_id) if m.message_id != current_message_id and _eligible(m)]
        if policy.mode in {"none", "current_message"}:
            selected = []
        elif policy.mode == "selected_message":
            selected = [m for m in history if m.message_id == source_message_id]
            if not selected:
                raise LLMContextError("Select an eligible message from this session.", "CONTEXT_MESSAGE_REQUIRED")
        else:
            count = policy.max_messages or (20 if policy.mode == "recent_messages" else None)
            selected = history[-count:] if count else history

        projected = [_project(m, include_attachments=policy.include_attachments == "explicit") for m in selected]
        projected = [m for m in projected if m is not None]
        if context_mode == "group_transcript":
            projected = [{"role": "user", "content": _transcript_line(m, include_attachments=policy.include_attachments == "explicit")} for m in selected]
        # Budget history before adding framing and persona instructions, retaining the current input.
        warnings = []
        if policy.max_chars is not None:
            remaining = max(0, policy.max_chars - len(current))
            projected = _limit_history(projected, remaining)
            if len(current) > policy.max_chars:
                warnings.append("Current message exceeds the history character budget; current input is retained.")
        if context_mode == "group_transcript":
            transcript = "\n".join(m["content"] for m in projected)
            content = f"<conversation_transcript>\n{transcript}\n</conversation_transcript>\n\n<current_user_message>\n{current}\n</current_user_message>"
            instruction = group_instruction or DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
            if persona_id is not None:
                instruction += "\nReply only as the current speaker: " + json.dumps({"persona_id": persona_id, "name": persona_name}, ensure_ascii=False) + "."
            messages = [{"role": "system", "content": instruction}, {"role": "user", "content": content}]
        else:
            messages = [*projected, {"role": "user", "content": current}]
        return ContextBuildResult(messages=validate_llm_context_messages(messages), warnings=warnings)

    def _current_text(self, text: str, message_id: str | None) -> str:
        if text: return text
        if message_id:
            try: return message_text(self.message_store.get_message(message_id))
            except KeyError: pass
        return ""


def validate_llm_context_messages(messages: list[dict[str,Any]]) -> list[dict[str,Any]]:
    for index,item in enumerate(messages):
        if item.get("role") not in {"system","user","assistant"}: raise LLMContextError(f"Illegal LLM context role at index {index}: {item.get('role')!r}")
        if not isinstance(item.get("content"),str): raise LLMContextError(f"Illegal LLM context content at index {index}")
    return messages


def message_text(message: Any, *, include_attachments: bool = True) -> str:
    rendered=[]
    for part in getattr(message,"parts",[]) or []:
        if not isinstance(part,dict): continue
        kind=part.get("type")
        if not include_attachments and kind in {"file", "image", "audio", "video", "media_group"}:
            continue
        if kind=="text": rendered.append(str(part.get("text") or ""))
        elif kind=="json": rendered.append(json.dumps(part.get("data"),ensure_ascii=False,indent=2,default=str))
        elif kind=="file": rendered.append(str(part.get("content") or part.get("filename") or "[file]"))
        elif kind=="image": rendered.append(f"[image{': '+str(part.get('alt')) if part.get('alt') else ''}]")
        elif kind in {"audio","video"}: rendered.append(f"[{kind} attachment]")
        elif kind=="media_group": rendered.append(f"[image gallery: {len(part.get('items') or [])} image(s)]")
        elif kind=="notice": rendered.append(str(part.get("text") or ""))
        elif kind in {"tool_call", "tool_result"}:
            rendered.append("[Tool data] " + json.dumps({key: value for key, value in part.items() if key != "id"}, ensure_ascii=False))
    attachments=(getattr(message,"metadata",{}) or {}).get("attachments")
    if include_attachments and isinstance(attachments,list):
        for item in attachments:
            if not isinstance(item,dict): continue
            context_text=item.get("context_text") or item.get("text")
            if context_text: rendered.append(f"[Attachment: {item.get('name') or item.get('id') or 'file'}]\n{context_text}")
            elif item.get("type") in {"image","file"}: rendered.append(f"[{item.get('type')} attachment: {item.get('name') or item.get('id') or ''}]")
    return "\n\n".join(part for part in rendered if part)


def _project(message: Any, *, include_attachments: bool = True) -> dict[str,str] | None:
    role=getattr(message,"role","")
    if role not in {"system","user","assistant","tool"}: return None
    text=message_text(message, include_attachments=include_attachments)
    if not text and role!="system": return None
    # A selected/truncated history may omit a call's partner. Historical tool
    # parts are quoted user data; only the live harness transcript uses native
    # assistant/tool protocol pairs. This also supports ordinary chat models.
    return {"role":"user" if role == "tool" else role,"content":text}


def _eligible(message: Any) -> bool:
    if getattr(message,"role","") not in {"system","user","assistant","tool"}: return False
    if any(isinstance(part,dict) and part.get("type")=="error" for part in getattr(message,"parts",[]) or []): return False
    metadata=getattr(message,"metadata",{}) or {}
    return not bool(metadata.get("event_type") or metadata.get("incomplete") or metadata.get("streaming"))


def _transcript_line(message: Any, *, include_attachments: bool = True) -> str:
    role = getattr(message, "role", "")
    label = "User" if role == "user" else getattr(message, "speaker_name", None) or ("System" if role == "system" else "Assistant")
    label = str(label).replace("\r", " ").replace("\n", " ")
    speaker_id = getattr(message, "speaker_id", None)
    identity = f" ({speaker_id})" if role == "assistant" and speaker_id else ""
    return f"[{label}{identity}] {message_text(message, include_attachments=include_attachments)}".rstrip()


def _limit_history(messages: list[dict[str,str]], limit: int) -> list[dict[str,str]]:
    kept=[]; used=0
    for item in reversed(messages):
        content=item["content"]
        if used+len(content)>limit: break
        kept.append(item); used+=len(content)
    return list(reversed(kept))
