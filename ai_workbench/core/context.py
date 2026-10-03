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
        candidates = [m for m in self.message_store.list_messages(session_id) if m.message_id != current_message_id]
        history = [m for m in candidates if _eligible(m)]
        turns, run_turns, current_turn = {}, {}, None
        for message in history:
            if message.role == "user":
                current_turn = message.message_id
            turn = message.parent_message_id or run_turns.get(message.run_id) or current_turn or message.message_id
            turns[message.message_id] = turn
            if message.run_id:
                run_turns[message.run_id] = turn
        trace.exclusions.extend(ContextExclusion(kind="history", reason="ineligible_history", reference_id=m.message_id)
                                for m in candidates if not _eligible(m))
        if policy.max_messages == 0:
            selected = []
        elif policy.max_messages is None:
            selected = history
        else:
            selected = history[-policy.max_messages:]

        selected_ids = {m.message_id for m in selected}
        trace.exclusions.extend(ContextExclusion(kind="history", reason="message_limit", reference_id=m.message_id)
                                for m in history if m.message_id not in selected_ids)
        pairs = [(m, _project(m, include_attachments=policy.include_attachments == "explicit")) for m in selected]
        trace.exclusions.extend(ContextExclusion(kind="history", reason="empty", reference_id=m.message_id)
                                for m, projected in pairs if projected is None)
        pairs = [(m, projected) for m, projected in pairs if projected is not None]
        projected = [item for _, item in pairs]
        # Budget history before adding framing and persona instructions, retaining the current input.
        warnings = []
        if policy.max_chars is not None:
            remaining = max(0, policy.max_chars - len(current))
            projected = _limit_history(projected, remaining)
            if len(current) > policy.max_chars:
                warnings.append("Current message exceeds the history character budget; current input is retained.")
        removed_count = len(pairs) - len(projected)
        trace.exclusions.extend(ContextExclusion(kind="history", reason="character_limit", reference_id=m.message_id)
                                for m, _ in pairs[:removed_count])
        for index, (message, item) in enumerate(pairs[removed_count:]):
            _trace_message(trace, message, index, item, "history", policy.include_attachments == "explicit",
                           turn_id=turns[message.message_id])
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
    return not bool(metadata.get("event_type") or metadata.get("incomplete") or metadata.get("streaming"))


def _limit_history(messages: list[ContextMessage], limit: int) -> list[ContextMessage]:
    kept=[]; used=0
    for item in reversed(messages):
        length = sum(len(part["text"]) for part in _parts(item["content"]) if part["type"] == "text")
        if used + length > limit: break
        kept.append(item); used += length
    return list(reversed(kept))
