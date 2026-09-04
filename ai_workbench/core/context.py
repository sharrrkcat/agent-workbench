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
    def __init__(self, message_store: Any) -> None: self.message_store=message_store

    def build(self, session_id: str, text: str, policy: ContextPolicy | None = None, *, source_message_id: str | None = None, current_message_id: str | None = None, context_mode: str = "single_assistant") -> ContextBuildResult:
        policy=policy or ContextPolicy(mode="session"); current=self._current_text(text,current_message_id); warnings=[]
        history=[item for item in self.message_store.list_messages(session_id) if item.message_id!=current_message_id and _eligible(item)]
        if policy.mode in {"none","current_message"}: selected=[]
        elif policy.mode=="selected_message":
            selected=[]
            if source_message_id:
                try: selected=[self.message_store.get_message(source_message_id)]
                except KeyError: warnings.append("selected message was not found")
            else: warnings.append("selected message context requested without a source message")
        else:
            selected=history
            if policy.max_messages is not None: selected=selected[-policy.max_messages:]
        if context_mode=="group_transcript":
            transcript="\n".join(_transcript_line(item) for item in selected if _transcript_line(item)); content=f"<conversation_transcript>\n{transcript}\n</conversation_transcript>\n\n<current_user_message>\n{current}\n</current_user_message>"
            messages=[{"role":"system","content":DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION},{"role":"user","content":content}]
        else:
            messages=[item for item in (_project(message) for message in selected) if item is not None]
            messages.append({"role":"user","content":current})
        messages=_limit_chars(messages,policy.max_chars)
        return ContextBuildResult(messages=validate_llm_context_messages(messages),warnings=warnings)

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


def group_transcript_identity_instruction(instruction: str | None = None) -> str: return instruction or DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION


def message_text(message: Any) -> str:
    rendered=[]
    for part in getattr(message,"parts",[]) or []:
        if not isinstance(part,dict): continue
        kind=part.get("type")
        if kind=="text": rendered.append(str(part.get("text") or ""))
        elif kind=="json": rendered.append(json.dumps(part.get("data"),ensure_ascii=False,indent=2,default=str))
        elif kind=="file": rendered.append(str(part.get("content") or part.get("filename") or "[file]"))
        elif kind=="image": rendered.append(f"[image{': '+str(part.get('alt')) if part.get('alt') else ''}]")
        elif kind in {"audio","video"}: rendered.append(f"[{kind} attachment]")
        elif kind=="media_group": rendered.append(f"[image gallery: {len(part.get('items') or [])} image(s)]")
        elif kind=="notice": rendered.append(str(part.get("text") or ""))
    attachments=(getattr(message,"metadata",{}) or {}).get("attachments")
    if isinstance(attachments,list):
        for item in attachments:
            if not isinstance(item,dict): continue
            context_text=item.get("context_text") or item.get("text")
            if context_text: rendered.append(f"[Attachment: {item.get('name') or item.get('id') or 'file'}]\n{context_text}")
            elif item.get("type") in {"image","file"}: rendered.append(f"[{item.get('type')} attachment: {item.get('name') or item.get('id') or ''}]")
    return "\n\n".join(part for part in rendered if part)


def _project(message: Any) -> dict[str,str] | None:
    role=getattr(message,"role","")
    if role not in {"system","user","assistant"}: return None
    text=message_text(message)
    if not text and role!="system": return None
    return {"role":role,"content":text}


def _eligible(message: Any) -> bool:
    if getattr(message,"role","") not in {"system","user","assistant"}: return False
    if any(isinstance(part,dict) and part.get("type")=="error" for part in getattr(message,"parts",[]) or []): return False
    metadata=getattr(message,"metadata",{}) or {}
    return not bool(metadata.get("event_type"))


def _transcript_line(message: Any) -> str:
    role=getattr(message,"role",""); label="User" if role=="user" else getattr(message,"speaker_name",None) or ("System" if role=="system" else "Assistant"); text=message_text(message)
    return f"[{label}] {text}".rstrip()


def _limit_chars(messages: list[dict[str,str]], limit: int | None) -> list[dict[str,str]]:
    if limit is None: return messages
    kept=[]; used=0
    for item in reversed(messages):
        content=item["content"]
        if kept and used+len(content)>limit: break
        kept.append(item); used+=len(content)
    return list(reversed(kept))
