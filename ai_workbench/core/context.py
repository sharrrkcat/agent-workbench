"""Conversation context projection for the single chat path."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.models.images import ContextMessage
from ai_workbench.core.context_snapshot import snapshot_attachment
from ai_workbench.core.schema.context_snapshot import ContextExclusion, ContextSource, ContextTrace


class ContextBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ContextMessage]
    warnings: list[str] = Field(default_factory=list)
    trace: ContextTrace = Field(default_factory=ContextTrace)


class ContextBuilder:
    def __init__(self, message_store: Any) -> None:
        self.message_store = message_store

    def build(self, session_id: str, text: str, policy: ContextPolicy | None = None, *,
              current_message_id: str | None = None) -> ContextBuildResult:
        policy = policy or ContextPolicy()
        current = self._current_text(text, current_message_id)
        current_refs = []
        if current_message_id and policy.include_attachments == "explicit":
            current_refs = _image_refs(self.message_store.get_message(current_message_id))
        current_content = _content(current, current_refs)
        trace = ContextTrace()
        warnings = []
        pairs = []
        if policy.max_messages != 0:
            total, eligible = self.message_store.context_history_counts(session_id, current_message_id)
            allowed = eligible if policy.max_messages is None else min(eligible, policy.max_messages)
            if total > eligible:
                trace.exclusions.append(ContextExclusion(kind="history", reason="ineligible_history", count=total - eligible))
            if eligible > allowed:
                trace.exclusions.append(ContextExclusion(kind="history", reason="message_limit", count=eligible - allowed))
            remaining = None if policy.max_chars is None else max(0, policy.max_chars - len(current))
            history = iter(self.message_store.iter_context_history(session_id, current_message_id))
            empty_count = 0
            for position in range(allowed):
                message = next(history)
                projected = _project(message, include_attachments=policy.include_attachments == "explicit")
                if projected is None:
                    if policy.max_messages is None:
                        empty_count += 1
                    else:
                        trace.exclusions.append(ContextExclusion(kind="history", reason="empty", reference_id=message.message_id))
                    continue
                length = sum(len(part["text"]) for part in _parts(projected["content"]) if part["type"] == "text")
                if remaining is not None:
                    if length > remaining:
                        trace.exclusions.append(ContextExclusion(kind="history", reason="character_limit", count=allowed - position))
                        break
                    remaining -= length
                pairs.append((message, projected))
            if empty_count:
                trace.exclusions.append(ContextExclusion(kind="history", reason="empty", count=empty_count))
            pairs.reverse()
        if policy.max_chars is not None and len(current) > policy.max_chars:
            warnings.append("Current message exceeds the history character budget; current input is retained.")
        projected = [item for _, item in pairs]
        for index, (message, item) in enumerate(pairs):
            _trace_message(trace, message, index, item, "history", policy.include_attachments == "explicit",
                           turn_id=self.message_store.context_turn_id(message))
        current_message = self.message_store.get_message(current_message_id) if current_message_id else None
        current_item = {"role": "user", "content": current_content}
        if current_message is not None:
            _trace_message(trace, current_message, len(projected), current_item, "current_input",
                           policy.include_attachments == "explicit")
        else:
            trace.sources.append(ContextSource(id="current", kind="current_input", message_index=len(projected), role="user"))
        messages = [*projected, {"role": "user", "content": current_content}]
        return ContextBuildResult(messages=messages, warnings=warnings, trace=trace)

    def _current_text(self, text: str, message_id: str | None) -> str:
        if text: return text
        if message_id:
            try: return message_text(self.message_store.get_message(message_id), include_attachments=False)
            except KeyError: pass
        return ""


def _image_refs(message: Any) -> list[dict]:
    if getattr(message, "role", "") != "user":
        return []
    return [{"type": "attachment_image", "attachment_id": item["uri"].removeprefix("local://attachments/")}
            for item in (getattr(message, "metadata", {}) or {}).get("attachments", [])
            if item.get("type") == "image"]


def _content(text: str, images: list[dict]):
    return [{"type": "text", "text": text}, *images] if images else text


def _parts(content):
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


def message_text(message: Any, *, include_attachments: bool = True, attachment_spans: list | None = None) -> str:
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
            if item.get("type") == "image": continue
            start = len("\n\n".join(part for part in rendered if part))
            start += 2 if start else 0
            context_text=item.get("context_text") or item.get("text")
            if context_text: rendered.append(f"[Attachment: {item.get('name') or item.get('id') or 'file'}]\n{context_text}")
            elif item.get("type") == "file": rendered.append(f"[file attachment: {item.get('name') or item.get('id') or ''}]")
            else: continue
            if attachment_spans is not None:
                attachment_spans.append((item, start, start + len(rendered[-1])))
    return "\n\n".join(part for part in rendered if part)


def _trace_message(trace, message, index, projected, kind, include_attachments, *, turn_id=None):
    source_id = "message:" + message.message_id
    trace.sources.append(ContextSource(id=source_id, kind=kind, message_index=index,
        reference_id=message.message_id, role=projected["role"], turn_id=turn_id))
    attachments = (message.metadata or {}).get("attachments", [])
    if not include_attachments:
        trace.exclusions.extend(ContextExclusion(kind="attachment", reason="attachments_disabled",
            reference_id=item.get("id"), name=item.get("name")) for item in attachments)
        return
    image_index = 1
    for item in attachments:
        if item.get("type") == "image":
            trace.sources.append(ContextSource(id=f"{source_id}:image:{image_index}", kind="attachment",
                parent_id=source_id, message_index=index, part_index=image_index, attachment=snapshot_attachment(item)))
            image_index += 1
    if kind == "history":
        spans = []
        message_text(message, attachment_spans=spans)
        for item, start, end in spans:
            trace.sources.append(ContextSource(id=f"{source_id}:file:{item['id']}", kind="attachment",
                parent_id=source_id, message_index=index, start=start, end=end, attachment=snapshot_attachment(item)))


def _project(message: Any, *, include_attachments: bool = True) -> ContextMessage | None:
    role=getattr(message,"role","")
    if role not in {"system","user","assistant","tool"}: return None
    text=message_text(message, include_attachments=include_attachments)
    images = _image_refs(message) if include_attachments else []
    if not text and not images and role!="system": return None
    # A selected/truncated history may omit a call's partner. Historical tool
    # parts are quoted user data; only the live harness transcript uses native
    # assistant/tool protocol pairs. This also supports ordinary chat models.
    return {"role":"user" if role == "tool" else role,
            "content": _content(text, images)}


def _eligible(message: Any) -> bool:
    if getattr(message,"role","") not in {"system","user","assistant","tool"}: return False
    if any(isinstance(part,dict) and part.get("type")=="error" for part in getattr(message,"parts",[]) or []): return False
    metadata=getattr(message,"metadata",{}) or {}
    return not bool(metadata.get("qq_internal") or metadata.get("event_type") or metadata.get("incomplete") or metadata.get("streaming"))
