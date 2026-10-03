"""Capture transport inputs without duplicating inference preparation."""
from __future__ import annotations

from copy import deepcopy
import json

from ai_workbench.core.schema.context_snapshot import (
    ContextAttachment, ContextDetail, ContextExclusion, ContextSnapshot, ContextSource, ContextSourceDetail, ContextTrace,
    SnapshotRequest,
)
from ai_workbench.core.time import utc_now
from ai_workbench.core.user_persona_context import append_system_context


def snapshot_attachment(item: dict) -> ContextAttachment:
    attachment_id = item["uri"].removeprefix("local://attachments/")
    return ContextAttachment(id=attachment_id, name=item.get("name") or attachment_id, type=item["type"],
                             mime_type=item.get("mime_type") or "application/octet-stream", size=item.get("size", 0),
                             uri=item["uri"])


def append_system_block(messages, trace: ContextTrace, text: str, kind, reference_id=None):
    """Append with the existing framing rules and track positions as they change."""
    if not text:
        trace.exclusions.append(ContextExclusion(kind=kind, reason="empty", reference_id=reference_id))
        return messages, None
    index = next((i for i, message in enumerate(messages) if message["role"] == "system"), None)
    if index is None:
        for source in trace.sources:
            if source.message_index is not None:
                source.message_index += 1
        index, start = 0, 0
    else:
        before = str(messages[index]["content"])
        length = len(before.rstrip()) if before.strip() else 0
        start = length + 2 if length else 0
        for source in trace.sources:
            if source.message_index == index and source.parent_id is None and source.kind == "history":
                source.end = length
            if source.message_index == index and source.end is not None:
                source.end = min(source.end, length)
                source.start = min(source.start, source.end)
    result = append_system_context(messages, text)
    if kind == "knowledge":
        # Knowledge has always stripped the outside of the combined system block.
        combined = result[index]["content"]
        leading = len(combined) - len(combined.lstrip())
        result[index]["content"] = combined.strip()
        start = max(0, start - leading)
        for source in trace.sources:
            if source.message_index == index:
                source.start = max(0, source.start - leading)
                if source.end is not None:
                    source.end = max(0, source.end - leading)
    root_id = f"system:{index}"
    if not any(source.id == root_id for source in trace.sources):
        trace.sources.insert(0, ContextSource(id=root_id, kind="system", message_index=index, role="system"))
        for source in trace.sources:
            if source.message_index == index and source.id != root_id and source.parent_id is None:
                source.parent_id = root_id
    source = ContextSource(id=kind, kind=kind, parent_id=root_id, message_index=index, role="system",
                          start=start, end=start + len(text), reference_id=reference_id)
    trace.sources.append(source)
    return result, source


def capture_context(runs, step_id, trace: ContextTrace, profile, policy, *, budget=None):
    """Bind one chat call to its step; the transport supplies the body it sends."""
    def capture(payload: dict) -> None:
        body = deepcopy(payload)
        sources = list(trace.sources)
        mapped = {source.message_index for source in sources if source.message_index is not None}
        for index, message in enumerate(body["messages"]):
            if index not in mapped:
                sources.append(ContextSource(id=f"call:{index}", kind="tool_result" if message["role"] == "tool" else "tool_call",
                    message_index=index, field="message", role=message["role"], reference_id=message.get("tool_call_id")))
        if body.get("tools"):
            sources.append(ContextSource(id="tools", kind="tools", field="tools"))
        attachments = []
        for source in sources:
            if source.attachment is None:
                continue
            attachments.append(source.attachment.id)
            if source.part_index is not None and source.attachment.type == "image":
                body["messages"][source.message_index]["content"][source.part_index]["image_url"]["url"] = source.attachment.uri
        # Validation and database errors may embed the private body in their text.
        from pydantic import ValidationError
        from sqlalchemy.exc import SQLAlchemyError
        from ai_workbench.core.models.errors import ModelError
        try:
            snapshot = ContextSnapshot(run_id=runs.get_step(step_id).run_id, step_id=step_id, captured_at=utc_now(),
                model_profile_id=profile.id, model_alias=profile.alias, source_type=profile.source.type,
                request=SnapshotRequest.model_validate(body), policy=policy,
                sources=sources, exclusions=trace.exclusions, attachment_ids=list(dict.fromkeys(attachments)),
                budget=budget.stats if budget is not None else None)
            runs.save_context_snapshot(step_id, snapshot)
        except (ValidationError, SQLAlchemyError) as exc:
            raise ModelError("CONTEXT_SAVE_FAILED", "The model input could not be saved.", 500) from exc
    return capture


def context_detail(snapshot: ContextSnapshot) -> ContextDetail:
    body = snapshot.request.model_dump(mode="json", exclude_unset=True, by_alias=True)
    sources = []
    for source in snapshot.sources:
        if source.field == "tools":
            value = body.get("tools", [])
        else:
            value = body["messages"][source.message_index]
            if source.field == "content":
                value = value.get("content")
                if isinstance(value, list):
                    value = value[source.part_index or 0]
                    if value["type"] == "text":
                        value = value["text"]
                if isinstance(value, str):
                    value = value[source.start:source.end]
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        chars = 0 if source.attachment is not None and source.attachment.type == "image" else len(text)
        sources.append(ContextSourceDetail(**source.model_dump(), text=text, char_count=chars))
    return ContextDetail(**{**snapshot.model_dump(), "sources": sources, "request": snapshot.request})


def omit_context_images(messages: list[dict], trace: ContextTrace) -> list[dict]:
    """Keep source indices aligned with the existing image-capability projection."""
    result, sources = [], []
    for old_index, message in enumerate(messages):
        content = message["content"]
        current_sources = [source for source in trace.sources if source.message_index == old_index]
        for source in current_sources:
            if source.attachment is not None and source.attachment.type == "image":
                trace.exclusions.append(ContextExclusion(kind="attachment", reason="images_unsupported",
                    reference_id=source.attachment.id, name=source.attachment.name))
        if isinstance(content, list):
            content = "\n".join(part["text"] for part in content if part["type"] == "text")
            if not content.strip():
                continue
        index = len(result)
        result.append({**message, "content": content})
        sources.extend(source.model_copy(update={"message_index": index, "part_index": None})
                       for source in current_sources if source.attachment is None or source.attachment.type != "image")
    trace.sources = sources
    return result
