"""Project original code-point spans once, before mention labels change lengths."""
from ai_workbench.core.qq_media import media_label
from ai_workbench.core.qq_names import mention_label, references_adapter
from ai_workbench.core.schema.qq import QQTextSegment, QQImageSegment


def ordered_segments(text, references_json, media, *, for_model=False):
    spans = [(item.text_start, item.text_end, item) for item in media]
    spans.extend((ref.start, ref.end, mention_label(ref, for_model=for_model))
        for ref in references_adapter.validate_json(references_json)
        if ref.type == "at" and ref.start is not None and ref.end is not None)
    offset, parts = 0, []

    def append(part):
        if isinstance(part, str):
            if not part:
                return
            if parts and isinstance(parts[-1], str):
                parts[-1] += part
                return
        parts.append(part)

    for start, end, value in sorted(spans, key=lambda span: span[0]):
        append(text[offset:start])
        append(value)
        offset = end
    append(text[offset:])
    return parts


def public_segments(text, references_json, media):
    return [QQTextSegment(text=part) if isinstance(part, str) else QQImageSegment(
        media_id=part.id, asset_id=part.asset_id, description=part.description,
        kind=part.kind, status=part.status, label=media_label(part),
        attachment=part.attachment, error_code=part.error_code)
        for part in ordered_segments(text, references_json, media)]
